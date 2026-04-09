from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class SearchProfile:
    started_at: float
    first_feasible_sec: Optional[float] = None
    incumbent_updates: int = 0
    evaluator_calls: int = 0
    evaluator_time_sec: float = 0.0
    repair_calls: int = 0
    repair_time_sec: float = 0.0
    exact_repair_calls: int = 0
    exact_repair_time_sec: float = 0.0
    feasible_candidate_count: int = 0
    rejected_candidate_count: int = 0
    fallback_count: int = 0

    def record_evaluation(self, duration_sec: float, *, feasible: bool, elapsed_sec: float) -> None:
        self.evaluator_calls += 1
        self.evaluator_time_sec += max(float(duration_sec), 0.0)
        if feasible:
            self.feasible_candidate_count += 1
            if self.first_feasible_sec is None:
                self.first_feasible_sec = max(float(elapsed_sec), 0.0)
        else:
            self.rejected_candidate_count += 1

    def record_repair(self, duration_sec: float, *, exact: bool = False) -> None:
        self.repair_calls += 1
        self.repair_time_sec += max(float(duration_sec), 0.0)
        if exact:
            self.exact_repair_calls += 1
            self.exact_repair_time_sec += max(float(duration_sec), 0.0)

    def record_incumbent(self, *, feasible: bool, elapsed_sec: float) -> None:
        self.incumbent_updates += 1
        if feasible and self.first_feasible_sec is None:
            self.first_feasible_sec = max(float(elapsed_sec), 0.0)

    def record_fallback(self) -> None:
        self.fallback_count += 1

    def snapshot(self, *, total_wall_clock_sec: float) -> Dict[str, Any]:
        evaluator_calls = max(int(self.evaluator_calls), 0)
        repair_calls = max(int(self.repair_calls), 0)
        exact_repair_calls = max(int(self.exact_repair_calls), 0)
        return {
            "total_wall_clock_sec": round(float(total_wall_clock_sec), 6),
            "first_feasible_sec": None if self.first_feasible_sec is None else round(float(self.first_feasible_sec), 6),
            "incumbent_updates": int(self.incumbent_updates),
            "evaluator_calls": evaluator_calls,
            "avg_evaluator_sec": round(self.evaluator_time_sec / evaluator_calls, 6) if evaluator_calls else 0.0,
            "repair_calls": repair_calls,
            "avg_repair_sec": round(self.repair_time_sec / repair_calls, 6) if repair_calls else 0.0,
            "exact_repair_calls": exact_repair_calls,
            "avg_exact_repair_sec": round(self.exact_repair_time_sec / exact_repair_calls, 6) if exact_repair_calls else 0.0,
            "feasible_candidate_ratio": round(self.feasible_candidate_count / evaluator_calls, 6) if evaluator_calls else 0.0,
            "rejected_candidate_ratio": round(self.rejected_candidate_count / evaluator_calls, 6) if evaluator_calls else 0.0,
            "fallback_count": int(self.fallback_count),
        }
