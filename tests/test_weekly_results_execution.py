from types import SimpleNamespace

import pytest

from tools.research.weekly_results import require_coverage
from tools.research.weekly_campaign import request, validate_budget
from bff.routers.optimization import _configure_assignment_energy_diagnostics
from tools.research import weekly_terminal_observer as observer
from tools.research.weekly_results import write_json


def test_weekly_budget_keeps_build_and_both_solver_stages():
    controls = request("prepared-example")
    validate_budget(controls)
    # Regression: the old 120-second global deadline expired during a
    # 234-second model build, despite a declared 1,800-second Stage 1.
    controls["time_limit_seconds"] = 120
    with pytest.raises(ValueError, match="model-build"):
        validate_budget(controls)


def test_weekly_root_uses_simplex_without_enlarging_machine_budget(monkeypatch):
    from bff.routers.optimization import RunOptimizationBody, _resolve_runtime_controls
    from src.optimization.common.problem import OptimizationConfig
    from src.optimization.milp.solver_adapter import _configured_stage1_gurobi_search_controls
    from src.solver_memory import ENV_KEY, apply_memory_limits

    request_body = RunOptimizationBody(**request("prepared-example"))
    _, _, threads = _resolve_runtime_controls(
        requested_stage1_best_obj_stop_enabled=False,
        requested_gurobi_threads=request_body.gurobi_threads,
        enforce_interactive_runtime_controls=True,
    )
    assert threads == request_body.gurobi_threads == 4
    controls = _configured_stage1_gurobi_search_controls(OptimizationConfig(
        stage1_gurobi_search_profile=request_body.stage1_gurobi_search_profile))
    assert controls["root_method"] == 1
    assert controls["no_rel_heur_work"] == 0
    monkeypatch.setenv(ENV_KEY, "16")
    model = SimpleNamespace(Params=SimpleNamespace(
        MemLimit=float("inf"), SoftMemLimit=controls["soft_mem_limit_gb"]))
    apply_memory_limits(model)
    assert model.Params.MemLimit == pytest.approx(14 * 1024**3 / 1e9)
    assert model.Params.SoftMemLimit == pytest.approx(12.6 * 1024**3 / 1e9)


@pytest.mark.parametrize("paths", [{"a": ["t1"]}, {"a": ["t1", "t2"], "b": ["t1"]}, {"a": ["t1", "t3"]}])
def test_weekly_reuse_rejects_missing_duplicate_or_invented_trips(paths):
    with pytest.raises(ValueError, match="exactly once"):
        require_coverage({"t1": {}, "t2": {}}, {"vehicle_paths": paths,
                         "served_trip_ids": ["t1", "t2"], "unserved_trip_ids": []})


def test_weekly_reuse_keeps_actual_vehicle_assignments():
    assert require_coverage({"t1": {}, "t2": {}}, {"vehicle_paths": {"a": ["t1"], "b": ["t2"]},
             "served_trip_ids": ["t1", "t2"], "unserved_trip_ids": []}) == {"t1": "a", "t2": "b"}


def test_frozen_compact_model_controls_reach_bff_problem(tmp_path):
    problem = SimpleNamespace(metadata={})
    declared = {"stage1_exact_depot_connection_factors": True, "stage1_sparse_charge_window_support": True,
                "stage1_native_log_enabled": True, "stage2_native_log_enabled": False}
    _configure_assignment_energy_diagnostics(problem, phase_token="phase3_two_stage", output_dir=tmp_path,
                                              research_run=False, prepared_config=declared)
    assert all(problem.metadata[k] is v for k, v in declared.items())
    assert problem.metadata["stage2_feedback_max_iterations"] == 1


def test_compact_control_refuses_truthy_string(tmp_path):
    with pytest.raises(ValueError, match="boolean"):
        _configure_assignment_energy_diagnostics(SimpleNamespace(metadata={}), phase_token="phase3_two_stage",
            output_dir=tmp_path, research_run=False, prepared_config={"stage1_exact_depot_connection_factors": "false"})


def test_observer_does_not_treat_unknown_process_as_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(observer, "process_identity", lambda pid: "unknown")
    assert observer.terminal(tmp_path, {"pid": 10, "process_identity": "birth"}) is None


def test_observer_detects_reused_pid_without_restarting_any_job(tmp_path, monkeypatch):
    monkeypatch.setattr(observer, "process_identity", lambda pid: "another-birth")
    assert observer.terminal(tmp_path, {"pid": 10, "process_identity": "birth"})[0] == "PROCESS_STOPPED"


def test_observer_preserves_partial_result_status(tmp_path):
    write_json(tmp_path / "state.json", {"status": "PARTIAL_OR_FAILED", "cases": {"summer": {"state": "VERIFIED"}}})
    assert observer.terminal(tmp_path, {})[0] == "PARTIAL_OR_FAILED"


def test_observer_never_requeues_a_recorded_terminal_event(tmp_path, monkeypatch):
    write_json(tmp_path / "terminal_observer/event.json", {"status": "QUEUE_ATTEMPTED"})
    monkeypatch.setattr(observer.subprocess, "run", lambda *a, **kw: pytest.fail("duplicate notification"))
    observer.notify_once(tmp_path, {}, ("COMPLETED", {}), "unused", tmp_path)
