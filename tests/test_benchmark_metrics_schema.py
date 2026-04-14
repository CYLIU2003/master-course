from __future__ import annotations

from pathlib import Path

from scripts.benchmark_fixed_prepared_scope import _build_row
from scripts.benchmark_solver_modes import _build_row as _build_solver_modes_row


def test_benchmark_row_includes_required_profiling_columns() -> None:
    payload = {
        "solver_status": "SOLVED_FEASIBLE",
        "status": "SOLVED_FEASIBLE",
        "objective_value": 100.0,
        "served_trip_ids": ("t1",),
        "unserved_trip_ids": (),
        "vehicle_paths": {"veh-1": ("t1",)},
        "duties": (),
        "metadata": {"source": "unit-test", "status": "SOLVED_FEASIBLE"},
        "warnings": (),
        "infeasibility_reasons": (),
        "strict_coverage_precheck": {
            "checked": True,
            "reason": "not_proven_infeasible",
            "relaxed_vehicle_lower_bound": 1,
            "available_vehicle_count": 1,
            "interval_only_lower_bound": 1,
            "diagnostic_message": "strict coverage lower bound is 1 vehicle, current fleet is 1.",
            "blocked_transition_reason_counts": {"deadhead_missing": 2},
        },
        "prepared_scope_audit": {
            "warning_codes": ["trip_distance_zero_or_missing"],
            "warnings": ["Prepared scope audit: 1/1 trips have zero or missing distance_km."],
            "trip_distance_audit": {"zero_or_missing_count": 1},
            "route_distance_audit": {"zero_or_missing_count": 0},
        },
        "incumbent_history": [
            {"iteration": 0, "objective_value": 150.0, "feasible": False, "wall_clock_sec": 10.0},
            {"iteration": 1, "objective_value": 120.0, "feasible": True, "wall_clock_sec": 305.0},
            {"iteration": 2, "objective_value": 100.0, "feasible": True, "wall_clock_sec": 800.0},
        ],
        "effective_limits": {},
        "solver_metadata": {
            "true_solver_family": "ga",
            "independent_implementation": True,
            "delegates_to": "none",
            "solver_display_name": "GA prototype",
            "solver_maturity": "prototype",
            "candidate_generation_mode": "genetic_population_search",
            "evaluation_mode": "total_cost",
            "fallback_applied": False,
            "fallback_reason": "none",
            "supports_exact_milp": False,
            "has_feasible_incumbent": True,
            "incumbent_count": 1,
            "warm_start_applied": True,
            "warm_start_source": "baseline_plan",
            "search_profile": {
                "total_wall_clock_sec": 5.0,
                "first_feasible_sec": 0.1,
                "incumbent_updates": 1,
                "evaluator_calls": 10,
                "avg_evaluator_sec": 0.01,
                "repair_calls": 8,
                "avg_repair_sec": 0.02,
                "exact_repair_calls": 1,
                "avg_exact_repair_sec": 0.5,
                "feasible_candidate_ratio": 0.7,
                "rejected_candidate_ratio": 0.3,
                "fallback_count": 0,
            },
        },
    }

    row = _build_row(
        mode_label="ga",
        result_payload=payload,
        result_json_path=Path("ga.json"),
        wall_clock_seconds=5.0,
        trip_meta_by_id={},
        vehicle_type_by_id={},
    )

    required_columns = {
        "solver_name",
        "delegates_to",
        "candidate_generation_mode",
        "evaluation_mode",
        "fallback_applied",
        "fallback_reason",
        "total_wall_clock_sec",
        "first_feasible_sec",
        "incumbent_updates",
        "evaluator_calls",
        "avg_evaluator_sec",
        "repair_calls",
        "avg_repair_sec",
        "exact_repair_calls",
        "avg_exact_repair_sec",
        "feasible_candidate_ratio",
        "rejected_candidate_ratio",
        "fallback_count",
        "solver_display_name",
        "solver_maturity",
        "comparison_tier",
        "objective_at_60s",
        "objective_at_300s",
        "objective_at_600s",
        "objective_at_1500s",
        "best_bound",
        "final_gap",
        "nodes_explored",
        "iis_generated",
        "presolve_reduction_summary",
        "strict_coverage_checked",
        "strict_coverage_relaxed_vehicle_lower_bound",
        "strict_coverage_message",
        "prepared_scope_warning_count",
        "prepared_scope_warning_codes",
    }

    assert required_columns.issubset(row.keys())
    assert row["total_wall_clock_sec"] == 5.0
    assert row["first_feasible_sec"] == 0.1
    assert row["evaluator_calls"] == 10
    assert row["repair_calls"] == 8
    assert row["counts_for_comparison"] is False
    assert row["solver_display_name"] == "GA prototype"
    assert row["solver_maturity"] == "prototype"
    assert row["comparison_tier"] == "prototype"
    assert row["objective_at_60s"] == 150.0
    assert row["objective_at_300s"] == 150.0
    assert row["objective_at_600s"] == 120.0
    assert row["objective_at_1500s"] == 100.0
    assert row["strict_coverage_checked"] is True
    assert row["strict_coverage_relaxed_vehicle_lower_bound"] == 1
    assert row["prepared_scope_warning_count"] == 1
    assert row["prepared_scope_warning_codes"] == ["trip_distance_zero_or_missing"]


