"""No-Gurobi means no availability probe, exact repair or hidden solve."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.solver_policy import (
    NO_GUROBI_PROFILE, SolverPolicyViolation, solver_policy_scope,
    require_gurobi, optimize_model, validate_no_gurobi_inputs,
)


def test_policy_cannot_be_swallowed_or_use_cached_availability(monkeypatch):
    from src import gurobi_runtime
    monkeypatch.setattr(gurobi_runtime, "_GUROBI_RUNTIME_AVAILABLE", True)
    with pytest.raises(SolverPolicyViolation, match="suppressed"):
        with solver_policy_scope(NO_GUROBI_PROFILE) as usage:
            try:
                gurobi_runtime.is_gurobi_available()
            except RuntimeError:
                pass
    assert usage.forbidden_calls == 1
    assert usage.environment_starts == usage.optimize_calls == 0


def test_cached_module_model_and_optimize_are_guarded():
    from src.gurobi_runtime import GurobiFacade
    module = GurobiFacade(SimpleNamespace(Model=lambda: pytest.fail("native Model called")))
    for operation in (module.Model, lambda: optimize_model(SimpleNamespace())):
        with pytest.raises(SolverPolicyViolation, match="GUROBI_FORBIDDEN"):
            with solver_policy_scope(NO_GUROBI_PROFILE):
                operation()


@pytest.mark.parametrize("control", [
    {"mode": "hybrid"}, {"research_run": True}, {"planning_days": 7},
    {"bess_enabled": True}, {"hourly_rolling": True}, {"daily_return": True},
])
def test_unsupported_combinations_are_rejected(control):
    with pytest.raises(SolverPolicyViolation, match="UNSUPPORTED"):
        validate_no_gurobi_inputs(NO_GUROBI_PROFILE, **({"mode": "alns"} | control))


def test_profile_rejects_before_prepare_and_unknown_modes_fail(monkeypatch):
    from bff.routers import optimization
    from fastapi import HTTPException
    monkeypatch.setattr(optimization, "_require_scenario", lambda _: None)
    monkeypatch.setattr(optimization.store, "get_scenario_document_shallow", lambda _: {
        "simulation_config": {"execution_profile": NO_GUROBI_PROFILE, "planning_days": 7}})
    monkeypatch.setattr(optimization, "get_or_build_run_preparation", lambda **_: pytest.fail("Prepare called"))
    with pytest.raises(HTTPException, match="UNSUPPORTED"):
        optimization.enqueue_optimization("s", optimization.RunOptimizationBody(
            execution_profile=NO_GUROBI_PROFILE, mode="alns", run_profile="day_ahead_exploratory",
            run_hourly_rolling=False), {})
    from bff.services.optimization_run.execute import normalize_solver_mode, parse_optimization_mode
    for function in (normalize_solver_mode, parse_optimization_mode):
        with pytest.raises(ValueError, match="UNKNOWN_SOLVER_MODE"):
            function("typo-alns")


def test_no_exact_operator_or_budget_in_canonical_alns():
    from src.optimization.alns.engine import ALNSOptimizer
    from src.optimization.common.problem import OptimizationConfig, OptimizationMode, AssignmentPlan
    from src.optimization.common.benchmarking import exact_repair_policy
    from test_reopt_alns_critical_fixes import _minimal_problem
    config = OptimizationConfig(mode=OptimizationMode.ALNS, execution_profile=NO_GUROBI_PROFILE,
                                alns_iterations=8, no_improvement_limit=4, time_limit_sec=2)
    assert exact_repair_policy(config).call_limit == 0
    assert exact_repair_policy(config).time_budget_sec == 0
    with solver_policy_scope(NO_GUROBI_PROFILE) as usage:
        # An empty dispatch is a legitimate infeasible candidate, not a missing plan.
        problem = replace(_minimal_problem(), baseline_plan=AssignmentPlan(unserved_trip_ids=("t1",)))
        result = ALNSOptimizer().solve(problem, replace(config, alns_iterations=0))
    assert usage.environment_starts == usage.optimize_calls == usage.forbidden_calls == 0
    assert result.solver_metadata["exact_repair_count"] == 0
    assert "partial_milp_repair" not in result.operator_stats


@pytest.mark.parametrize("profile,threads", [("existing_solver_v1", 0), (NO_GUROBI_PROFILE, 1)])
def test_bff_guard_admits_before_execution_and_records_even_caught_license_failure(profile, threads, monkeypatch):
    from contextlib import contextmanager
    from bff.services.optimization_run import solver_policy as policy
    from bff.store import job_store
    from src.gurobi_session import current_session
    calls, updates = [], []
    @contextmanager
    def resources(job_id, cpu_threads):
        calls.append(("resources", cpu_threads))
        yield
        calls.append("resources_released")
    monkeypatch.setattr(policy, "local_resource_scope", resources)
    monkeypatch.setattr(policy, "local_license_callbacks", lambda _: (lambda: calls.append("license"), lambda _: calls.append("released")))
    monkeypatch.setattr(job_store, "get_job", lambda _: SimpleNamespace(metadata={}))
    monkeypatch.setattr(job_store, "update_job", lambda *a, **kw: updates.append(kw))
    @policy.guarded_execution
    def execute(job_id, execution_profile):
        calls.append("execute")
        if profile != NO_GUROBI_PROFILE:
            current_session().license_failed = True
    execute("job", profile)
    assert calls[0] == ("resources", threads)
    assert calls[-1] == "resources_released"
    if profile != NO_GUROBI_PROFILE:
        assert calls.index("license") < calls.index("execute") < calls.index("released")
        assert any(row.get("error") == "GUROBI_LICENSE_UNAVAILABLE" for row in updates)
    else:
        assert "license" not in calls
    assert updates[-1]["metadata"]["solver_usage"]["environment_starts"] == 0
