from pathlib import Path
import json

import pytest

from scripts.benchmarks.prepare_shibu21_24_seasonal_inputs import (
    apply_seasonal_bess_policy,
)
import scripts.benchmarks.run_shibu21_24_seasonal_diagnostic as seasonal_runner
from src.optimization.rolling.reoptimizer import RollingReoptimizer
from scripts.benchmarks.run_shibu21_24_seasonal_diagnostic import (
    audit_parent_fleet,
    discover_route_scope,
    normalize_route_code,
)


ROOT = Path(__file__).resolve().parents[1]


def test_seasonal_bess_policy_preserves_asset_controls_and_removes_inventory_target():
    source = {
        "depot_id": "tsurumaki",
        "bess_enabled": True,
        "bess_energy_kwh": 6000.0,
        "bess_power_kw": 900.0,
        "bess_initial_soc_kwh": 3000.0,
        "bess_charge_efficiency": 0.95,
        "bess_discharge_efficiency": 0.95,
        "grid_to_bess_price_threshold_yen_per_kwh": 12.5,
        "bess_terminal_soc_min_kwh": 3000.0,
        "bess_terminal_soc_policy": "fixed_target",
        "bess_terminal_soc_target_kwh": 3000.0,
    }

    seasonal = apply_seasonal_bess_policy(source)

    for key in (
        "bess_energy_kwh",
        "bess_power_kw",
        "bess_initial_soc_kwh",
        "bess_charge_efficiency",
        "bess_discharge_efficiency",
        "grid_to_bess_price_threshold_yen_per_kwh",
    ):
        assert seasonal[key] == source[key]
    assert seasonal["bess_soc_min_kwh"] == pytest.approx(1200.0)
    assert seasonal["bess_soc_max_kwh"] == pytest.approx(4800.0)
    assert seasonal["bess_terminal_soc_min_kwh"] == pytest.approx(1200.0)
    assert seasonal["bess_terminal_soc_policy"] == "minimum_only"
    assert seasonal["bess_terminal_soc_target_kwh"] == 0.0
    assert source["bess_terminal_soc_policy"] == "fixed_target"


def test_seasonal_runner_contract_accepts_floor_only_bess_and_reports_no_target():
    config = json.loads(
        (ROOT / "config/shibu21_24_2025_seasonal_test.json").read_text(encoding="utf-8")
    )
    asset = type("Asset", (), {
        "bess_enabled": True,
        "bess_energy_kwh": 6000.0,
        "bess_initial_soc_kwh": 3000.0,
        "bess_soc_min_kwh": 1200.0,
        "bess_soc_max_kwh": 4800.0,
        "bess_terminal_soc_min_kwh": 1200.0,
        "bess_terminal_soc_policy": "minimum_only",
        "bess_terminal_soc_target_kwh": 0.0,
        "bess_balance_period": "evaluation_period",
    })()
    problem = type("Problem", (), {
        "metadata": {
            "bev_terminal_soc_policy": "return_to_initial",
            "final_soc_target_tolerance_percent": 0.0,
            "daily_return_depot_id": "tsurumaki",
            "rolling_window_terminal_policy": "day_ahead_boundary_state",
            "rolling_bess_terminal_policy": "minimum_only",
            "bess_balance_period": "evaluation_period",
        },
        "vehicles": (),
        "depot_energy_assets": {"tsurumaki": asset},
    })()

    contract = seasonal_runner.verify_evaluation_contract(problem, config)

    assert contract["bess_controls"]["tsurumaki"]["terminal_soc_target_kwh"] is None
    assert contract["bess_controls"]["tsurumaki"]["terminal_soc_floor_kwh"] == pytest.approx(1200.0)


def test_seasonal_rolling_policy_requires_day_ahead_reference():
    problem = type("Problem", (), {
        "metadata": {"rolling_window_terminal_policy": "day_ahead_boundary_state"},
    })()

    with pytest.raises((AttributeError, ValueError)):
        RollingReoptimizer._apply_window_terminal_targets(problem, None, 60, 24)


def test_route_matching_normalizes_full_width_digits_without_broad_matching():
    assert normalize_route_code(" 渋２１ ") == "渋21"
    assert normalize_route_code("渋２１臨時") != "渋21"


