from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from src.dispatch.models import ValidationResult, VehicleDuty
from src.dispatch.validator import DutyValidator

from .problem import AssignmentPlan, CanonicalOptimizationProblem


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

        soc_errors = self._evaluate_soc(problem, plan)
        errors.extend(soc_errors)

        feasible = not errors and not uncovered
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

        charge_by_vehicle: Dict[str, Dict[int, float]] = {}
        for slot in plan.charging_slots:
            vid = str(slot.vehicle_id)
            by_slot = charge_by_vehicle.setdefault(vid, {})
            by_slot[int(slot.slot_index)] = by_slot.get(int(slot.slot_index), 0.0) + max(float(slot.charge_kw or 0.0), 0.0)

        for duty in plan.duties:
            vehicle_id = self._vehicle_id_from_duty_id(duty.duty_id)
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

                req_dep = float(trip.required_soc_departure_percent or 0.0)
                req_dep_kwh = req_dep * capacity if req_dep <= 1.0 else (req_dep / 100.0) * capacity
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

    def _vehicle_id_from_duty_id(self, duty_id: str) -> str:
        if duty_id.startswith("milp_") and len(duty_id) > 5:
            return duty_id[5:]
        return duty_id

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
