from __future__ import annotations

import json
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.audit_small_integrated_weather_milp as oracle
from tools.november_2026 import run_small_oracle_matrix as oracle_runner
from tools.november_2026.analyze_candidate_profile_results import (
    analyze_profiles,
    validate_profile_results,
    write_outputs,
)
from tools.november_2026 import run_rain_candidate_sensitivity as rain
from tools.november_2026.normalize_rain_profile_result import (
    normalize_profile_result,
    write_profile_result,
)


PROFILE_PATH = Path("config/research/november_2026/rain_candidate_profiles_v3.json")


def test_oracle_plan_only_never_calls_solve(monkeypatch, tmp_path: Path) -> None:
    problem = SimpleNamespace(
        trips=(SimpleNamespace(trip_id="t1"),),
        vehicles=(SimpleNamespace(vehicle_id="bev-1", vehicle_type="BEV"),),
    )
    monkeypatch.setattr(oracle, "collect_git_state", lambda **_: {
        "git_state_available": True, "git_dirty": False, "git_sha": "a" * 40,
    })
    monkeypatch.setattr(oracle, "load_prepared_input", lambda **_: {"prepared": True})
    monkeypatch.setattr(oracle, "_build_problem", lambda *_: problem)
    monkeypatch.setattr(
        oracle, "OptimizationEngine",
        lambda: SimpleNamespace(solve=lambda *_: pytest.fail("solve was called")),
    )
    args = SimpleNamespace(
        output=str(tmp_path / "plan.json"), gurobi_threads=1, random_seed=42,
        time_limit_sec=300, scenario_id="scenario", prepared_input_id="prepared-new",
        depot_id="tsurumaki", service_id="WEEKDAY", plan_only=True,
    )

    assert oracle.run(args) == 0
    payload = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "PLAN_ONLY_NO_SOLVE"
    assert payload["formulations"] == [
        "P3_ALIGNED_REFERENCE", "P4_SCALAR_EXACT_REFERENCE"
    ]


def test_rain_profiles_load_exact_2x2_and_stage2_is_fixed() -> None:
    payload = rain.load_profiles(PROFILE_PATH)

    assert set(payload["profiles"]) == rain.EXPECTED_PROFILES
    assert {row["stage2_time_limit_seconds"] for row in payload["profiles"].values()} == {30}
    assert payload["profiles"]["BASE"]["time_limit_seconds"] == 585
    assert payload["profiles"]["RANGE_ONLY"]["time_limit_seconds"] == 585
    assert payload["profiles"]["BUDGET_ONLY"]["time_limit_seconds"] == 1650
    assert payload["profiles"]["FULL_EXPANDED"]["time_limit_seconds"] == 1650


def test_rain_profile_rejects_nonallowlisted_field(tmp_path: Path) -> None:
    payload = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    payload["profiles"]["BASE"]["mip_gap"] = 0.9
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="non-allowlisted"):
        rain.load_profiles(path)


def test_rain_rejects_nonprofile_request_drift() -> None:
    requests = {name: {"mip_gap": 0.1, "stage1_time_limit_seconds": 435} for name in rain.EXPECTED_PROFILES}
    requests["RANGE_ONLY"]["mip_gap"] = 0.2

    with pytest.raises(ValueError, match="forbidden non-profile drift"):
        rain.validate_nonprofile_drift(requests, {"stage1_time_limit_seconds"})


def test_rain_plan_separates_requested_and_effective_controls() -> None:
    profiles = rain.load_profiles(PROFILE_PATH)
    plan = rain.build_plan(
        common_prepare={"day_type": "WEEKDAY"},
        common_optimization={"mip_gap": 0.1, "gurobi_threads": 1},
        profile_payload=profiles, adapter_sha="a" * 40,
    )

    assert plan["requested_requests"]["BASE"]["mip_gap"] == 0.1
    assert "mip_gap" not in plan["effective_controls"]["BASE"]
    assert plan["effective_controls"]["FULL_EXPANDED"]["stage2_time_limit_seconds"] == 30
    assert "prepared_manifest.json" in plan["planned_artifacts"]
    assert all(
        f"{profile}/profile_result_v1.json" in plan["planned_artifacts"]
        for profile in rain.PROFILE_ORDER
    )
    assert "candidate_inventory.json" not in plan["planned_artifacts"]


