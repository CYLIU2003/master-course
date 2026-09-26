"""Frozen per-attempt native memory budget, inherited by hourly subprocesses."""
from __future__ import annotations
import math
import os

ENV_KEY = "MC_SOLVER_MEMORY_BUDGET_GIB"


def memory_limits() -> dict[str, float] | None:
    raw = os.environ.get(ENV_KEY)
    if raw is None:
        return None
    budget = float(raw)
    if not math.isfinite(budget) or budget < 4:
        raise ValueError("INVALID_SOLVER_MEMORY_BUDGET")
    # Keep 2 GiB within the task budget for Python/input/reporting. Gurobi uses
    # decimal GB; the scheduler and Windows probes use binary GiB.
    hard = (budget - 2) * (1024 ** 3) / 1e9
    return {"task_budget_gib": budget, "native_hard_gb": hard, "native_soft_gb": hard * .9}


def apply_memory_limits(model) -> None:
    limits = memory_limits()
    if limits is None:
        return
    # Reapply at every optimize boundary: profiles and cloned models may have
    # larger defaults. Never increase an already stricter model limit.
    model.Params.MemLimit = min(float(model.Params.MemLimit), limits["native_hard_gb"])
    model.Params.SoftMemLimit = min(float(model.Params.SoftMemLimit), limits["native_soft_gb"])
