from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.optimization.common.problem import CanonicalOptimizationProblem, OptimizationConfig


@dataclass(frozen=True)
class MILPSolverOutcome:
    solver_status: str
    used_backend: str
    supports_exact_milp: bool


class SolverAdapter(Protocol):
    backend_name: str

    def solve(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> MILPSolverOutcome:
        ...


class DispatchBaselineMILPAdapter:
    backend_name = "dispatch_baseline"

    def solve(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> MILPSolverOutcome:
        return MILPSolverOutcome(
            solver_status="baseline_feasible",
            used_backend=self.backend_name,
            supports_exact_milp=False,
        )
