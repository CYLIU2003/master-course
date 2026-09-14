from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import scripts.benchmarks.run_exact_seasonal_campaign as campaign

from scripts.benchmarks.run_exact_seasonal_campaign import (
    _empty_case_after_failure,
    _phase_summary,
    campaign_case_design,
    canonical_design_hash,
)


def test_campaign_case_design_is_one_week_and_preserves_source_hash() -> None:
    source = {
        "evaluation_weeks": ["2025-02-03", "2025-05-12"],
        "input_manifests_directory": "old/inputs",
        "prepared_inputs_directory": "old/prepared",
        "stage1_exact_depot_connection_factors": False,
        "research_status": "DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS",
    }
    before = deepcopy(source)
    source_hash = canonical_design_hash(source)

    case = campaign_case_design(
        source,
        week="2025-05-12",
        declared_weeks=("2025-02-03", "2025-05-12"),
        input_manifests_directory="output/campaign/inputs",
        source_design_sha256=source_hash,
    )

    assert source == before
    assert case["evaluation_weeks"] == ["2025-05-12"]
    assert case["campaign_declared_weeks"] == ["2025-02-03", "2025-05-12"]
    assert case["stage1_exact_depot_connection_factors"] is True
    assert case["campaign_source_design_sha256"] == source_hash
    assert case["input_manifests_directory"] == "output/campaign/inputs"
    assert case["prepared_inputs_directory"] == "output/prepared_inputs"


def test_monthly_campaign_forwards_frozen_design_to_all_twelve_preparations(tmp_path, monkeypatch):
    from bff.services import date_series_inputs
    from scripts.benchmarks import prepare_shibu21_24_seasonal_inputs as preparation
    from scripts.benchmarks import run_shibu21_24_seasonal_diagnostic as diagnostic
    root = Path(__file__).resolve().parents[1]
    design = json.loads((root / "config/shibu21_23_monthly_2025_20260914.json").read_text(encoding="utf-8"))
    before = deepcopy(design)
    monkeypatch.setattr(campaign, "ROOT", tmp_path)
    monkeypatch.setattr(diagnostic, "git_state", lambda: {"sha": "frozen", "status_porcelain": ""})
    monkeypatch.setattr(preparation, "build_source_candidate", lambda **_: {})
    monkeypatch.setattr(date_series_inputs, "_verified_holiday_manifest", lambda *_: {
        "sha256": design["calendar_source_sha256"], "holiday_dates": design["selection_holiday_dates"]})
    prepared_weeks = []

    def prepare(week, _output, _source, *, existing, validation_mode, design):
        assert existing is None and validation_mode is True
        assert design["require_balanced_monthly_weeks"] is True
        assert design["forecast_holdouts_directory"] == before["forecast_holdouts_directory"]
        assert design["evaluation_weeks"] == [week]
        assert design["successor_pruning"] == 0 and design["postsolve_repair"] is False
        prepared_weeks.append(week)
        return {"formal_prepared": True, "input_preparation_valid": True}

    monkeypatch.setattr(preparation, "prepare_week", prepare)
    monkeypatch.setattr(diagnostic, "run_diagnostic", lambda *_: [{"status": "DIAGNOSTIC_EXECUTION_PASSED"}])
    result = campaign.run_campaign(design, tmp_path / "monthly")
    assert prepared_weeks == before["evaluation_weeks"]
    assert len(result["summaries"]) == 12
    assert design == before


def test_failed_case_record_is_explicitly_not_executed() -> None:
    state = {"sha": "abc123", "status_porcelain": ""}
    record = _empty_case_after_failure(
        "2025-08-04",
        reason="2025-05-12: case failed with status DAY_AHEAD_FAILED",
        source_state_before=state,
        source_state_after=state,
    )

    assert record["status"] == "NOT_EXECUTED_AFTER_FAILURE"
    assert record["solve_attempted"] is False
    assert record["formal_solve"] is False
    assert record["reasons"]


def test_phase_summary_keeps_rolling_physical_and_accounting_separate() -> None:
    phases = _phase_summary(
        {
            "formal_prepared": True,
            "input_preparation_valid": True,
            "prepared_input_id": "prepared-1",
        },
        {
            "solve_attempted": True,
            "day_ahead_feasible": True,
            "day_ahead_physical_accepted": True,
            "hourly_steps_accepted": 168,
            "physical_accepted": True,
            "accounting_eligible": False,
            "executed_cost": {"total_cost": 123.0},
        },
    )

    assert phases["prepare"]["status"] == "PREPARED"
    assert phases["solve"]["status"] == "DAY_AHEAD_PASSED"
    assert phases["rolling"]["status"] == "168_PREFIXES_ACCEPTED"
    assert phases["physical"]["rolling_accepted"] is True
    assert phases["accounting"]["eligible"] is False


