from __future__ import annotations

from dataclasses import replace

from src.optimization.alns.engine import ALNSOptimizer
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationEngineResult,
    OptimizationMode,
)


class GAOptimizer:
    """Genetic-algorithm style optimizer.

    Current implementation reuses the ALNS neighborhood engine with
    GA-oriented defaults (larger diversification and different metadata).
    This keeps objective/constraint consistency across modes while exposing
    GA as an explicit, independently selectable solver mode.
    """

    def __init__(self) -> None:
        self._delegate = ALNSOptimizer()

    def solve(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> OptimizationEngineResult:
        ga_config = replace(
            config,
            mode=OptimizationMode.GA,
            acceptance="genetic_like",
            operator_selection="adaptive_roulette",
            destroy_fraction=max(config.destroy_fraction, 0.35),
            alns_iterations=max(config.alns_iterations, 600),
        )
        result = self._delegate.solve(problem, ga_config)
        return OptimizationEngineResult(
            mode=OptimizationMode.GA,
            solver_status=result.solver_status,
            objective_value=result.objective_value,
            plan=result.plan,
            feasible=result.feasible,
            warnings=result.warnings,
            infeasibility_reasons=result.infeasibility_reasons,
            cost_breakdown=result.cost_breakdown,
            solver_metadata={
                **dict(result.solver_metadata),
                "metaheuristic": "ga",
                "delegate": "alns_kernel",
                "effective_limits": {
                    "time_limit_sec": int(ga_config.time_limit_sec),
                    "alns_iterations": int(ga_config.alns_iterations),
                    "no_improvement_limit": int(ga_config.no_improvement_limit),
                },
            },
            operator_stats=result.operator_stats,
            incumbent_history=result.incumbent_history,
        )