def test_four_route_scope_keeps_missing_shibu24_as_a_blocker():
    config = {
        "route_codes": ["渋21", "渋22", "渋23", "渋24"],
        "route_source": "data/derived/timetables/tsurumaki_20260901/selected_routes.json",
        "route_source_fallback": "data/catalog-fast/bundle.json",
        "route_timetable_audit_source": "data/derived/timetables/tsurumaki_20260901/timetable_rows.json",
    }
    audit = discover_route_scope(config)
    assert audit["route_scope_complete"] is False
    assert audit["timetable_evidence"]["渋24"]["trip_count"] == 0
    assert audit["timetable_evidence"]["渋21"]["trip_count"] > 0
    assert any("渋24" in blocker for blocker in audit["blockers"])


def test_parent_fleet_contract_is_read_from_untouched_scenario():
    config = {
        "parent_scenario_id": "771d115b-75b0-49f7-a7f0-25f259a2cd21",
        "expected_fleet": {"count": 60, "BEV": 35, "ICE": 25},
        "daily_return_depot_id": "tsurumaki",
    }
    audit = audit_parent_fleet(config)
    assert audit["status"] == "PARENT_FLEET_READY"
    assert audit["powertrain_counts"] == {"BEV": 35, "ICE": 25}


def test_prepared_input_audit_blocks_lightweight_candidate_with_deferred_transition_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(seasonal_runner, "ROOT", tmp_path)
    week = "2025-02-03"
    scenario_id = "scenario-four-route"
    prepared_input_id = "prepared-four-route"
    manifest_dir = tmp_path / "manifests" / week
    prepared_dir = tmp_path / "prepared" / scenario_id
    manifest_dir.mkdir(parents=True)
    prepared_dir.mkdir(parents=True)
    (manifest_dir / "derived_scenarios.json").write_text(
        json.dumps({
            "status": "INPUTS_PREPARED_DIAGNOSTIC",
            "cases": [{
                "input_preparation_valid": True,
                "scenario_id": scenario_id,
                "prepared_input_id": prepared_input_id,
            }],
        }),
        encoding="utf-8",
    )
    (prepared_dir / f"{prepared_input_id}.json").write_text(
        json.dumps({
            "prepared_scope_audit": {
                "status": "CANONICAL_INPUT_PREPARED_STRICT_TRANSITION_AUDIT_DEFERRED",
                "strict_transition_audit_executed": False,
            },
        }),
        encoding="utf-8",
    )

    audit = seasonal_runner.audit_prepared_inputs({
        "input_manifests_directory": "manifests",
        "prepared_inputs_directory": "prepared",
        "evaluation_weeks": [week],
    })

    assert audit["status"] == "BLOCKED_PREPARED_INPUTS"
    assert audit["cases"][week]["status"] == "BLOCKED_STRICT_TRANSITION_AUDIT_DEFERRED"
    assert audit["cases"][week]["strict_transition_audit_executed"] is False
    assert audit["blockers"] == [
        f"{week}: lightweight canonical candidate has deferred strict transition audit"
    ]


def test_prepared_input_audit_rejects_candidate_namespace_even_with_audit_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(seasonal_runner, "ROOT", tmp_path)
    week = "2025-05-12"
    scenario_id = "scenario-candidate"
    prepared_input_id = "prepared-candidate"
    manifest_dir = tmp_path / "manifests" / week
    candidate_path = tmp_path / "candidate" / scenario_id / f"{prepared_input_id}.json"
    manifest_dir.mkdir(parents=True)
    candidate_path.parent.mkdir(parents=True)
    (manifest_dir / "derived_scenarios.json").write_text(
        json.dumps({
            "status": "INPUTS_PREPARED_DIAGNOSTIC_CANDIDATE",
            "cases": [{
                "input_preparation_valid": False,
                "scenario_id": scenario_id,
                "prepared_input_id": prepared_input_id,
                "prepared_input_namespace": "candidate_prepared_inputs",
                "prepared_input_path": "candidate/scenario-candidate/prepared-candidate.json",
            }],
        }),
        encoding="utf-8",
    )
    candidate_path.write_text(
        json.dumps({"prepared_scope_audit": {
            "status": "CANONICAL_INPUT_PREPARED_STRICT_TRANSITION_AUDIT_DEFERRED",
            "strict_transition_audit_executed": False,
        }}),
        encoding="utf-8",
    )

    audit = seasonal_runner.audit_prepared_inputs({
        "input_manifests_directory": "manifests",
        "prepared_inputs_directory": "prepared",
        "evaluation_weeks": [week],
    })

    assert audit["cases"][week]["status"] == "BLOCKED_CANDIDATE_NAMESPACE"
    assert audit["blockers"] == [
        f"{week}: candidate prepared input is outside the formal prepared_inputs namespace"
    ]


