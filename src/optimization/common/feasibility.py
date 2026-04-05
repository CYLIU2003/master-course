from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from src.dispatch.models import ValidationResult, VehicleDuty
from src.dispatch.validator import DutyValidator

from .problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    normalize_required_soc_departure_ratio,
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
            warnings.append(
                "Uncovered trips: " + ", ".join(uncovered)
            )
        if duplicates:
            errors.append(
                "Duplicate trip assignments: " + ", ".join(sorted(set(duplicates)))
            )

        invalid_duties = tuple(
            duty_id for duty_id, result in validation.items() if not result.valid
        )

        errors.extend(self._evaluate_vehicle_fragment_integrity(problem, plan))
        errors.extend(self._evaluate_startup_deadhead(problem, plan))

        soc_errors = self._evaluate_soc(problem, plan)
        errors.extend(soc_errors)

        # Unserved trips are a penalized soft term in the objective, so they
        # should remain warnings rather than forcing the candidate to be marked
        # infeasible.
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

        charge_by_vehicle: Dict[str, Dict[int, float]] = {}
        for slot in plan.charging_slots:
            vid = str(slot.vehicle_id)
            by_slot = charge_by_vehicle.setdefault(vid, {})
            by_slot[int(slot.slot_index)] = by_slot.get(int(slot.slot_index), 0.0) + max(float(slot.charge_kw or 0.0), 0.0)

        for duty in plan.duties:
            vehicle_id = duty_vehicle_map.get(duty.duty_id, duty.duty_id)
            vehicle = vehicle_by_id.get(vehicle_id)
            vtype = type_by_id.get(duty.vehicle_type)
            powertrain = str((vtype.powertrain_type if vtype else duty.vehicle_type) or "").upper()
            if powertrain not in {"BEV", "PHEV", "FCEV"}:
                continue

            capacity = float((vehicle.battery_capacity_kwh if vehicle else None) or (vtype.battery_capacity_kwh if vtype else 0.0) or 0.0)
            if capacity <= 0.0:
                continue
            reserve = float((vehicle.reserve_soc if vehicle else None) or (vtype.reserve_soc if vtype else None) or (0.15 * capacity))
            soc = float((vehicle.initial_soc if vehicle else None) or (0.8 * capacity))
            if soc <= 1.0:
                soc = soc * capacity
            soc = min(max(soc, 0.0), capacity)

            last_slot = -1
            for leg in duty.legs:
                trip = trip_by_id.get(leg.trip.trip_id)
                if trip is None:
                    continue

                dep_slot = self._slot_index(problem, leg.trip.departure_min)
                for slot_idx in sorted(k for k in charge_by_vehicle.get(vehicle_id, {}) if last_slot < k <= dep_slot):
                    soc = min(capacity, soc + charge_by_vehicle[vehicle_id][slot_idx] * dt_h * 0.95)
                last_slot = dep_slot

                req_dep_ratio = normalize_required_soc_departure_ratio(
                    trip.required_soc_departure_percent,
                    treat_values_le_one_as_percent=(
                        str((problem.metadata or {}).get("required_soc_departure_unit") or "").strip().lower()
                        == "percent_0_100"
                    ),
                )
                req_dep_kwh = float(req_dep_ratio or 0.0) * capacity
                min_departure = max(reserve, req_dep_kwh)
                if soc + 1.0e-6 < min_departure:
                    errors.append(
                        f"[SOC] duty={duty.duty_id} trip={trip.trip_id} departure SOC {soc:.2f} < required {min_departure:.2f}"
                    )

                trip_energy = max(float(trip.energy_kwh or 0.0), 0.0)
                deadhead_energy = self._deadhead_energy_kwh(problem, leg.deadhead_from_prev_min, trip)
                soc -= (trip_energy + deadhead_energy)
                if soc < -1.0e-6:
                    errors.append(
                        f"[SOC] duty={duty.duty_id} trip={trip.trip_id} post-trip SOC {soc:.2f} < 0"
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

        context = problem.dispatch_context
        get_deadhead_min = getattr(context, "get_deadhead_min", None)
        locations_equivalent = getattr(context, "locations_equivalent", None)
        has_location_data = getattr(context, "has_location_data", None)
        if not callable(get_deadhead_min):
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
            origin_key = str(
                getattr(first_leg.trip, "origin_stop_id", "")
                or getattr(first_leg.trip, "origin", "")
                or ""
            ).strip()
            if not home_depot_id or not origin_key:
                continue
            equivalent = bool(callable(locations_equivalent) and locations_equivalent(home_depot_id, origin_key))
            required_deadhead_min = max(int(get_deadhead_min(home_depot_id, origin_key) or 0), 0)
            if required_deadhead_min <= 0 and not equivalent:
                if callable(has_location_data) and has_location_data(home_depot_id):
                    errors.append(
                        f"[STARTUP] duty={duty.duty_id} vehicle={vehicle_id} has no deadhead path from depot '{home_depot_id}' to first origin '{origin_key}'"
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
        max_start_fragments = int(problem.metadata.get("max_start_fragments_per_vehicle") or 1)
        max_end_fragments = int(problem.metadata.get("max_end_fragments_per_vehicle") or 1)
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
            ordered = sorted(
                duties,
                key=lambda duty: (
                    duty.legs[0].trip.departure_min if duty.legs else 10**9,
                    duty.legs[-1].trip.arrival_min if duty.legs else 10**9,
                    duty.duty_id,
                ),
            )
            for index, prev_duty in enumerate(ordered):
                for next_duty in ordered[index + 1 :]:
                    if not self._duties_overlap_in_time(prev_duty, next_duty):
                        continue
                    errors.append(
                        f"[FRAGMENT] vehicle={vehicle_id} has overlapping fragments {prev_duty.duty_id} and {next_duty.duty_id}"
                    )
        return errors

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
