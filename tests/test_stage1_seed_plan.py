"""A Stage 1 seed is a MIP start only: rejected seeds stop the run, and the objective ignores it."""
import inspect
from types import SimpleNamespace

from bff.routers.optimization import RunOptimizationBody
from src.optimization.common.problem import OptimizationConfig
from src.optimization.milp import seed_snapshot, solver_adapter


def test_request_carries_rolling_limit_and_embedded_seed():
    body = RunOptimizationBody(rolling_time_limit_seconds=600, stage1_seed_plan={"duties": []})
    dumped = body.model_dump()
    assert dumped["rolling_time_limit_seconds"] == 600 and dumped["stage1_seed_plan"] == {"duties": []}
    defaults = RunOptimizationBody().model_dump()
    assert defaults["rolling_time_limit_seconds"] is None and defaults["stage1_seed_plan"] is None


def test_seed_is_a_separate_config_field_not_the_baseline():
    assert OptimizationConfig().stage1_seed_plan is None
    # switch cost reads problem.baseline_plan, so the seed must not be stored there.
    source = inspect.getsource(seed_snapshot.restore_stage1_seed_plan)
    assert "baseline_plan" not in source


def test_restore_marks_the_seed_source(monkeypatch):
    from src.optimization.common.problem import AssignmentPlan
    from src.optimization.rolling import reoptimizer
    monkeypatch.setattr(reoptimizer, "assignment_plan_from_serialized_result",
                        lambda problem, payload: AssignmentPlan(metadata={"duty_vehicle_map": {"d": "v"}}))
    plan = seed_snapshot.restore_stage1_seed_plan(SimpleNamespace(), {"duties": []})
    assert plan.metadata == {"duty_vehicle_map": {"d": "v"}, "source": "stage1_seed_from_prior_run"}


def test_rejected_seed_stops_the_run():
    source = inspect.getsource(solver_adapter)
    assert '"stage1_seed_plan was rejected: "' in source
