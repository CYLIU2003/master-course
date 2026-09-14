from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path

import pytest

from scripts.benchmarks.monthly_week_contract import select_monthly_weeks, validate_balanced_week
from src.optimization.common.date_series import materialize_dated_timetable


def _week(start="2025-11-10", holidays=()):
    templates = [{"trip_id": service, "route_id": "route", "service_id": service,
                  "operator_id": "tokyu", "departure": "09:00", "arrival": "09:30",
                  "distance_km": 4.0, "distance_source": "verified_source"}
                 for service in ("WEEKDAY", "SAT", "SUN_HOL")]
    dates = [(date.fromisoformat(start) + timedelta(days=i)).isoformat() for i in range(7)]
    return materialize_dated_timetable(templates, service_dates=dates, holiday_dates=holidays,
                                       source_provenance={})


def test_balanced_week_checks_actual_service_rows_without_mutating_them():
    rows, contract = _week()
    before = deepcopy((rows, contract))
    result = validate_balanced_week(rows, contract, week="2025-11-10")
    assert result["day_type_counts"] == {"weekday": 5, "saturday": 1, "sunday_or_holiday": 1}
    assert result["holiday_dates_in_window"] == []
    assert (rows, contract) == before


def test_culture_day_week_is_rejected_even_with_a_valid_materialized_timetable():
    rows, contract = _week("2025-11-03", ["2025-11-03"])
    with pytest.raises(ValueError, match="public holidays"):
        validate_balanced_week(rows, contract, week="2025-11-03")


@pytest.mark.parametrize("start", ["2025-11-11", "2025-09-29"])
def test_non_monday_or_cross_month_week_is_rejected(start):
    rows, contract = _week(start)
    with pytest.raises(ValueError, match="Monday-Sunday within one month"):
        validate_balanced_week(rows, contract, week=start)


def test_weekday_template_tampering_is_rejected():
    rows, contract = _week()
    rows[0]["service_id"] = "SUN_HOL"
    with pytest.raises(ValueError, match="changed after materialization"):
        validate_balanced_week(rows, contract, week="2025-11-10")


def test_2025_selection_preserves_all_months_and_skips_golden_week_and_culture_day():
    root = Path(__file__).resolve().parents[1]
    selection = json.loads((root / "config/shibu21_23_monthly_2025_20260914.json").read_text(encoding="utf-8"))
    weeks = select_monthly_weeks(2025, selection["selection_holiday_dates"])
    assert weeks == selection["evaluation_weeks"]
    assert [date.fromisoformat(week).month for week in weeks] == list(range(1, 13))
    assert weeks[4] == "2025-05-12"
    assert weeks[10] == "2025-11-10"


@pytest.mark.parametrize("change", ["none", "weekday_template", "manifest_counts", "forecast", "holiday_hash"])
def test_canonical_prepared_audit_rechecks_monthly_evidence(tmp_path, monkeypatch, change):
    from scripts.benchmarks import run_shibu21_24_seasonal_diagnostic as runner
    from src.optimization.common.date_series import content_hash
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    rows, contract = _week()
    contract["source_provenance"]["holiday_source_sha256"] = "calendar-hash"
    audit = validate_balanced_week(rows, contract, week="2025-11-10")
    forecast = {"weekly_profile_verified": True, "training_end_exclusive": "2025-01-01"}
    contract["forecast_audit"] = deepcopy(forecast)
    route = {"id": "route", "distanceKm": 4.0}
    case = {"input_preparation_valid": True, "scenario_id": "scenario", "prepared_input_id": "input",
            "declared_route_metadata_sha256": content_hash({"route": route}), "route_metadata_preserved": True,
            "scope_summary": {"route_catalog_audit": {"issueCount": 0, "checkedRouteCount": 1}},
            "balanced_week_audit": audit, "forecast_audit": forecast}
    if change == "weekday_template":
        rows[0]["service_id"] = "SUN_HOL"
    elif change == "manifest_counts":
        case["balanced_week_audit"]["day_type_counts"]["weekday"] = 4
    elif change == "forecast":
        contract["forecast_audit"]["weekly_profile_verified"] = False
    elif change == "holiday_hash":
        contract["source_provenance"]["holiday_source_sha256"] = "wrong"
    manifest_dir = tmp_path / "manifests/2025-11-10"
    canonical_dir = tmp_path / "prepared/scenario"
    manifest_dir.mkdir(parents=True)
    canonical_dir.mkdir(parents=True)
    (manifest_dir / "derived_scenarios.json").write_text(json.dumps({"cases": [case]}), encoding="utf-8")
    (canonical_dir / "input.json").write_text(json.dumps({
        "routes": [route], "trips": rows, "simulation_config": {"date_series_contract": contract},
        "prepared_scope_audit": {"strict_coverage_precheck": {"checked": True, "infeasible": False},
            "formal_transition_network_ready": True, "formal_turnaround_sensitivity_ready": True,
            "formal_vehicle_trip_compatibility_ready": True}}), encoding="utf-8")
    result = runner.audit_prepared_inputs({"evaluation_weeks": ["2025-11-10"],
        "input_manifests_directory": "manifests", "prepared_inputs_directory": "prepared",
        "require_balanced_monthly_weeks": True, "training_end_exclusive": "2025-01-01",
        "calendar_source_sha256": "calendar-hash"})
    assert result["cases"]["2025-11-10"]["status"] == (
        "READY" if change == "none" else "BLOCKED_MONTHLY_WEEK_CONTRACT")
