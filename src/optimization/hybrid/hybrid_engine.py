from __future__ import annotations

from dataclasses import replace

from src.optimization.alns.engine import ALNSOptimizer
from src.optimization.common.benchmarking import solver_benchmark_eligibility
from src.optimization.hybrid.column_generation import ColumnPool, PricingProblem
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationEngineResult,
    OptimizationMode,
)
from src.optimization.milp.engine import MILPOptimizer


class HybridOptimizer:
    def __init__(self) -> None:
        self._milp = MILPOptimizer()
        self._alns = ALNSOptimizer()
        self._column_pool = ColumnPool()
        self._pricing_problem = PricingProblem()

    def solve(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> OptimizationEngineResult:
        milp_result = self._milp.solve(problem, config)
        initial_state = None
        if milp_result.plan is not None:
            from src.optimization.common.evaluator import CostEvaluator
            from src.optimization.common.feasibility import FeasibilityChecker
            from src.optimization.common.problem import SolutionState

            report = FeasibilityChecker().evaluate(problem, milp_result.plan)
            evaluator = CostEvaluator()
            breakdown = evaluator.evaluate(problem, milp_result.plan)
            vehicle_ledger, daily_ledger = evaluator.build_plan_ledgers(problem, milp_result.plan, breakdown)
            seeded_plan = replace(
                milp_result.plan,
                vehicle_cost_ledger=vehicle_ledger,
                daily_cost_ledger=daily_ledger,
            )
            costs = breakdown.to_dict()
            initial_state = SolutionState(
                problem=problem,
                plan=seeded_plan,
                cost_breakdown=costs,
                feasible=report.feasible,
                infeasibility_reasons=report.errors,
                metadata={"seeded_from": "milp"},
            )
        alns_result = self._alns.solve(problem, config, initial_state=initial_state)
        solver_metadata = dict(alns_result.solver_metadata or {})
        solver_metadata.update(
            {
                "milp_seed_status": milp_result.solver_status,
                "partial_milp_calls": 1,
                "termination_reason": solver_metadata.get("termination_reason", "time_limit_or_gap"),
                "effective_limits": solver_metadata.get("effective_limits", {}),
                "true_solver_family": "milp_seeded_alns",
                "independent_implementation": True,
                "delegates_to": "alns",
                "solver_display_name": "MILPSeededALNS",
                "solver_maturity": "prototype",
                "candidate_generation_mode": "milp_seeded_alns",
                "warm_start_applied": True,
                "warm_start_source": "milp_seed",
                "comparison_note": "MILP-seeded ALNS wrapper; appendix benchmark only.",
                **solver_benchmark_eligibility(
                    OptimizationMode.HYBRID,
                    solver_maturity="prototype",
                    true_solver_family="milp_seeded_alns",
                    solver_display_name="MILPSeededALNS",
                ),
            }
        )
        return OptimizationEngineResult(
            mode=OptimizationMode.HYBRID,
            solver_status=alns_result.solver_status,
            objective_value=alns_result.objective_value,
            plan=alns_result.plan,
            feasible=alns_result.feasible,
            warnings=alns_result.warnings,
            infeasibility_reasons=alns_result.infeasibility_reasons,
            cost_breakdown=alns_result.cost_breakdown,
            solver_metadata=solver_metadata,
            operator_stats=alns_result.operator_stats,
            incumbent_history=alns_result.incumbent_history,
        )