def test_rain_execute_rejects_null_advisor_fields() -> None:
    with pytest.raises(RuntimeError, match="advisor fields"):
        rain.require_execution_approval({
            "advisor_decision_date": None,
            "advisor_approved_threshold": None,
            "approved_profiles": None,
        })


def test_rain_main_rejects_dirty_sha_before_io(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(rain, "_git_state", lambda: ("a" * 40, True))

    with pytest.raises(RuntimeError, match="dirty"):
        rain.main([
            "--plan-only", "--prepare-request", str(tmp_path / "missing.json"),
            "--optimization-request", str(tmp_path / "missing2.json"),
            "--output-dir", str(tmp_path / "out"),
        ])


def test_rain_plan_only_uses_no_http_and_rejects_nonempty_output(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(rain, "_git_state", lambda: ("a" * 40, False))
    prepare = tmp_path / "prepare.json"
    optimization = tmp_path / "optimization.json"
    prepare.write_text('{"day_type":"WEEKDAY"}', encoding="utf-8")
    optimization.write_text('{"mip_gap":0.1}', encoding="utf-8")
    output = tmp_path / "out"
    output.mkdir()
    (output / "keep.txt").write_text("user data", encoding="utf-8")

    with pytest.raises(FileExistsError, match="empty"):
        rain.main([
            "--plan-only", "--prepare-request", str(prepare),
            "--optimization-request", str(optimization), "--output-dir", str(output),
        ])


def _candidate(candidate_hash: str, cost: float, assignment: str | None = None) -> dict:
    assignment_hash = assignment or candidate_hash
    if len(assignment_hash) != 64:
        assignment_hash = (assignment_hash * 64)[:64]
    return {
        "candidate_hash": candidate_hash,
        "assignment_hash": assignment_hash,
        "assignment_powertrain_hash": (candidate_hash * 64)[:64],
        "selectable": True,
        "stage2_feasible": True,
        "canonical_evaluation_feasible": True,
        "accounting_reconciliation_passed": True,
        "physical_validation_feasible": True,
        "trip_count_served": 264,
        "trip_count_unserved": 0,
        "fallback_used": False,
        "repair_used": False,
        "proxy_used": False,
        "assignment_hash_verified": True,
        "covers_264_unique_trips": True,
        "unique_vehicle_count": 3,
        "stage2_actual_canonical_cost_jpy": cost,
        "used_vehicle_count": 3,
        "used_bev": 2, "used_ice": 1, "bev_trips": 5, "ice_trips": 3,
    }


def test_candidate_analysis_jaccard_retention_winner_and_no_threshold_verdict() -> None:
    profiles = {
        "BASE": {"candidates": [_candidate("a", 100), _candidate("b", 110)]},
        "RANGE_ONLY": {"candidates": [_candidate("a", 100), _candidate("c", 90)]},
        "BUDGET_ONLY": {"candidates": [_candidate("b", 95), _candidate("d", 120)]},
        "FULL_EXPANDED": {"candidates": [_candidate("a", 100), _candidate("b", 110), _candidate("c", 90)]},
    }

    result = analyze_profiles(profiles)

    base_range = next(row for row in result["pairwise_overlaps"] if row["left_profile"] == "BASE" and row["right_profile"] == "RANGE_ONLY")
    assert base_range["jaccard"] == pytest.approx(1 / 3)
    assert result["profile_summaries"]["FULL_EXPANDED"]["base_candidate_retention_rate"] == 1.0
    assert result["profile_summaries"]["RANGE_ONLY"]["base_winner_present"] is True
    assert result["union_winner"]["candidate_hash"] == "c"
    assert result["status"] == "AWAITING_ADVISOR_THRESHOLD"
    assert result["stability_verdict"] is None


def test_candidate_analysis_uses_assignment_not_candidate_provenance() -> None:
    same_a = _candidate("source-a", 100, "a" * 64)
    same_b = _candidate("source-b", 100, "a" * 64)
    other = _candidate("source-a", 90, "b" * 64)
    profiles = {
        "BASE": {"candidates": [same_a]},
        "RANGE_ONLY": {"candidates": [same_b]},
        "BUDGET_ONLY": {"candidates": [other]},
        "FULL_EXPANDED": {"candidates": [same_a, same_b, other]},
    }

    result = analyze_profiles(profiles)
    base_range = result["pairwise_overlaps"][0]

    assert base_range["jaccard"] == 1.0
    assert result["profile_summaries"]["FULL_EXPANDED"]["selectable_candidate_count"] == 2
    assert result["union_winner"]["assignment_hash"] == "b" * 64


def test_candidate_winner_matches_production_tiebreak() -> None:
    expensive_fleet = _candidate("z", 100, "c" * 64)
    expensive_fleet.update(used_vehicle_count=4, used_bev=3, used_ice=1)
    small_fleet_late_hash = _candidate("x", 100, "d" * 64)
    small_fleet_early_hash = _candidate("y", 100, "b" * 64)
    rows = [expensive_fleet, small_fleet_late_hash, small_fleet_early_hash]
    profiles = {name: {"candidates": rows} for name in rain.PROFILE_ORDER}

    result = analyze_profiles(profiles)

    assert result["union_winner"]["assignment_hash"] == "b" * 64


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("accounting_reconciliation_passed", False),
        ("fallback_used", True),
        ("repair_used", True),
        ("proxy_used", True),
        ("trip_count_served", 263),
        ("stage2_actual_canonical_cost_jpy", float("nan")),
    ],
)
def test_candidate_formal_gate_excludes_invalid_rows(field: str, value: object) -> None:
    invalid = _candidate("a", 1)
    invalid[field] = value
    valid = _candidate("b", 2)
    profiles = {name: {"candidates": [invalid, valid]} for name in rain.PROFILE_ORDER}

    result = analyze_profiles(profiles)

    assert result["union_winner"]["candidate_hash"] == "b"


