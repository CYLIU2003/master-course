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
            alns_iterations=max(config.alns_iterations, 1800),  # Increased from 700
            no_improvement_limit=max(config.no_improvement_limit, 350),  # Increased patience
        )
        result = self._delegate.solve(problem, abc_config)
        
        # Map solver status to 4-category result classification
        if result.feasible and len(result.incumbent_history or []) > 0:
            result_category = "SOLVED_FEASIBLE"
        elif not result.feasible and len(result.incumbent_history or []) > 0:
            result_category = "SOLVED_INFEASIBLE"
        elif len(result.incumbent_history or []) == 0:
            result_category = "NO_INCUMBENT"
        else:
            result_category = result.solver_status
        
        return OptimizationEngineResult(
            mode=OptimizationMode.ABC,
            solver_status=result_category,
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
                "true_solver_family": "alns",  # ABC delegates to ALNS kernel
                "independent_implementation": False,  # Not a true independent solver
                "original_alns_status": result.solver_status,
                "has_feasible_incumbent": result.feasible,
                "incumbent_count": len(result.incumbent_history or []),
                "effective_limits": {
                    "time_limit_sec": int(abc_config.time_limit_sec),
                    "alns_iterations": int(abc_config.alns_iterations),
                    "no_improvement_limit": int(abc_config.no_improvement_limit),
                },
            },
            operator_stats=result.operator_stats,
            incumbent_history=result.incumbent_history,
        )
