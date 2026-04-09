from __future__ import annotations

from pathlib import Path

from scripts.benchmark_fixed_prepared_scope import _build_row


def _payload(
    *,
    solver_status: str,
    solver_metadata: dict,
    objective_value: float = 123.0,
) -> dict:
    return {
        "solver_status": solver_status,
        "status": solver_status,
        "objective_value": objective_value,
        "served_trip_ids": ("t1",),
        "unserved_trip_ids": (),
        "vehicle_paths": {"veh-1": ("t1",)},
        "duties": (),
        "metadata": {"source": "unit-test", "status": solver_status},
        "warnings": (),
        "infeasibility_reasons": (),
        "incumbent_history": [
            {
                "iteration": 0,
                "objective_value": objective_value,
                "feasible": True,
                "wall_clock_sec": 0.0,
            }
        ],
        "effective_limits": {},
        "solver_metadata": solver_metadata,
    }


def test_benchmark_row_exposes_solver_identity_and_profiling() -> None:
    cases = [
        (
            "milp",
            _payload(
                solver_status="truthful_baseline_guardrail",
                objective_value=321.0,
                solver_metadata={
                    "true_solver_family": "milp",
                    "independent_implementation": True,
                    "delegates_to": "none",
                    "solver_display_name": "MILP",
                    "solver_maturity": "core",
                    "candidate_generation_mode": "exact_branch_and_cut",
                    "evaluation_mode": "total_cost",
                    "fallback_applied": True,
                    "fallback_reason": "truthful_baseline_guardrail",
                    "supports_exact_milp": False,
                    "has_feasible_incumbent": False,
                    "incumbent_count": 0,
                    "warm_start_applied": True,
                    "warm_start_source": "baseline_plan",
                    "best_bound": 200.0,
                    "final_gap": 0.15,
                    "nodes_explored": 42,
                    "iis_generated": False,
                    "presolve_reduction_summary": {"col_deleted": 1},
                    "search_profile": {
                        "total_wall_clock_sec": 12.5,
                        "first_feasible_sec": None,
                        "incumbent_updates": 0,
                        "evaluator_calls": 0,
                        "avg_evaluator_sec": 0.0,
                        "repair_calls": 0,
                        "avg_repair_sec": 0.0,
                        "exact_repair_calls": 0,
                        "avg_exact_repair_sec": 0.0,
                        "feasible_candidate_ratio": 0.0,
                        "rejected_candidate_ratio": 1.0,
                        "fallback_count": 1,
                    },
                },
            ),
            {
                "result_category": "truthful_baseline_guardrail",
                "counts_for_comparison": False,
                "solver_display_name": "MILP",
                "comparison_tier": "excluded",
                "fallback_applied": True,
                "delegates_to": "none",
                "candidate_generation_mode": "exact_branch_and_cut",
                "best_bound": 200.0,
                "nodes_explored": 42,
                "evaluator_calls": 0,
                "repair_calls": 0,
                "fallback_reason": "truthful_baseline_guardrail",
            },
        ),
        (
            "alns",
            _payload(
                solver_status="SOLVED_FEASIBLE",
                objective_value=210.0,
                solver_metadata={
                    "true_solver_family": "alns",
                    "independent_implementation": True,
                    "delegates_to": "none",
                    "solver_display_name": "ALNS",
                    "solver_maturity": "core",
                    "candidate_generation_mode": "destroy_repair_local_search",
                    "evaluation_mode": "total_cost",
                    "fallback_applied": False,
                    "fallback_reason": "none",
                    "supports_exact_milp": False,
                    "has_feasible_incumbent": True,
                    "incumbent_count": 2,
                    "warm_start_applied": True,
                    "warm_start_source": "baseline_plan",
                    "search_profile": {
                        "total_wall_clock_sec": 7.5,
                        "first_feasible_sec": 0.2,
                        "incumbent_updates": 2,
                        "evaluator_calls": 20,
                        "avg_evaluator_sec": 0.1,
                        "repair_calls": 18,
                        "avg_repair_sec": 0.2,
                        "exact_repair_calls": 1,
                        "avg_exact_repair_sec": 1.0,
                        "feasible_candidate_ratio": 0.8,
                        "rejected_candidate_ratio": 0.2,
                        "fallback_count": 0,
                    },
                },
            ),
            {
                "result_category": "SOLVED_FEASIBLE",
                "counts_for_comparison": True,
                "solver_display_name": "ALNS",
                "comparison_tier": "core",
                "fallback_applied": False,
                "delegates_to": "none",
                "candidate_generation_mode": "destroy_repair_local_search",
                "best_bound": None,
                "nodes_explored": None,
                "evaluator_calls": 20,
                "repair_calls": 18,
                "fallback_reason": "none",
            },
        ),
        (
            "ga",
            _payload(
                solver_status="SOLVED_FEASIBLE",
                solver_metadata={
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
                    "incumbent_count": 3,
                    "warm_start_applied": True,
                    "warm_start_source": "baseline_plan",
                    "search_profile": {
                        "total_wall_clock_sec": 8.25,
                        "first_feasible_sec": 0.02,
                        "incumbent_updates": 2,
                        "evaluator_calls": 14,
                        "avg_evaluator_sec": 0.1,
                        "repair_calls": 11,
                        "avg_repair_sec": 0.2,
                        "exact_repair_calls": 1,
                        "avg_exact_repair_sec": 1.5,
                        "feasible_candidate_ratio": 0.75,
                        "rejected_candidate_ratio": 0.25,
                        "fallback_count": 0,
                    },
                },
            ),
            {
                "result_category": "SOLVED_FEASIBLE",
                "counts_for_comparison": False,
                "solver_display_name": "GA prototype",
                "comparison_tier": "prototype",
                "fallback_applied": False,
                "delegates_to": "none",
                "candidate_generation_mode": "genetic_population_search",
                "best_bound": None,
                "nodes_explored": None,
                "evaluator_calls": 14,
                "repair_calls": 11,
                "fallback_reason": "none",
            },
        ),
        (
            "abc",
            _payload(
                solver_status="SOLVED_INFEASIBLE",
                solver_metadata={
                    "true_solver_family": "abc",
                    "independent_implementation": True,
                    "delegates_to": "none",
                    "solver_display_name": "ABC prototype",
                    "solver_maturity": "prototype",
                    "candidate_generation_mode": "bee_colony_search",
                    "evaluation_mode": "total_cost",
                    "fallback_applied": False,
                    "fallback_reason": "none",
                    "supports_exact_milp": False,
                    "has_feasible_incumbent": True,
                    "incumbent_count": 4,
                    "warm_start_applied": True,
                    "warm_start_source": "baseline_plan",
                    "search_profile": {
                        "total_wall_clock_sec": 9.75,
                        "first_feasible_sec": 0.03,
                        "incumbent_updates": 3,
                        "evaluator_calls": 18,
                        "avg_evaluator_sec": 0.08,
                        "repair_calls": 15,
                        "avg_repair_sec": 0.18,
                        "exact_repair_calls": 1,
                        "avg_exact_repair_sec": 1.2,
                        "feasible_candidate_ratio": 0.67,
                        "rejected_candidate_ratio": 0.33,
                        "fallback_count": 1,
                    },
                },
            ),
            {
                "result_category": "SOLVED_INFEASIBLE",
                "counts_for_comparison": False,
                "solver_display_name": "ABC prototype",
                "comparison_tier": "prototype",
                "fallback_applied": False,
                "delegates_to": "none",
                "candidate_generation_mode": "bee_colony_search",
                "best_bound": None,
                "nodes_explored": None,
                "evaluator_calls": 18,
                "repair_calls": 15,
                "fallback_reason": "none",
            },
        ),
    ]

    for mode, payload, expected in cases:
        row = _build_row(
            mode_label=mode,
            result_payload=payload,
            result_json_path=Path(f"{mode}.json"),
            wall_clock_seconds=1.0,
            trip_meta_by_id={},
            vehicle_type_by_id={},
        )

        assert row["solver_name"] == mode
        assert row["mode"] == mode
        assert row["result_category"] == expected["result_category"]
        assert row["counts_for_comparison"] is expected["counts_for_comparison"]
        assert row["solver_display_name"] == expected["solver_display_name"]
        assert row["comparison_tier"] == expected["comparison_tier"]
        assert row["delegates_to"] == expected["delegates_to"]
        assert row["candidate_generation_mode"] == expected["candidate_generation_mode"]
        assert row["fallback_applied"] is expected["fallback_applied"]
        assert row["fallback_reason"] == expected["fallback_reason"]
        assert row["evaluator_calls"] == expected["evaluator_calls"]
        assert row["repair_calls"] == expected["repair_calls"]
        assert row["best_bound"] == expected["best_bound"]
        assert row["nodes_explored"] == expected["nodes_explored"]
