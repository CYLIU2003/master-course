from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Mapping, Optional

from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationMode,
    classify_peak_slots,
)
from src.optimization.common.soc_helpers import horizon_start_min, slot_index
from src.optimization.engine import OptimizationEngine

from .reoptimizer import RollingReoptimizer


@dataclass(frozen=True)
class HourlyExecutionState:
    """Measured-state payload required by the next hourly optimization.

    The state is extracted only from the executed prefix of a feasible solver
    result. Vehicle SOC uses the next slot's start value; stationary-battery
    SOC uses the executed slot's end value. This difference is intentional and
    follows the result contract emitted by the Phase 3 charging model.
    """

    current_min: int
    actual_vehicle_soc_kwh: Mapping[str, float]
    actual_bess_soc_kwh: Mapping[str, float]
    observed_on_peak_kw_by_depot: Mapping[str, float]
    observed_off_peak_kw_by_depot: Mapping[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_min": int(self.current_min),
            "actual_vehicle_soc_kwh": dict(self.actual_vehicle_soc_kwh),
            "actual_bess_soc_kwh": dict(self.actual_bess_soc_kwh),
            "observed_on_peak_kw_by_depot": dict(
                self.observed_on_peak_kw_by_depot
            ),
            "observed_off_peak_kw_by_depot": dict(
                self.observed_off_peak_kw_by_depot
            ),
            "state_semantics": {
                "vehicle_soc": "start_of_next_slot",
                "bess_soc": "end_of_last_executed_slot",
                "demand_peak": "maximum_grid_import_kw_over_executed_slots",
            },
        }


def build_next_execution_state(
    problem: CanonicalOptimizationProblem,
    result: Any,
    *,
    current_min: int,
    execution_minutes: int,
    prior_on_peak_kw_by_depot: Optional[Mapping[str, float]] = None,
    prior_off_peak_kw_by_depot: Optional[Mapping[str, float]] = None,
) -> HourlyExecutionState:
    """Extract the exact state passed to the next receding-horizon solve.

    This function deliberately fails on a missing SOC trajectory. Substituting
    a configured initial value would erase the previous hour's operation and
    invalidate both SOC continuity and demand-charge accounting.
    """

    if not bool(getattr(result, "feasible", False)):
        raise ValueError("Cannot advance hourly state from an infeasible result")

    def _nonnegative_finite(raw_value: Any, label: str) -> float:
        value = float(raw_value)
        if not math.isfinite(value) or value < 0.0:
            raise ValueError(f"{label} must be finite and non-negative")
        return value

    timestep_min = max(int(problem.scenario.timestep_min), 1)
    execution_minutes = int(execution_minutes)
    if execution_minutes <= 0 or execution_minutes % timestep_min != 0:
        raise ValueError(
            "execution_minutes must be a positive multiple of timestep_min"
        )

    metadata = {
        **dict(getattr(getattr(result, "plan", None), "metadata", {}) or {}),
        **dict(getattr(result, "solver_metadata", {}) or {}),
    }
    expected_start_slot = slot_index(problem, int(current_min))
    raw_start_slot = metadata.get("rolling_start_slot_index")
    start_slot = (
        expected_start_slot if raw_start_slot is None else int(raw_start_slot)
    )
    if start_slot != expected_start_slot:
        raise ValueError(
            "Rolling result start slot does not match the executed current time: "
            f"expected={expected_start_slot}, actual={start_slot}"
        )

    executed_slot_count = execution_minutes // timestep_min
    last_executed_slot = start_slot + executed_slot_count - 1
    next_boundary_slot = last_executed_slot + 1
    plan = result.plan

    assigned_vehicle_ids = set(plan.vehicle_paths())
    electric_vehicle_ids = sorted(
        str(vehicle.vehicle_id)
        for vehicle in problem.vehicles
        if str(vehicle.vehicle_id) in assigned_vehicle_ids
        and str(vehicle.vehicle_type).upper() in {"BEV", "PHEV", "FCEV"}
    )
    vehicle_soc = {}
    missing_vehicle_soc = []
    vehicle_trajectories = dict(
        plan.vehicle_soc_kwh_by_vehicle_slot or {}
    )
    for vehicle_id in electric_vehicle_ids:
        trajectory = dict(vehicle_trajectories.get(vehicle_id) or {})
        if next_boundary_slot not in trajectory:
            missing_vehicle_soc.append(vehicle_id)
            continue
        vehicle_soc[vehicle_id] = _nonnegative_finite(
            trajectory[next_boundary_slot],
            f"Vehicle SOC for {vehicle_id!r}",
        )

    enabled_bess_depots = sorted(
        str(depot_id)
        for depot_id, asset in dict(problem.depot_energy_assets or {}).items()
        if bool(getattr(asset, "bess_enabled", False))
    )
    bess_soc = {}
    missing_bess_soc = []
    bess_trajectories = dict(plan.bess_soc_kwh_by_depot_slot or {})
    for depot_id in enabled_bess_depots:
        trajectory = dict(bess_trajectories.get(depot_id) or {})
        if last_executed_slot not in trajectory:
            missing_bess_soc.append(depot_id)
            continue
        bess_soc[depot_id] = _nonnegative_finite(
            trajectory[last_executed_slot],
            f"BESS SOC for {depot_id!r}",
        )

    if missing_vehicle_soc or missing_bess_soc:
        raise ValueError(
            "Hourly result is missing the SOC boundary required for the next "
            f"solve: vehicle_soc={missing_vehicle_soc}, bess_soc={missing_bess_soc}"
        )

    on_peak_slots, off_peak_slots = classify_peak_slots(problem.price_slots)
    timestep_h = timestep_min / 60.0
    depot_ids = sorted(str(key) for key in problem.depot_energy_assets)
    on_peak = {
        depot_id: _nonnegative_finite(
            (prior_on_peak_kw_by_depot or {}).get(depot_id, 0.0) or 0.0,
            f"Prior on-peak demand for {depot_id!r}",
        )
        for depot_id in depot_ids
    }
    off_peak = {
        depot_id: _nonnegative_finite(
            (prior_off_peak_kw_by_depot or {}).get(depot_id, 0.0) or 0.0,
            f"Prior off-peak demand for {depot_id!r}",
        )
        for depot_id in depot_ids
    }
    grid_to_bus = dict(plan.grid_to_bus_kwh_by_depot_slot or {})
    grid_to_bess = dict(plan.grid_to_bess_kwh_by_depot_slot or {})
    for depot_id in depot_ids:
        bus_slots = dict(grid_to_bus.get(depot_id) or {})
        bess_slots = dict(grid_to_bess.get(depot_id) or {})
        for slot_idx in range(start_slot, last_executed_slot + 1):
            grid_import_kw = (
                _nonnegative_finite(
                    bus_slots.get(slot_idx, 0.0) or 0.0,
                    f"Grid-to-bus energy for {depot_id!r} slot {slot_idx}",
                )
                + _nonnegative_finite(
                    bess_slots.get(slot_idx, 0.0) or 0.0,
                    f"Grid-to-BESS energy for {depot_id!r} slot {slot_idx}",
                )
            ) / timestep_h
            if slot_idx in on_peak_slots:
                on_peak[depot_id] = max(on_peak[depot_id], grid_import_kw)
            elif slot_idx in off_peak_slots:
                off_peak[depot_id] = max(off_peak[depot_id], grid_import_kw)

    service_current = int(current_min)
    if service_current < horizon_start_min(problem):
        service_current += 24 * 60
    return HourlyExecutionState(
        current_min=service_current + execution_minutes,
        actual_vehicle_soc_kwh=vehicle_soc,
        actual_bess_soc_kwh=bess_soc,
        observed_on_peak_kw_by_depot=on_peak,
        observed_off_peak_kw_by_depot=off_peak,
    )


