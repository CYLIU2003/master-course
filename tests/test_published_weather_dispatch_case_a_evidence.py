from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPO_ROOT / "docs" / "evidence" / "weather_dispatch_case_a_3ec8714"
FULL_INDEX_SHA256 = (
    "68244b2c57f8f2055c1751f91e2d946a08b1a876830ccc6fd321eb3894c96981"
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
