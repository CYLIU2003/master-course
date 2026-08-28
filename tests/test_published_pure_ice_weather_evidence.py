from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = (
    REPO_ROOT / "docs" / "evidence" / "pure_ice_weather_ab_453b1d3"
)
EXECUTION_SHA = "453b1d340311de109645d006b9ec5a0de2788c2e"
FULL_INDEX_SHA256 = (
    "f6b7232164ee2ed9df5f9cf7b005f25a5f25c1c6f3699240acae05b41bcbe672"
)
PUBLISHED_SOURCE_PATHS = {
    "weather_ab_result.json": "weather_ab_result.json",
    "SUNNY_repeated_comparison.json": (
        "scenarios/SUNNY/repeated_comparison.json"
    ),
    "SUNNY_repeated_comparison.csv": (
        "scenarios/SUNNY/repeated_comparison.csv"
    ),
    "SUNNY_repeated_comparison.md": "scenarios/SUNNY/repeated_comparison.md",
    "RAIN_repeated_comparison.json": "scenarios/RAIN/repeated_comparison.json",
    "RAIN_repeated_comparison.csv": "scenarios/RAIN/repeated_comparison.csv",
    "RAIN_repeated_comparison.md": "scenarios/RAIN/repeated_comparison.md",
    "weather_cross_scenario_comparison.json": (
        "weather_cross_scenario_comparison.json"
    ),
    "weather_cross_scenario_comparison.csv": (
        "weather_cross_scenario_comparison.csv"
    ),
    "weather_cross_scenario_comparison.md": (
        "weather_cross_scenario_comparison.md"
    ),
    "request_manifest.json": "request_manifest.json",
    "fresh_prepare_manifest.json": "preparation/fresh_prepare_manifest.json",
}


def _read_json(name: str) -> dict[str, Any]:
    payload = json.loads((EVIDENCE_ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_published_evidence_matches_frozen_full_bundle_index() -> None:
    artifact_index_path = EVIDENCE_ROOT / "artifact_hashes.json"
    assert _sha256(artifact_index_path) == FULL_INDEX_SHA256
    full_index = _read_json("artifact_hashes.json")["sha256"]
    assert len(full_index) == 103

    for published_name, source_relative_path in PUBLISHED_SOURCE_PATHS.items():
        published_path = EVIDENCE_ROOT / published_name
        assert published_path.is_file(), published_name
        assert _sha256(published_path) == full_index[source_relative_path]


def test_published_evidence_preserves_verdict_and_claim_controls() -> None:
    result = _read_json("weather_ab_result.json")
    assert result["status"] == "COMPLETED"
    assert result["git_sha"] == EXECUTION_SHA
    assert result["completed_case_counts"] == {"SUNNY": 10, "RAIN": 10}
    assert result["scenario_verdicts"] == {
        "SUNNY": "PASS_STRUCTURAL_ONLY",
        "RAIN": "PASS_STRUCTURAL_ONLY",
    }

    for scenario in ("SUNNY", "RAIN"):
        repeated = _read_json(f"{scenario}_repeated_comparison.json")
        assert repeated["correctness"]["passed"] is True
        assert repeated["correctness"]["all_individual_runs_valid"] is True
        assert repeated["correctness"]["median_solver_time_improved"] is False
        assert repeated["verdict"] == "PASS_STRUCTURAL_ONLY"
        assert len(repeated["case_runs"]) == 10

    request = _read_json("request_manifest.json")
    assert request["git_sha"] == EXECUTION_SHA
    assert request["git_dirty"] is False
    assert request["solver_controls"] == {
        "random_seed": 42,
        "gurobi_threads": 1,
        "mip_gap": 0.1,
        "stage1_time_limit_seconds": 435,
        "stage2_time_limit_seconds": 30,
        "wall_clock_overhead_seconds": 120,
        "stage1_best_obj_stop_enabled": False,
        "stage1_powertrain_selector_strengthening": False,
        "time_step_min": 15,
        "rolling_execution_minutes": 60,
    }
    assert request["prepared_content_contract"][
        "all_fixed_prepared_content_matches"
    ] is True
    assert request["prepared_inputs"]["RAIN"]["service_date"] == "2025-08-05"
    rain_weather = request["prepared_inputs"]["RAIN"][
        "weather_and_counterfactual_fields"
    ]
    assert rain_weather["counterfactual_pv_source_date"] == "2025-08-10"
    assert rain_weather["calendar_policy"] == (
        "fixed_weekday_timetable_pv_counterfactual"
    )
    assert rain_weather["enable_weather_operation_policy"] is False

    cross = _read_json("weather_cross_scenario_comparison.json")
    assert cross["input_contract"]["all_fixed_controls_match"] is True
    assert cross["input_contract"]["pv_profile_hashes_differ"] is True

    readme = " ".join(
        (EVIDENCE_ROOT / "README.md").read_text(encoding="utf-8").split()
    )
    for prohibited_claim in (
        "solver speedup",
        "optimality improvement",
        "integrated global optimum",
        "1%-optimal result",
    ):
        assert prohibited_claim in readme