def test_rain_rejects_broken_2x2_vector(tmp_path: Path) -> None:
    payload = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    payload["profiles"]["BUDGET_ONLY"]["stage1_composition_search_radius"] = 8
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="2x2 range vector"):
        rain.load_profiles(path)


def _approval_manifest() -> dict:
    return {
        "schema_version": "rain_2x2_approval_v1",
        "experiment_id": "november-2026-rain-2x2",
        "experiment_family": "rain_2x2",
        "planning_sha": rain.PLANNING_SHA,
        "adapter_sha": "2" * 40,
        "canonical_reference_sha": rain.CANONICAL_REFERENCE_SHA,
        "profile_definition_sha": "4" * 64,
        "request_sha": "5" * 64,
        "advisor_name": "Advisor",
        "advisor_decision_date": "2026-08-31",
        "approval_statement": "Approved for the exact listed runs",
        "approved_threshold": 1.0,
        "threshold_unit": "percent",
        "approved_run_list": list(rain.PROFILE_ORDER),
        "scenario_ids": ["b23fd26c-1233-4c73-bb9e-bdb8b1584760"],
        "stop_rules": ["any formal gate failure"],
        "solver_budget": {"seconds": 12000},
        "wall_budget": {"seconds": 14400},
        "disk_budget": {"bytes": 1000000},
        "claim_boundary": "finite preregistered profile matrix only",
        "forbidden_claims": ["global optimality"],
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("planning_sha", "bad", "40-hex"),
        ("advisor_decision_date", "31/08/2026", "ISO"),
        ("approved_threshold", float("inf"), "finite"),
        ("threshold_unit", "ratio", "percent"),
    ],
)
def test_execution_manifest_rejects_bad_types(
    field: str, value: object, message: str,
) -> None:
    manifest = _approval_manifest()
    manifest[field] = value

    with pytest.raises(RuntimeError, match=message):
        rain.require_execution_approval(manifest)


