from __future__ import annotations

from pathlib import Path

from scripts.benchmark_solver_modes import _build_row


def test_benchmark_row_exports_search_profile_fields() -> None:
    payload = {
        "solver_status": "SOLVED_FEASIBLE",
        "status": "SOLVED_FEASIBLE",
        "objective_value": 123.0,
        "solve_time_seconds": 12.5,
        "summary": {
            "trip_count_served": 1,
            "trip_count_unserved": 0,
            "vehicle_count_used": 1,
        },
        "cost_breakdown": {"objective_value": 123.0},
        "canonical_solver_result": {
            "solver_status": "SOLVED_FEASIBLE",
            "objective_value": 123.0,
            "served_trip_ids": ["t1"],
            "unserved_trip_ids": [],
            "vehicle_paths": {"veh-1": ["t1"]},
            "incumbent_history": [
                {"iteration": 0, "objective_value": 150.0, "feasible": False, "wall_clock_sec": 10.0},
                {"iteration": 1, "objective_value": 120.0, "feasible": True, "wall_clock_sec": 300.0},
                {"iteration": 2, "objective_value": 123.0, "feasible": True, "wall_clock_sec": 600.0},
            ],
            "solver_metadata": {
                "true_solver_family": "alns",
                "independent_implementation": True,
                "delegates_to": "none",
                "solver_display_name": "ALNS",
                "solver_maturity": "core",
                "candidate_generation_mode": "destroy_repair_local_search",
                "evaluation_mode": "total_cost",
                "eligible_for_main_benchmark": True,
                "eligible_for_appendix_benchmark": False,
                "comparison_note": "Core metaheuristic; main benchmark candidate.",
                "fallback_applied": False,
                "fallback_reason": "none",
                "supports_exact_milp": False,
                "has_feasible_incumbent": True,
                "incumbent_count": 2,
                "warm_start_applied": True,
                "warm_start_source": "baseline_plan",
                "uses_exact_repair": True,
                "search_profile": {
                    "total_wall_clock_sec": 12.5,
                    "first_feasible_sec": 0.2,
                    "incumbent_updates": 2,
                    "evaluator_calls": 10,
                    "avg_evaluator_sec": 0.1,
                    "repair_calls": 8,
                    "avg_repair_sec": 0.2,
                    "exact_repair_calls": 1,
                    "avg_exact_repair_sec": 0.5,
                    "feasible_candidate_ratio": 0.8,
                    "rejected_candidate_ratio": 0.2,
                    "fallback_count": 0,
                },
            },
        },
    }

    row = _build_row(
        mode_label="alns",
        result_payload=payload,
        wall_clock_seconds=12.5,
        result_json_path=Path("alns.json"),
    )

    assert row["benchmark_tier"] == "main"
    assert row["counts_for_comparison"] is True
    assert row["solver_display_name"] == "ALNS"
    assert row["solver_maturity"] == "core"
    assert row["true_solver_family"] == "alns"
    assert row["eligible_for_main_benchmark"] is True
    assert row["eligible_for_appendix_benchmark"] is False
    assert row["comparison_note"].startswith("Core metaheuristic")
    assert row["first_feasible_sec"] == 0.2
    assert row["incumbent_updates"] == 2
    assert row["evaluator_calls"] == 10
    assert row["avg_evaluator_sec"] == 0.1
    assert row["repair_calls"] == 8
    assert row["avg_repair_sec"] == 0.2
    assert row["exact_repair_calls"] == 1
    assert row["avg_exact_repair_sec"] == 0.5
    assert row["feasible_candidate_ratio"] == 0.8
    assert row["fallback_count"] == 0
    assert row["uses_exact_repair"] is True
