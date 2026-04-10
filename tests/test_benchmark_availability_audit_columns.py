from __future__ import annotations

from scripts.benchmark_solver_modes import _build_row


def test_benchmark_row_exports_availability_audit_columns() -> None:
    row = _build_row(
        mode_label="mode_alns_only",
        result_payload={
            "solver_status": "SOLVED_FEASIBLE",
            "objective_mode": "total_cost",
            "scenario_hash": "s",
            "scope_hash": "p",
            "summary": {
                "trip_count_served": 1,
                "trip_count_unserved": 0,
                "vehicle_count_used": 1,
                "available_vehicle_count_total": 2,
                "unused_available_vehicle_ids": ["veh-2"],
                "startup_infeasible_assignment_count": 1,
                "startup_infeasible_trip_ids": ["t2"],
                "startup_infeasible_vehicle_ids": ["veh-3"],
                "service_coverage_mode": "strict",
            },
            "canonical_solver_result": {
                "solver_status": "SOLVED_FEASIBLE",
                "served_trip_ids": ["t1"],
                "unserved_trip_ids": [],
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
                "trip_count": 1,
                "vehicle_count": 2,
                "available_vehicle_count_total": 2,
            },
        },
        wall_clock_seconds=1.0,
        prepared_input_id="prepared-x",
    )

    assert row["available_vehicle_count_total"] == 2
    assert row["unused_available_vehicle_ids"] == ["veh-2"]
    assert row["startup_infeasible_assignment_count"] == 1
    assert row["startup_infeasible_trip_ids"] == ["t2"]
    assert row["startup_infeasible_vehicle_ids"] == ["veh-3"]
    assert row["strict_coverage_enforced"] is True
