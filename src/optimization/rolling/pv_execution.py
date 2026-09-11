"""Replay issued charging commands against PV observed in the current slot.

This controller is distinct from optimization and post-solve repair. It leaves
bus charging and scheduled BESS discharge/grid charge unchanged. PV serves the
remaining bus demand, then the issued PV-to-BESS command; other PV is curtailed.
Grid supply covers the remaining bus demand under the configured import rule.
No future observation is accepted by the single-slot control interface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import math
from typing import Mapping

from src.optimization.common.problem import (
    CanonicalOptimizationProblem, DepotEnergyAsset, OptimizationEngineResult,
)


POLICY = "fixed_commands_pv_bus_then_planned_storage_v1"
TOLERANCE_KWH = 1.0e-6
FLOW_FIELDS = (
    "grid_to_bus", "pv_to_bus", "bess_to_bus", "pv_to_bess", "grid_to_bess",
    "pv_curtail", "bess_soc", "contract_over_limit",
)


@dataclass(frozen=True)
class IssuedEnergyCommand:
    bus_demand_kwh: float
    bess_to_bus_kwh: float = 0.0
    grid_to_bess_kwh: float = 0.0
    pv_to_bess_kwh: float = 0.0


@dataclass(frozen=True)
class ExecutedEnergySlot:
    grid_to_bus_kwh: float
    pv_to_bus_kwh: float
    bess_to_bus_kwh: float
    pv_to_bess_kwh: float
    grid_to_bess_kwh: float
    pv_curtail_kwh: float
    bess_soc_kwh: float
    contract_over_limit_kwh: float


def _nonnegative(value: float, label: str) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{label} must be numeric energy') from exc
    if isinstance(value, bool) or not math.isfinite(numeric) or numeric < 0:
        raise ValueError(f"{label} must be finite non-negative energy")
    return numeric


def execute_energy_slot(
    asset: DepotEnergyAsset,
    command: IssuedEnergyCommand,
    *,
    actual_pv_kwh: float,
    initial_bess_soc_kwh: float,
    timestep_minutes: int,
    import_limit_kw: float,
    allow_contract_overage: bool,
    slot_index: int,
    grid_price_yen_per_kwh: float,
) -> ExecutedEnergySlot:
    """Apply one predeclared causal control policy or fail without a repair."""
    for label, value in asdict(command).items():
        _nonnegative(value, label)
    pv = _nonnegative(actual_pv_kwh, "actual PV")
    if pv > TOLERANCE_KWH and not asset.pv_enabled:
        raise ValueError('Actual PV cannot supply energy from disabled equipment')
    soc = _nonnegative(initial_bess_soc_kwh, "initial BESS SOC")
    limit_kw = _nonnegative(import_limit_kw, "import limit")
    if timestep_minutes <= 0:
        raise ValueError("Execution timestep must be positive")
    duration = timestep_minutes / 60.0
    discharge = command.bess_to_bus_kwh
    grid_charge = command.grid_to_bess_kwh
    pv_command = command.pv_to_bess_kwh
    if discharge > command.bus_demand_kwh + TOLERANCE_KWH:
        raise ValueError("Issued BESS discharge exceeds bus demand")
    if discharge > TOLERANCE_KWH and grid_charge + pv_command > TOLERANCE_KWH:
        raise ValueError("Issued command charges and discharges BESS simultaneously")
    if not asset.bess_enabled and discharge + grid_charge + pv_command > TOLERANCE_KWH:
        raise ValueError("Issued command uses disabled BESS")
    if discharge > TOLERANCE_KWH and not asset.allow_bess_to_bus:
        raise ValueError("Issued BESS discharge is disabled")
    if pv_command > TOLERANCE_KWH and not asset.allow_pv_to_bess:
        raise ValueError("Issued PV-to-BESS command is disabled")
    if grid_charge > TOLERANCE_KWH:
        allowed = asset.grid_to_bess_allowed_slot_indices
        threshold = asset.grid_to_bess_price_threshold_yen_per_kwh
        if (not asset.allow_grid_to_bess or (allowed and slot_index not in allowed)
                or (threshold > 0 and grid_price_yen_per_kwh > threshold)):
            raise ValueError("Issued grid-to-BESS command violates source/time/price control")
    remaining_bus = max(command.bus_demand_kwh - discharge, 0.0)
    pv_bus = min(pv, remaining_bus)
    grid_bus = remaining_bus - pv_bus
    pv_charge = min(pv_command, max(pv - pv_bus, 0.0))
    if asset.bess_enabled:
        lower, upper = asset.bess_soc_min_kwh, asset.bess_soc_max_kwh
        eta_c, eta_d = asset.bess_charge_efficiency, asset.bess_discharge_efficiency
        if not (0 < eta_c <= 1 and 0 < eta_d <= 1):
            raise ValueError("BESS efficiencies must lie in (0,1]")
        if not lower - TOLERANCE_KWH <= soc <= upper + TOLERANCE_KWH:
            raise ValueError("Observed BESS SOC is outside configured bounds")
        maximum_energy = asset.bess_power_kw * duration
        if (discharge > maximum_energy + TOLERANCE_KWH
                or grid_charge + pv_command > maximum_energy + TOLERANCE_KWH):
            raise ValueError("Issued BESS command exceeds power limit")
        soc += (grid_charge + pv_charge) * eta_c - discharge / eta_d
        if not lower - TOLERANCE_KWH <= soc <= upper + TOLERANCE_KWH:
            raise ValueError("Actual PV cannot execute the command within BESS SOC bounds")
    overage = max(grid_bus + grid_charge - limit_kw * duration, 0.0) if limit_kw > 0 else 0.0
    if overage > TOLERANCE_KWH and not allow_contract_overage:
        raise ValueError("Actual PV shortfall exceeds the hard grid import limit")
    return ExecutedEnergySlot(
        grid_bus, pv_bus, discharge, pv_charge, grid_charge,
        pv - pv_bus - pv_charge, soc, overage,
    )


def execute_pv_prefix(
    problem: CanonicalOptimizationProblem,
    result: OptimizationEngineResult,
    *,
    actual_pv_by_depot_slot: Mapping[str, Mapping[int, float]],
    actual_bess_soc_kwh: Mapping[str, float],
    start_slot: int,
    stop_slot: int,
) -> tuple[CanonicalOptimizationProblem, OptimizationEngineResult, dict]:
    """Replay only a supplied execution prefix; reject future observations.

    Forecast trajectories outside the prefix remain predictions. The caller
    must stitch executed prefixes before evaluating the full-period ledger.
    Vehicle-level source labels become unspecified: depot measurements do not
    establish an exact allocation among vehicles sharing that depot.
    """
    if not result.feasible or stop_slot <= start_slot:
        raise ValueError("PV execution requires a feasible plan and a nonempty prefix")
    slots = set(range(start_slot, stop_slot))
    if set(actual_pv_by_depot_slot) != set(problem.depot_energy_assets):
        raise ValueError("Observed PV must cover the exact depot set")
    if any(set(values) != slots for values in actual_pv_by_depot_slot.values()):
        raise ValueError("Observed PV must contain exactly executed slots, without future observations")
    plan = result.plan
    maps = {name: {owner: dict(values) for owner, values in
                   getattr(plan, f"{name}_kwh_by_depot_slot").items()} for name in FLOW_FIELDS}
    assets = dict(problem.depot_energy_assets)
    depots = {depot.depot_id: depot for depot in problem.depots}
    prices = {slot.slot_index: slot.grid_buy_yen_per_kwh for slot in problem.price_slots}
    step_minutes = int(problem.scenario.timestep_min)
    vehicles = {vehicle.vehicle_id: vehicle for vehicle in problem.vehicles}
    demand: dict[tuple[str, int], float] = {}
    for charge in plan.charging_slots:
        if charge.slot_index not in slots:
            continue
        vehicle = vehicles[charge.vehicle_id]
        depot = charge.charging_depot_id or vehicle.home_depot_id
        if depot not in assets or charge.discharge_kw > TOLERANCE_KWH:
            raise ValueError("PV execution requires depot charging without vehicle-to-grid")
        key = (depot, charge.slot_index)
        demand[key] = demand.get(key, 0.0) + charge.charge_kw * step_minutes / 60
    rows = []
    bess_starts = {owner: dict(values) for owner, values in
                   dict(plan.metadata.get('bess_soc_start_kwh_by_depot_slot') or {}).items()}
    for depot, asset in assets.items():
        if any(value != 0 for value in asset.depot_load_kwh_by_slot):
            raise ValueError('PV execution currently requires explicit zero nontraction load')
        if asset.bess_enabled and depot not in actual_bess_soc_kwh:
            raise ValueError(f"Missing observed BESS state: {depot}")
        if depot not in depots:
            raise ValueError(f"Missing depot import configuration: {depot}")
        profile = list(asset.pv_generation_kwh_by_slot)
        if len(profile) < stop_slot:
            raise ValueError("Forecast PV does not cover the executed prefix")
        soc = actual_bess_soc_kwh.get(depot, 0.0)
        for slot in sorted(slots):
            def planned(name: str) -> float:
                return float(maps[name].get(depot, {}).get(slot, 0.0))
            bus_energy = demand.get((depot, slot), 0.0)
            planned_bus = sum(planned(name) for name in ("grid_to_bus", "pv_to_bus", "bess_to_bus"))
            if abs(bus_energy - planned_bus) > TOLERANCE_KWH:
                raise ValueError("Issued depot source flows disagree with vehicle charge demand")
            actual = actual_pv_by_depot_slot[depot][slot]
            executed = execute_energy_slot(
                asset, IssuedEnergyCommand(bus_energy, planned("bess_to_bus"),
                                          planned("grid_to_bess"), planned("pv_to_bess")),
                actual_pv_kwh=actual, initial_bess_soc_kwh=soc,
                timestep_minutes=step_minutes, import_limit_kw=depots[depot].import_limit_kw,
                allow_contract_overage=bool(problem.metadata.get("enable_contract_overage_penalty", True)),
                slot_index=slot, grid_price_yen_per_kwh=prices[slot],
            )
            for name in FLOW_FIELDS:
                maps[name].setdefault(depot, {})[slot] = getattr(executed, f"{name}_kwh")
            rows.append({"depot_id": depot, "slot_index": slot, "forecast_pv_kwh": profile[slot],
                         "actual_pv_kwh": actual, "initial_bess_soc_kwh": soc, **asdict(executed)})
            bess_starts.setdefault(depot, {})[slot] = soc
            soc = executed.bess_soc_kwh
            profile[slot] = float(actual)
        assets[depot] = replace(asset, pv_generation_kwh_by_slot=tuple(profile),
                                available_pv_surplus_kwh_by_slot=tuple(profile))
    audit = {"policy": POLICY, "start_slot": start_slot, "stop_slot": stop_slot,
             "bus_charging_commands_unchanged": True, "rows": rows,
             "future_observations_used": False,
             "provenance": "depot_slot_controller_replay_of_historical_estimated_actuals"}
    metadata = {**dict(plan.metadata), "pv_execution": audit,
                "source_provenance_exact": True,
                "source_provenance_level": "depot_slot_physical_controller_replay",
                "charging_source_provenance_exact": False,
                "vehicle_source_provenance_exact": False,
                "vehicle_source_allocation_policy": "depot_flow_proportional_inference",
                "bess_soc_start_kwh_by_depot_slot": bess_starts,
                "bess_soc_end_kwh_by_depot_slot": maps['bess_soc'],
                "canonical_source_flow_context": {
                    **{f'{name}_kwh_by_depot_slot': values for name, values in maps.items()},
                    'bess_soc_start_kwh_by_depot_slot': bess_starts,
                    'bess_soc_end_kwh_by_depot_slot': maps['bess_soc'],
                    'source_provenance_exact': True,
                    'source_provenance_level': 'depot_slot_physical_controller_replay',
                }}
    # Solver output splits one physical charger command into source rows.
    # Merge those rows before removing their forecast source attribution;
    # otherwise the execution ledger's duplicate guard would lose energy.
    charges = []
    merged_charges = {}
    for charge in plan.charging_slots:
        if charge.slot_index not in slots:
            charges.append(charge)
            continue
        key = (charge.vehicle_id, charge.slot_index, charge.charger_id, charge.charging_depot_id)
        previous = merged_charges.get(key)
        merged_charges[key] = replace(charge, energy_source=None,
            charge_kw=charge.charge_kw + (previous.charge_kw if previous else 0.0))
    charges.extend(merged_charges.values())
    realized_plan = replace(plan, charging_slots=tuple(charges), metadata=metadata,
                            **{f"{name}_kwh_by_depot_slot": values for name, values in maps.items()})
    realized = replace(result, plan=realized_plan,
                       solver_metadata={**dict(result.solver_metadata), **{
                           "pv_execution_policy": POLICY, "vehicle_source_provenance_exact": False,
                           "vehicle_source_allocation_policy": "depot_flow_proportional_inference",
                           "cost_breakdown_basis": "original_forecast_solve_not_execution_ledger"}})
    return replace(problem, depot_energy_assets=assets), realized, audit
