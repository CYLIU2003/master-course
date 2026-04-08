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
            alns_iterations=max(config.alns_iterations, 1500),  # Increased from 600
            no_improvement_limit=max(config.no_improvement_limit, 300),  # Increased patience
        )
        result = self._delegate.solve(problem, ga_config)
        
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
            mode=OptimizationMode.GA,
            solver_status=result_category,
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
                "true_solver_family": "alns",  # GA delegates to ALNS kernel
                "independent_implementation": False,  # Not a true independent solver
                "original_alns_status": result.solver_status,
                "has_feasible_incumbent": result.feasible,
                "incumbent_count": len(result.incumbent_history or []),
                "effective_limits": {
                    "time_limit_sec": int(ga_config.time_limit_sec),
                    "alns_iterations": int(ga_config.alns_iterations),
                    "no_improvement_limit": int(ga_config.no_improvement_limit),
                },
            },
            operator_stats=result.operator_stats,
            incumbent_history=result.incumbent_history,
        )
