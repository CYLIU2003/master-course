import json
from pathlib import Path

import pytest

from bff.services.cluster.contracts import canonical, digest
from tools.research.execution_detail import inspect_attempt, native_detail


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
