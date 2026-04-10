from __future__ import annotations

from scripts.benchmark_solver_modes import _build_row


def test_strict_unserved_with_unused_available_sets_failure_flag() -> None:
    row = _build_row(
        mode_label="mode_alns_only",
        result_payload={
            "solver_status": "SOLVED_FEASIBLE",
            "objective_mode": "total_cost",
            "scenario_hash": "s",
            "scope_hash": "scope",
            "summary": {
                "trip_count_served": 1,
                "trip_count_unserved": 1,
                "vehicle_count_used": 1,
                "available_vehicle_count_total": 2,
                "unused_available_vehicle_ids": ["veh-unused"],
                "service_coverage_mode": "strict",
            },
            "canonical_solver_result": {
                "solver_status": "SOLVED_FEASIBLE",
                "served_trip_ids": ["t1"],
                "unserved_trip_ids": ["t2"],
                "solver_metadata": {
                    "true_solver_family": "alns",
                    "solver_display_name": "ALNS",
                    "solver_maturity": "core",
                    "has_feasible_incumbent": True,
                    "fallback_applied": False,
                    "search_profile": {},
                },
            },
            "canonical_problem_summary": {
                "trip_count": 2,
                "vehicle_count": 2,
                "available_vehicle_count_total": 2,
            },
        },
        wall_clock_seconds=1.0,
        prepared_input_id="prepared-x",
    )

    assert row["strict_unused_available_failure"] is True
