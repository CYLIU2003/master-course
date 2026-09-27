import base64
import json
import zipfile

import pytest

from tools.research import recover_weekly_reporting as recovery
from tools.research.weekly_results import write_json


@pytest.fixture
def evidence(tmp_path):
    case, rebuilt = tmp_path / "case", tmp_path / "rebuilt"
    git = {"sha": "a" * 40, "dirty": False}
    request = {"prepared_input_id": "prepared", "execution_profile": "existing_solver_v1"}
    spec = {"schema_version": 1, "batch_id": "batch", "git_sha": git["sha"], "tasks": [
        {"task_id": "2025-01-06", "submission": {"scenario_id": "scenario", "minimum_ram_gb": 32, "request": request}}]}
    inputs = b'{"trips":[],"vehicles":[]}'
    bundle = {"kwargs": {"scenario_id": "scenario", **request}, "scenario": {"meta": {"id": "scenario"}},
              "prepared_base64": base64.b64encode(inputs).decode()}
    bbytes = recovery.canonical(bundle)
    manifest = {"id": "job", "bundle_sha256": recovery.digest(bbytes), "git": git,
                "source_digest": "source", "execution_profile": "existing_solver_v1"}
    mbytes = recovery.canonical(manifest)
    worker = {"id": "job", "state": "FAILED", "manifest_sha256": recovery.digest(mbytes),
              "provenance": {"git": git, "source_digest": "source"},
              "result": {"error": "LiteratureFigureError: Conflicting grid CO2 factors"}}
    wbytes = recovery.canonical(worker)
    files = {"rolling_hourly_chain/executed_day_accounting.json": b'{}',
             "run_manifest.json": b'{"files":[],"research_run_accepted":false}',
             "research_claim_scope.json": b'{"physical_feasibility_claim_eligible":true,"teacher_release_status":"BLOCKED"}',
             "solver_usage.json": b'{"execution_profile":"existing_solver_v1","counts_complete":true}'}
    archive_path = case / "state/job.zip"
    archive_path.parent.mkdir(parents=True)
    with zipfile.ZipFile(archive_path, "w") as z:
        for name, data in {"manifest.json": mbytes, "bundle.json": bbytes, "state.json": wbytes}.items():
            z.writestr(name, data)
        for name, data in files.items():
            z.writestr("out/" + name, data)
            p = rebuilt / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
    write_json(case / "batch.json", spec)
    write_json(case / "prepared.json", {"week": "2025-01-06", "source_git": git, "scenario_id": "scenario",
        "prepared_input_id": "prepared", "prepared_sha256": recovery.digest(inputs)})
    item = {"state": "FAILED", "job_id": "job", "worker_id": "worker", "artifacts": "job.zip",
            "collected_sha256": recovery.sha(archive_path)}
    write_json(case / "state/batch-state.json", {"batch_sha256": recovery.digest(recovery.canonical(spec)),
                                               "tasks": {"2025-01-06": item}})
    write_json(rebuilt / "figure_rebuild_receipt.json", {"original_job_id": "job", "original_worker_state": "FAILED",
        "source_worker_state_sha256": recovery.digest(wbytes), "source_files_sha256": {n: recovery.digest(b) for n, b in files.items()}})
    return case, rebuilt


def test_original_failed_attempt_and_claim_are_preserved(evidence):
    case, rebuilt = evidence
    verified = recovery.verify_source(case, rebuilt)
    assert verified["item"]["state"] == "FAILED"
    assert verified["original_claim"]["teacher_release_status"] == "BLOCKED"


@pytest.mark.parametrize("name", ["solver_usage.json", "run_manifest.json", "rolling_hourly_chain/executed_day_accounting.json"])
def test_nonfigure_evidence_cannot_be_replaced(evidence, name):
    case, rebuilt = evidence
    (rebuilt / name).write_bytes(b'{"tampered":true}')
    with pytest.raises(ValueError, match="Non-figure evidence changed"):
        recovery.verify_source(case, rebuilt)


def test_foreign_rebuild_and_archive_corruption_rejected(evidence):
    case, rebuilt = evidence
    receipt = recovery.read(rebuilt / "figure_rebuild_receipt.json")
    write_json(rebuilt / "figure_rebuild_receipt.json", {**receipt, "original_job_id": "other"})
    with pytest.raises(ValueError, match="different attempt"):
        recovery.verify_source(case, rebuilt)
    (case / "state/job.zip").write_bytes(b'corrupt')
    with pytest.raises(ValueError, match="archive hash"):
        recovery.verify_source(case, rebuilt)


def test_live_attempt_cannot_be_recovered(evidence):
    case, rebuilt = evidence
    state = recovery.read(case / "state/batch-state.json")
    state["tasks"]["2025-01-06"]["state"] = "RUNNING"
    write_json(case / "state/batch-state.json", state)
    with pytest.raises(ValueError, match="terminal failed"):
        recovery.verify_source(case, rebuilt)


def test_repaired_manifest_allows_inventory_only_never_acceptance_change(evidence):
    case, rebuilt = evidence
    manifest = recovery.read(rebuilt / "run_manifest.json")
    write_json(rebuilt / "run_manifest.json", {**manifest, "files": ["solver_usage.json"]})
    recovery.verify_source(case, rebuilt, repaired_manifest=True)
    write_json(rebuilt / "run_manifest.json", {**manifest, "research_run_accepted": True})
    with pytest.raises(ValueError, match="Run verdict changed"):
        recovery.verify_source(case, rebuilt, repaired_manifest=True)


def test_added_nonfigure_evidence_is_rejected(evidence):
    case, rebuilt = evidence
    (rebuilt / "invented_validation.json").write_bytes(b'{}')
    with pytest.raises(ValueError, match="Unexpected added"):
        recovery.verify_source(case, rebuilt)


def test_recovery_never_overwrites_source_or_existing_output(evidence, tmp_path):
    case, rebuilt = evidence
    for output in (rebuilt, case / "new", rebuilt / "new"):
        with pytest.raises(ValueError, match="Output must be new"):
            recovery.recover(case, rebuilt, output)


def test_failed_full_audit_never_exports_or_issues_success_receipt(evidence, tmp_path, monkeypatch):
    case, rebuilt = evidence
    monkeypatch.setattr(recovery, "audit_frontend_run_artifacts", lambda *a, **kw: {"accepted": False})
    monkeypatch.setattr(recovery, "export_executed_week", lambda *a: pytest.fail("must not export"))
    before = recovery.inventory(rebuilt)
    out = tmp_path / "output"
    with pytest.raises(ValueError, match="artifact audit failed"):
        recovery.recover(case, rebuilt, out)
    assert not (out / "recovery.json").exists()
    assert recovery.inventory(rebuilt) == before
    manifest = recovery.read(out / "run/run_manifest.json")
    assert manifest["research_run_accepted"] is False
    assert "solver_usage.json" in manifest["files"]
