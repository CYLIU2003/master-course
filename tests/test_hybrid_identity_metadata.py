from __future__ import annotations

from types import SimpleNamespace

from src.optimization.alns.engine import ALNSOptimizer
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    AssignmentPlan,
    OptimizationConfig,
    OptimizationEngineResult,
    OptimizationMode,
)
from src.optimization.hybrid.hybrid_engine import HybridOptimizer
from src.optimization.milp.engine import MILPOptimizer


def _dummy_result(*, mode: OptimizationMode, solver_status: str, solver_metadata: dict[str, object]) -> OptimizationEngineResult:
    return OptimizationEngineResult(
        mode=mode,
        solver_status=solver_status,
        objective_value=1.0,
        plan=AssignmentPlan(),
        feasible=True,
        warnings=(),
        infeasibility_reasons=(),
        cost_breakdown={"objective_value": 1.0},
        solver_metadata=solver_metadata,
        operator_stats={},
        incumbent_history=(),
    )


def test_hybrid_optimizer_reports_milp_seeded_alns_identity(monkeypatch) -> None:
    monkeypatch.setattr(
        MILPOptimizer,
        "solve",
        lambda self, problem, config: _dummy_result(
            mode=OptimizationMode.MILP,
            solver_status="SOLVED_FEASIBLE",
            solver_metadata={
                "solver_status": "SOLVED_FEASIBLE",
                "search_profile": {
                    "total_wall_clock_sec": 1.0,
                    "first_feasible_sec": 0.1,
                    "incumbent_updates": 1,
                    "evaluator_calls": 1,
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
        ),
    )
    monkeypatch.setattr(
        ALNSOptimizer,
        "solve",
        lambda self, problem, config, initial_state=None: _dummy_result(
            mode=OptimizationMode.ALNS,
            solver_status="SOLVED_FEASIBLE",
            solver_metadata={
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
                "incumbent_count": 1,
                "warm_start_applied": True,
                "warm_start_source": "baseline_plan",
                "uses_exact_repair": False,
                "search_profile": {
                    "total_wall_clock_sec": 2.0,
                    "first_feasible_sec": 0.2,
                    "incumbent_updates": 1,
                    "evaluator_calls": 2,
                    "avg_evaluator_sec": 0.0,
                    "repair_calls": 1,
                    "avg_repair_sec": 0.0,
                    "exact_repair_calls": 0,
                    "avg_exact_repair_sec": 0.0,
                    "feasible_candidate_ratio": 1.0,
                    "rejected_candidate_ratio": 0.0,
                    "fallback_count": 0,
                },
            },
        ),
    )

    optimizer = HybridOptimizer()
    monkeypatch.setattr(
        FeasibilityChecker,
        "evaluate",
        lambda self, problem, plan: SimpleNamespace(feasible=True, errors=(), warnings=()),
    )
    monkeypatch.setattr(
        CostEvaluator,
        "evaluate",
        lambda self, problem, plan: SimpleNamespace(to_dict=lambda: {"objective_value": 1.0}),
    )
    monkeypatch.setattr(
        CostEvaluator,
        "build_plan_ledgers",
        lambda self, problem, plan, breakdown: ((), ()),
    )

    result = optimizer.solve(
        SimpleNamespace(),
        OptimizationConfig(
            mode=OptimizationMode.HYBRID,
            time_limit_sec=2,
            random_seed=3,
            alns_iterations=4,
            no_improvement_limit=4,
            warm_start=True,
        ),
    )

    metadata = dict(result.solver_metadata)

    assert result.mode == OptimizationMode.HYBRID
    assert metadata["true_solver_family"] == "milp_seeded_alns"
    assert metadata["solver_display_name"] == "MILPSeededALNS"
    assert metadata["solver_maturity"] == "prototype"
    assert metadata["delegates_to"] == "alns"
    assert metadata["candidate_generation_mode"] == "milp_seeded_alns"
    assert metadata["eligible_for_main_benchmark"] is False
    assert metadata["eligible_for_appendix_benchmark"] is True
    assert "MILP-seeded ALNS" in metadata["comparison_note"]
    assert metadata["milp_seed_status"] == "SOLVED_FEASIBLE"
    assert metadata["warm_start_source"] == "milp_seed"
    assert metadata["search_profile"]["evaluator_calls"] == 2
