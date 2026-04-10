from __future__ import annotations

from pathlib import Path

from scripts.benchmark_solver_modes import _build_row


def test_benchmark_row_includes_cost_min_strict_schema_fields() -> None:
    payload = {
        "solver_status": "SOLVED_FEASIBLE",
        "status": "SOLVED_FEASIBLE",
        "objective_mode": "total_cost",
        "objective_value": 123.0,
        "scenario_hash": "scenario-hash-1",
        "scope_hash": "scope-hash-1",
        "summary": {
            "trip_count_served": 2,
            "trip_count_unserved": 0,
            "vehicle_count_used": 1,
            "same_day_depot_cycles_enabled": True,
            "max_depot_cycles_per_vehicle_per_day": 3,
            "vehicle_fragment_counts": {"veh-1": 2},
            "vehicles_with_multiple_fragments": ["veh-1"],
            "max_fragments_observed": 2,
            "service_coverage_mode": "strict",
            "fixed_route_band_mode": False,
            "daily_fragment_limit": 3,
            "scenario_hash": "scenario-hash-1",
            "scope_hash": "scope-hash-1",
        },
        "canonical_solver_result": {
            "solver_status": "SOLVED_FEASIBLE",
            "objective_value": 123.0,
            "served_trip_ids": ["t1", "t2"],
            "unserved_trip_ids": [],
            "vehicle_paths": {"veh-1": ["t1", "t2"]},
            "solver_metadata": {
                "true_solver_family": "ga",
                "independent_implementation": True,
                "delegates_to": "none",
                "solver_display_name": "GA prototype",
                "solver_maturity": "prototype",
                "candidate_generation_mode": "genetic_population_search",
                "evaluation_mode": "total_cost",
                "fallback_applied": False,
                "has_feasible_incumbent": True,
                "incumbent_count": 4,
                "search_profile": {
                    "total_wall_clock_sec": 12.5,
                    "first_feasible_sec": 0.2,
                    "incumbent_updates": 4,
                    "evaluator_calls": 12,
                    "avg_evaluator_sec": 0.05,
                    "repair_calls": 6,
                    "avg_repair_sec": 0.07,
                    "exact_repair_calls": 1,
                    "avg_exact_repair_sec": 0.5,
                    "feasible_candidate_ratio": 0.7,
                    "rejected_candidate_ratio": 0.3,
                    "fallback_count": 0,
                },
            },
        },
    }

    row = _build_row(
        mode_label="mode_ga_only",
        result_payload=payload,
        wall_clock_seconds=12.5,
        prepared_input_id="prepared-1",
        result_json_path=Path("ga.json"),
    )

    required_fields = {
        "mode",
        "objective_mode",
        "service_coverage_mode",
        "status",
        "objective_value",
        "vehicle_count_used",
        "trip_count_served",
        "trip_count_unserved",
        "vehicles_with_multiple_fragments",
        "max_fragments_observed",
        "first_feasible_sec",
        "incumbent_count",
        "evaluator_calls",
        "avg_evaluator_sec",
        "repair_calls",
        "avg_repair_sec",
        "exact_repair_calls",
        "avg_exact_repair_sec",
        "fallback_applied",
        "scenario_hash",
        "scope_hash",
    }

    assert required_fields.issubset(row.keys())
    assert row["objective_mode"] == "total_cost"
    assert row["service_coverage_mode"] == "strict"
    assert row["scenario_hash"] == "scenario-hash-1"
    assert row["scope_hash"] == "scope-hash-1"