def test_execution_manifest_hashes_must_match_request() -> None:
    manifest = _approval_manifest()

    rain.require_execution_approval(
        manifest,
        adapter_sha="2" * 40,
        profile_sha="4" * 64,
        complete_request_sha="5" * 64,
    )

    with pytest.raises(RuntimeError, match="do not match"):
        rain.require_execution_approval(manifest, complete_request_sha="6" * 64)


def test_clean_sha_drift_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(rain, "_git_state", lambda: ("b" * 40, False))

    with pytest.raises(RuntimeError, match="drifted"):
        rain._require_clean_expected_sha("a" * 40)


def test_existing_empty_execute_output_is_accepted_and_failure_checkpointed(
    monkeypatch, tmp_path: Path,
) -> None:
    import scripts.run_frontend_controlled_pv_pair as pair

    class FakeClient:
        def __init__(self, _base_url: str) -> None:
            pass

        def request_json(self, *_args, **_kwargs):
            raise RuntimeError("mocked prepare failure")

    monkeypatch.setattr(pair, "HttpJsonClient", FakeClient)
    monkeypatch.setattr(rain, "_require_clean_expected_sha", lambda _sha: None)
    output = tmp_path / "existing-empty"
    output.mkdir()
    plan = {
        "adapter_commit_sha": "a" * 40,
        "scenario_id": "scenario",
        "profile_definition": {},
        "common_prepare_request": {},
        "common_optimization_request": {},
        "requested_requests": {},
    }

    with pytest.raises(RuntimeError, match="mocked prepare failure"):
        rain.execute_approved_plan(
            base_url="http://invalid", output_dir=output, plan=plan,
            timeout_seconds=1, poll_interval_seconds=0,
        )

    progress = json.loads((output / "progress_manifest.json").read_text(encoding="utf-8"))
    assert progress["status"] == "INTERRUPTED"
    assert progress["completed_profiles"] == []
    assert progress["code_sha"] == "a" * 40
    assert (output / "artifact_hashes.json").is_file()


def _write_profile_artifacts(root: Path, *, accounting_ok: bool = True) -> None:
    sha = "a" * 40
    candidate = _candidate("candidate-source", 100, "b" * 64)
    candidate.update(
        candidate_index=1,
        proxy_used=False,
        vehicle_trip_assignments=[
            {
                "trip_id": f"trip-{index}",
                "powertrain": "BEV" if index % 3 < 2 else "ICE",
                "vehicle_id": f"vehicle-{index % 3}",
            }
            for index in range(264)
        ],
    )
    pairs = sorted(
        (row["vehicle_id"], row["trip_id"])
        for row in candidate["vehicle_trip_assignments"]
    )
    candidate["assignment_hash"] = hashlib.sha256(
        json.dumps(pairs, separators=(",", ":")).encode()
    ).hexdigest()
    payloads = {
        "stage1_stage2_candidate_evaluation.json": {
            "selected_candidate_index": 1,
            "candidate_count_evaluated": 1,
            "selected_candidate_hash": candidate["candidate_hash"],
            "selected_canonical_actual_cost_jpy": candidate[
                "stage2_actual_canonical_cost_jpy"
            ],
            "candidates": [candidate],
        },
        "physical_schedule_validation.json": {"accepted": True, "failed_checks": []},
        "rolling_hourly_chain/rolling_chain_summary.json": {
            "chain_accepted": True, "all_steps_feasible": True,
            "expected_step_count": 24, "step_count": 24,
            "day_ahead_git_sha": sha, "prepared_input_id": "prepared-1",
            "prepared_input_sha256": "1" * 64,
            "effective_scenario_sha256": "2" * 64,
            "trip_input_hash": "3" * 64, "vehicle_input_hash": "4" * 64,
            "scenario_fleet_contract_hash": "5" * 64,
            "active_vehicle_id_hash": "6" * 64,
            "vehicle_parameter_hash": "7" * 64, "initial_state_hash": "8" * 64,
            "charger_configuration_hash": "9" * 64,
            "initial_soc_input_hash": "a" * 64,
        },
        "rolling_hourly_chain/executed_day_accounting.json": {"eligible": accounting_ok},
        "final_cost_reconciliation.json": {
            "status": "OK" if accounting_ok else "FAILED", "failed_artifacts": {},
        },
        "summary.json": {
            "scenario_id": "b23fd26c-1233-4c73-bb9e-bdb8b1584760",
            "trip_count_served": 264, "trip_count_unserved": 0,
            "stage1_certified_mip_gap_ratio": 0.1,
            "stage1_gurobi_raw_mip_gap_ratio": 0.2,
            "solve_time_seconds": 10, "stage1_termination_reason": "time_limit",
            "solution_validity": {"research_acceptance_checks": {
                "no_fallback": True, "no_postsolve_modification": True,
            }},
        },
        "optimization_parameters.json": {
            "prepared_input_id": "prepared-1", "effective_optimization_config": {},
        },
        "code_provenance.json": {"git_sha": sha, "git_dirty": False},
        "input_audit.json": {
            "prepared_input_sha256": "1" * 64,
            "effective_scenario_sha256": "2" * 64,
            "trip_input_hash": "3" * 64, "vehicle_input_hash": "4" * 64,
            "scenario_fleet_contract_hash": "5" * 64,
            "active_vehicle_id_hash": "6" * 64,
            "vehicle_parameter_hash": "7" * 64, "initial_state_hash": "8" * 64,
            "charger_configuration_hash": "9" * 64,
            "initial_soc_input_hash": "a" * 64,
            "effective_pv_profiles_sha256": "b" * 64,
            "depot_energy_assets_fixed_hash": "c" * 64,
        },
        "effective_controls.json": {"matched": True, "effective": {}},
    }
    for relative, payload in payloads.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")


