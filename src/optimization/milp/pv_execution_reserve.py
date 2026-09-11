"""Pre-solve reserves for fixed commands issued before actual PV is observed."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.optimization.common.problem import CanonicalOptimizationProblem, OptimizationConfig


POLICY = "committed_prefix_no_unobserved_pv_credit_v1"


def committed_pv_execution_slots(
    problem: CanonicalOptimizationProblem,
    config: OptimizationConfig,
    slot_indices: Sequence[int],
    *,
    is_remaining_day_reoptimization: bool,
) -> tuple[int, ...]:
    """Select only the issued prefix of the declared forecast/actual contract."""
    contract = problem.metadata.get("date_series_contract") or {}
    if (not is_remaining_day_reoptimization
            or contract.get("pv_information_mode") != "training_only_forecast_proxy"):
        return ()
    minutes = config.rolling_execution_minutes
    step = int(problem.scenario.timestep_min)
    if (isinstance(minutes, bool) or not isinstance(minutes, int)
            or minutes <= 0 or step <= 0 or minutes % step):
        raise ValueError("PV execution reserve requires an aligned positive execution interval")
    slots = tuple(slot_indices[:minutes // step])
    if slots and slots != tuple(range(slots[0], slots[0] + len(slots))):
        raise ValueError("PV execution reserve requires contiguous committed slots")
    return slots


def add_pv_execution_reserve_constraints(
    model: Any,
    problem: CanonicalOptimizationProblem,
    config: OptimizationConfig,
    slot_indices: Sequence[int],
    *,
    is_remaining_day_reoptimization: bool,
    grid_to_bus_var: Mapping[tuple[str, int], Any],
    pv_to_bus_var: Mapping[tuple[str, int], Any],
    grid_to_bess_var: Mapping[tuple[str, int], Any],
    bess_to_bus_var: Mapping[tuple[str, int], Any],
) -> dict[str, Any]:
    """Keep each committed slot executable for any nonnegative actual PV.

    BESS discharge and grid charging are fixed controller commands. Only
    observed initial inventory and scheduled grid charge may fund discharge
    before the next state update. The ordinary forecast trajectory continues
    to enforce upper SOC, power, modes, terminal conditions and source rules.
    """
    slots = committed_pv_execution_slots(
        problem, config, slot_indices,
        is_remaining_day_reoptimization=is_remaining_day_reoptimization,
    )
    audit: dict[str, Any] = {
        "policy": POLICY,
        "enabled": bool(slots),
        "committed_slot_indices": list(slots),
        "actual_pv_lower_bound_kwh": 0.0,
        "future_observations_used": False,
        "bess_floor_constraint_count": 0,
        "hard_import_constraint_count": 0,
        "initial_bess_soc_kwh_by_depot": {},
        "physical_floor_kwh_by_depot": {},
    }
    if not slots:
        return audit
    depots = {depot.depot_id: depot for depot in problem.depots}
    duration = problem.scenario.timestep_min / 60.0
    hard_import = not bool(problem.metadata.get("enable_contract_overage_penalty", True))
    for depot_id, asset in problem.depot_energy_assets.items():
        if asset.bess_enabled:
            remaining_energy = float(asset.bess_initial_soc_kwh)
            lower = float(asset.bess_soc_min_kwh)
            audit["initial_bess_soc_kwh_by_depot"][depot_id] = remaining_energy
            audit["physical_floor_kwh_by_depot"][depot_id] = lower
            for slot in slots:
                key = (depot_id, slot)
                remaining_energy = (remaining_energy
                    + float(asset.bess_charge_efficiency) * grid_to_bess_var[key]
                    - bess_to_bus_var[key] / float(asset.bess_discharge_efficiency))
                model.addConstr(
                    remaining_energy >= lower,
                    name=f"pv_execution_bess_floor__{depot_id}__{slot}",
                )
                audit["bess_floor_constraint_count"] += 1
        if hard_import:
            limit_kw = float(depots[depot_id].import_limit_kw or 0.0)
            if limit_kw <= 0.0:
                continue
            for slot in slots:
                key = (depot_id, slot)
                model.addConstr(
                    grid_to_bus_var[key] + pv_to_bus_var[key] + grid_to_bess_var[key]
                    <= limit_kw * duration,
                    name=f"pv_execution_hard_import__{depot_id}__{slot}",
                )
                audit["hard_import_constraint_count"] += 1
    return audit
