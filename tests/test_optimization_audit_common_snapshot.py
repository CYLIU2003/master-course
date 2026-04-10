from __future__ import annotations

from pathlib import Path

from scripts.benchmark_solver_modes import _build_row


def _payload() -> dict:
    return {
        "solver_status": "SOLVED_FEASIBLE",
        "status": "SOLVED_FEASIBLE",
        "objective_mode": "total_cost",
        "objective_value": 100.0,
        "scenario_hash": "scenario-hash-1",
        "scope_hash": "scope-hash-1",
        "summary": {
            "trip_count_served": 2,
            "trip_count_unserved": 0,
            "vehicle_count_used": 1,
            "service_coverage_mode": "strict",
            "fixed_route_band_mode": False,
            "daily_fragment_limit": 3,
            "scenario_hash": "scenario-hash-1",
            "scope_hash": "scope-hash-1",
        },
        "canonical_solver_result": {
            "solver_status": "SOLVED_FEASIBLE",
            "objective_value": 100.0,
            "served_trip_ids": ["t1", "t2"],
            "unserved_trip_ids": [],
            "vehicle_paths": {"veh-1": ["t1", "t2"]},
            "solver_metadata": {
                "true_solver_family": "milp",
                "independent_implementation": True,
                "delegates_to": "none",
                "solver_display_name": "MILP",
                "solver_maturity": "core",
                "candidate_generation_mode": "exact_branch_and_cut",
                "evaluation_mode": "total_cost",
                "eligible_for_main_benchmark": True,
                "eligible_for_appendix_benchmark": False,
                "fallback_applied": False,
                "has_feasible_incumbent": True,
                "incumbent_count": 1,
                "search_profile": {
                    "total_wall_clock_sec": 1.0,
                    "first_feasible_sec": 0.1,
                    "incumbent_updates": 1,
                    "evaluator_calls": 0,
                    "avg_evaluator_sec": 0.0,
                    "repair_calls": 0,
                    "avg_repair_sec": 0.0,
                    "exact_repair_calls": 0,
                    "avg_exact_repair_sec": 0.0,
                    "feasible_candidate_ratio": 1.0,
                    "rejected_candidate_ratio": 0.0,
                    "fallback_count": 0,
                },
            },
        },
    }


def test_rows_from_same_snapshot_keep_common_prepared_input_and_scope_hash() -> None:
    rows = [
        _build_row(
            mode_label=mode,
            result_payload=_payload(),
            wall_clock_seconds=1.0,
            prepared_input_id="prepared-1",
            result_json_path=Path(f"{mode}.json"),
        )
        for mode in ("mode_milp_only", "mode_alns_only", "mode_ga_only", "mode_abc_only")
    ]

    assert {row["prepared_input_id"] for row in rows} == {"prepared-1"}
    assert {row["scope_hash"] for row in rows} == {"scope-hash-1"}
    assert {row["scenario_hash"] for row in rows} == {"scenario-hash-1"}
    assert {row["service_coverage_mode"] for row in rows} == {"strict"}
