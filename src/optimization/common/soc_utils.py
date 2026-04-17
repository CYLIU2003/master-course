"""Shared helpers for SOC normalization.

The repository accepts SOC inputs in two compatible forms:
- ratio in [0, 1]
- percent-like values > 1, which are interpreted as percentages and divided by 100
"""

from __future__ import annotations

from typing import Any, Optional


def normalize_soc_ratio_like(value: Any) -> Optional[float]:
    """Normalize a ratio-like SOC value to a fraction in [0, 1]."""

    if value is None or value == "":
        return None
    try:
        ratio = float(value)
    except (TypeError, ValueError):
        return None
    if ratio < 0.0:
        return None
    if ratio > 1.0:
        ratio /= 100.0
    return max(0.0, min(ratio, 1.0))


def resolve_soc_kwh(
    raw_value: Any,
    battery_kwh: Optional[float],
    default_ratio: Any = None,
    *,
    fallback_full_when_missing: bool = False,
) -> Optional[float]:
    """Resolve an SOC input to kWh using the vehicle battery capacity.

    Args:
        raw_value: Explicit per-vehicle SOC input.
        battery_kwh: Battery capacity used to scale the normalized ratio.
        default_ratio: Global fallback SOC input when ``raw_value`` is absent.
        fallback_full_when_missing: If true, use a full battery fallback when
            both the explicit and default inputs are missing.
    """

    if battery_kwh is None:
        return None

    ratio = normalize_soc_ratio_like(raw_value)
    if ratio is not None:
        return battery_kwh * ratio

    default_ratio_value = normalize_soc_ratio_like(default_ratio)
    if default_ratio_value is not None:
        return battery_kwh * default_ratio_value

    if fallback_full_when_missing:
        return battery_kwh
    return None