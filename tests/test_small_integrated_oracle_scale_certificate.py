from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from copy import deepcopy

import pytest

from scripts.build_small_integrated_oracle_scale_certificate import (
    build_scale_certificate,
    normalize_trip_counts,
)


def test_scale_certificate_cli_help_runs_from_scripts_directory() -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / (
        "build_small_integrated_oracle_scale_certificate.py"
    )

    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=script.parent,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--gurobi-threads" in completed.stdout


def _exact_case(phase: str, *, cost: float) -> dict:
    common = {
        "analysis_label": "primary",
        "phase": phase,
        "timestep_min": 15,
        "feasible": True,
        "trip_count_unserved": 0,
        "elapsed_seconds": 1.0,
        "accounted_total_cost_jpy": cost,
    }
    if phase == "phase4_integrated":
        common.update(
            {
                "solver_status": "optimal",
                "final_gap_ratio": 0.0,
                "integrated_actual_cost_objective_requested": True,
                "integrated_actual_cost_contract_applied": True,
                "objective_is_actual_cost": True,
                "objective_matches_accounting": True,
                "ev_energy_inventory_balanced": True,
            }
        )
    return common


def _result(trip_count: int, *, gap_ratio: float = 0.0) -> dict:
    integrated_cost = 1000.0 + trip_count
    two_stage_cost = integrated_cost * (1.0 + gap_ratio)
    return {
        "trip_count": trip_count,
        "return_code": 0,
        "command": ["python", "audit.py", "--trip-count", str(trip_count)],
        "audit_path": f"trips_{trip_count}/audit.json",
        "audit_sha256": "a" * 64,
        "log_path": f"trips_{trip_count}/run.log",
        "audit": {
            "trip_count": trip_count,
            "primary_comparison": {
                "integrated_exact_oracle_eligible": True,
                "two_stage_comparison_available": True,
                "comparison_lower_bound_consistent": True,
                "integrated_accounted_total_cost_jpy": integrated_cost,
                "two_stage_accounted_total_cost_jpy": two_stage_cost,
                "two_stage_minus_integrated_cost_jpy": (
                    two_stage_cost - integrated_cost
                ),
                "two_stage_approx_gap_identifiable": True,
                "two_stage_approx_gap_ratio": gap_ratio,
                "two_stage_approx_gap_status": "computed",
                "used_vehicle_count_delta": 0,
                "used_vehicle_type_mix_matches": True,
                "served_trip_type_mix_matches": True,
                "assignment_powertrain_hash_matches": True,
            },
            "cases": [
                _exact_case("phase3_two_stage", cost=two_stage_cost),
                _exact_case("phase4_integrated", cost=integrated_cost),
            ],
        },
    }


def test_scale_certificate_accepts_complete_exact_series() -> None:
    certificate = build_scale_certificate(
        [_result(8), _result(12, gap_ratio=0.01), _result(24, gap_ratio=0.02)],
        expected_trip_counts=(8, 12, 24),
        provenance={"git_sha_before": "a" * 40},
    )

    assert certificate["status"] == "VERIFIED_BOUNDED_SMALL_INSTANCES"
    assert certificate["all_sizes_verified"] is True
    assert certificate["verified_trip_counts"] == [8, 12, 24]
    assert certificate["maximum_two_stage_approx_gap_ratio"] == pytest.approx(0.02)
    assert certificate["mean_two_stage_approx_gap_ratio"] == pytest.approx(0.01)
    assert certificate["approx_gap_not_identifiable_trip_counts"] == []
    assert certificate["formal_full_network_optimality_substitute"] is False
    assert certificate["bounded_formulation_conclusion_eligible"] is True
    assert certificate["research_conclusion_eligible"] is False
    assert len(certificate["payload_sha256"]) == 64
    assert certificate["sizes"][0]["command"][-1] == "8"


def test_scale_certificate_blocks_missing_actual_cost_contract() -> None:
    invalid = _result(8)
    phase4 = invalid["audit"]["cases"][1]
    phase4["objective_is_actual_cost"] = False

    certificate = build_scale_certificate(
        [invalid],
        expected_trip_counts=(8,),
        provenance={"git_sha_before": "a" * 40},
    )

    assert certificate["status"] == "BLOCKED"
    assert certificate["all_sizes_verified"] is False
    assert "trip_8:phase4_objective_is_actual_cost_failed" in certificate["blockers"]


def test_scale_certificate_blocks_incomplete_size_series() -> None:
    certificate = build_scale_certificate(
        [_result(8), _result(24)],
        expected_trip_counts=(8, 12, 24),
        provenance={"git_sha_before": "a" * 40},
    )

    assert certificate["status"] == "BLOCKED"
    assert "trip_count_series_incomplete_or_unordered" in certificate["blockers"]


def test_scale_certificate_blocks_missing_child_return_code() -> None:
    invalid = _result(8)
    invalid.pop("return_code")

    certificate = build_scale_certificate(
        [invalid],
        expected_trip_counts=(8,),
        provenance={"git_sha_before": "a" * 40},
    )

    assert certificate["status"] == "BLOCKED"
    assert "trip_8:child_audit_nonzero_exit" in certificate["blockers"]


def test_scale_certificate_does_not_mutate_child_audit() -> None:
    result = _result(8)
    original = deepcopy(result)

    build_scale_certificate(
        [result],
        expected_trip_counts=(8,),
        provenance={"git_sha_before": "a" * 40},
    )

    assert result == original


def test_scale_certificate_excludes_zero_cost_reference_from_approx_gap() -> None:
    result = _result(8)
    comparison = result["audit"]["primary_comparison"]
    comparison.update(
        {
            "integrated_accounted_total_cost_jpy": 0.0,
            "two_stage_accounted_total_cost_jpy": 0.0,
            "two_stage_minus_integrated_cost_jpy": 0.0,
            "two_stage_approx_gap_identifiable": False,
            "two_stage_approx_gap_ratio": None,
            "two_stage_approx_gap_status": "not_identifiable_zero_reference_cost",
        }
    )

    certificate = build_scale_certificate(
        [result], expected_trip_counts=(8,), provenance={"git_sha_before": "a" * 40}
    )

    assert certificate["status"] == "VERIFIED_BOUNDED_SMALL_INSTANCES"
    assert certificate["approx_gap_identifiable_trip_counts"] == []
    assert certificate["approx_gap_not_identifiable_trip_counts"] == [8]
    assert certificate["maximum_two_stage_approx_gap_ratio"] is None


@pytest.mark.parametrize("counts", [(), (0,), (8, 8)])
def test_normalize_trip_counts_rejects_invalid_series(counts: tuple[int, ...]) -> None:
    with pytest.raises(ValueError):
        normalize_trip_counts(counts)
