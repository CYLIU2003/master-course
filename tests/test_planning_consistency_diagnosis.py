import json

import pytest

from scripts.benchmarks import run_planning_consistency_diagnosis as runner


def setup(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "git_state", lambda: {"sha": "frozen", "status_porcelain": ""})
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"diagnostic_stop_after_day_ahead": True}))
    return config


def test_preflight_failure_keeps_original_reasons_without_reading_missing_progress(tmp_path, monkeypatch):
    config = setup(monkeypatch, tmp_path)
    reason = "渋21: verified timetable dataset has zero trips"
    monkeypatch.setattr(runner, "run_campaign", lambda *_args, **_kwargs: {
        "status": "STOPPED_AFTER_FAILED_CASE", "summaries": [{
            "status": "BLOCKED_CASE_PREFLIGHT", "diagnostic_result": {
                "solve_attempted": False, "reasons": [reason]}}]})
    with pytest.raises(RuntimeError, match="BLOCKED_CASE_PREFLIGHT"):
        runner.run(config, tmp_path / "run")
    failure = json.loads((tmp_path / "run/failure.json").read_text())
    assert reason in failure["error"]
    assert "FileNotFoundError" not in failure["error"]
    assert failure["campaign_outcome"]["reasons"] == [reason]
    assert failure["campaign_outcome"]["solve_attempted"] is False
    assert not failure["email_sent"] and not failure["monthly_complete"]


def test_successful_day_ahead_diagnosis_has_its_own_completion_status(tmp_path, monkeypatch):
    config = setup(monkeypatch, tmp_path)

    def campaign(_design, output, **_kwargs):
        case = output / "cases/2025-05-12/diagnostic/2025-05-12"
        case.mkdir(parents=True)
        for name, payload in {
            "progress.json": {"status": "DAY_AHEAD_ONLY_DIAGNOSIS_COMPLETE",
                              "day_ahead_physical_accepted": True, "day_ahead_seconds": 3},
            "canonical_solver_result.json": {"metadata": {}},
            "day_ahead_physical_validation.json": {"accepted": True},
            "day_ahead_optimization_quality.json": {"subproblem_gap_targets_met": False},
            "input_audit.json": {"accepted": True},
        }.items():
            (case / name).write_text(json.dumps(payload))
        return {"status": "DAY_AHEAD_ONLY_CAMPAIGN_COMPLETE", "summaries": [{
            "status": "DAY_AHEAD_ONLY_DIAGNOSIS_COMPLETE", "diagnostic_result": {"solve_attempted": True}}]}

    monkeypatch.setattr(runner, "run_campaign", campaign)
    summary = runner.run(config, tmp_path / "run")
    assert summary["status"] == "DIAGNOSIS_COMPLETE" and summary["physical_accepted"]
    assert not summary["monthly_complete"] and not summary["email_sent"]
    assert len(summary["evidence_sha256"]) == 4
