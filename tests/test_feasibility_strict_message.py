from __future__ import annotations

from types import SimpleNamespace

from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemTrip,
)


def test_strict_coverage_violation_message_includes_count() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="strict-message", service_coverage_mode="strict"),
        dispatch_context=SimpleNamespace(),
        trips=(
            ProblemTrip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_min=480,
                arrival_min=490,
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
        ),
        vehicles=(),
    )

    report = FeasibilityChecker().evaluate(problem, AssignmentPlan())

    assert report.feasible is False
    assert any("strict coverage violated with 1 uncovered trips" in error for error in report.errors)
