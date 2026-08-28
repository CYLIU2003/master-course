from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPO_ROOT / "docs" / "evidence" / "weather_dispatch_case_a_3ec8714"
FULL_INDEX_SHA256 = (
    "68244b2c57f8f2055c1751f91e2d946a08b1a876830ccc6fd321eb3894c96981"
)
REAUDIT_INDEX_SHA256 = (
    "d57ed42ed9f76e3513347054aae50b7e5ad38ec2c0053901028cb22751341e6d"
)
PUBLISHED_SOURCE_PATHS = {
    "cross_weather_fixed_dispatch_matrix.json": (
        "cross_weather_fixed_dispatch_matrix.json"
    ),
    "cross_weather_fixed_dispatch_matrix.csv": "cross_weather_fixed_dispatch_matrix.csv",
    "cross_weather_fixed_dispatch_matrix.md": "cross_weather_fixed_dispatch_matrix.md",
    "case_a_candidate_selection_audit.json": "case_a_candidate_selection_audit.json",
    "case_a_candidate_selection_audit.csv": "case_a_candidate_selection_audit.csv",
    "case_a_candidate_selection_audit.md": "case_a_candidate_selection_audit.md",
    "normal_confirmation_input_contract.json": "normal_confirmation_input_contract.json",
    "normal_confirmation_input_contract.csv": "normal_confirmation_input_contract.csv",
    "normal_confirmation_input_contract.md": "normal_confirmation_input_contract.md",
    "confirmation_manifest.json": (
        "normal_path_confirmation_fixed_controls_ba5ac4a/confirmation_manifest.json"
    ),
    "weather_dispatch_diagnosis_report.md": "weather_dispatch_diagnosis_report.md",
    "goal_completion_audit.md": "goal_completion_audit.md",
}
REAUDIT_SOURCE_PATHS = {
    "normal_confirmation_reaudit_b18cf48.json": (
        "normal_path_confirmation_fixed_controls_ba5ac4a/confirmation_manifest.json"
    ),
    "normal_confirmation_input_contract_reaudit_b18cf48.json": (
        "normal_confirmation_input_contract.json"
    ),
    "normal_confirmation_input_contract_reaudit_b18cf48.csv": (
        "normal_confirmation_input_contract.csv"
    ),
    "normal_confirmation_input_contract_reaudit_b18cf48.md": (
        "normal_confirmation_input_contract.md"
    ),
    "case_a_candidate_selection_audit_reaudit_b18cf48.json": (
        "case_a_candidate_selection_audit.json"
    ),
    "case_a_candidate_selection_audit_reaudit_b18cf48.csv": (
        "case_a_candidate_selection_audit.csv"
    ),
    "case_a_candidate_selection_audit_reaudit_b18cf48.md": (
        "case_a_candidate_selection_audit.md"
    ),
}