class DayAheadHourlyOptimizer:
    """Coordinate day-ahead assignment and hourly charging re-optimization.

    Step 1 solves the existing Phase 3 full-day model.  Step 2 fixes the
    resulting vehicle-trip assignment and repeatedly solves the remaining-day
    charging/PV/BESS problem, executing only the first hour before updating
    measured state.  The two steps therefore answer different questions and
    must not be described as one integrated global optimum.
    """

    def __init__(self) -> None:
        self._engine = OptimizationEngine()
        self._rolling = RollingReoptimizer()

    def solve_day_ahead(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ):
        day_ahead_config = replace(
            config,
            mode=OptimizationMode.MILP,
            phase="phase3_two_stage",
            requested_phase="phase3_two_stage",
            resolved_phase="phase3_two_stage",
            executed_phase="phase3_two_stage",
            thesis_mode=True,
        )
        return self._engine.solve(problem, day_ahead_config)

    def reoptimize_hour(
        self,
        problem: CanonicalOptimizationProblem,
        day_ahead_plan: AssignmentPlan,
        config: OptimizationConfig,
        current_min: int,
        *,
        actual_vehicle_soc_kwh: Optional[Mapping[str, float]] = None,
        actual_bess_soc_kwh: Optional[Mapping[str, float]] = None,
        observed_on_peak_kw_by_depot: Optional[Mapping[str, float]] = None,
        observed_off_peak_kw_by_depot: Optional[Mapping[str, float]] = None,
        execution_minutes: int = 60,
        bess_terminal_policy: str = "scenario",
    ):
        return self._rolling.reoptimize_charging_hour(
            problem,
            day_ahead_plan,
            config,
            current_min,
            actual_soc=actual_vehicle_soc_kwh,
            actual_bess_soc_kwh=actual_bess_soc_kwh,
            observed_on_peak_kw_by_depot=observed_on_peak_kw_by_depot,
            observed_off_peak_kw_by_depot=observed_off_peak_kw_by_depot,
            execution_minutes=execution_minutes,
            bess_terminal_policy=bess_terminal_policy,
        )
