from __future__ import annotations

from types import SimpleNamespace

from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemTrip,
)


def _problem(service_coverage_mode: str) -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="feasibility-coverage",
            service_coverage_mode=service_coverage_mode,
        ),
        dispatch_context=SimpleNamespace(),
        trips=(
            ProblemTrip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_min=480,
                arrival_min=510,
                distance_km=5.0,
                allowed_vehicle_types=("ICE",),
            ),
        ),
        vehicles=(),
        metadata={"service_coverage_mode": service_coverage_mode},
    )


def test_strict_service_marks_uncovered_trip_infeasible() -> None:
    report = FeasibilityChecker().evaluate(_problem("strict"), AssignmentPlan())

    assert report.feasible is False
    assert any("uncovered trips" in error for error in report.errors)


def test_penalized_service_keeps_uncovered_trip_as_warning() -> None:
    report = FeasibilityChecker().evaluate(_problem("penalized"), AssignmentPlan())

    assert report.feasible is True
    assert any("Uncovered trips:" in warning for warning in report.warnings)
