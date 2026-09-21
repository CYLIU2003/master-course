import pytest

from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import AssignmentPlan


@pytest.mark.parametrize("status", ["time_limit", "memory_limit", "infeasible"])
def test_no_dispatch_incumbent_is_not_reported_as_a_charging_failure(status):
    plan = AssignmentPlan(metadata={"stage1_has_feasible_incumbent": False,
        "stage1_solver_status": status, "stage2_solver_status": "not_run",
        "stage2_feasible": False})
    report = FeasibilityChecker().evaluate(None, plan)
    assert not report.feasible
    assert "STAGE1_NO_INCUMBENT" in report.errors[0]
    assert status in report.errors[0]
    assert "Stage 2 charging was not run" in report.errors[0]
    assert not report.metrics["physical_trajectory_available"]


@pytest.mark.parametrize("status", ["time_limit", "infeasible"])
def test_actual_charging_failure_preserves_stage2_reason(status):
    plan = AssignmentPlan(metadata={"stage1_has_feasible_incumbent": True,
        "stage2_solver_status": status, "stage2_feasible": False})
    report = FeasibilityChecker().evaluate(None, plan)
    assert not report.feasible
    assert "STAGE2_NO_INCUMBENT" in report.errors[0]
    assert status in report.errors[0]