def test_benchmark_row_includes_fragment_cycle_metrics() -> None:
    payload = {
        "solver_status": "SOLVED_FEASIBLE",
        "status": "SOLVED_FEASIBLE",
        "objective_value": 100.0,
        "served_trip_ids": ("t1", "t2"),
        "unserved_trip_ids": (),
        "vehicle_paths": {"veh-1": ("t1", "t2")},
        "summary": {
            "same_day_depot_cycles_enabled": True,
            "max_depot_cycles_per_vehicle_per_day": 2,
            "vehicle_fragment_counts": {"veh-1": 2},
            "vehicles_with_multiple_fragments": ["veh-1"],
            "max_fragments_observed": 2,
            "prepared_scope_audit": {
                "warning_codes": ["trip_distance_zero_or_missing"],
                "warnings": ["Prepared scope audit: 2/2 trips have zero or missing distance_km."],
                "trip_distance_audit": {"zero_or_missing_count": 2},
                "route_distance_audit": {"zero_or_missing_count": 1},
            },
        },
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
            "comparison_note": "Core exact solver.",
            "fallback_applied": False,
            "fallback_reason": "none",
            "supports_exact_milp": True,
            "has_feasible_incumbent": True,
            "incumbent_count": 1,
            "warm_start_applied": True,
            "warm_start_source": "baseline_plan",
            "uses_exact_repair": False,
            "same_day_depot_cycles_enabled": True,
            "max_depot_cycles_per_vehicle_per_day": 2,
            "vehicle_fragment_counts": {"veh-1": 2},
            "vehicles_with_multiple_fragments": ["veh-1"],
            "max_fragments_observed": 2,
            "strict_coverage_precheck": {
                "checked": True,
                "infeasible": False,
                "relaxed_vehicle_lower_bound": 1,
                "available_vehicle_count": 1,
                "interval_only_lower_bound": 1,
                "diagnostic_message": "strict coverage lower bound is 1 vehicle, current fleet is 1.",
            },
            "search_profile": {
                "total_wall_clock_sec": 5.0,
                "first_feasible_sec": 0.2,
                "incumbent_updates": 1,
                "evaluator_calls": 10,
                "avg_evaluator_sec": 0.01,
                "repair_calls": 0,
                "avg_repair_sec": 0.0,
                "exact_repair_calls": 0,
                "avg_exact_repair_sec": 0.0,
                "feasible_candidate_ratio": 1.0,
                "rejected_candidate_ratio": 0.0,
                "fallback_count": 0,
            },
        },
    }

    row = _build_solver_modes_row(
        mode_label="mode_milp_only",
        result_payload=payload,
        result_json_path=Path("milp.json"),
        wall_clock_seconds=5.0,
    )

    assert row["same_day_depot_cycles_enabled"] is True
    assert row["max_depot_cycles_per_vehicle_per_day"] == 2
    assert row["vehicle_fragment_counts"] == {"veh-1": 2}
    assert row["vehicles_with_multiple_fragments"] == ["veh-1"]
    assert row["max_fragments_observed"] == 2
    assert row["strict_coverage_checked"] is True
    assert row["prepared_scope_warning_count"] == 1
    assert row["prepared_scope_zero_or_missing_trip_distance_count"] == 2
