from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import pytest

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


@pytest.mark.parametrize("day_ahead_only", [False, True])
def test_two_campaigns_build_real_sources_without_collision_or_reuse(tmp_path, monkeypatch, day_ahead_only):
    from scripts.benchmarks import prepare_shibu21_24_seasonal_inputs as preparation
    from scripts.benchmarks import run_shibu21_24_seasonal_diagnostic as diagnostic
    from test_shibu21_24_source_scopes import _write_three_route_source

    raw = tmp_path / "raw"
    _write_three_route_source(raw)
    monkeypatch.setattr(campaign, "ROOT", tmp_path)
    monkeypatch.setattr(preparation, "ROOT", tmp_path)
    monkeypatch.setattr(preparation, "OLD_SOURCE_DIR", raw)
    monkeypatch.setattr(diagnostic, "ROOT", tmp_path)
    legacy = tmp_path / "legacy_source"
    monkeypatch.setattr(preparation, "THREE_ROUTE_SOURCE_CANDIDATE_DIR", legacy)
    preparation.build_source_candidate(route_codes=preparation.THREE_ROUTE_CODES)
    # Poison the old audit location so this test cannot pass by accidentally
    # reading a previous campaign's otherwise identical input.
    (legacy / "timetable_rows.json").write_text("[]")
    snapshot = {p.name: p.read_bytes() for p in legacy.iterdir()}
    monkeypatch.setattr(diagnostic, "git_state", lambda: {"sha": "frozen", "status_porcelain": ""})
    sources = []

    def prepare(week, output, source, *, existing, validation_mode):
        assert existing is None and validation_mode is True
        sources.append(source)
        return {"formal_prepared": True, "input_preparation_valid": True}

    monkeypatch.setattr(preparation, "prepare_week", prepare)
    monkeypatch.setattr(diagnostic, "audit_prepared_inputs", lambda _: {
        "cases": {"2025-05-12": {"status": "READY"}}, "blockers": []})
    monkeypatch.setattr(diagnostic, "audit_parent_fleet", lambda _: {"blockers": []})
    monkeypatch.setattr(diagnostic, "build_public_evaluation", lambda *_: {})
    case_status = "DAY_AHEAD_ONLY_DIAGNOSIS_COMPLETE" if day_ahead_only else "DIAGNOSTIC_EXECUTION_PASSED"
    solver_calls = []

    def solve(week, output, config, **kwargs):
        solver_calls.append(week)
        return {"week": week, "status": case_status, "day_ahead_feasible": True}

    monkeypatch.setattr(diagnostic, "solve_week", solve)
    design = {"evaluation_weeks": ["2025-05-12"], "route_codes": list(preparation.THREE_ROUTE_CODES),
              "route_source": "legacy_source/selected_routes.json",
              "route_source_fallback": "missing_catalog.json",
              "route_timetable_audit_source": "legacy_source/timetable_rows.json",
              "research_status": "DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS",
              "diagnostic_stop_after_day_ahead": day_ahead_only}
    original_design = deepcopy(design)
    for profile in ("dual", "norel"):
        result = campaign.run_campaign(design, tmp_path / profile)
        assert result["status"] == ("DAY_AHEAD_ONLY_CAMPAIGN_COMPLETE" if day_ahead_only else "COMPLETED")
        audit = json.loads((tmp_path / profile / "cases/2025-05-12/diagnostic/scope_audit.json").read_text(encoding="utf-8"))
        assert audit["route_scope_complete"]
        assert all(row["trip_count"] == 1 for row in audit["timetable_evidence"].values())
        for filename in ("design.json", "cases/2025-05-12/design.json", "cases/2025-05-12/diagnostic/design.json"):
            effective = json.loads((tmp_path / profile / filename).read_text(encoding="utf-8"))
            assert effective["route_timetable_audit_source"] == f"{profile}/source_candidate/timetable_rows.json"
    assert solver_calls == ["2025-05-12", "2025-05-12"]
    assert design == original_design
    assert len(sources) == 2
    assert sources[0]["source_directory"] != sources[1]["source_directory"]
    assert sources[0]["artifacts"] == sources[1]["artifacts"]
    for source in sources:
        copied = tmp_path / source["source_directory"] / "timetable_rows.json"
        assert json.loads(copied.read_text(encoding="utf-8")) == json.loads((raw / "timetable_rows.json").read_text(encoding="utf-8"))
    assert {p.name: p.read_bytes() for p in legacy.iterdir()} == snapshot


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