def test_profile_result_accepts_only_all_formal_gates(tmp_path: Path) -> None:
    _write_profile_artifacts(tmp_path)

    result = normalize_profile_result(
        tmp_path, profile_name="BASE", requested_controls={}, expected_code_sha="a" * 40,
    )

    assert result["status"] == "ACCEPTED"
    assert result["candidate_counts"] == {"generated": 1, "evaluated": 1, "fully_selectable": 1}
    assert result["selected_candidate"]["selectable"] is True
    assert len(result["selected_candidate"]["assignment_powertrain_hash"]) == 64


def test_profile_result_preserves_formal_nonselected_candidates(tmp_path: Path) -> None:
    """Candidate gates must not collapse to the one run-level selected row."""

    _write_profile_artifacts(tmp_path)
    path = tmp_path / "stage1_stage2_candidate_evaluation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for candidate_index in range(1, 4):
        row = dict(payload["candidates"][0])
        row.update(
            candidate_index=candidate_index,
            candidate_hash=f"{candidate_index}" * 64,
            selectable=True,
            accounting_reconciliation_passed=True,
            fallback_used=False,
            repair_used=False,
            proxy_used=False,
            trip_count_served=264,
            trip_count_unserved=0,
            stage2_actual_canonical_cost_jpy=100.0 + candidate_index,
            vehicle_trip_assignments=[
                {
                    "trip_id": f"trip-{trip_index}",
                    "powertrain": "BEV" if trip_index % 3 < 2 else "ICE",
                    "vehicle_id": f"vehicle-{candidate_index}-{trip_index % 3}",
                }
                for trip_index in range(264)
            ],
        )
        pairs = sorted(
            (assignment["vehicle_id"], assignment["trip_id"])
            for assignment in row["vehicle_trip_assignments"]
        )
        row["assignment_hash"] = hashlib.sha256(
            json.dumps(pairs, separators=(",", ":")).encode()
        ).hexdigest()
        rows.append(row)
    payload["candidates"] = rows
    payload["selected_candidate_index"] = 1
    payload["selected_candidate_hash"] = rows[0]["candidate_hash"]
    payload["selected_canonical_actual_cost_jpy"] = rows[0][
        "stage2_actual_canonical_cost_jpy"
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = normalize_profile_result(
        tmp_path, profile_name="BASE", requested_controls={}, expected_code_sha="a" * 40,
    )

    assert result["candidate_counts"] == {
        "generated": 3,
        "evaluated": 3,
        "fully_selectable": 3,
    }
    assert result["selected_candidate"]["candidate_index"] == 1


def test_profile_result_rejects_accounting_failure(tmp_path: Path) -> None:
    _write_profile_artifacts(tmp_path, accounting_ok=False)

    result = normalize_profile_result(
        tmp_path, profile_name="BASE", requested_controls={}, expected_code_sha="a" * 40,
    )

    assert result["status"] == "REJECTED"
    assert result["formal_gates"]["accounting_reconciliation_passed"] is False


def test_candidate_duplicate_trip_is_not_formally_selectable(tmp_path: Path) -> None:
    _write_profile_artifacts(tmp_path)
    path = tmp_path / "stage1_stage2_candidate_evaluation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    row = payload["candidates"][0]
    row["vehicle_trip_assignments"][1]["trip_id"] = row["vehicle_trip_assignments"][0]["trip_id"]
    pairs = sorted(
        (item["vehicle_id"], item["trip_id"])
        for item in row["vehicle_trip_assignments"]
    )
    row["assignment_hash"] = hashlib.sha256(
        json.dumps(pairs, separators=(",", ":")).encode()
    ).hexdigest()
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = normalize_profile_result(
        tmp_path, profile_name="BASE", requested_controls={}, expected_code_sha="a" * 40,
    )

    assert result["candidate_counts"]["fully_selectable"] == 0
    assert "covers_264_unique_trips" in result["selected_candidate"]["candidate_gate_blockers"]


def test_candidate_missing_candidate_level_field_is_not_promoted(tmp_path: Path) -> None:
    _write_profile_artifacts(tmp_path)
    path = tmp_path / "stage1_stage2_candidate_evaluation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    del payload["candidates"][0]["accounting_reconciliation_passed"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = normalize_profile_result(
        tmp_path, profile_name="BASE", requested_controls={}, expected_code_sha="a" * 40,
    )

    assert result["candidate_counts"]["fully_selectable"] == 0
    assert result["selected_run_formally_accepted"] is True
    assert result["candidate_stability_evidence_status"] == "INSUFFICIENT"


