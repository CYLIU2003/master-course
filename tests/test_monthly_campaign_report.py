import base64
import json
from pathlib import Path
import zipfile

import pytest

from tools.cluster.batch import digest
from tools.research import monthly_campaign_report as report


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def operation(tmp_path, name="campaign", week="2025-02-03", status="VERIFIED"):
    campaign = tmp_path / name
    op = {"git_sha": "fixed-sha", "parent": "parent", "weeks": [week], "campaign": str(campaign)}
    path = tmp_path / (name + ".json")
    save(path, op)
    save(campaign / "state.json", {"git_sha": "fixed-sha", "cases": {week: {"state": status}}})
    return path, campaign / week, op


def verified_case(tmp_path, monkeypatch):
    path, case, op = operation(tmp_path)
    save(case / "prepared.json", {"source_git": {"sha": "fixed-sha", "dirty": False},
         "parent_id": "parent", "week": "2025-02-03", "parent_hash": "parent-hash",
         "prepared_sha256": digest(b"input"), "overnight": {"extra_slots": 23}})
    save(case / "batch.json", {"git_sha": "fixed-sha"})
    save(case / "state/batch-state.json", {"tasks": {"2025-02-03": {
        "job_id": "job", "worker_id": "worker", "artifacts": "job.zip", "collected_sha256": "archive-hash"}}})
    with zipfile.ZipFile(case / "state/job.zip", "w") as z:
        z.writestr("bundle.json", json.dumps({"prepared_base64": base64.b64encode(b"input").decode()}))
        z.writestr("out/rolling_hourly_chain/executed_day_accounting.json", json.dumps({
            "eligible": True, "missing_slots": [], "duplicate_slots": [], "executed_slot_count": 695,
            "cost_breakdown": {"total_cost": 123.5, "fuel_cost": 20}}))
    save(case / "results/weekly_summary.json", {"git_sha": "fixed-sha", "week": "2025-02-03",
        "job_id": "job", "worker_id": "worker", "total_cost": 123.5, "fuel_cost": 20,
        "executed_slots_including_overnight": 695})
    (case / "results/daily_summary.csv").write_text("total_cost_jpy\n100\n23.5\n", encoding="utf-8")
    monkeypatch.setattr(report, "audit_batch", lambda *args: {"unverified": 0, "tasks": [
        {"task_id": "2025-02-03", "physical_feasibility_claim_eligible": True}]})
    return path, case


def test_pending_costs_are_not_zero_and_duplicate_weeks_are_rejected(tmp_path):
    path, _, _ = operation(tmp_path, status="SUBMITTED")
    result = report.snapshot([path])
    assert result["rows"] == [] and not result["complete"]
    assert "total_cost_jpy" not in result["cases"][0]
    with pytest.raises(ValueError, match="Duplicate"):
        report.snapshot([path, path])
    destination = report.publish(result, tmp_path / "report")
    assert "未確定" in (destination / "report.md").read_text(encoding="utf-8")


def test_multiple_campaigns_keep_declared_months_and_accept_only_verified(tmp_path, monkeypatch):
    path, _ = verified_case(tmp_path, monkeypatch)
    pending, _, _ = operation(tmp_path, "remaining", "2025-03-03", "NOT_STARTED")
    result = report.snapshot([path, pending])
    assert len(result["cases"]) == 2 and len(result["rows"]) == 1
    assert result["rows"][0]["total_cost"] == 123.5 and not result["complete"]
    assert len(result["daily"]) == 2


@pytest.mark.parametrize("field,value", [("total_cost", 99), ("fuel_cost", float("nan")),
                                         ("job_id", "another"), ("git_sha", "old-sha")])
def test_summary_tampering_is_excluded(tmp_path, monkeypatch, field, value):
    path, case = verified_case(tmp_path, monkeypatch)
    row = report.read(case / "results/weekly_summary.json")
    row[field] = value
    save(case / "results/weekly_summary.json", row)
    result = report.snapshot([path])
    assert not result["complete"] and not result["rows"]
    assert result["cases"][0]["state"] == "REPORT_REJECTED"


def test_archive_audit_failure_is_excluded(tmp_path, monkeypatch):
    path, _ = verified_case(tmp_path, monkeypatch)
    monkeypatch.setattr(report, "audit_batch", lambda *args: {"unverified": 1, "tasks": []})
    assert report.snapshot([path])["cases"][0]["state"] == "REPORT_REJECTED"


def test_mixed_source_and_parent_are_rejected(tmp_path):
    a, _, _ = operation(tmp_path, status="NOT_STARTED")
    b, _, op = operation(tmp_path, "remaining", "2025-03-03", "NOT_STARTED")
    for field in ("git_sha", "parent"):
        save(b, {**op, field: "different"})
        with pytest.raises(ValueError, match="Cannot combine"):
            report.snapshot([a, b])


def test_prepared_input_archive_mismatch_is_excluded(tmp_path, monkeypatch):
    path, case = verified_case(tmp_path, monkeypatch)
    prepared = report.read(case / "prepared.json")
    save(case / "prepared.json", {**prepared, "prepared_sha256": "different"})
    assert report.snapshot([path])["cases"][0]["state"] == "REPORT_REJECTED"


def test_report_revision_is_repeatable_and_refuses_modified_outputs(tmp_path):
    path, _, _ = operation(tmp_path, status="SUBMITTED")
    result = report.snapshot([path])
    destination = report.publish(result, tmp_path / "report")
    assert report.publish(result, tmp_path / "report") == destination
    (destination / "report.md").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="content changed"):
        report.publish(result, tmp_path / "report")


def test_watch_updates_on_terminal_failure_without_submitting_jobs(tmp_path, monkeypatch):
    path, case, _ = operation(tmp_path, status="SUBMITTED")
    monkeypatch.setattr(report.sys, "argv", ["report", "--operation", str(path), "--output", str(tmp_path / "report"), "--watch"])
    sleeps = []

    def finish(seconds):
        sleeps.append(seconds)
        save(case.parent / "state.json", {"git_sha": "fixed-sha", "status": "PARTIAL_OR_FAILED",
            "cases": {"2025-02-03": {"state": "FAILED_OR_UNVERIFIED"}}})

    monkeypatch.setattr(report.time, "sleep", finish)
    report.main()
    assert sleeps == [60]
    latest = report.read(tmp_path / "report/latest.json")
    assert latest["included"] == 0 and not latest["complete"]
    final = report.read(Path(latest["directory"]) / "comparison.json")
    assert final["cases"][0]["state"] == "FAILED_OR_UNVERIFIED"
