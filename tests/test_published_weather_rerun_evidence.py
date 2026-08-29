from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = REPO_ROOT / "docs" / "evidence" / "weather_dispatch_rerun_bb0c005"
EXECUTION_SHA = "bb0c0050883a91dd86a9e8813ae88d4b6d8c361d"


def _read_json(relative_path: str) -> dict[str, Any]:
    payload = json.loads((EVIDENCE_ROOT / relative_path).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_published_weather_rerun_passes_bounded_gates() -> None:
    summary = _read_json("result_summary.json")
    confirmation = _read_json("confirmation_manifest.json")
    input_contract = _read_json("normal_confirmation_input_contract.json")

    assert summary["execution_git_sha"] == EXECUTION_SHA
    assert summary["status"] == "PASS_NORMAL_PATH_CONFIRMATION"
    assert summary["teacher_release_status"] == "BLOCKED"
    assert confirmation["execution_git_sha"] == EXECUTION_SHA
    assert confirmation["finalization_git_sha"] == EXECUTION_SHA
    assert confirmation["execution_git_dirty"] is False
    assert confirmation["finalization_git_dirty"] is False
    assert confirmation["effective_solver_controls_equal"] is True
    assert input_contract["status"] == "PASS_FULL_INPUT_CONTRACT"
    assert input_contract["fixed_nonweather_inputs_equal"] is True

    for code in ("SUNNY", "RAIN"):
        scenario = summary["scenarios"][code]
        gate = _read_json(f"{code}/confirmation_gate.json")
        physical = _read_json(f"{code}/physical_schedule_validation.json")
        rolling = _read_json(f"{code}/rolling_chain_summary.json")
        accounting = _read_json(f"{code}/executed_day_accounting.json")
        selected = _read_json(f"{code}/selected_candidate.json")
        solver_metrics = _read_json(f"{code}/solver_metrics.json")
        assert scenario["served_trips"] == 264
        assert scenario["unserved_trips"] == 0
        assert scenario["candidate_count_evaluated"] == 22
        assert scenario["feasible_candidate_count"] == 22
        assert all(gate["checks"].values())
        assert physical["accepted"] is True
        assert rolling["chain_accepted"] is True
        assert rolling["step_count"] == rolling["expected_step_count"] == 24
        assert accounting["eligible"] is True
        selected_row = selected["selected_candidate"]
        assert selected_row["used_bev"] == scenario["used_bev"]
        assert selected_row["used_ice"] == scenario["used_ice"]
        assert selected_row["bev_trips"] == scenario["bev_trips"]
        assert selected_row["ice_trips"] == scenario["ice_trips"]
        assert solver_metrics["solve_time_seconds"] == scenario["solve_time_seconds"]
        solver = solver_metrics["solver_metadata"]
        assert solver["stage1_certified_mip_gap_ratio"] == scenario[
            "stage1_certified_gap_ratio"
        ]
        assert solver["stage1_model_variable_count"] == scenario[
            "stage1_model_variables"
        ]
        assert accounting["cost_breakdown"]["total_cost"] == pytest.approx(
            scenario["executed_day_cost_jpy"], abs=1.0e-9
        )


def test_published_weather_rerun_hash_inventory_matches_bytes() -> None:
    index = _read_json("artifact_hashes.json")["sha256"]
    published = {
        path.relative_to(EVIDENCE_ROOT).as_posix(): _sha256(path)
        for path in EVIDENCE_ROOT.rglob("*")
        if path.is_file() and path.name != "artifact_hashes.json"
    }
    assert index == published


def test_published_weather_rerun_claims_stay_bounded() -> None:
    summary = _read_json("result_summary.json")
    assert summary["scenarios"]["SUNNY"]["stage1_certified_gap_ratio"] > 0.01
    assert summary["scenarios"]["RAIN"]["stage1_certified_gap_ratio"] > 0.01
    assert "Integrated global optimality" in summary["claim_boundary"]["not_supported"]
    assert "Thesis release readiness" in summary["claim_boundary"]["not_supported"]