def test_selected_candidate_identity_drift_rejects_profile(tmp_path: Path) -> None:
    _write_profile_artifacts(tmp_path)
    path = tmp_path / "stage1_stage2_candidate_evaluation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["selected_candidate_hash"] = "f" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    result = normalize_profile_result(
        tmp_path, profile_name="BASE", requested_controls={}, expected_code_sha="a" * 40,
    )

    assert result["status"] == "REJECTED"
    assert result["formal_gates"]["selected_candidate_hash_matches"] is False


def test_missing_profile_artifact_fails_closed(tmp_path: Path) -> None:
    _write_profile_artifacts(tmp_path)
    (tmp_path / "physical_schedule_validation.json").unlink()

    with pytest.raises(FileNotFoundError, match="missing required profile artifact"):
        normalize_profile_result(
            tmp_path, profile_name="BASE", requested_controls={},
            expected_code_sha="a" * 40,
        )


def test_interrupted_profile_result_is_retained(tmp_path: Path) -> None:
    case = tmp_path / "BASE"
    case.mkdir()
    rain._write_interrupted_profile_result(
        case, profile_name="BASE",
        plan={
            "scenario_id": "scenario", "adapter_commit_sha": "a" * 40,
            "requested_requests": {"BASE": {"time_limit_seconds": 585}},
        },
        reason="RuntimeError: injected",
    )

    payload = json.loads((case / "profile_result_v1.json").read_text(encoding="utf-8"))
    assert payload["status"] == "INTERRUPTED"
    assert payload["termination_reason"] == "RuntimeError: injected"


