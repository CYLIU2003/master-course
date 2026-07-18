from __future__ import annotations

import json
from pathlib import Path

from scripts.verify_research_phase3_baseline import verify_run


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_valid_run(run_dir: Path) -> None:
    validation = {
        "unassigned_trip_count": 0,
        "duplicate_trip_count": 0,
        "vehicle_time_overlap_count": 0,
        "infeasible_transition_count": 0,
        "ev_soc_lower_violation_count": 0,
        "ev_soc_upper_violation_count": 0,
        "ev_soc_violation_count": 0,
        "bess_soc_lower_violation_count": 0,
        "bess_soc_upper_violation_count": 0,
        "bess_soc_violation_count": 0,
        "contract_power_violation_count": 0,
        "charger_concurrency_violation_count": 0,
        "all_required_validation_checks_passed": True,
    }
    _write_json(
        run_dir / "summary.json",
        {
            "git_sha": "abc123",
            "git_dirty": False,
            "prepared_input_id": "prepared-fixed",
            "prepared_input_sha256": "input-hash",
            "experiment_hash": "experiment-hash",
            "time_step_min": 15,
            "pv_enabled": False,
            "bess_enabled": False,
            "weather_operation_policy_enabled": False,
            "trip_count_total": 264,
            "trip_count_served": 264,
            "trip_count_unserved": 0,
            "feasible": True,
            "stage1_solver_status": "time_limit",
            "stage1_has_feasible_incumbent": True,
            "stage2_solver_status": "optimal",
            "stage2_has_feasible_incumbent": True,
            "validation_metrics": validation,
            "arc_pruning_summary": {
                "successor_pruning_enabled": False,
                "pruned_arc_count": 0,
            },
            "accounting_total_cost_jpy": 100.0,
            "accounting_recalculation": {
                "passed": True,
                "max_abs_residual_jpy": 0.0,
                "tolerance_jpy": 1.0e-6,
            },
            "research_run_accepted": True,
            "research_feasibility_eligible": True,
        },
    )
    _write_json(
        run_dir / "solver_result.json",
        {
            "solver_metadata": {
                "supports_exact_milp": True,
                "fallback_applied": False,
                "postsolve_assignment_rebuilt": False,
                "postsolve_charging_recomputed": False,
                "postsolve_soc_repair_applied": False,
                "postsolve_opportunistic_topup_applied": False,
                "postsolve_modified_solution": False,
            }
        },
    )
    _write_json(
        run_dir / "controlled_model_validation_input.json",
        {"slot_count": 96, "prepared_input_sha256": "input-hash"},
    )
    _write_json(
        run_dir / "research_run_manifest.json",
        {"git_sha": "abc123", "git_dirty": False},
    )


def test_verify_run_accepts_the_formal_baseline_contract(tmp_path: Path) -> None:
    _write_valid_run(tmp_path)

    report = verify_run(tmp_path, expected_git_sha="abc123")

    assert report["passed"] is True
    assert report["failed_checks"] == []


def test_verify_run_rejects_an_unserved_trip(tmp_path: Path) -> None:
    _write_valid_run(tmp_path)
    summary_path = tmp_path / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["trip_count_served"] = 263
    summary["trip_count_unserved"] = 1
    _write_json(summary_path, summary)

    report = verify_run(tmp_path, expected_git_sha="abc123")

    assert report["passed"] is False
    assert "all_264_trips_served" in report["failed_checks"]
