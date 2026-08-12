from __future__ import annotations

from dataclasses import replace
import math
from typing import Any, Mapping, Optional

from src.dispatch.feasibility import FeasibilityEngine
from src.dispatch.models import DutyLeg, VehicleDuty
from src.dispatch.validator import DutyValidator
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationMode,
)
from src.optimization.common.soc_helpers import (
    BEV_TERMINAL_SOC_TARGET_KWH_BY_VEHICLE_KEY,
    effective_final_soc_target_kwh,
    horizon_start_min,
    is_electric_vehicle,
)
from src.optimization.common.bess_terminal_policy import (
    resolve_bess_terminal_soc_target_kwh,
)
from src.optimization.engine import OptimizationEngine
from src.optimization.milp.solver_adapter import (
    ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT,
)
from .state_locking import lock_started_trips


_SOC_BOUNDARY_TOLERANCE_KWH = 1.0e-6


def assignment_plan_from_serialized_result(
    problem: CanonicalOptimizationProblem,
    serialized_result: Mapping[str, Any],
) -> AssignmentPlan:
    """Rebuild the fixed day-ahead assignment from a persisted solver result.

    Charging decisions are intentionally not restored: the hourly model must
    recompute them from the latest SOC, PV forecast, and observed demand peak.
    Timetable rows are never rewritten; every leg points back to the canonical
    dispatch trip already present in ``problem``.
    """

    dispatch_context = problem.dispatch_context
    trip_lookup = (
        dispatch_context.trips_by_id()
        if dispatch_context is not None
        and callable(getattr(dispatch_context, "trips_by_id", None))
        else {}
    )
    if not trip_lookup:
        raise ValueError(
            "Cannot restore a day-ahead assignment without canonical dispatch trips"
        )

    duties = []
    assigned_trip_ids: list[str] = []
    seen_duty_ids: set[str] = set()
    seen_trip_ids: set[str] = set()
    for raw_duty in list(serialized_result.get("duties") or []):
        if not isinstance(raw_duty, Mapping):
            raise ValueError("Persisted day-ahead assignment contains an invalid duty")
        duty_id = str(raw_duty.get("duty_id") or "").strip()
        if not duty_id:
            raise ValueError("Persisted day-ahead assignment contains an empty duty_id")
        if duty_id in seen_duty_ids:
            raise ValueError(
                f"Persisted day-ahead assignment duplicates duty_id {duty_id!r}"
            )
        seen_duty_ids.add(duty_id)

        raw_legs = list(raw_duty.get("legs") or [])
        if not raw_legs:
            raw_legs = [
                {"trip_id": trip_id, "deadhead_from_prev_min": 0}
                for trip_id in list(raw_duty.get("trip_ids") or [])
            ]
        if not raw_legs:
            raise ValueError(
                f"Persisted day-ahead duty {duty_id!r} contains no trip legs"
            )
        legs = []
        for raw_leg in raw_legs:
            if not isinstance(raw_leg, Mapping):
                raise ValueError(
                    f"Persisted day-ahead duty {duty_id!r} contains an invalid leg"
                )
            trip_id = str(raw_leg.get("trip_id") or "").strip()
            if not trip_id:
                raise ValueError(
                    f"Persisted day-ahead duty {duty_id!r} contains an empty trip_id"
                )
            if trip_id in seen_trip_ids:
                raise ValueError(
                    f"Persisted day-ahead assignment duplicates trip {trip_id!r}"
                )
            trip = trip_lookup.get(trip_id)
            if trip is None:
                raise ValueError(
                    f"Persisted day-ahead assignment references unknown trip {trip_id!r}"
                )
            deadhead_min = int(raw_leg.get("deadhead_from_prev_min") or 0)
            if deadhead_min < 0:
                raise ValueError(
                    f"Persisted day-ahead duty {duty_id!r} has negative deadhead time"
                )
            legs.append(
                DutyLeg(
                    trip=trip,
                    deadhead_from_prev_min=deadhead_min,
                )
            )
            assigned_trip_ids.append(trip_id)
            seen_trip_ids.add(trip_id)
        duties.append(
            VehicleDuty(
                duty_id=duty_id,
                vehicle_type=str(raw_duty.get("vehicle_type") or "").strip(),
                legs=tuple(legs),
            )
        )
    if not duties:
        raise ValueError("Persisted day-ahead assignment contains no duties")

    raw_served_trip_ids = tuple(
        str(item)
        for item in list(serialized_result.get("served_trip_ids") or [])
        if str(item).strip()
    )
    served_trip_ids = (
        raw_served_trip_ids
        if "served_trip_ids" in serialized_result
        else tuple(assigned_trip_ids)
    )
    if len(served_trip_ids) != len(set(served_trip_ids)):
        raise ValueError("Persisted day-ahead result duplicates served_trip_ids")
    if set(served_trip_ids) != seen_trip_ids:
        raise ValueError(
            "Persisted served_trip_ids do not match the trips assigned to duties"
        )

    unserved_trip_ids = tuple(
        str(item)
        for item in list(serialized_result.get("unserved_trip_ids") or [])
        if str(item).strip()
    )
    if len(unserved_trip_ids) != len(set(unserved_trip_ids)):
        raise ValueError("Persisted day-ahead result duplicates unserved_trip_ids")
    if seen_trip_ids.intersection(unserved_trip_ids):
        raise ValueError(
            "Persisted day-ahead result marks assigned trips as unserved"
        )
    problem_trip_ids = {str(trip.trip_id) for trip in problem.trips}
    persisted_trip_ids = seen_trip_ids.union(unserved_trip_ids)
    if persisted_trip_ids != problem_trip_ids:
        missing = sorted(problem_trip_ids.difference(persisted_trip_ids))
        extra = sorted(persisted_trip_ids.difference(problem_trip_ids))
        raise ValueError(
            "Persisted day-ahead result does not match the current trip scope: "
            f"missing={missing}, extra={extra}"
        )

    metadata = dict(serialized_result.get("metadata") or {})
    metadata.update(
        {
            "source": "persisted_day_ahead_optimization_result",
            "charging_recomputed_by_hourly_reoptimizer": True,
        }
    )
    plan = AssignmentPlan(
        duties=tuple(duties),
        served_trip_ids=served_trip_ids,
        unserved_trip_ids=unserved_trip_ids,
        metadata=metadata,
    )
    vehicle_by_id = {
        str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles
    }
    duty_validator = DutyValidator()
    connection_engine = FeasibilityEngine()
    for duty in plan.duties:
        vehicle_id = plan.vehicle_id_for_duty(duty.duty_id)
        vehicle = vehicle_by_id.get(vehicle_id)
        if vehicle is None:
            raise ValueError(
                f"Persisted duty {duty.duty_id!r} maps to unknown vehicle "
                f"{vehicle_id!r}"
            )
        duty_type = str(duty.vehicle_type or "").strip().upper()
        vehicle_type = str(vehicle.vehicle_type or "").strip().upper()
        if duty_type and duty_type != vehicle_type:
            raise ValueError(
                f"Persisted duty {duty.duty_id!r} has vehicle type {duty_type!r}, "
                f"but mapped vehicle {vehicle_id!r} has type {vehicle_type!r}"
            )
        validation = duty_validator.validate_vehicle_duty(duty, dispatch_context)
        if not validation.valid:
            raise ValueError(
                f"Persisted duty {duty.duty_id!r} violates current dispatch rules: "
                f"{list(validation.errors)}"
            )
        for previous_leg, next_leg in zip(duty.legs, duty.legs[1:]):
            connection = connection_engine.can_connect(
                previous_leg.trip,
                next_leg.trip,
                dispatch_context,
                duty.vehicle_type,
            )
            stored_deadhead_min = int(next_leg.deadhead_from_prev_min)
            canonical_deadhead_min = int(connection.deadhead_time_min or 0)
            if stored_deadhead_min != canonical_deadhead_min:
                raise ValueError(
                    f"Persisted duty {duty.duty_id!r} has deadhead "
                    f"{stored_deadhead_min} min before trip "
                    f"{next_leg.trip.trip_id!r}, but current canonical rules "
                    f"require {canonical_deadhead_min} min"
                )
    return plan


