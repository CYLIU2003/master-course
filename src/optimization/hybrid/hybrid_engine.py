from __future__ import annotations

from src.optimization.alns.engine import ALNSOptimizer
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
            costs = CostEvaluator().evaluate(problem, milp_result.plan).to_dict()
            initial_state = SolutionState(
                problem=problem,
                plan=milp_result.plan,
                cost_breakdown=costs,
                feasible=report.feasible,
                infeasibility_reasons=report.errors,
                metadata={"seeded_from": "milp"},
            )
        alns_result = self._alns.solve(problem, config, initial_state=initial_state)
        return OptimizationEngineResult(
            mode=OptimizationMode.HYBRID,
            solver_status=alns_result.solver_status,
            objective_value=alns_result.objective_value,
            plan=alns_result.plan,
            feasible=alns_result.feasible,
            warnings=alns_result.warnings,
            infeasibility_reasons=alns_result.infeasibility_reasons,
            cost_breakdown=alns_result.cost_breakdown,
            solver_metadata={
                "milp_seed_status": milp_result.solver_status,
                "partial_milp_calls": 1,
                "generated_columns": len(
                    self._pricing_problem.generate_columns({"baseline_objective": milp_result.objective_value})
                ),
                **dict(alns_result.solver_metadata),
            },
            operator_stats=alns_result.operator_stats,
            incumbent_history=alns_result.incumbent_history,
        )
