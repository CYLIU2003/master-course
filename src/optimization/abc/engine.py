from __future__ import annotations

from dataclasses import replace

from src.optimization.alns.engine import ALNSOptimizer
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationEngineResult,
    OptimizationMode,
)


class ABCOptimizer:
    """Artificial Bee Colony style optimizer.

    Uses the shared neighborhood kernel with ABC-oriented search settings
    (strong exploration, larger iteration budget).
    """

    def __init__(self) -> None:
        self._delegate = ALNSOptimizer()

    def solve(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> OptimizationEngineResult:
        abc_config = replace(
            config,
            mode=OptimizationMode.ABC,
            acceptance="bee_colony_like",
            operator_selection="adaptive_roulette",
            destroy_fraction=max(config.destroy_fraction, 0.4),
            alns_iterations=max(config.alns_iterations, 700),
        )
        result = self._delegate.solve(problem, abc_config)
        return OptimizationEngineResult(
            mode=OptimizationMode.ABC,
            solver_status=result.solver_status,
            objective_value=result.objective_value,
            plan=result.plan,
            feasible=result.feasible,
            warnings=result.warnings,
            infeasibility_reasons=result.infeasibility_reasons,
            cost_breakdown=result.cost_breakdown,
            solver_metadata={
                **dict(result.solver_metadata),
                "metaheuristic": "abc",
                "delegate": "alns_kernel",
                "effective_limits": {
                    "time_limit_sec": int(abc_config.time_limit_sec),
                    "alns_iterations": int(abc_config.alns_iterations),
                    "no_improvement_limit": int(abc_config.no_improvement_limit),
                },
            },
            operator_stats=result.operator_stats,
            incumbent_history=result.incumbent_history,
        )
