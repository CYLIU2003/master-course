import json
from pathlib import Path

import pytest

from bff.services.cluster.contracts import canonical, digest
from tools.research.execution_detail import inspect_attempt, native_detail


def test_memory_missing_identity_never_queries_pid_or_reports_zero(monkeypatch):
    from tools.research import execution_detail as detail
    monkeypatch.setattr(detail.os, "name", "nt")
    monkeypatch.setattr(detail, "_windows_process_memory", lambda *_: pytest.fail("must not query unbound PID"))
    for state in ({}, {"pid": 99}, {"pid": True, "process_identity": "1:2"}, {"pid": 99, "process_identity": "unknown"}):
        assert detail.process_memory(state) == {"status": "IDENTITY_UNAVAILABLE"}


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows read-only process metrics')
def test_windows_memory_matches_birth_and_rejects_reused_pid():
    import os
    from bff.services.cluster.runner import process_identity
    from tools.research.execution_detail import process_memory
    observed = process_memory({"pid": os.getpid(), "process_identity": process_identity(os.getpid())})
    assert observed["status"] == "OBSERVED"
    assert 0 < observed["working_set_gib"] <= observed["peak_working_set_gib"]
    assert observed["private_commit_gib"] > 0
    wrong = process_memory({"pid": os.getpid(), "process_identity": "1:2"})
    assert wrong == {"pid": os.getpid(), "status": "IDENTITY_MISMATCH"}


def attempt(tmp_path):
    root = tmp_path / "attempt-1"
    root.mkdir()
    manifest = {"id": root.name}
    (root / "manifest.json").write_bytes(canonical(manifest))
    (root / "state.json").write_bytes(canonical({"id": root.name, "manifest_sha256": digest(canonical(manifest))}))
    run = root / "output/2026-09-25/run_20260925_1200"
    run.mkdir(parents=True)
    return root, run


def test_native_barrier_iteration_is_not_optimality_or_week_completion(tmp_path):
    root, run = attempt(tmp_path)
    p = run / "stage1_native_1.log"
    p.write_text("WLS password=must-not-leak\n  75 2.25e+06 2.24e+06 6.32e-07 4.60e-10 3.31e-06 1223s\n")
    d = inspect_attempt(root)
    assert d["phase"] == "STAGE1"
    assert d["native"]["metrics"] == {"solver_seconds": 1223.0, "barrier_iteration": 75}
    assert "must-not-leak" not in json.dumps(d)
    assert d["rolling_feasible"] == 0 and not d["chain_accepted"]


def test_parameter_log_creation_is_not_a_started_solve(tmp_path):
    root, run = attempt(tmp_path)
    p = run / "stage1_native_1.log"
    p.write_text("Set parameter SoftMemLimit to value 18\n", encoding="utf-8")
    assert inspect_attempt(root)["phase"] == "MODEL_BUILD"
    p.write_text("Optimize a model with 50 rows, 100 columns and 200 nonzeros\n", encoding="utf-8")
    assert inspect_attempt(root)["phase"] == "STAGE1"


def test_rolling_failed_and_partial_windows_are_not_counted_as_feasible(tmp_path):
    root, run = attempt(tmp_path)
    for i, item in enumerate([{"feasible": True}, {"feasible": False}, {"feasible": True, "chain_rejection_reason": "handoff"}]):
        p = run / f"rolling_hourly_chain/step_{i:03}/hourly_summary.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps(item))
    d = inspect_attempt(root)
    assert d["phase"] == "ROLLING"
    assert d["rolling_feasible"] == 1 and d["rolling_saved"] == 3
    assert d["chain_accepted"] is False


def test_mismatched_attempt_manifest_is_rejected(tmp_path):
    root, _ = attempt(tmp_path)
    (root / "manifest.json").write_text('{"id":"different"}')
    with pytest.raises(ValueError, match="ATTEMPT_ID"):
        inspect_attempt(root)


def test_partial_checkpoint_does_not_masquerade_as_progress(tmp_path):
    root, _ = attempt(tmp_path)
    (root / "state.json").write_text('{"id":')
    with pytest.raises(ValueError):
        inspect_attempt(root)


def test_stage_gap_is_read_only_from_mip_log_not_lp_objectives(tmp_path):
    p = tmp_path / "stage2.log"
    p.write_text("Best objective 1.0e+03, best bound 9.9e+02, gap 1.0000%\n")
    assert native_detail(p)["metrics"]["stage_gap_percent"] == 1


def test_presolve_progress_is_visible_without_claiming_root_lp_finished(tmp_path):
    p = tmp_path / 'stage1.log'
    p.write_text('Presolve removed 20 rows (presolve time = 195s)...\nPresolve time: 202.92s\nPresolved: 902682 rows, 6796155 columns, 25228776 nonzeros\n')
    detail = native_detail(p)
    assert detail['metrics'] == {'presolve_seconds': 202.92, 'solver_seconds': 202.92}
    assert detail['solve_started']
    assert len(detail['lines']) == 3


def test_multiple_runs_cannot_inflate_rolling_progress(tmp_path):
    root, run = attempt(tmp_path)
    (run.parent / "run_other").mkdir()
    with pytest.raises(ValueError, match="AMBIGUOUS_RUN_DIRECTORY"):
        inspect_attempt(root)


def test_disconnected_controller_preserves_prior_attempt_without_claiming_live(tmp_path, monkeypatch):
    from tools.research import publish_execution_detail as publisher
    operation = tmp_path / "operation.json"
    monkeypatch.setattr(publisher, "campaign_rows", lambda _: [{"job_id": "same-attempt", "connection": "CONNECTED", "observed_at": "old-time"}])
    previous = publisher.collect_snapshot([operation], {})
    def disconnected(_):
        raise OSError("sensitive connection details")
    monkeypatch.setattr(publisher, "campaign_rows", disconnected)
    current = publisher.collect_snapshot([operation], previous)
    assert current["cases"][0]["job_id"] == "same-attempt"
    assert current["cases"][0]["observed_at"] == "old-time"
    assert current["cases"][0]["connection"] == "UNKNOWN"
    assert "sensitive" not in json.dumps(current)
