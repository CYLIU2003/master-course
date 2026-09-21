"""Pre-solve reserves for fixed commands issued before actual PV is observed."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.optimization.common.problem import CanonicalOptimizationProblem, OptimizationConfig
from src.optimization.common.bess_reserve_policy import bess_reserve_policy, bess_reserve_targets
from src.optimization.milp.bess_planning_reserve import add_bess_planning_reserve_constraints
from src.optimization.common.bess_dispatch_policy import uses_auxiliary_bess


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
    bess_soc_start_var: Mapping[tuple[str, int], Any] | None = None,
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
        "bess_reserve_policy": bess_reserve_policy(problem),
        "protected_floor_kwh_by_depot": {},
        "evaluation_terminal_target_kwh_by_depot": {},
        "adaptive_bess_depot_ids": [],
    }
    if (any(asset.bess_enabled and uses_auxiliary_bess(asset) for asset in problem.depot_energy_assets.values())
            and bess_reserve_policy(problem) != "physical_floor_only"):
        raise ValueError("Auxiliary BESS cannot use a forecast inventory reserve")
    planning = add_bess_planning_reserve_constraints(
        model, problem, slot_indices, execution_minutes=config.rolling_execution_minutes,
        bess_soc_start_var=bess_soc_start_var or {},
        grid_to_bess_var=grid_to_bess_var, bess_to_bus_var=bess_to_bus_var,
    )
    audit["planning_reserve"] = planning
    if planning["enabled"]:
        audit.update(enabled=True,
                     evaluation_terminal_target_kwh_by_depot=planning["evaluation_terminal_target_kwh_by_depot"])
    if not slots:
        return audit
    reserve_targets = bess_reserve_targets(problem)
    audit["evaluation_terminal_target_kwh_by_depot"] = reserve_targets
    depots = {depot.depot_id: depot for depot in problem.depots}
    duration = problem.scenario.timestep_min / 60.0
    hard_import = problem.metadata.get("enable_contract_overage_penalty") is not True
    for depot_id, asset in problem.depot_energy_assets.items():
        adaptive = uses_auxiliary_bess(asset)
        if adaptive:
            audit["adaptive_bess_depot_ids"].append(depot_id)
        if asset.bess_enabled and not adaptive:
            remaining_energy = float(asset.bess_initial_soc_kwh)
            lower = float(asset.bess_soc_min_kwh)
            audit["initial_bess_soc_kwh_by_depot"][depot_id] = remaining_energy
            audit["physical_floor_kwh_by_depot"][depot_id] = lower
            lower = max(lower, reserve_targets.get(depot_id, lower))
            audit["protected_floor_kwh_by_depot"][depot_id] = lower
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
                    + (bess_to_bus_var[key] if adaptive else 0.0)
                    <= limit_kw * duration,
                    name=f"pv_execution_hard_import__{depot_id}__{slot}",
                )
                audit["hard_import_constraint_count"] += 1
    return audit
