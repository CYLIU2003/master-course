"""Explicit solver policy, independent of frontend and cluster transport."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from functools import wraps
import inspect

DEFAULT_PROFILE = "existing_solver_v1"
NO_GUROBI_PROFILE = "alns_no_gurobi_v1"
PROFILES = {DEFAULT_PROFILE, NO_GUROBI_PROFILE}


class SolverPolicyViolation(RuntimeError):
    """A requested execution path conflicts with its frozen solver policy."""


@dataclass
class SolverUsage:
    execution_profile: str
    environment_starts: int = 0
    model_creations: int = 0
    optimize_calls: int = 0
    forbidden_calls: int = 0
    counts_complete: bool = True


_usage: ContextVar[SolverUsage | None] = ContextVar("solver_usage", default=None)


def current_usage() -> SolverUsage | None:
    return _usage.get()


def validate_profile(profile: str) -> None:
    if profile not in PROFILES:
        raise SolverPolicyViolation("UNKNOWN_EXECUTION_PROFILE")


def validate_no_gurobi_inputs(profile: str, *, mode: str, research_run: bool = False,
                             planning_days: int = 1, bess_enabled: bool = False,
                             daily_return: bool = False, hourly_rolling: bool = False) -> None:
    validate_profile(profile)
    if profile != NO_GUROBI_PROFILE:
        return
    if (mode not in {"alns", "mode_alns_only", "heuristic"} or research_run
            or planning_days != 1 or bess_enabled or daily_return or hourly_rolling):
        raise SolverPolicyViolation(
            "NO_GUROBI_PROFILE_UNSUPPORTED: requires canonical ALNS, diagnostic single-day "
            "execution, no BESS, no daily-return contract and no hourly rolling")


def require_gurobi(operation: str) -> None:
    from src.execution_control import check_cancelled
    check_cancelled()
    usage = current_usage()
    if usage is not None and usage.execution_profile == NO_GUROBI_PROFILE:
        usage.forbidden_calls += 1
        raise SolverPolicyViolation(f"GUROBI_FORBIDDEN: {operation}")


@contextmanager
def solver_policy_scope(profile: str = DEFAULT_PROFILE):
    validate_profile(profile)
    parent = current_usage()
    if parent is not None:
        if parent.execution_profile != profile:
            raise SolverPolicyViolation("NESTED_SOLVER_POLICY_MISMATCH")
        yield parent
        return
    usage = SolverUsage(profile)
    token = _usage.set(usage)
    try:
        yield usage
        # Legacy callers may catch RuntimeError. A swallowed violation must
        # never turn into a successful heuristic fallback or accepted output.
        if usage.forbidden_calls:
            raise SolverPolicyViolation("GUROBI_FORBIDDEN: a nested caller suppressed the policy violation")
    finally:
        _usage.reset(token)


def guarded_prepare(function):
    """Apply the persisted profile before Prepare can build a baseline."""
    signature = inspect.signature(function)

    @wraps(function)
    def wrapped(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        scenario = bound.arguments["scenario"]
        profile = (scenario.get("simulation_config") or {}).get("execution_profile", DEFAULT_PROFILE)
        with solver_policy_scope(profile):
            return function(*args, **kwargs)
    return wrapped


def usage_record() -> dict:
    usage = current_usage()
    return asdict(usage) if usage else {}


def optimize_model(model, *args, **kwargs):
    """Keep every reachable optimize call observable, including model clones."""
    require_gurobi("optimize")
    from src.gurobi_session import track_model
    track_model(model)
    usage = current_usage()
    if usage is not None:
        usage.optimize_calls += 1
    from src.execution_control import cancellation_checker, check_cancelled
    cancelled = cancellation_checker()
    if cancelled is None:
        return model.optimize(*args, **kwargs)
    # Preserve the original callback's arguments and logic. Cancellation only
    # requests termination of this model, never kills unrelated Python jobs.
    original = args[0] if args else kwargs.pop("callback", None)
    if len(args) > 1:
        raise TypeError("optimize accepts one callback")
    def callback(current_model, where):
        if cancelled():
            current_model.terminate()
        elif original is not None:
            original(current_model, where)
    result = model.optimize(callback)
    check_cancelled()
    return result