def test_run_diagnostic_records_one_week_failure_and_continues(tmp_path, monkeypatch):
    weeks = ["2025-02-03", "2025-05-12"]
    preflight = {
        "status": "READY_FOR_FROZEN_RUN",
        "blockers": [],
        "worktree_dirty": False,
        "route_scope": {"blockers": []},
        "prepared_inputs": {"cases": {
            week: {"status": "READY"} for week in weeks
        }},
    }
    monkeypatch.setattr(seasonal_runner, "run_preflight", lambda config, output: preflight)
    monkeypatch.setattr(
        seasonal_runner,
        "git_state",
        lambda: {"sha": "frozen-sha", "status_porcelain": ""},
    )

    def fake_solve(week, output, config, **kwargs):
        assert kwargs["contract_validator"] is seasonal_runner.verify_evaluation_contract
        if week == weeks[0]:
            raise RuntimeError("synthetic week failure")
        return {
            "week": week,
            "status": "DIAGNOSTIC",
            "hourly_steps_accepted": 0,
            "physical_accepted": None,
            "accounting_eligible": None,
            "executed_cost": {},
        }

    monkeypatch.setattr(seasonal_runner, "solve_week", fake_solve)
    summaries = seasonal_runner.run_diagnostic({
        "evaluation_weeks": weeks,
        "research_status": "DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS",
        "route_codes": ["渋21", "渋22", "渋23", "渋24"],
    }, tmp_path)

    assert [row["status"] for row in summaries] == [
        "DIAGNOSTIC_CASE_FAILED", "DIAGNOSTIC"
    ]
    assert (tmp_path / weeks[0] / "failure.json").is_file()
    assert (tmp_path / weeks[1] / "git_state_after.json").is_file()
    final_summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert final_summary["source_state_stable"] is True
    assert final_summary["completed_weeks"] == weeks
    public = json.loads((tmp_path / "seasonal_evaluation.json").read_text(encoding="utf-8"))
    assert public["rows"][0]["reasons"] == ["RuntimeError: synthetic week failure"]
    assert public["status"] == "DIAGNOSTIC_EVALUATION_COMPLETE"
    assert public["formal_solve_executed"] is False


def test_invalid_prepare_blocks_only_its_week_and_preserves_four_route_scope(tmp_path, monkeypatch):
    weeks = ["2025-02-03", "2025-05-12"]
    preflight = {
        "status": "BLOCKED", "blockers": [f"{weeks[0]}: strict audit failed"],
        "worktree_dirty": False, "route_scope": {"blockers": []},
        "parent_fleet": {"blockers": []},
        "prepared_inputs": {
            "cases": {weeks[0]: {"status": "INVALID"}, weeks[1]: {"status": "READY"}},
            "blockers": [f"{weeks[0]}: strict audit failed"],
        },
    }
    monkeypatch.setattr(seasonal_runner, "run_preflight", lambda config, output: preflight)
    monkeypatch.setattr(seasonal_runner, "git_state", lambda: {"sha": "frozen", "status_porcelain": ""})
    solved = []

    def solve(week, output, config, **kwargs):
        assert kwargs["contract_validator"] is seasonal_runner.verify_evaluation_contract
        solved.append((week, config["route_codes"]))
        return {"week": week, "status": "DAY_AHEAD_FAILED", "hourly_steps_accepted": 0}

    monkeypatch.setattr(seasonal_runner, "solve_week", solve)
    codes = ["渋21", "渋22", "渋23", "渋24"]
    results = seasonal_runner.run_diagnostic({
        "evaluation_weeks": weeks, "route_codes": codes,
        "research_status": "DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS",
    }, tmp_path)
    assert solved == [(weeks[1], codes)]
    assert results[0]["status"] == "BLOCKED_CASE_PREFLIGHT"
    assert results[0]["physical_accepted"] is None
    assert results[0]["accounting_eligible"] is None