def _read_json(name: str) -> dict[str, Any]:
    payload = json.loads((EVIDENCE_ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_published_case_a_evidence_matches_frozen_source_index() -> None:
    index_path = EVIDENCE_ROOT / "artifact_hashes.json"
    assert _sha256(index_path) == FULL_INDEX_SHA256
    full_index = _read_json("artifact_hashes.json")["sha256"]
    assert len(full_index) == 73

    for published_name, source_relative_path in PUBLISHED_SOURCE_PATHS.items():
        published_path = EVIDENCE_ROOT / published_name
        assert published_path.is_file(), published_name
        assert _sha256(published_path) == full_index[source_relative_path]


def test_published_case_a_claim_stays_bounded_and_auditable() -> None:
    matrix = _read_json("cross_weather_fixed_dispatch_matrix.json")
    assert matrix["candidate_count"] == 22
    assert len(matrix["rows"]) == 44
    assert matrix["verdict"]["case"] == "A"
    assert matrix["dispatch_reoptimization_performed"] is False

    audit = _read_json("case_a_candidate_selection_audit.json")
    assert audit["verdict"] == "FIXED"
    assert audit["case"] == "A"
    assert audit["candidate_union"]["unique_physical_assignment_count"] == 22
    assert all(
        all(scenario["checks"].values())
        for scenario in audit["scenarios"].values()
    )

    confirmation = _read_json("confirmation_manifest.json")
    assert confirmation["status"] == "PASS_NORMAL_PATH_CONFIRMATION"
    assert confirmation["execution_git_sha"] == (
        "ba5ac4abac490caccca006260670dfbc2c411fa9"
    )
    assert confirmation["pure_ice_aggregate_B_executed"] is False
    assert all(confirmation["winner_matches_fixed_dispatch_diagnosis"].values())

    input_contract = _read_json("normal_confirmation_input_contract.json")
    assert input_contract["status"] == "PASS_FULL_INPUT_CONTRACT"
    assert input_contract["fixed_nonweather_inputs_equal"] is True

    readme = " ".join((EVIDENCE_ROOT / "README.md").read_text().split())
    for prohibited_claim in (
        "integrated global optimum",
        "general weather benefit",
        "1%-optimal solution",
    ):
        assert prohibited_claim in readme


def test_published_confirmation_reaudit_is_fail_closed() -> None:
    index_path = EVIDENCE_ROOT / "reaudit_source_artifact_hashes_b18cf48.json"
    assert _sha256(index_path) == REAUDIT_INDEX_SHA256
    reaudited_index = _read_json(index_path.name)["sha256"]
    for published_name, source_relative_path in REAUDIT_SOURCE_PATHS.items():
        assert _sha256(EVIDENCE_ROOT / published_name) == reaudited_index[
            source_relative_path
        ]

    confirmation = _read_json("normal_confirmation_reaudit_b18cf48.json")
    assert confirmation["status"] == "PASS_NORMAL_PATH_CONFIRMATION"
    assert confirmation["execution_git_sha"] == (
        "ba5ac4abac490caccca006260670dfbc2c411fa9"
    )
    assert confirmation["finalization_git_sha"] == (
        "b18cf48e1d74a576132501e544596a686dd48a37"
    )
    assert confirmation["finalization_git_dirty"] is False
    assert confirmation["fixed_request_controls_equal"] is True
    assert confirmation["effective_solver_controls_equal"] is True
    assert confirmation["effective_solver_control_differences"] == []

    expected_frontier = {
        "stage1_stage2_candidate_limit": 22,
        "stage1_composition_search_radius": 4,
        "stage1_composition_target_time_limit_sec": 60.0,
        "stage1_bev_frontier_enabled": True,
        "stage1_bev_frontier_min_count": 15,
        "stage1_bev_frontier_max_count": 35,
        "stage1_bev_frontier_target_time_limit_sec": 120.0,
    }
    scenarios = confirmation["scenarios"]
    for scenario in scenarios.values():
        assert all(scenario["checks"].values())
        assert scenario["final_cost_source"].endswith(
            "executed_day_accounting.json:cost_breakdown.total_cost"
        )
        for key, value in expected_frontier.items():
            assert scenario["effective_solver_controls"][key] == value

    assert scenarios["SUNNY"]["executed_day_accounting_total_cost_jpy"] == (
        scenarios["SUNNY"]["day_ahead_selected_canonical_actual_cost_jpy"]
    )
    assert scenarios["RAIN"][
        "executed_day_accounting_total_cost_jpy"
    ] == pytest.approx(698_598.628643161, abs=1.0e-6)
    assert scenarios["RAIN"][
        "day_ahead_selected_canonical_actual_cost_jpy"
    ] == pytest.approx(698_296.465283954, abs=1.0e-6)

    contract = _read_json(
        "normal_confirmation_input_contract_reaudit_b18cf48.json"
    )
    assert contract["status"] == "PASS_FULL_INPUT_CONTRACT"
    assert contract["fixed_nonweather_inputs_equal"] is True
    for scenario in contract["scenarios"].values():
        assert len(scenario["mandatory_hash_keys"]) == 22
        assert scenario["mismatches_from_frozen_A"] == []
        assert scenario["missing_hashes_from_frozen_A_contract"] == []
