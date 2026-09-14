"""Portable evidence-contract tests; fixtures are synthetic, never run results."""
from datetime import date, timedelta
import hashlib
import json

import pytest

from scripts.build_monthly_interpretation import collect, markdown
from src.optimization.common.date_series import materialize_dated_timetable

SOURCE_SHA = "a" * 40
WEEKS = ["2025-01-06", "2025-02-03", "2025-03-03", "2025-04-07",
         "2025-05-12", "2025-06-02", "2025-07-07", "2025-08-04",
         "2025-09-01", "2025-10-06", "2025-11-10", "2025-12-01"]


def _write(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(document, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _passed_week(campaign, week):
    case = campaign / "cases" / week / "diagnostic" / week
    chain = case / "rolling_hourly_chain"
    templates = [{"trip_id": service, "route_id": "route", "service_id": service,
                  "operator_id": "test", "departure": "09:00", "arrival": "09:30",
                  "distance_km": 4.0, "distance_source": "synthetic_test"}
                 for service in ("WEEKDAY", "SAT", "SUN_HOL")]
    dates = [(date.fromisoformat(week) + timedelta(days=i)).isoformat() for i in range(7)]
    trips, contract = materialize_dated_timetable(
        templates, service_dates=dates, holiday_dates=(),
        source_provenance={"holiday_source_sha256": "synthetic-calendar"},
    )
    contract["forecast_audit"] = {"model_sha256": "synthetic-forecast"}
    prepared = {"simulation_config": {"date_series_contract": contract},
                "trips": trips, "vehicles": [{"id": "bus", "type": "BEV", "initialSoc": 0.8}],
                "chargers": [{"id": "charger", "powerKw": 90}]}
    state = {"sha": SOURCE_SHA, "status_porcelain": ""}
    summary = {"status": "DIAGNOSTIC_EXECUTION_PASSED", "git_state_before": state,
               "git_state_after": state, "hourly_steps_accepted": 168,
               "day_ahead_physical_accepted": True, "physical_accepted": True,
               "trip_count": 7, "distance_km": 28.0, "used_vehicles": 1,
               "stage1_certified_gap": 0.5}
    costs = {"total_cost": 140305.0, "vehicle_usage_cost": 140000.0,
             "electricity_cost": 300.0, "fuel_cost": 0.0, "co2_cost": 5.0,
             "contract_overage_cost": 0.0, "used_vehicle_day_count": 7,
             "grid_import_kwh": 10.0, "peak_grid_kw": 40.0,
             "pv_generated_kwh": 6.0, "pv_used_total_kwh": 5.0, "pv_curtailed_kwh": 1.0,
             "pv_to_bus_kwh": 2.0, "pv_to_bess_kwh": 3.0, "bess_to_bus_kwh": 0.5,
             "grid_to_bess_kwh": 0.0, "contract_over_limit_kwh": 0.0,
             "total_co2_kg": 5.0, "ice_fuel_consumed_l": 0.0,
             "pv_asset_cost": 0.0, "bess_asset_cost": 0.0,
             "stationary_battery_degradation_cost": 0.0, "bess_discharge_cost": 0.0}
    accounting = {"eligible": True, "expected_slot_count": 672, "executed_slot_count": 672,
                  "missing_slots": [], "duplicate_slots": [], "cost_breakdown": costs,
                  "bess_terminal_soc_by_depot": {"tsurumaki": {
                      "initial_soc_kwh": 3000, "terminal_soc_kwh": 1200}}}
    plan = {"daily_cost_ledger": [{"total_cost_jpy": 20305.0}] +
                                 [{"total_cost_jpy": 20000.0} for _ in range(6)]}
    for field, quantity in {"grid_to_bus": 10.0, "grid_to_bess": 0.0, "pv_to_bus": 2.0,
                            "pv_to_bess": 3.0, "pv_curtail": 1.0, "bess_to_bus": 0.5}.items():
        plan[field + "_kwh_by_depot_slot"] = {"tsurumaki": {
            str(slot): quantity if slot == 0 else 0.0 for slot in range(672)}}
    physical = {"accepted": True, "status": "VALID", "violations": []}
    documents = {"case_summary": (case / "summary.json", summary),
                 "prepared_input": (campaign / "prepared" / f"{week}.json", prepared),
                 "executed_day_accounting": (chain / "executed_day_accounting.json", accounting),
                 "executed_plan": (chain / "executed_plan.json", plan),
                 "physical_validation": (chain / "physical_validation.json", physical)}
    hashes = {key: _write(path, document) for key, (path, document) in documents.items()}
    audit = {"status": "DIAGNOSTIC_EXECUTION_PASSED", "case_root": str(case),
             "prepared_input_path": str(documents["prepared_input"][0]), "hashes": hashes,
             "controls": {"pruned_arc_count": 0, "pruned_origin_count": 0,
                          "successor_pruning_enabled": False, "allow_postsolve_repair": False,
                          "synthetic_pv_fallback_applied": False}}
    return audit, documents


def _campaign(tmp_path, *, count=1, status="RUNNING_WEEK"):
    campaign = tmp_path / "campaign"
    design = {"campaign_declared_weeks": WEEKS, "calendar_source_sha256": "synthetic-calendar",
              "expected_fleet": {"count": 1, "BEV": 1}}
    _write(campaign / "design.json", design)
    _write(campaign / "progress.json", {"status": status, "base_git_sha": SOURCE_SHA})
    audit = {"expected_sha": SOURCE_SHA, "weeks": {}}
    documents = {}
    for week in WEEKS[:count]:
        audit["weeks"][week], documents[week] = _passed_week(campaign, week)
    audit_path = tmp_path / "audit.json"
    _write(audit_path, audit)
    return campaign, audit_path, audit, documents


def test_verified_partial_report_keeps_unexecuted_weeks_out_of_costs(tmp_path):
    campaign, audit_path, _, _ = _campaign(tmp_path)
    report = collect(campaign, audit_path, partial=True)
    assert report["completed_count"] == 1
    assert report["weeks"][0]["total_cost"] == 140305.0
    assert report["weeks"][0]["grid_import_kwh"] == 10.0
    assert report["pending_weeks"] == WEEKS[1:]
    assert report["seasons"] == []
    with pytest.raises(ValueError, match="remains incomplete"):
        collect(campaign, audit_path, partial=False)


def test_changed_source_bytes_cannot_pass_a_previous_independent_audit(tmp_path):
    campaign, audit_path, _, documents = _campaign(tmp_path)
    path, document = documents[WEEKS[0]]["executed_day_accounting"]
    document["cost_breakdown"]["total_cost"] += 1
    _write(path, document)
    with pytest.raises(ValueError, match="source hash mismatch"):
        collect(campaign, audit_path, partial=True)


@pytest.mark.parametrize("mutation,error", [
    ("source_state", "source state drift"), ("short_chain", "physical gate"),
    ("physical_violation", "physical gate"), ("missing_slot", "slot coverage gate"),
    ("ledger_mismatch", "daily ledger"), ("energy_mismatch", "grid_import_kwh"),
])
def test_rehashed_artifacts_still_have_to_pass_execution_and_accounting_gates(tmp_path, mutation, error):
    campaign, audit_path, audit, documents = _campaign(tmp_path)
    items = documents[WEEKS[0]]
    if mutation == "source_state":
        items["case_summary"][1]["git_state_after"] = {"sha": "b" * 40, "status_porcelain": ""}
    elif mutation == "short_chain":
        items["case_summary"][1]["hourly_steps_accepted"] = 167
    elif mutation == "physical_violation":
        items["physical_validation"][1]["violations"] = ["synthetic SOC violation"]
    elif mutation == "missing_slot":
        items["executed_day_accounting"][1]["executed_slot_count"] = 671
    elif mutation == "ledger_mismatch":
        items["executed_plan"][1]["daily_cost_ledger"][0]["total_cost_jpy"] += 1
    elif mutation == "energy_mismatch":
        items["executed_plan"][1]["grid_to_bus_kwh_by_depot_slot"]["tsurumaki"]["0"] = 11
    for key, (path, document) in items.items():
        audit["weeks"][WEEKS[0]]["hashes"][key] = _write(path, document)
    _write(audit_path, audit)
    with pytest.raises(ValueError, match=error):
        collect(campaign, audit_path, partial=True)


def test_failed_week_is_reported_and_its_summary_hash_is_checked(tmp_path):
    campaign, audit_path, audit, _ = _campaign(tmp_path, status="STOPPED_AFTER_FAILED_CASE")
    week = WEEKS[3]
    path = campaign / "cases" / week / "diagnostic" / week / "summary.json"
    failed = {"status": "HOURLY_SOLVE_FAILED", "hourly_steps_accepted": 23,
              "failed_hour": 23, "hourly_reasons": ["synthetic failure"]}
    audit["weeks"][week] = {"status": "HOURLY_SOLVE_FAILED", "failure": {"failed_hour": 23},
                            "hashes": {"case_summary": _write(path, failed)}}
    _write(audit_path, audit)
    report = collect(campaign, audit_path, partial=True)
    assert report["status"] == "STOPPED_AFTER_FAILED_CASE"
    assert len(report["weeks"]) == 1
    assert report["failed_weeks"][0]["failed_hour"] == 23
    failed["failed_hour"] = 24
    _write(path, failed)
    with pytest.raises(ValueError, match="failure source hash mismatch"):
        collect(campaign, audit_path, partial=True)


def test_twelve_audited_weeks_still_require_a_stable_completed_campaign(tmp_path):
    campaign, audit_path, _, _ = _campaign(tmp_path, count=12, status="COMPLETED")
    final = {"status": "COMPLETED", "base_git_sha": SOURCE_SHA, "source_state_stable": True}
    _write(campaign / "summary.json", final)
    report = collect(campaign, audit_path, partial=False)
    assert report["status"] == "COMPLETED"
    assert len(report["weeks"]) == 12 and len(report["seasons"]) == 4
    rendered = markdown(report, None)
    assert "季節別の記述的比較" in rendered and "観察と示唆" in rendered
    assert "1,800.0〜1,800.0 kWh" in rendered
    assert "研究採用BLOCKED" in rendered
    final["source_state_stable"] = False
    _write(campaign / "summary.json", final)
    with pytest.raises(ValueError, match="Final campaign gate failed"):
        collect(campaign, audit_path, partial=False)
