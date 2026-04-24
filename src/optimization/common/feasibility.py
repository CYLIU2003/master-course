from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from src.dispatch.feasibility import evaluate_startup_feasibility
from src.dispatch.models import ValidationResult, VehicleDuty
from src.dispatch.route_band import (
    duty_route_band_ids,
    fragment_transition_diagnostic,
    fragment_transition_is_feasible,
)
from src.dispatch.validator import DutyValidator

from .problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    day_index_for_minute,
    normalize_service_coverage_mode,
)
from .soc_helpers import (
    deadhead_energy_kwh,
    effective_final_soc_target_kwh,
    final_soc_floor_kwh,
    post_return_target_slot_index,
    return_deadhead_energy_kwh,
    return_deadhead_min_to_home,
    required_departure_soc_kwh,
    slot_index_ceil,
    trip_active_in_slot,
    trip_active_slot_indices,
    trip_energy_kwh,
    trip_slot_energy_fraction,
)


@dataclass(frozen=True)
class FeasibilityReport:
    feasible: bool
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    invalid_duties: tuple[str, ...] = ()
    uncovered_trip_ids: tuple[str, ...] = ()
    duplicate_trip_ids: tuple[str, ...] = ()
    validation: Dict[str, ValidationResult] = field(default_factory=dict)