def test_prepare_success_does_not_override_failed_scope_audit(tmp_path, monkeypatch):
    monkeypatch.setattr(seasonal_runner, "ROOT", tmp_path)
    week = "2025-02-03"
    manifest_dir = tmp_path / "manifests" / week
    canonical_dir = tmp_path / "prepared" / "scenario"
    manifest_dir.mkdir(parents=True)
    canonical_dir.mkdir(parents=True)
    (manifest_dir / "derived_scenarios.json").write_text(json.dumps({"cases": [{
        "input_preparation_valid": True, "scenario_id": "scenario", "prepared_input_id": "input",
    }]}), encoding="utf-8")
    (canonical_dir / "input.json").write_text(json.dumps({"prepared_scope_audit": {
        "strict_coverage_precheck": {"checked": False},
        "formal_transition_network_ready": False,
        "formal_turnaround_sensitivity_ready": False,
        "formal_vehicle_trip_compatibility_ready": True,
    }}), encoding="utf-8")
    result = seasonal_runner.audit_prepared_inputs({
        "evaluation_weeks": [week], "input_manifests_directory": "manifests",
        "prepared_inputs_directory": "prepared",
    })
    assert result["cases"][week]["status"] == "BLOCKED_PREPARED_SCOPE_CONTRACT"
    assert "strict_coverage_precheck_not_checked" in result["blockers"][0]


@pytest.mark.parametrize("change", ["none", "missing_hash", "direction", "zero_distance", "catalog_warning"])
def test_preflight_requires_captured_route_metadata_after_all_physical_audits(
    tmp_path, monkeypatch, change,
):
    monkeypatch.setattr(seasonal_runner, "ROOT", tmp_path)
    week = "2025-02-03"
    manifest_dir = tmp_path / "manifests" / week
    canonical_dir = tmp_path / "prepared" / "scenario"
    manifest_dir.mkdir(parents=True)
    canonical_dir.mkdir(parents=True)
    route = {"id": "route-a", "distanceKm": 5.5, "canonicalDirection": "outbound"}
    case = {
        "input_preparation_valid": True, "scenario_id": "scenario", "prepared_input_id": "input",
        "declared_route_metadata_sha256": seasonal_runner.content_hash({"route-a": route}),
        "route_metadata_preserved": True,
        "scope_summary": {"route_catalog_audit": {"issueCount": 0, "checkedRouteCount": 1}},
    }
    if change == "missing_hash":
        case.pop("declared_route_metadata_sha256")
    elif change == "direction":
        route["canonicalDirection"] = "inbound"
    elif change == "zero_distance":
        route["distanceKm"] = 0
    elif change == "catalog_warning":
        case["scope_summary"]["route_catalog_audit"]["issueCount"] = 1
    (manifest_dir / "derived_scenarios.json").write_text(
        json.dumps({"cases": [case]}), encoding="utf-8",
    )
    (canonical_dir / "input.json").write_text(json.dumps({
        "routes": [route],
        "prepared_scope_audit": {
            "strict_coverage_precheck": {"checked": True, "infeasible": False},
            "formal_transition_network_ready": True,
            "formal_turnaround_sensitivity_ready": True,
            "formal_vehicle_trip_compatibility_ready": True,
        },
    }), encoding="utf-8")
    result = seasonal_runner.audit_prepared_inputs({
        "evaluation_weeks": [week], "input_manifests_directory": "manifests",
        "prepared_inputs_directory": "prepared",
    })
    expected = "READY" if change == "none" else "BLOCKED_ROUTE_METADATA_PROVENANCE"
    assert result["cases"][week]["status"] == expected


@pytest.mark.parametrize("distance", [None, True, "5.5", "invalid", float("nan"), float("inf"), -1.0])
def test_route_distance_provenance_rejects_unusable_values_without_throwing(distance):
    assert seasonal_runner._route_metadata_provenance_verified(
        {"routes": [{"id": "route-a", "distanceKm": distance}]}, {},
    ) is False
