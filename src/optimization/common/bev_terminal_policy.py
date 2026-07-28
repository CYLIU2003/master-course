"""Explicit end-of-horizon SOC policies for electric buses."""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Any, Mapping, Optional


class BevTerminalSocPolicy(StrEnum):
    """How a one-day plan treats the energy left in each electric bus."""

    MINIMUM_ONLY = "minimum_only"
    RETURN_TO_INITIAL = "return_to_initial"
    FIXED_TARGET = "fixed_target"


def _safe_nonnegative_float_metadata(
    metadata: Mapping[str, Any],
    key: str,
    *,
    default: float,
) -> float:
    """Resolve a finite non-negative number from problem/run metadata.

    Invalid overrides must not widen a terminal-SOC acceptance band. This
    helper therefore treats negative, non-finite, and non-numeric values as
    absent and retains the documented default.
    """

    try:
        value = float((metadata or {}).get(key))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value >= 0.0 else default


def bev_terminal_numeric_acceptance_contract(
    problem_metadata: Mapping[str, Any],
    *,
    gurobi_feasibility_tol: Optional[float],
) -> dict[str, Any]:
    """Resolve the shared terminal-SOC scientific/numeric contract.

    The scientific tolerance is the physical energy-balance criterion. The
    numeric comparison margin only absorbs solver/float representation noise;
    it does not change the scientific tolerance. Stage 2 and the independent
    physical-event validator must consume this same contract.
    """

    scientific = _safe_nonnegative_float_metadata(
        problem_metadata,
        "bev_terminal_soc_scientific_tolerance_kwh",
        default=_safe_nonnegative_float_metadata(
            problem_metadata,
            "bev_terminal_soc_equality_tolerance_kwh",
            default=1.0e-6,
        ),
    )
    if gurobi_feasibility_tol is None:
        gurobi_feasibility_tol = _safe_nonnegative_float_metadata(
            problem_metadata,
            "stage2_gurobi_feasibility_tol",
            default=1.0e-9,
        )
    else:
        try:
            parsed_gurobi_feasibility_tol = float(gurobi_feasibility_tol)
        except (TypeError, ValueError):
            parsed_gurobi_feasibility_tol = 1.0e-9
        gurobi_feasibility_tol = (
            parsed_gurobi_feasibility_tol
            if math.isfinite(parsed_gurobi_feasibility_tol)
            and parsed_gurobi_feasibility_tol >= 0.0
            else 1.0e-9
        )
    numeric_margin = _safe_nonnegative_float_metadata(
        problem_metadata,
        "bev_terminal_soc_numeric_margin_kwh",
        default=max(float(gurobi_feasibility_tol), 1.0e-9),
    )
    return {
        "scientific_tolerance_kwh": scientific,
        "numeric_comparison_margin_kwh": numeric_margin,
        "gurobi_feasibility_tol_kwh": float(gurobi_feasibility_tol),
        "contract_source_keys": (
            "bev_terminal_soc_scientific_tolerance_kwh",
            "bev_terminal_soc_numeric_margin_kwh",
            "bev_terminal_soc_equality_tolerance_kwh",
        ),
        "legacy_equality_tolerance_kwh": _safe_nonnegative_float_metadata(
            problem_metadata,
            "bev_terminal_soc_equality_tolerance_kwh",
            default=1.0e-6,
        ),
    }


def normalize_bev_terminal_soc_policy(
    value: Any,
    *,
    has_explicit_target: bool = False,
) -> BevTerminalSocPolicy:
    """Normalize a policy while preserving legacy fixed-target scenarios."""

    text = str(value or "").strip().lower()
    if not text:
        return (
            BevTerminalSocPolicy.FIXED_TARGET
            if has_explicit_target
            else BevTerminalSocPolicy.MINIMUM_ONLY
        )
    aliases = {
        "minimum_soc": BevTerminalSocPolicy.MINIMUM_ONLY,
        "minimum": BevTerminalSocPolicy.MINIMUM_ONLY,
        "initial": BevTerminalSocPolicy.RETURN_TO_INITIAL,
        "same_as_initial": BevTerminalSocPolicy.RETURN_TO_INITIAL,
        "target": BevTerminalSocPolicy.FIXED_TARGET,
    }
    if text in aliases:
        return aliases[text]
    try:
        return BevTerminalSocPolicy(text)
    except ValueError as exc:
        allowed = ", ".join(policy.value for policy in BevTerminalSocPolicy)
        raise ValueError(
            f"bev_terminal_soc_policy must be one of: {allowed}"
        ) from exc


def resolve_bev_terminal_soc_target_kwh(
    *,
    policy: BevTerminalSocPolicy | str | None,
    initial_soc_kwh: float,
    configured_target_kwh: float | None,
    terminal_soc_floor_kwh: float,
    maximum_soc_kwh: float,
) -> float | None:
    """Return the hard lower target for the selected terminal policy.

    ``minimum_only`` deliberately returns ``None`` because the ordinary SOC
    reserve remains the only terminal requirement. ``return_to_initial``
    makes representative-day comparisons energy neutral. ``fixed_target``
    keeps the legacy percentage target behavior.
    """

    maximum = max(float(maximum_soc_kwh or 0.0), 0.0)
    floor = min(max(float(terminal_soc_floor_kwh or 0.0), 0.0), maximum)
    normalized = normalize_bev_terminal_soc_policy(
        policy,
        has_explicit_target=configured_target_kwh is not None,
    )
    if normalized is BevTerminalSocPolicy.MINIMUM_ONLY:
        return None
    if normalized is BevTerminalSocPolicy.RETURN_TO_INITIAL:
        target = float(initial_soc_kwh or 0.0)
    else:
        if configured_target_kwh is None:
            raise ValueError(
                "fixed_target policy requires final_soc_target_percent"
            )
        target = float(configured_target_kwh)
    return min(max(target, floor), maximum)
