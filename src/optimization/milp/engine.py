from __future__ import annotations

from .model_builder import MILPModelBuilder
from .solver_adapter import DispatchBaselineMILPAdapter
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationEngineResult,
    OptimizationMode,
)


class MILPOptimizer:
    def __init__(self) -> None:
        self._builder = MILPModelBuilder()
        self._adapter = DispatchBaselineMILPAdapter()
        self._feasibility = FeasibilityChecker()
        self._evaluator = CostEvaluator()

    def solve(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> OptimizationEngineResult:
        model = self._builder.build(problem)
        outcome = self._adapter.solve(problem, config)
        plan = problem.baseline_plan
        report = self._feasibility.evaluate(problem, plan)
        costs = self._evaluator.evaluate(problem, plan).to_dict()
        return OptimizationEngineResult(
            mode=OptimizationMode.MILP,
            solver_status=outcome.solver_status,
            objective_value=costs["total_cost"],
            plan=plan,
            feasible=report.feasible,
            warnings=report.warnings,
            infeasibility_reasons=report.errors,
            cost_breakdown=costs,
            solver_metadata={
                "backend": outcome.used_backend,
                "supports_exact_milp": outcome.supports_exact_milp,
                "model_stats": {
                    "variables": model.variable_counts,
                    "constraints": model.constraint_counts,
                    "objective_terms": model.objective_terms,
                    "variable_samples": [variable.name for variable in model.variables[:10]],
                    "constraint_samples": [constraint.name for constraint in model.constraints[:10]],
                },
                "time_limit_sec": config.time_limit_sec,
                "mip_gap": config.mip_gap,
            },
        )
