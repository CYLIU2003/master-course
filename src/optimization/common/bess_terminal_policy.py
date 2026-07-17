from __future__ import annotations

from typing import Optional


BESS_TERMINAL_POLICY_MINIMUM_ONLY = "minimum_only"
BESS_TERMINAL_POLICY_RETURN_TO_INITIAL = "return_to_initial"
BESS_TERMINAL_POLICY_FIXED_TARGET = "fixed_target"

VALID_BESS_TERMINAL_POLICIES = frozenset(
    {
        BESS_TERMINAL_POLICY_MINIMUM_ONLY,
        BESS_TERMINAL_POLICY_RETURN_TO_INITIAL,
        BESS_TERMINAL_POLICY_FIXED_TARGET,
    }
)


def normalize_bess_terminal_policy(
    value: object,
    *,
    has_explicit_target: bool = False,
) -> str:
    """Return the canonical stationary-battery terminal-SOC policy.

    A missing policy keeps old scenarios reproducible: a positive legacy
    terminal target is interpreted as ``fixed_target``; otherwise only the
    configured terminal lower bound is enforced.
    """

    normalized = str(value or "").strip().lower()
    aliases = {
        "minimum": BESS_TERMINAL_POLICY_MINIMUM_ONLY,
        "range_only": BESS_TERMINAL_POLICY_MINIMUM_ONLY,
        "operating_range": BESS_TERMINAL_POLICY_MINIMUM_ONLY,
        "initial": BESS_TERMINAL_POLICY_RETURN_TO_INITIAL,
        "cyclic": BESS_TERMINAL_POLICY_RETURN_TO_INITIAL,
        "target": BESS_TERMINAL_POLICY_FIXED_TARGET,
    }
    normalized = aliases.get(normalized, normalized)
    if not normalized:
        return (
            BESS_TERMINAL_POLICY_FIXED_TARGET
            if has_explicit_target
            else BESS_TERMINAL_POLICY_MINIMUM_ONLY
        )
    if normalized not in VALID_BESS_TERMINAL_POLICIES:
        allowed = ", ".join(sorted(VALID_BESS_TERMINAL_POLICIES))
        raise ValueError(f"bess_terminal_soc_policy must be one of: {allowed}")
    return normalized


def resolve_bess_terminal_soc_target_kwh(
    *,
    policy: object,
    initial_soc_kwh: float,
    configured_target_kwh: float,
    terminal_soc_floor_kwh: float,
    maximum_soc_kwh: float,
) -> Optional[float]:
    """Resolve an optional target while retaining hard SOC bounds.

    ``minimum_only`` deliberately returns ``None``. The hard terminal lower
    bound and the regular BESS SOC bounds remain active in every policy.
    """

    configured_target = max(float(configured_target_kwh or 0.0), 0.0)
    normalized = normalize_bess_terminal_policy(
        policy,
        has_explicit_target=configured_target > 0.0,
    )
    if normalized == BESS_TERMINAL_POLICY_MINIMUM_ONLY:
        return None
    if normalized == BESS_TERMINAL_POLICY_RETURN_TO_INITIAL:
        raw_target = max(float(initial_soc_kwh or 0.0), 0.0)
    else:
        raw_target = configured_target
    if normalized == BESS_TERMINAL_POLICY_FIXED_TARGET and raw_target <= 0.0:
        return None

    lower = max(float(terminal_soc_floor_kwh or 0.0), 0.0)
    upper = max(float(maximum_soc_kwh or 0.0), lower)
    return min(max(raw_target, lower), upper)