class RollingReoptimizer:
    def __init__(self) -> None:
        self._engine = OptimizationEngine()

    def reoptimize(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
        current_min: int,
        actual_soc: Optional[Mapping[str, float]] = None,
        actual_bess_soc_kwh: Optional[Mapping[str, float]] = None,
    ):
        problem = self._freeze_bev_terminal_soc_targets(problem)
        problem = self._freeze_bess_terminal_soc_targets(problem)
        if actual_soc:
            problem = self._apply_actual_soc(problem, actual_soc)
        if actual_bess_soc_kwh:
            problem = self._apply_actual_bess_soc(problem, actual_bess_soc_kwh)

        if problem.baseline_plan is not None:
            locked_plan = lock_started_trips(problem.baseline_plan, current_min)
            problem = replace(
                problem,
                baseline_plan=locked_plan,
                metadata=dict(problem.metadata),
            )
        return self._engine.solve(problem, config)

    def reoptimize_charging_hour(
        self,
        problem: CanonicalOptimizationProblem,
        day_ahead_plan: AssignmentPlan,
        config: OptimizationConfig,
        current_min: int,
        *,
        actual_soc: Optional[Mapping[str, float]] = None,
        actual_bess_soc_kwh: Optional[Mapping[str, float]] = None,
        observed_on_peak_kw_by_depot: Optional[Mapping[str, float]] = None,
        observed_off_peak_kw_by_depot: Optional[Mapping[str, float]] = None,
        active_charge_session_vehicle_ids: tuple[str, ...] = (),
        execution_minutes: int = 60,
        bess_terminal_policy: str = "scenario",
    ):
        """Return a remaining-day charging plan for receding-horizon control.

        The vehicle-trip assignment is fixed to ``day_ahead_plan``.  This is a
        receding-horizon charging controller, not a second vehicle-scheduling
        solve.  Only the first ``execution_minutes`` of the returned plan is
        actionable before the next state update.  Calls after the service-day
        start require measured vehicle and BESS state plus observed demand
        peaks so past energy and demand charge cannot be silently forgotten.
        """

        timestep_min = max(int(problem.scenario.timestep_min), 1)
        service_start = horizon_start_min(problem)
        service_current = int(current_min)
        if service_current < service_start:
            service_current += 24 * 60
        if (service_current - service_start) % timestep_min != 0:
            raise ValueError(
                "Hourly charging re-optimization must start on a model slot boundary"
            )
        execution_minutes = int(execution_minutes)
        if execution_minutes <= 0 or execution_minutes % timestep_min != 0:
            raise ValueError(
                "execution_minutes must be a positive multiple of timestep_min"
            )

        assigned_vehicle_ids = set(day_ahead_plan.vehicle_paths())
        electric_vehicle_ids = {
            str(vehicle.vehicle_id)
            for vehicle in problem.vehicles
            if str(vehicle.vehicle_id) in assigned_vehicle_ids
            and str(vehicle.vehicle_type).upper() in {"BEV", "PHEV", "FCEV"}
        }
        enabled_bess_depots = {
            str(depot_id)
            for depot_id, asset in dict(problem.depot_energy_assets or {}).items()
            if bool(getattr(asset, "bess_enabled", False))
        }
        if service_current > service_start:
            missing_vehicle_soc = sorted(
                electric_vehicle_ids.difference(set(actual_soc or {}))
            )
            missing_bess_soc = sorted(
                enabled_bess_depots.difference(set(actual_bess_soc_kwh or {}))
            )
            missing_on_peak = sorted(
                set(problem.depot_energy_assets).difference(
                    set(observed_on_peak_kw_by_depot or {})
                )
            )
            missing_off_peak = sorted(
                set(problem.depot_energy_assets).difference(
                    set(observed_off_peak_kw_by_depot or {})
                )
            )
            missing_state = {
                "vehicle_soc": missing_vehicle_soc,
                "bess_soc": missing_bess_soc,
                "observed_on_peak": missing_on_peak,
                "observed_off_peak": missing_off_peak,
            }
            if any(missing_state.values()):
                raise ValueError(
                    "Hourly charging re-optimization is missing measured state: "
                    f"{missing_state}"
                )

        vehicle_by_id = {
            str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles
        }
        for vehicle_id, raw in dict(actual_soc or {}).items():
            vehicle = vehicle_by_id.get(str(vehicle_id))
            if vehicle is None:
                raise ValueError(
                    f"Measured SOC references unknown vehicle {vehicle_id!r}"
                )
            capacity = max(float(vehicle.battery_capacity_kwh or 0.0), 0.0)
            value = float(raw)
            value_kwh = value * capacity if 0.0 <= value <= 1.0 else value
            if (
                not math.isfinite(value_kwh)
                or value_kwh < 0.0
                or (capacity > 0.0 and value_kwh > capacity)
            ):
                raise ValueError(
                    f"Measured SOC for {vehicle_id!r} is outside [0, {capacity}] kWh"
                )
        known_depot_ids = set(map(str, problem.depot_energy_assets))
        normalized_active_charge_session_vehicle_ids = tuple(
            sorted(
                {
                    str(vehicle_id)
                    for vehicle_id in active_charge_session_vehicle_ids
                    if str(vehicle_id).strip()
                }
            )
        )
        unknown_active_charge_session_vehicle_ids = sorted(
            set(normalized_active_charge_session_vehicle_ids).difference(
                electric_vehicle_ids
            )
        )
        if unknown_active_charge_session_vehicle_ids:
            raise ValueError(
                "Active charge-session state references a vehicle outside "
                "the fixed electric assignment: "
                f"{unknown_active_charge_session_vehicle_ids}"
            )
        for label, observed_peaks in (
            ("on-peak", observed_on_peak_kw_by_depot or {}),
            ("off-peak", observed_off_peak_kw_by_depot or {}),
        ):
            unknown_depots = sorted(
                set(map(str, observed_peaks)).difference(known_depot_ids)
            )
            if unknown_depots:
                raise ValueError(
                    f"Measured {label} demand peak references unknown depots: "
                    f"{unknown_depots}"
                )
            invalid_depots = sorted(
                str(depot_id)
                for depot_id, raw in observed_peaks.items()
                if not math.isfinite(float(raw)) or float(raw) < 0.0
            )
            if invalid_depots:
                raise ValueError(
                    f"Measured {label} demand peak must be finite and "
                    f"non-negative for depots: {invalid_depots}"
                )
        problem = self._freeze_bev_terminal_soc_targets(problem)
        problem = self._freeze_bess_terminal_soc_targets(problem)
        if actual_soc:
            problem = self._apply_actual_soc(problem, actual_soc)
        if actual_bess_soc_kwh:
            problem = self._apply_actual_bess_soc(problem, actual_bess_soc_kwh)
        problem = self._apply_bess_terminal_policy(problem, bess_terminal_policy)

        rolling_config = replace(
            config,
            mode=OptimizationMode.MILP,
            phase="phase1_charging_only",
            requested_phase="phase1_charging_only",
            resolved_phase="phase1_charging_only",
            executed_phase="phase1_charging_only",
            thesis_mode=False,
            fixed_assignment=day_ahead_plan,
            rolling_current_min=int(current_min),
            rolling_horizon_policy=ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT,
            rolling_execution_minutes=execution_minutes,
            rolling_observed_on_peak_kw_by_depot=dict(
                observed_on_peak_kw_by_depot or {}
            ),
            rolling_observed_off_peak_kw_by_depot=dict(
                observed_off_peak_kw_by_depot or {}
            ),
            rolling_active_charge_session_vehicle_ids=(
                normalized_active_charge_session_vehicle_ids
            ),
        )
        return self._engine.solve(problem, rolling_config)

    @staticmethod
    def _freeze_bev_terminal_soc_targets(
        problem: CanonicalOptimizationProblem,
    ) -> CanonicalOptimizationProblem:
        """Keep the day-start terminal target fixed across hourly updates.

        Measured SOC becomes the rolling model's current state, but it must not
        redefine a ``return_to_initial`` target. Otherwise the required
        end-of-day energy would fall every time the controller is rerun.
        """

        metadata = dict(problem.metadata or {})
        existing = metadata.get(BEV_TERMINAL_SOC_TARGET_KWH_BY_VEHICLE_KEY)
        if isinstance(existing, Mapping):
            return problem
        targets: dict[str, float] = {}
        for vehicle in problem.vehicles:
            if not is_electric_vehicle(problem, vehicle):
                continue
            target = effective_final_soc_target_kwh(problem, vehicle)
            if target is not None:
                targets[str(vehicle.vehicle_id)] = float(target)
        if not targets:
            return problem
        metadata[BEV_TERMINAL_SOC_TARGET_KWH_BY_VEHICLE_KEY] = targets
        metadata["bev_terminal_soc_target_source"] = (
            "day_start_problem_before_rolling_state_update"
        )
        return replace(problem, metadata=metadata)

    @staticmethod
    def _freeze_bess_terminal_soc_targets(
        problem: CanonicalOptimizationProblem,
    ) -> CanonicalOptimizationProblem:
        """Keep stationary-battery day-start targets fixed while SOC changes."""

        assets = dict(problem.depot_energy_assets or {})
        updated_assets = dict(assets)
        frozen_targets: dict[str, float] = {}
        for depot_id, asset in assets.items():
            target = resolve_bess_terminal_soc_target_kwh(
                policy=asset.bess_terminal_soc_policy,
                initial_soc_kwh=asset.bess_initial_soc_kwh,
                configured_target_kwh=asset.bess_terminal_soc_target_kwh,
                terminal_soc_floor_kwh=asset.bess_terminal_soc_min_kwh,
                maximum_soc_kwh=(
                    asset.bess_soc_max_kwh or asset.bess_energy_kwh
                ),
            )
            if target is None:
                continue
            depot_key = str(depot_id)
            frozen_targets[depot_key] = float(target)
            updated_assets[depot_key] = replace(
                asset,
                bess_terminal_soc_policy="fixed_target",
                bess_terminal_soc_target_kwh=float(target),
            )
        if not frozen_targets:
            return problem
        metadata = dict(problem.metadata or {})
        metadata["bess_terminal_soc_target_kwh_by_depot"] = frozen_targets
        metadata["bess_terminal_soc_target_source"] = (
            "day_start_problem_before_rolling_state_update"
        )
        return replace(
            problem,
            depot_energy_assets=updated_assets,
            metadata=metadata,
        )

    def _apply_actual_soc(
        self,
        problem: CanonicalOptimizationProblem,
        actual_soc: Mapping[str, float],
    ) -> CanonicalOptimizationProblem:
        normalized_soc = {
            str(vehicle_id): value for vehicle_id, value in actual_soc.items()
        }
        known_vehicle_ids = {
            str(vehicle.vehicle_id) for vehicle in problem.vehicles
        }
        unknown_vehicle_ids = sorted(
            set(normalized_soc).difference(known_vehicle_ids)
        )
        if unknown_vehicle_ids:
            raise ValueError(
                "Measured SOC references unknown vehicles: "
                f"{unknown_vehicle_ids}"
            )

        applied = 0
        updated_vehicles = []
        for vehicle in problem.vehicles:
            vehicle_id = str(vehicle.vehicle_id)
            if vehicle_id not in normalized_soc:
                updated_vehicles.append(vehicle)
                continue
            raw = float(normalized_soc[vehicle_id])
            capacity = float(vehicle.battery_capacity_kwh or 0.0)
            if 0.0 <= raw <= 1.0 and capacity > 0.0:
                value = raw * capacity
            else:
                value = raw
            if (
                not math.isfinite(value)
                or value < 0.0
                or (capacity > 0.0 and value > capacity)
            ):
                raise ValueError(
                    f"Measured SOC for {vehicle_id!r} is outside "
                    f"[0, {capacity}] kWh"
                )
            updated_vehicles.append(replace(vehicle, initial_soc=value))
            applied += 1

        new_metadata = dict(problem.metadata)
        new_metadata["rolling_actual_soc_applied_count"] = int(applied)
        return replace(
            problem,
            vehicles=tuple(updated_vehicles),
            metadata=new_metadata,
        )

    def _apply_actual_bess_soc(
        self,
        problem: CanonicalOptimizationProblem,
        actual_bess_soc_kwh: Mapping[str, float],
    ) -> CanonicalOptimizationProblem:
        assets = dict(problem.depot_energy_assets or {})
        applied = 0
        for depot_id, raw in actual_bess_soc_kwh.items():
            asset = assets.get(str(depot_id))
            if asset is None:
                raise ValueError(
                    f"Measured BESS SOC references unknown depot {depot_id!r}"
                )
            lower = max(float(asset.bess_soc_min_kwh or 0.0), 0.0)
            upper = max(
                float(asset.bess_soc_max_kwh or asset.bess_energy_kwh or 0.0),
                lower,
            )
            value = float(raw)
            if (
                not math.isfinite(value)
                or value < lower - _SOC_BOUNDARY_TOLERANCE_KWH
                or value > upper + _SOC_BOUNDARY_TOLERANCE_KWH
            ):
                raise ValueError(
                    f"Measured BESS SOC for {depot_id!r} is outside "
                    f"[{lower}, {upper}] kWh"
                )
            # A solver handoff can differ from an active bound by a few ULPs
            # (for example 119.99999999999999 for a 120 kWh lower bound).
            # Clamp only values already within the shared numerical tolerance;
            # materially out-of-range measurements remain hard failures.
            value = min(max(value, lower), upper)
            assets[str(depot_id)] = replace(asset, bess_initial_soc_kwh=value)
            applied += 1
        metadata = dict(problem.metadata or {})
        metadata["rolling_actual_bess_soc_applied_count"] = int(applied)
        return replace(problem, depot_energy_assets=assets, metadata=metadata)

    @staticmethod
    def _apply_bess_terminal_policy(
        problem: CanonicalOptimizationProblem,
        policy: str,
    ) -> CanonicalOptimizationProblem:
        normalized = str(policy or "scenario").strip().lower()
        if normalized == "scenario":
            return problem
        if normalized != "minimum_only":
            raise ValueError(
                "bess_terminal_policy must be 'scenario' or 'minimum_only'"
            )
        assets = {
            str(depot_id): replace(
                asset,
                bess_terminal_soc_policy="minimum_only",
                bess_terminal_soc_target_kwh=0.0,
            )
            for depot_id, asset in dict(problem.depot_energy_assets or {}).items()
        }
        metadata = dict(problem.metadata or {})
        metadata["rolling_bess_terminal_policy"] = "minimum_only"
        return replace(problem, depot_energy_assets=assets, metadata=metadata)
