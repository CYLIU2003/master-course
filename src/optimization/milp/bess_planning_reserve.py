"""Apply the controller's reserve to every predicted execution interval."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from src.optimization.common.bess_reserve_policy import (
    EVALUATION_TARGET_EVERY_PREFIX, bess_reserve_policy, bess_reserve_targets,
)
from src.optimization.common.problem import CanonicalOptimizationProblem


def add_bess_planning_reserve_constraints(
    model: Any,
    problem: CanonicalOptimizationProblem,
    slot_indices: Sequence[int],
    *,
    execution_minutes: int,
    bess_soc_start_var: Mapping[tuple[str, int], Any],
    grid_to_bess_var: Mapping[tuple[str, int], Any],
    bess_to_bus_var: Mapping[tuple[str, int], Any],
) -> dict[str, Any]:
    """Use block-start inventory, excluding PV not observed within that block.

    Forecast PV stored in earlier blocks remains usable. This is a receding
    horizon policy consistency constraint, not a zero-PV whole-horizon robust
    optimization or a promise that future forecast states will occur.
    """
    policy = bess_reserve_policy(problem)
    audit: dict[str, Any] = {"enabled": False, "bess_reserve_policy": policy,
                             "bess_floor_constraint_count": 0}
    if policy != EVALUATION_TARGET_EVERY_PREFIX:
        return audit
    step = problem.scenario.timestep_min
    if (isinstance(execution_minutes, bool) or not isinstance(execution_minutes, int)
            or execution_minutes <= 0 or step <= 0 or execution_minutes % step):
        raise ValueError("BESS planning reserve requires an aligned positive execution interval")
    slots = tuple(slot_indices)
    if not slots or slots != tuple(range(slots[0], slots[0] + len(slots))):
        raise ValueError("BESS planning reserve requires nonempty contiguous slots")
    # All windows must share the day-ahead execution grid. An offset controller
    # must declare a new grid rather than silently using a different policy.
    block_size = execution_minutes // step
    if slots[0] % block_size:
        raise ValueError("BESS planning reserve window must start on the execution grid")
    targets = bess_reserve_targets(problem)
    blocks = [slots[i:i + block_size] for i in range(0, len(slots), block_size)]
    for depot_id, target in targets.items():
        asset = problem.depot_energy_assets[depot_id]
        for block in blocks:
            remaining = bess_soc_start_var[(depot_id, block[0])]
            for slot in block:
                key = (depot_id, slot)
                remaining = (remaining + asset.bess_charge_efficiency * grid_to_bess_var[key]
                             - bess_to_bus_var[key] / asset.bess_discharge_efficiency)
                model.addConstr(remaining >= target,
                                name=f"bess_planning_reserve__{depot_id}__{slot}")
                audit["bess_floor_constraint_count"] += 1
    audit.update(enabled=True, execution_minutes=execution_minutes,
                 block_start_slot_indices=[block[0] for block in blocks],
                 protected_slot_indices=list(slots),
                 protected_floor_kwh_by_depot=targets,
                 evaluation_terminal_target_kwh_by_depot=targets,
                 actual_pv_lower_bound_kwh=0.0, future_observations_used=False,
                 inventory_semantics="modeled_start_of_each_execution_block")
    return audit
