from __future__ import annotations

import time


class MaxIterationsStop:
    def __init__(self, max_iterations: int) -> None:
        self.max_iterations = max_iterations

    def should_stop(self, iteration: int, no_improve: int, started_at: float) -> bool:
        return iteration >= self.max_iterations


class CompositeStop:
    def __init__(
        self,
        *,
        max_iterations: int,
        max_runtime_sec: float,
        no_improvement_limit: int,
    ) -> None:
        self.max_iterations = max_iterations
        self.max_runtime_sec = max_runtime_sec
        self.no_improvement_limit = no_improvement_limit

    def should_stop(self, iteration: int, no_improve: int, started_at: float) -> bool:
        return (
            iteration >= self.max_iterations
            or no_improve >= self.no_improvement_limit
            or (time.perf_counter() - started_at) >= self.max_runtime_sec
        )
