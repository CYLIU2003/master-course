import json
import zipfile

import pytest

from tools.cluster.audit_batch import audit_batch
from tools.cluster.batch import canonical, digest


def fixture(tmp_path, *, count=0, damage=False):
    profile = "alns_no_gurobi_v1"
    spec = {"schema_version": 1, "batch_id": "audit", "controller_url": "http://127.0.0.1:8868",
            "git_sha": "a" * 40, "tasks": [{"task_id": "month", "submission": {"scenario_id": "s", "minimum_ram_gb": 1,
            "request": {"prepared_input_id": "prepared", "execution_profile": profile}}}]}
    bundle = {"scenario": {"meta": {"id": "s"}},
              "kwargs": {"scenario_id": "s", "prepared_input_id": "prepared", "execution_profile": profile}}
    manifest = {"id": "attempt", "git": {"sha": spec["git_sha"], "dirty": False},
                "execution_profile": profile, "source_digest": "source", "bundle_sha256": digest(canonical(bundle))}
    receipt = {"id": "attempt", "state": "COMPLETED", "manifest_sha256": digest(canonical(manifest)),
               "provenance": {"git": manifest["git"], "source_digest": "source"},
               "result": {"message": "Optimization complete (terminal_soc_balance_failed)."}}
    files = {"manifest.json": canonical(manifest), "state.json": canonical(receipt), "bundle.json": canonical(bundle),
             "run/report.json": b'{"diagnostic":true}'}
    artifact = {"sha256": digest(files["run/report.json"]), "size_bytes": len(files["run/report.json"])}
    files["run/artifact_completeness.json"] = canonical({"accepted": True, "required_artifact_count": 1,
        "verified_artifact_count": 1, "required_artifacts": ["report.json"], "artifacts": {"report.json": artifact}})
    files["run/solver_usage.json"] = canonical({"execution_profile": profile, "counts_complete": True,
        "environment_starts": count, "model_creations": 0, "optimize_calls": 0, "forbidden_calls": 0})
    files["run/research_claim_scope.json"] = canonical({"teacher_release_status": "BLOCKED",
        "teacher_release_failed_checks": ["physical_schedule_not_validated"], "physical_feasibility_claim_eligible": False})
    if damage:
        files["run/report.json"] = b'{"diagnostic":false}'
    target = tmp_path / "attempt.zip"
    with zipfile.ZipFile(target, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    state = {"batch_sha256": digest(canonical(spec)), "tasks": {"month": {"state": "COMPLETED",
        "job_id": "attempt", "artifacts": target.name, "collected_sha256": digest(target.read_bytes()), "worker_id": "pc"}}}
    return spec, state


@pytest.mark.parametrize("field,value", [("scenario_id", "other"), ("prepared_input_id", "other")])
def test_audit_rejects_valid_archive_bound_to_wrong_submission(tmp_path, field, value):
    spec, state = fixture(tmp_path)
    spec["tasks"][0]["submission"]["request" if field == "prepared_input_id" else "scenario_id"] = (
        {"prepared_input_id": value, "execution_profile": "alns_no_gurobi_v1"}
        if field == "prepared_input_id" else value)
    state["batch_sha256"] = digest(canonical(spec))
    report = audit_batch(spec, state, tmp_path)
    assert report["collection_verified"] == 0
    assert report["unverified"] == 1
    assert "mismatch" in report["tasks"][0]["error"]


def test_verified_collection_never_upgrades_failed_research_gates(tmp_path):
    spec, state = fixture(tmp_path)
    report = audit_batch(spec, state, tmp_path)
    assert report["collection_verified"] == 1
    assert report["research_approval"] == "NOT_GRANTED_BY_CLUSTER"
    row = report["tasks"][0]
    assert row["teacher_release_status"] == "BLOCKED"
    assert row["physical_feasibility_claim_eligible"] is False
    assert "terminal_soc_balance_failed" in row["worker_message"]


@pytest.mark.parametrize("change", ["zip", "file", "env", "failed", "path"])
def test_audit_keeps_corrupt_or_failed_cases_in_denominator(tmp_path, change):
    spec, state = fixture(tmp_path, count=int(change == "env"), damage=change == "file")
    item = state["tasks"]["month"]
    if change == "zip":
        item["collected_sha256"] = "wrong"
    if change == "failed":
        item["state"] = "FAILED"
    if change == "path":
        item.update(job_id="../attempt", artifacts="../attempt.zip")
    report = audit_batch(spec, state, tmp_path)
    assert report["total"] == report["unverified"] == 1
    assert report["collection_verified"] == report["excluded_tasks"] == 0


def test_controller_refusal_is_persisted_without_sensitive_body(tmp_path, monkeypatch, capsys):
    import io
    from urllib.error import HTTPError
    from tools.cluster import batch
    spec, _ = fixture(tmp_path)
    manifest = tmp_path / "batch.json"
    manifest.write_bytes(canonical(spec))
    def refused(*args):
        raise HTTPError("http://127.0.0.1:8868/api/cluster/jobs", 409, "Conflict", {}, io.BytesIO(b"secret-body"))
    monkeypatch.setattr(batch, "advance", refused)
    monkeypatch.setattr(batch.sys, "argv", ["batch.py", "run", str(manifest), "--state-dir", str(tmp_path)])
    assert batch.main() == 1
    state = json.loads((tmp_path / "batch-state.json").read_bytes())
    assert state["connection"] == {"status": "REQUEST_REJECTED", "http_status": 409,
                                   "retryable": False, "error_code": "HTTP_409_UNCLASSIFIED"}
    assert "secret-body" not in capsys.readouterr().out
