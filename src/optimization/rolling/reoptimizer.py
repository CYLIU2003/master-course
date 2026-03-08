from __future__ import annotations

from src.optimization.common.problem import CanonicalOptimizationProblem, OptimizationConfig
from src.optimization.engine import OptimizationEngine
from .state_locking import lock_started_trips


class RollingReoptimizer:
    def __init__(self) -> None:
        self._engine = OptimizationEngine()

    def reoptimize(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
        current_min: int,
    ):
        if problem.baseline_plan is not None:
            locked_plan = lock_started_trips(problem.baseline_plan, current_min)
            problem = CanonicalOptimizationProblem(
                scenario=problem.scenario,
                dispatch_context=problem.dispatch_context,
                trips=problem.trips,
                vehicles=problem.vehicles,
                chargers=problem.chargers,
                price_slots=problem.price_slots,
                pv_slots=problem.pv_slots,
                feasible_connections=problem.feasible_connections,
                objective_weights=problem.objective_weights,
                baseline_plan=locked_plan,
                metadata=problem.metadata,
            )
        return self._engine.solve(problem, config)
