from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .problem import OptimizationConfig, OptimizationMode


@dataclass(frozen=True)
class ExactRepairPolicy:
    call_limit: int
    time_budget_sec: float


def exact_repair_policy(config: OptimizationConfig) -> ExactRepairPolicy:
    return ExactRepairPolicy(
        call_limit=max(1, min(5, int(config.alns_iterations // 250) + 1)),
        time_budget_sec=max(10.0, min(float(config.time_limit_sec) * 0.2, 120.0)),
    )


def solver_benchmark_eligibility(
    mode: OptimizationMode | str,
    *,
    solver_maturity: str = "",
    true_solver_family: str = "",
    solver_display_name: str = "",
) -> Dict[str, Any]:
    normalized_mode = str(getattr(mode, "value", mode)).strip().lower()
    family = str(true_solver_family or "").strip().lower()
    maturity = str(solver_maturity or "").strip().lower()
    display_name = str(solver_display_name or "").strip().lower()

    def _main(note: str) -> Dict[str, Any]:
        return {
            "eligible_for_main_benchmark": True,
            "eligible_for_appendix_benchmark": False,
            "comparison_note": note,
        }

    def _appendix(note: str) -> Dict[str, Any]:
        return {
            "eligible_for_main_benchmark": False,
            "eligible_for_appendix_benchmark": True,
            "comparison_note": note,
        }

    if normalized_mode == "milp" or family == "milp":
        return _main("Exact core solver; main benchmark candidate.")
    if normalized_mode == "alns" or family == "alns":
        return _main("Core metaheuristic; main benchmark candidate.")
    if normalized_mode == "ga" or family == "ga":
        return _appendix("Prototype genetic search; appendix benchmark only.")
    if normalized_mode == "abc" or family == "abc":
        return _appendix("Prototype bee-colony search; appendix benchmark only.")
    if normalized_mode == "hybrid" or family == "milp_seeded_alns" or "milpseededalns" in display_name:
        return _appendix("MILP-seeded ALNS wrapper; appendix benchmark only.")
    if maturity in {"core", "production"}:
        return _main("Core or production solver; main benchmark candidate.")
    if maturity in {"prototype", "exploratory"}:
        return _appendix("Prototype solver; appendix benchmark only.")
    return {
        "eligible_for_main_benchmark": False,
        "eligible_for_appendix_benchmark": False,
        "comparison_note": "Benchmark eligibility not declared.",
    }
