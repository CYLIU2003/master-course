from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.audit_small_integrated_weather_milp as oracle
from tools.november_2026.analyze_candidate_profile_results import analyze_profiles
from tools.november_2026 import run_rain_candidate_sensitivity as rain


PROFILE_PATH = Path("config/research/november_2026/rain_candidate_profiles_v2.json")


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
    assert payload["formulations"] == ["P3_DEPLOYED", "P4_SCALAR"]


def test_rain_profiles_load_exact_2x2_and_stage2_is_fixed() -> None:
    payload = rain.load_profiles(PROFILE_PATH)

    assert set(payload["profiles"]) == rain.EXPECTED_PROFILES
    assert {row["stage2_time_limit_seconds"] for row in payload["profiles"].values()} == {30}


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
    return {
        "candidate_hash": candidate_hash,
        "assignment_hash": assignment or candidate_hash,
        "stage2_feasible": True,
        "canonical_evaluation_feasible": True,
        "physical_validation_feasible": True,
        "stage2_actual_canonical_cost_jpy": cost,
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