class FeasibilityChecker:
    def __init__(self) -> None:
        self._validator = DutyValidator()

    def evaluate(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> FeasibilityReport:
        eligible_trip_ids = set(problem.eligible_trip_ids())
        service_coverage_mode = normalize_service_coverage_mode(
            getattr(problem.scenario, "service_coverage_mode", None)
            or problem.metadata.get("service_coverage_mode", "strict")
        )
        assigned_trip_ids: List[str] = []
        validation: Dict[str, ValidationResult] = {}
        errors: List[str] = []
        warnings: List[str] = []

        for duty in plan.duties:
            result = self._validator.validate_vehicle_duty(
                duty,
                problem.dispatch_context,
            )
            validation[duty.duty_id] = result
            assigned_trip_ids.extend(duty.trip_ids)
            if not result.valid:
                for message in result.errors:
                    errors.append(f"[{duty.duty_id}] {message}")

        seen: set[str] = set()
        duplicates: List[str] = []
        for trip_id in assigned_trip_ids:
            if trip_id in seen:
                duplicates.append(trip_id)
            seen.add(trip_id)

        uncovered = sorted(eligible_trip_ids - set(assigned_trip_ids))
        if uncovered:
            uncovered_message = "Uncovered trips: " + ", ".join(uncovered)
            if service_coverage_mode == "penalized":
                warnings.append(uncovered_message)
            else:
                errors.append(
                    f"strict coverage violated with {len(uncovered)} uncovered trips: "
                    + ", ".join(uncovered)
                )
        if duplicates:
            errors.append(
                "Duplicate trip assignments: " + ", ".join(sorted(set(duplicates)))
            )

        invalid_duties = tuple(
            duty_id for duty_id, result in validation.items() if not result.valid
        )

        errors.extend(self._evaluate_vehicle_fragment_integrity(problem, plan))
        errors.extend(self._evaluate_vehicle_availability(problem, plan))
        errors.extend(self._evaluate_route_band_integrity(problem, plan))
        errors.extend(self._evaluate_startup_deadhead(problem, plan))

        soc_errors = self._evaluate_soc(problem, plan)
        errors.extend(soc_errors)

        # Unserved trips are only soft when partial service is explicitly allowed.
        feasible = not errors
        return FeasibilityReport(
            feasible=feasible,
            warnings=tuple(warnings),
            errors=tuple(errors),
            invalid_duties=invalid_duties,
            uncovered_trip_ids=tuple(uncovered),
            duplicate_trip_ids=tuple(sorted(set(duplicates))),
            validation=validation,
        )

    def _evaluate_soc(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> List[str]:
        errors: List[str] = []
        if not plan.duties:
            return errors

        trip_by_id = problem.trip_by_id()
        vehicle_by_id = {v.vehicle_id: v for v in problem.vehicles}
        type_by_id = {vt.vehicle_type_id: vt for vt in problem.vehicle_types}
        dt_h = max(problem.scenario.timestep_min, 1) / 60.0
        duty_vehicle_map = plan.duty_vehicle_map()
        target_enabled = (problem.metadata or {}).get("final_soc_target_percent") is not None
        horizon_start_min = self._horizon_start_min(problem)

        charge_by_vehicle: Dict[str, Dict[int, float]] = {}
        for slot in plan.charging_slots:
            vid = str(slot.vehicle_id)
            by_slot = charge_by_vehicle.setdefault(vid, {})
            by_slot[int(slot.slot_index)] = by_slot.get(int(slot.slot_index), 0.0) + max(float(slot.charge_kw or 0.0), 0.0)

        last_duty_by_vehicle_day: Dict[tuple[str, int], str] = {}
        if target_enabled:
            for duty in plan.duties:
                if not duty.legs:
                    continue
                vehicle_id = str(duty_vehicle_map.get(duty.duty_id, duty.duty_id))
                day_idx = day_index_for_minute(int(duty.legs[-1].trip.departure_min), horizon_start_min)
                key = (vehicle_id, day_idx)
                incumbent_id = last_duty_by_vehicle_day.get(key)
                if incumbent_id is None:
                    last_duty_by_vehicle_day[key] = str(duty.duty_id)
                    continue
                incumbent = next((item for item in plan.duties if str(item.duty_id) == incumbent_id), None)
                incumbent_end = int(incumbent.legs[-1].trip.arrival_min) if incumbent and incumbent.legs else -1
                if int(duty.legs[-1].trip.arrival_min) >= incumbent_end:
                    last_duty_by_vehicle_day[key] = str(duty.duty_id)

        for duty in plan.duties:
            vehicle_id = str(duty_vehicle_map.get(duty.duty_id, duty.duty_id))
            vehicle = vehicle_by_id.get(vehicle_id)
            vtype = type_by_id.get(duty.vehicle_type)
            powertrain = str((vtype.powertrain_type if vtype else duty.vehicle_type) or "").upper()
            if powertrain not in {"BEV", "PHEV", "FCEV"}:
                continue

            capacity = float(
                (vehicle.battery_capacity_kwh if vehicle else None)
                or (vtype.battery_capacity_kwh if vtype else 0.0)
                or 0.0
            )
            if capacity <= 0.0:
                continue

            reserve = float(
                (vehicle.reserve_soc if vehicle else None)
                or (vtype.reserve_soc if vtype else None)
                or (0.15 * capacity)
            )
            soc = float((vehicle.initial_soc if vehicle else None) or (0.8 * capacity))
            if soc <= 1.0:
                soc = soc * capacity
            soc = min(max(soc, 0.0), capacity)

            active_legs: List[tuple[VehicleDuty, object, tuple[int, ...]]] = []
            for leg in duty.legs:
                trip = trip_by_id.get(leg.trip.trip_id)
                if trip is None:
                    continue
                slots = trip_active_slot_indices(problem, trip.departure_min, trip.arrival_min)
                if not slots:
                    continue
                active_legs.append((leg, trip, slots))

            if not active_legs:
                continue

            first_slot = min(slots[0] for _leg, _trip, slots in active_legs)
            last_slot = max(slots[-1] for _leg, _trip, slots in active_legs)
            vehicle_charges = charge_by_vehicle.get(vehicle_id, {})
            if vehicle_charges:
                first_slot = min(first_slot, min(vehicle_charges.keys()))
                last_slot = max(last_slot, max(vehicle_charges.keys()))

            target_kwh = None
            target_slot_idx = None
            return_event_slot_idx = None
            return_event_energy_kwh = 0.0
            return_event_applied = False
            day_idx = day_index_for_minute(int(duty.legs[-1].trip.departure_min), horizon_start_min)
            if (
                target_enabled
                and last_duty_by_vehicle_day.get((vehicle_id, day_idx)) == str(duty.duty_id)
            ):
                target_kwh = effective_final_soc_target_kwh(problem, vehicle, cap_kwh=capacity)
                last_problem_trip = trip_by_id.get(duty.legs[-1].trip.trip_id)
                if target_kwh is not None and last_problem_trip is not None:
                    return_exists, return_deadhead_min = return_deadhead_min_to_home(
                        problem,
                        vehicle,
                        last_problem_trip,
                    )
                    if not return_exists:
                        errors.append(
                            f"[SOC_TARGET] duty={duty.duty_id} vehicle={vehicle_id} final trip={last_problem_trip.trip_id} cannot return to home depot"
                        )
                    else:
                        return_complete_min = int(duty.legs[-1].trip.arrival_min) + int(return_deadhead_min)
                        return_event_slot_idx = slot_index_ceil(problem, return_complete_min)
                        return_event_energy_kwh = return_deadhead_energy_kwh(
                            problem,
                            vehicle,
                            last_problem_trip,
                        )
                        target_slot_idx = post_return_target_slot_index(problem, day_idx)
                        first_slot = min(first_slot, return_event_slot_idx)
                        last_slot = max(last_slot, target_slot_idx)
                else:
                    target_kwh = None

            soc_at_target_slot = None
            for slot_idx in range(first_slot, last_slot + 1):
                if (
                    return_event_slot_idx is not None
                    and not return_event_applied
                    and slot_idx >= return_event_slot_idx
                ):
                    soc -= return_event_energy_kwh
                    return_event_applied = True
                    floor_kwh = final_soc_floor_kwh(problem, vehicle, cap_kwh=capacity)
                    if soc + 1.0e-6 < floor_kwh:
                        errors.append(
                            f"[SOC_TARGET] duty={duty.duty_id} vehicle={vehicle_id} post-return SOC {soc:.2f} < floor {floor_kwh:.2f}"
                        )
                charge_kwh = max(float(vehicle_charges.get(slot_idx, 0.0) or 0.0), 0.0) * dt_h * 0.95
                if charge_kwh > 0.0 and any(trip_active_in_slot(problem, leg.trip.departure_min, leg.trip.arrival_min, slot_idx) for leg, _trip, _slots in active_legs):
                    errors.append(
                        f"[SOC] duty={duty.duty_id} vehicle={vehicle_id} charging occurs during active trip slot {slot_idx}"
                    )
                if (
                    charge_kwh > 0.0
                    and target_slot_idx is not None
                    and return_event_slot_idx is not None
                    and self._slot_index(problem, int(duty.legs[-1].trip.arrival_min))
                    <= slot_idx
                    < return_event_slot_idx
                ):
                    errors.append(
                        f"[SOC_TARGET] duty={duty.duty_id} vehicle={vehicle_id} charges before return deadhead completion at slot {slot_idx}"
                    )
                soc = min(capacity, soc + charge_kwh)

                for leg_index, (leg, trip, slots) in enumerate(active_legs):
                    if slot_idx not in slots:
                        continue
                    if slot_idx == slots[0]:
                        required = required_departure_soc_kwh(
                            problem,
                            vehicle,
                            trip,
                            cap_kwh=capacity,
                            final_soc_floor_kwh=reserve,
                        )
                        if soc + 1.0e-6 < required:
                            errors.append(
                                f"[SOC] duty={duty.duty_id} trip={trip.trip_id} departure SOC {soc:.2f} < required {required:.2f}"
                            )
                        if leg_index > 0:
                            prev_trip = active_legs[leg_index - 1][1]
                            soc -= deadhead_energy_kwh(problem, vehicle, prev_trip, trip)
                            if soc < -1.0e-6:
                                errors.append(
                                    f"[SOC] duty={duty.duty_id} trip={trip.trip_id} deadhead-adjusted SOC {soc:.2f} < 0"
                                )

                    trip_energy = trip_energy_kwh(problem, vehicle, trip)
                    fraction = trip_slot_energy_fraction(
                        problem,
                        trip.departure_min,
                        trip.arrival_min,
                        slot_idx,
                    )
                    soc -= trip_energy * fraction
                    if soc < -1.0e-6:
                        errors.append(
                            f"[SOC] duty={duty.duty_id} trip={trip.trip_id} post-slot SOC {soc:.2f} < 0"
                        )
                if target_slot_idx is not None and slot_idx == target_slot_idx:
                    soc_at_target_slot = soc

            if target_kwh is not None:
                checked_soc = soc if soc_at_target_slot is None else soc_at_target_slot
                if checked_soc + 1.0e-6 < target_kwh:
                    errors.append(
                        f"[SOC_TARGET] duty={duty.duty_id} vehicle={vehicle_id} post-return target SOC {checked_soc:.2f} < required {target_kwh:.2f}"
                    )

        return errors

    def _evaluate_startup_deadhead(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> List[str]:
        errors: List[str] = []
        if not plan.duties:
            return errors

        vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
        duty_vehicle_map = plan.duty_vehicle_map()
        for duty in plan.duties:
            if not duty.legs:
                continue
            vehicle_id = str(duty_vehicle_map.get(duty.duty_id) or duty.duty_id)
            vehicle = vehicle_by_id.get(vehicle_id)
            if vehicle is None:
                continue
            home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "").strip()
            first_leg = duty.legs[0]
            if not home_depot_id:
                continue
            startup_result = evaluate_startup_feasibility(
                first_leg.trip,
                problem.dispatch_context,
                home_depot_id,
            )
            required_deadhead_min = max(int(startup_result.deadhead_time_min or 0), 0)
            if not startup_result.feasible:
                errors.append(
                    f"[STARTUP] duty={duty.duty_id} vehicle={vehicle_id} "
                    f"{startup_result.reason_code}: {startup_result.reason}"
                )
                continue
            actual_deadhead_min = max(int(first_leg.deadhead_from_prev_min or 0), 0)
            if actual_deadhead_min + 1.0e-6 < required_deadhead_min:
                errors.append(
                    f"[STARTUP] duty={duty.duty_id} vehicle={vehicle_id} startup deadhead {actual_deadhead_min} < required {required_deadhead_min}"
                )
        return errors

    def _evaluate_vehicle_fragment_integrity(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> List[str]:
        errors: List[str] = []
        max_start_fragments = max(int(problem.metadata.get("max_start_fragments_per_vehicle") or 1), 1)
        max_end_fragments = max(int(problem.metadata.get("max_end_fragments_per_vehicle") or 1), 1)
        allow_same_day_depot_cycles = bool(
            getattr(problem.scenario, "allow_same_day_depot_cycles", True)
            if getattr(problem.scenario, "allow_same_day_depot_cycles", None) is not None
            else problem.metadata.get("allow_same_day_depot_cycles", True)
        )
        max_depot_cycles_per_vehicle_per_day = max(
            int(
                getattr(problem.scenario, "max_depot_cycles_per_vehicle_per_day", None)
                or problem.metadata.get("max_depot_cycles_per_vehicle_per_day", 1)
                or 1
            ),
            1,
        )
        if not allow_same_day_depot_cycles:
            max_depot_cycles_per_vehicle_per_day = 1
        horizon_start_min = self._horizon_start_min(problem)
        fixed_route_band_mode = bool((problem.metadata or {}).get("fixed_route_band_mode", False))
        duties_by_vehicle = plan.duties_by_vehicle()
        for vehicle_id, duties in duties_by_vehicle.items():
            fragment_count = len(duties)
            if fragment_count > max_start_fragments:
                errors.append(
                    f"[FRAGMENT] vehicle={vehicle_id} fragment_count={fragment_count} exceeds max_start_fragments_per_vehicle={max_start_fragments}"
                )
            if fragment_count > max_end_fragments:
                errors.append(
                    f"[FRAGMENT] vehicle={vehicle_id} fragment_count={fragment_count} exceeds max_end_fragments_per_vehicle={max_end_fragments}"
                )
            day_start_counts: Dict[int, int] = {}
            day_end_counts: Dict[int, int] = {}
            day_fragment_counts: Dict[int, int] = {}
            for duty in duties:
                if not duty.legs:
                    continue
                start_day = day_index_for_minute(int(duty.legs[0].trip.departure_min), horizon_start_min)
                end_day = day_index_for_minute(int(duty.legs[-1].trip.arrival_min), horizon_start_min)
                day_start_counts[start_day] = day_start_counts.get(start_day, 0) + 1
                day_end_counts[end_day] = day_end_counts.get(end_day, 0) + 1
                day_fragment_counts[start_day] = day_fragment_counts.get(start_day, 0) + 1
            for day_idx in sorted(set(day_start_counts) | set(day_end_counts)):
                start_count = int(day_start_counts.get(day_idx, 0))
                end_count = int(day_end_counts.get(day_idx, 0))
                fragment_count = int(day_fragment_counts.get(day_idx, 0))
                if start_count > max_depot_cycles_per_vehicle_per_day:
                    errors.append(
                        f"[FRAGMENT] vehicle={vehicle_id} day={day_idx} start_fragment_count={start_count} exceeds max_depot_cycles_per_vehicle_per_day={max_depot_cycles_per_vehicle_per_day}"
                    )
                if end_count > max_depot_cycles_per_vehicle_per_day:
                    errors.append(
                        f"[FRAGMENT] vehicle={vehicle_id} day={day_idx} end_fragment_count={end_count} exceeds max_depot_cycles_per_vehicle_per_day={max_depot_cycles_per_vehicle_per_day}"
                    )
                if fragment_count > max_depot_cycles_per_vehicle_per_day:
                    errors.append(
                        f"[FRAGMENT] vehicle={vehicle_id} day={day_idx} fragment_count={fragment_count} exceeds max_depot_cycles_per_vehicle_per_day={max_depot_cycles_per_vehicle_per_day}"
                    )
            ordered = sorted(
                duties,
                key=lambda duty: (
                    duty.legs[0].trip.departure_min if duty.legs else 10**9,
                    duty.legs[-1].trip.arrival_min if duty.legs else 10**9,
                    duty.duty_id,
                ),
            )
            vehicle = next(
                (
                    candidate
                    for candidate in problem.vehicles
                    if str(candidate.vehicle_id) == str(vehicle_id)
                ),
                None,
            )
            home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "").strip()
            for index, prev_duty in enumerate(ordered):
                for next_duty in ordered[index + 1 :]:
                    if not self._duties_overlap_in_time(prev_duty, next_duty):
                        break
                    errors.append(
                        f"[FRAGMENT] vehicle={vehicle_id} has overlapping fragments {prev_duty.duty_id} and {next_duty.duty_id}"
                    )
            for prev_duty, next_duty in zip(ordered, ordered[1:]):
                transition = fragment_transition_diagnostic(
                    prev_duty,
                    next_duty,
                    home_depot_id=home_depot_id,
                    dispatch_context=problem.dispatch_context,
                    fixed_route_band_mode=fixed_route_band_mode,
                    allow_same_day_depot_cycles=allow_same_day_depot_cycles,
                )
                if transition.feasible:
                    continue
                if allow_same_day_depot_cycles:
                    errors.append(
                        f"[FRAGMENT] vehicle={vehicle_id} transition_reason={transition.reason_code} lacks direct-or-depot transition feasibility between {prev_duty.duty_id} and {next_duty.duty_id}"
                    )
                else:
                    errors.append(
                        f"[FRAGMENT] vehicle={vehicle_id} transition_reason={transition.reason_code} lacks direct connection and same-day depot cycles are disabled between {prev_duty.duty_id} and {next_duty.duty_id}"
                    )
        return errors

    def _evaluate_vehicle_availability(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> List[str]:
        errors: List[str] = []
        vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
        for vehicle_id, duties in plan.duties_by_vehicle().items():
            vehicle = vehicle_by_id.get(str(vehicle_id))
            if vehicle is not None and not bool(getattr(vehicle, "available", True)):
                errors.append(
                    f"[AVAILABILITY] unavailable vehicle={vehicle_id} has {len(duties)} assigned duties"
                )
        return errors

    def _evaluate_route_band_integrity(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> List[str]:
        if not bool((problem.metadata or {}).get("fixed_route_band_mode", False)):
            return []
        errors: List[str] = []
        duties_by_vehicle = plan.duties_by_vehicle()
        horizon_start_min = self._horizon_start_min(problem)
        allow_same_day_depot_cycles = bool(
            getattr(problem.scenario, "allow_same_day_depot_cycles", True)
            if getattr(problem.scenario, "allow_same_day_depot_cycles", None) is not None
            else problem.metadata.get("allow_same_day_depot_cycles", True)
        )
        for duty in plan.duties:
            duty_bands = duty_route_band_ids(duty)
            if len(duty_bands) > 1:
                errors.append(
                    f"[ROUTE_BAND] duty={duty.duty_id} spans multiple route bands {list(duty_bands)}"
                )
        for vehicle_id, duties in duties_by_vehicle.items():
            ordered = sorted(
                duties,
                key=lambda duty: (
                    duty.legs[0].trip.departure_min if duty.legs else 10**9,
                    duty.legs[-1].trip.arrival_min if duty.legs else 10**9,
                    duty.duty_id,
                ),
            )
            for prev_duty, next_duty in zip(ordered, ordered[1:]):
                prev_band = duty_route_band_ids(prev_duty)
                next_band = duty_route_band_ids(next_duty)
                if not prev_band or not next_band or prev_band == next_band:
                    continue
                prev_day = day_index_for_minute(
                    int(prev_duty.legs[0].trip.departure_min),
                    horizon_start_min,
                )
                next_day = day_index_for_minute(
                    int(next_duty.legs[0].trip.departure_min),
                    horizon_start_min,
                )
                if prev_day != next_day:
                    continue
                if allow_same_day_depot_cycles:
                    errors.append(
                        f"[ROUTE_BAND] vehicle={vehicle_id} changes route band within day {prev_day} from {list(prev_band)} to {list(next_band)}"
                    )
                else:
                    errors.append(
                        f"[ROUTE_BAND] vehicle={vehicle_id} changes route band within day {prev_day} from {list(prev_band)} to {list(next_band)} while same-day depot cycles are disabled"
                    )
        return errors

    def _horizon_start_min(self, problem: CanonicalOptimizationProblem) -> int:
        start = str(getattr(problem.scenario, "horizon_start", "") or "").strip()
        if not start:
            return 0
        try:
            hh_text, mm_text = start.split(":", 1)
            return int(hh_text) * 60 + int(mm_text)
        except ValueError:
            return 0

    def _duties_overlap_in_time(
        self,
        duty_a: VehicleDuty,
        duty_b: VehicleDuty,
    ) -> bool:
        for leg_a in duty_a.legs:
            start_a = int(leg_a.trip.departure_min)
            end_a = int(leg_a.trip.arrival_min)
            for leg_b in duty_b.legs:
                start_b = int(leg_b.trip.departure_min)
                end_b = int(leg_b.trip.arrival_min)
                if start_a < end_b and start_b < end_a:
                    return True
        return False

    def _slot_index(self, problem: CanonicalOptimizationProblem, minute: int) -> int:
        step = max(problem.scenario.timestep_min, 1)
        start = 0
        if problem.scenario.horizon_start:
            try:
                hh, mm = problem.scenario.horizon_start.split(":", 1)
                start = int(hh) * 60 + int(mm)
            except ValueError:
                start = 0
        m = int(minute)
        if m < start:
            m += 24 * 60
        return max((m - start) // step, 0)

    def _deadhead_energy_kwh(self, problem: CanonicalOptimizationProblem, deadhead_min: int, trip: object) -> float:
        if deadhead_min <= 0:
            return 0.0
        speed = 18.0
        try:
            speed = float((problem.metadata or {}).get("deadhead_speed_kmh") or 18.0)
        except (TypeError, ValueError):
            speed = 18.0
        dist_km = max(float(deadhead_min), 0.0) * max(speed, 0.0) / 60.0
        trip_dist = max(float(getattr(trip, "distance_km", 0.0) or 0.0), 1.0e-6)
        per_km = max(float(getattr(trip, "energy_kwh", 0.0) or 0.0), 0.0) / trip_dist
        return max(dist_km * per_km, 0.0)