def test_small_oracle_plan_shares_one_fresh_prepared_input(tmp_path: Path) -> None:
    prepare = tmp_path / "prepare.json"
    optimization = tmp_path / "optimization.json"
    prepare.write_text('{"day_type":"WEEKDAY"}', encoding="utf-8")
    optimization.write_text('{"mip_gap":0.0}', encoding="utf-8")
    args = SimpleNamespace(
        prepare_request=prepare, optimization_template=optimization,
        scenario_code="RAIN", trip_counts=[8, 12, 24], output_dir=tmp_path / "out",
        depot_id="tsurumaki", service_id="WEEKDAY", time_limit_sec=300,
        random_seed=42, gurobi_threads=1, vehicles_per_type=5,
    )

    plan = oracle_runner.build_plan(args, adapter_sha="a" * 40)

    assert plan["fresh_prepare_count"] == 1
    assert plan["trip_counts"] == [8, 12, 24]
    assert plan["formulations"] == [
        "P3_ALIGNED_REFERENCE", "P4_SCALAR_EXACT_REFERENCE"
    ]
    assert len(plan["expected_case_outputs"]) == 3


def test_small_oracle_execute_requires_complete_family_signoff(tmp_path: Path) -> None:
    plan = {
        "scenario_id": oracle_runner.SCENARIOS["RAIN"], "scenario_code": "RAIN",
        "trip_counts": [8, 12, 24], "adapter_commit_sha": "a" * 40,
        "complete_request_sha256": "b" * 64,
        "case_definition_sha256": "c" * 64,
    }

    with pytest.raises(RuntimeError, match="incomplete small-oracle signoff"):
        oracle_runner.require_execution_approval({}, plan=plan)

    approval = {
        "schema_version": "small_oracle_approval_v1",
        "experiment_id": "november-2026-small-oracle",
        "experiment_family": "small_oracle",
        "planning_sha": oracle_runner.PLANNING_SHA,
        "adapter_sha": "a" * 40,
        "canonical_reference_sha": oracle_runner.CANONICAL_REFERENCE_SHA,
        "scenario_ids": [oracle_runner.SCENARIOS["RAIN"]],
        "request_sha": "b" * 64,
        "case_definition_sha": "c" * 64,
        "approved_run_list": ["RAIN:8", "RAIN:12", "RAIN:24"],
        "advisor_name": "Advisor",
        "advisor_decision_date": "2026-08-31",
        "approval_statement": "Approved for exact listed runs",
        "approved_threshold": 0.1,
        "threshold_unit": "percent",
        "solver_budget": {"seconds": 1800},
        "wall_budget": {"seconds": 43200},
        "disk_budget": {"bytes": 1000000},
        "stop_rules": ["exact gate failure"],
        "claim_boundary": "deterministic subsets only",
        "forbidden_claims": ["264-trip approximation guarantee"],
    }
    oracle_runner.require_execution_approval(approval, plan=plan)
    approval["threshold_unit"] = "ratio"
    with pytest.raises(RuntimeError, match="unit must be percent"):
        oracle_runner.require_execution_approval(approval, plan=plan)


def test_offline_four_profile_e2e_is_deterministic_twice(tmp_path: Path) -> None:
    manifests = []
    for repetition in (1, 2):
        root = tmp_path / f"rehearsal-{repetition}"
        profiles = {}
        for profile_name in rain.PROFILE_ORDER:
            case = root / profile_name
            case.mkdir(parents=True)
            _write_profile_artifacts(case)
            result = normalize_profile_result(
                case, profile_name=profile_name, requested_controls={"seed": 42},
                expected_code_sha="a" * 40,
            )
            write_profile_result(case / "profile_result_v1.json", result)
            profiles[profile_name] = result
        validate_profile_results(profiles)
        comparison = analyze_profiles(profiles, advisor_threshold_percent=0.1)
        write_outputs(comparison, root / "analysis")
        hashes = {
            path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(root.rglob("*")) if path.is_file()
        }
        manifest = hashlib.sha256(
            json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        manifests.append(manifest)

    assert manifests[0] == manifests[1]
