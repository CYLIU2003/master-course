from __future__ import annotations

from types import SimpleNamespace

from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationObjectiveWeights,
    OptimizationScenario,
)


def test_strict_unserved_plan_has_infinite_objective_and_infeasible_eval() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="eval", service_coverage_mode="strict"),
        dispatch_context=SimpleNamespace(),
        trips=(),
        vehicles=(),
        objective_weights=OptimizationObjectiveWeights(unserved=10000.0),
        metadata={"service_coverage_mode": "strict"},
    )
    result = CostEvaluator().evaluate(
        problem,
        AssignmentPlan(served_trip_ids=(), unserved_trip_ids=("t1",)),
    )

    assert result.objective_value == float("inf")
    assert result.evaluation_feasible is False
    assert result.unserved_penalty == 0.0
