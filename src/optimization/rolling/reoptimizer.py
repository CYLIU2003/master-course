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
    vehicle_reserve_soc_kwh,
    vehicle_maximum_soc_kwh,
)
from src.optimization.common.bess_terminal_policy import (
    resolve_bess_terminal_soc_target_kwh,
)
from src.optimization.common.bess_reserve_policy import bess_reserve_targets
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
        actual_vehicle_fuel_l: Optional[Mapping[str, float]] = None,
        actual_vehicle_positions: Optional[Mapping[str, Mapping[str, Any]]] = None,
        connected_charger_by_vehicle: Optional[Mapping[str, str]] = None,
        observed_on_peak_kw_by_depot: Optional[Mapping[str, float]] = None,
        observed_off_peak_kw_by_depot: Optional[Mapping[str, float]] = None,
        active_charge_session_vehicle_ids: tuple[str, ...] = (),
        execution_minutes: int = 60,
        bess_terminal_policy: str = "scenario",
        lookahead_hours: int | None = None,
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
        if lookahead_hours is not None and lookahead_hours not in (24,48,72,168):
            raise ValueError('Rolling lookahead must be 24, 48, 72, or 168 hours')
        if execution_minutes <= 0 or execution_minutes % timestep_min != 0:
            raise ValueError(
                "execution_minutes must be a positive multiple of timestep_min"
            )

        assigned_vehicle_ids = set(day_ahead_plan.vehicle_paths())
        daily_return = bool(getattr(problem.dispatch_context, "daily_return_depot_id", ""))
        if daily_return:
            from .vehicle_execution import vehicle_positions_at
            expected_positions = vehicle_positions_at(problem, day_ahead_plan, service_current)
            ice_ids = {str(vehicle.vehicle_id) for vehicle in problem.vehicles if not is_electric_vehicle(problem, vehicle)}
            if service_current > service_start:
                if set(actual_vehicle_fuel_l or {}) != ice_ids:
                    raise ValueError("Hourly daily-return execution requires the exact ICE fuel handoff")
                if dict(actual_vehicle_positions or {}) != expected_positions:
                    raise ValueError("Hourly vehicle position/in-progress state disagrees with the fixed native schedule")
            elif actual_vehicle_positions and dict(actual_vehicle_positions) != expected_positions:
                raise ValueError("Initial vehicle positions disagree with the depot start")
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
            value_kwh = value
            minimum = vehicle_reserve_soc_kwh(problem, vehicle, cap_kwh=capacity)
            maximum = vehicle_maximum_soc_kwh(problem, vehicle, cap_kwh=capacity)
            if (
                not math.isfinite(value_kwh)
                or value_kwh < minimum-_SOC_BOUNDARY_TOLERANCE_KWH
                or value_kwh > maximum+_SOC_BOUNDARY_TOLERANCE_KWH
            ):
                raise ValueError(
                    f"Measured SOC for {vehicle_id!r} is outside [{minimum}, {maximum}] kWh"
                )
        known_depot_ids = set(map(str, problem.depot_energy_assets))
        for vehicle_id, raw in dict(actual_vehicle_fuel_l or {}).items():
            vehicle = vehicle_by_id.get(str(vehicle_id))
            if vehicle is None or is_electric_vehicle(problem, vehicle):
                raise ValueError(f"Measured fuel references a non-ICE vehicle: {vehicle_id}")
            value = float(raw)
            if isinstance(raw, bool) or not math.isfinite(value) or not float(vehicle.fuel_reserve_l or 0.0)-1e-6 <= value <= float(vehicle.fuel_tank_capacity_l or 0.0)+1e-6:
                raise ValueError(f"Measured fuel is outside physical bounds: {vehicle_id}")
        charger_by_id = {str(charger.charger_id):charger for charger in problem.chargers}
        for vehicle_id, charger_id in dict(connected_charger_by_vehicle or {}).items():
            charger = charger_by_id.get(str(charger_id))
            position = (actual_vehicle_positions or {}).get(str(vehicle_id), {})
            if str(vehicle_id) not in electric_vehicle_ids or charger is None:
                raise ValueError("Measured charger connection references an unknown vehicle or charger")
            if daily_return and not problem.dispatch_context.locations_equivalent(str(position.get("location_id") or ""), str(charger.depot_id)):
                raise ValueError("Measured charger connection disagrees with vehicle location")
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
        if daily_return and set(normalized_active_charge_session_vehicle_ids).difference(connected_charger_by_vehicle or {}):
            raise ValueError("Active charge sessions require their physical charger connections")
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
        problem = self._apply_window_terminal_targets(
            problem, day_ahead_plan, service_current, lookahead_hours,
            bess_terminal_policy=bess_terminal_policy,
        )
        if actual_soc:
            problem = self._apply_actual_soc(problem, actual_soc, unit="kwh")
        if actual_bess_soc_kwh:
            problem = self._apply_actual_bess_soc(problem, actual_bess_soc_kwh)
        if actual_vehicle_fuel_l:
            problem = replace(problem, vehicles=tuple(
                replace(vehicle, initial_fuel_l=float(actual_vehicle_fuel_l[str(vehicle.vehicle_id)]))
                if str(vehicle.vehicle_id) in actual_vehicle_fuel_l else vehicle for vehicle in problem.vehicles))
        if daily_return:
            problem = replace(problem, metadata={**problem.metadata,
                "rolling_actual_vehicle_positions": dict(actual_vehicle_positions or {}),
                "rolling_actual_vehicle_fuel_l": dict(actual_vehicle_fuel_l or {})})
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
            rolling_lookahead_hours=lookahead_hours,
            rolling_observed_on_peak_kw_by_depot=dict(
                observed_on_peak_kw_by_depot or {}
            ),
            rolling_observed_off_peak_kw_by_depot=dict(
                observed_off_peak_kw_by_depot or {}
            ),
            rolling_active_charge_session_vehicle_ids=(
                normalized_active_charge_session_vehicle_ids
            ),
            rolling_connected_charger_by_vehicle=dict(connected_charger_by_vehicle or {}),
        )
        return self._engine.solve(problem, rolling_config)

    @staticmethod
    def _apply_window_terminal_targets(problem: CanonicalOptimizationProblem, plan: AssignmentPlan,
                                       current_min: int, lookahead_hours: int | None, *,
                                       bess_terminal_policy: str = "scenario") -> CanonicalOptimizationProblem:
        reserve_targets = bess_reserve_targets(problem)
        if reserve_targets and str(bess_terminal_policy or "scenario").strip().lower() != "scenario":
            raise ValueError("BESS reserve must retain the scenario evaluation target")
        policy = problem.metadata.get("rolling_window_terminal_policy", "return_to_evaluation_initial")
        if policy == "return_to_evaluation_initial":
            return problem
        if policy != "day_ahead_boundary_state":
            raise ValueError(f"Unsupported rolling-window terminal policy: {policy}")
        end_min = horizon_start_min(problem)+problem.scenario.planning_days*1440
        window_end = min(end_min,current_min+lookahead_hours*60) if lookahead_hours is not None else end_min
        if window_end >= end_min:
            return problem
        boundary = (window_end-horizon_start_min(problem))//problem.scenario.timestep_min
        charge_slots_by_vehicle: dict[str, set[int]] = {}
        for charge in plan.charging_slots:
            if float(charge.charge_kw) > 1.0e-6:
                charge_slots_by_vehicle.setdefault(str(charge.vehicle_id), set()).add(
                    int(charge.slot_index)
                )
        continuation_slots: dict[str, int] = {}
        for vid, charge_slots in charge_slots_by_vehicle.items():
            if boundary - 1 not in charge_slots:
                continue
            next_slot = boundary
            while next_slot in charge_slots:
                next_slot += 1
            if next_slot > boundary:
                continuation_slots[vid] = next_slot - boundary
        targets = {}
        vehicles = {str(vehicle.vehicle_id):vehicle for vehicle in problem.vehicles}
        for vid in plan.vehicle_paths():
            if not is_electric_vehicle(problem,vehicles[vid]):
                continue
            trace = plan.vehicle_soc_kwh_by_vehicle_slot.get(vid,{})
            if boundary not in trace:
                raise ValueError(f"Day-ahead terminal reference lacks vehicle {vid} at boundary {boundary}")
            targets[vid] = float(trace[boundary])
        assets = dict(problem.depot_energy_assets)
        minimum_only_bess = str(bess_terminal_policy or "scenario").strip().lower() == "minimum_only"
        for depot, asset in assets.items():
            if not asset.bess_enabled:
                continue
            if depot in reserve_targets:
                # Use a reachable, invariant boundary under PV shortfall. BEV
                # boundaries still follow the fixed day-ahead charging plan.
                assets[depot] = replace(
                    asset, bess_terminal_soc_policy="fixed_target",
                    bess_terminal_soc_target_kwh=reserve_targets[depot],
                    bess_terminal_soc_min_kwh=float(asset.bess_soc_min_kwh),
                )
                continue
            # A minimum-only window has no BESS reference equality. Building a
            # discarded fixed target here can reject harmless solver roundoff
            # before the explicit rolling policy is applied below.
            if minimum_only_bess:
                assets[depot] = replace(
                    asset,
                    bess_terminal_soc_policy="minimum_only",
                    bess_terminal_soc_target_kwh=0.0,
                    bess_terminal_soc_min_kwh=float(asset.bess_soc_min_kwh or 0.0),
                )
                continue
            trace = plan.bess_soc_kwh_by_depot_slot.get(depot,{})
            if boundary-1 not in trace:
                raise ValueError(f"Day-ahead terminal reference lacks BESS {depot} at boundary {boundary}")
            assets[depot] = replace(asset,bess_terminal_soc_policy="fixed_target",
                                    bess_terminal_soc_target_kwh=float(trace[boundary-1]),
                                    # The period-end floor is restored at the
                                    # evaluation end. An intermediate reference
                                    # is governed by the physical SOC floor;
                                    # daily balance retains its frozen target.
                                    bess_terminal_soc_min_kwh=float(asset.bess_soc_min_kwh or 0.0))
        return replace(problem,depot_energy_assets=assets,metadata={**problem.metadata,
            BEV_TERMINAL_SOC_TARGET_KWH_BY_VEHICLE_KEY:targets,
            "rolling_window_terminal_reference":{"policy":policy,"boundary_slot":boundary,
                **({"bess_policy": "evaluation_target_zero_pv",
                    "bess_target_kwh_by_depot": reserve_targets} if reserve_targets else {}),
                "charge_session_continuation_slots_by_vehicle":continuation_slots,
                "source":"fixed_day_ahead_forecast_plan_not_future_actuals"}})

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
        from src.optimization.common.bess_reserve_policy import freeze_bess_terminal_soc_targets
        return freeze_bess_terminal_soc_targets(problem)

    def _apply_actual_soc(
        self,
        problem: CanonicalOptimizationProblem,
        actual_soc: Mapping[str, float],
        *,
        unit: str | None = None,
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
            if (unit or getattr(vehicle, "soc_input_unit", "legacy_ratio_or_kwh")) != "kwh" and 0.0 <= raw <= 1.0 and capacity > 0.0:
                value = raw * capacity
            else:
                value = raw
            minimum = vehicle_reserve_soc_kwh(problem, vehicle, cap_kwh=capacity)
            maximum = vehicle_maximum_soc_kwh(problem, vehicle, cap_kwh=capacity)
            if (
                not math.isfinite(value)
                or value < minimum-_SOC_BOUNDARY_TOLERANCE_KWH
                or value > maximum+_SOC_BOUNDARY_TOLERANCE_KWH
            ):
                raise ValueError(
                    f"Measured SOC for {vehicle_id!r} is outside "
                    f"[{minimum}, {maximum}] kWh"
                )
            updated_vehicles.append(replace(vehicle, initial_soc=value, soc_input_unit="kwh"))
            applied += 1

        new_metadata = dict(problem.metadata)
        new_metadata["rolling_actual_soc_applied_count"] = int(applied)
        new_metadata["rolling_actual_soc_kwh"] = {
            str(vehicle.vehicle_id): float(vehicle.initial_soc)
            for vehicle in updated_vehicles if str(vehicle.vehicle_id) in normalized_soc
        }
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
