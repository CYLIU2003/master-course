"""Explicit end-of-horizon SOC policies for electric buses."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class BevTerminalSocPolicy(StrEnum):
    """How a one-day plan treats the energy left in each electric bus."""

    MINIMUM_ONLY = "minimum_only"
    RETURN_TO_INITIAL = "return_to_initial"
    FIXED_TARGET = "fixed_target"


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
