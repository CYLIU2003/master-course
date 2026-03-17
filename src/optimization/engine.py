from __future__ import annotations

from src.optimization.abc.engine import ABCOptimizer
from src.optimization.alns.engine import ALNSOptimizer
from src.optimization.ga.engine import GAOptimizer
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationEngineResult,
    OptimizationMode,
)
from src.optimization.hybrid.hybrid_engine import HybridOptimizer
from src.optimization.milp.engine import MILPOptimizer


class OptimizationEngine:
    def __init__(self) -> None:
        self._milp = MILPOptimizer()
        self._alns = ALNSOptimizer()
        self._ga = GAOptimizer()
        self._abc = ABCOptimizer()
        self._hybrid = HybridOptimizer()

    def solve(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> OptimizationEngineResult:
        if config.mode == OptimizationMode.MILP:
            return self._milp.solve(problem, config)
        if config.mode == OptimizationMode.ALNS:
            return self._alns.solve(problem, config)
        if config.mode == OptimizationMode.GA:
            return self._ga.solve(problem, config)
        if config.mode == OptimizationMode.ABC:
            return self._abc.solve(problem, config)
        return self._hybrid.solve(problem, config)
