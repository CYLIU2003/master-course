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