def test_campaign_stops_after_failure_without_preparing_later_weeks(tmp_path, monkeypatch):
    from scripts.benchmarks import prepare_shibu21_24_seasonal_inputs as preparation
    from scripts.benchmarks import run_shibu21_24_seasonal_diagnostic as diagnostic
    monkeypatch.setattr(campaign, "ROOT", tmp_path)
    state = {"sha": "frozen", "status_porcelain": ""}
    monkeypatch.setattr(diagnostic, "git_state", lambda: dict(state))
    monkeypatch.setattr(preparation, "build_source_candidate", lambda **_: {})
    events = []

    def prepare(week, _output, _source, *, existing, validation_mode):
        assert existing is None and validation_mode is True
        events.append(("prepare", week))
        return {"formal_prepared": True, "input_preparation_valid": True}

    def solve(design, _output):
        week = design["evaluation_weeks"][0]
        events.append(("solve", week))
        return [{"week": week, "status": "DAY_AHEAD_FAILED", "solve_attempted": True,
                 "day_ahead_feasible": False}]

    monkeypatch.setattr(preparation, "prepare_week", prepare)
    monkeypatch.setattr(diagnostic, "run_diagnostic", solve)
    result = campaign.run_campaign(
        {"evaluation_weeks": ["2025-02-03", "2025-05-12"], "route_codes": ["渋21", "渋22", "渋23"]},
        tmp_path / "campaign",
    )
    assert events == [("prepare", "2025-02-03"), ("solve", "2025-02-03")]
    assert result["status"] == "STOPPED_AFTER_FAILED_CASE"
    assert result["summaries"][0]["rolling"]["status"] == "NOT_ATTEMPTED"
    assert result["summaries"][1]["prepare"]["status"] == "NOT_ATTEMPTED"


def test_rolling_exception_does_not_relabel_missing_day_ahead_result_as_failure():
    phases = _phase_summary({}, {
        "solve_attempted": True,
        "day_ahead_physical_accepted": True,
        "hourly_steps_accepted": 54,
        "reasons": ["ValueError: invalid rolling BESS reference"],
        "accounting_eligible": False,
    })
    assert phases["solve"]["status"] == "DAY_AHEAD_RESULT_UNAVAILABLE"
    assert phases["solve"]["feasible"] is None
    assert phases["rolling"]["status"] == "ROLLING_FAILED"
    assert phases["rolling"]["hourly_steps_accepted"] == 54
    assert phases["rolling"]["reasons"] == ["ValueError: invalid rolling BESS reference"]
    assert phases["accounting"]["eligible"] is False


def test_explicit_day_ahead_infeasibility_remains_failed():
    phases = _phase_summary({}, {"solve_attempted": True, "day_ahead_feasible": False})
    assert phases["solve"]["status"] == "DAY_AHEAD_FAILED"
    assert phases["rolling"]["status"] == "NOT_ATTEMPTED"


def test_source_drift_blocks_before_fresh_prepare(tmp_path, monkeypatch):
    from scripts.benchmarks import prepare_shibu21_24_seasonal_inputs as preparation
    from scripts.benchmarks import run_shibu21_24_seasonal_diagnostic as diagnostic
    monkeypatch.setattr(campaign, "ROOT", tmp_path)
    reads = []

    def state():
        reads.append(1)
        return {"sha": "frozen", "status_porcelain": "" if len(reads) <= 2 else " M source.py"}

    monkeypatch.setattr(diagnostic, "git_state", state)
    monkeypatch.setattr(preparation, "build_source_candidate", lambda **_: {})

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Prepare must not start after source drift")

    monkeypatch.setattr(preparation, "prepare_week", forbidden)
    result = campaign.run_campaign(
        {"evaluation_weeks": ["2025-02-03"], "route_codes": ["渋21", "渋22", "渋23"]},
        tmp_path / "campaign",
    )
    assert result["status"] == "BLOCKED_SOURCE_STATE_DRIFT"
    assert result["summaries"][0]["error"] == "Git SHA or dirty state changed before Prepare"
