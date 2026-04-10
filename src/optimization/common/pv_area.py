from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


DEFAULT_USABLE_AREA_RATIO = 0.35
DEFAULT_PANEL_POWER_DENSITY_KW_M2 = 0.20
DEFAULT_PERFORMANCE_RATIO = 0.85


@dataclass(frozen=True)
class DepotPvAreaEstimate:
    depot_area_m2: Optional[float]
    usable_area_ratio: float
    panel_power_density_kw_m2: float
    installable_area_m2: float
    capacity_kw: float


def safe_optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def positive_or_none(value: Any) -> Optional[float]:
    parsed = safe_optional_float(value)
    if parsed is None or parsed <= 0.0:
        return None
    return parsed


def positive_ratio_or_default(value: Any, default: float) -> float:
    parsed = safe_optional_float(value)
    if parsed is None or parsed <= 0.0:
        return float(default)
    return float(parsed)


def estimate_depot_pv_from_area(
    depot_area_m2: Any,
    *,
    usable_area_ratio: Any = None,
    panel_power_density_kw_m2: Any = None,
) -> DepotPvAreaEstimate:
    area_m2 = positive_or_none(depot_area_m2)
    usable_ratio = positive_ratio_or_default(
        usable_area_ratio,
        DEFAULT_USABLE_AREA_RATIO,
    )
    panel_density = positive_ratio_or_default(
        panel_power_density_kw_m2,
        DEFAULT_PANEL_POWER_DENSITY_KW_M2,
    )
    installable_area_m2 = (area_m2 or 0.0) * usable_ratio
    capacity_kw = installable_area_m2 * panel_density
    return DepotPvAreaEstimate(
        depot_area_m2=area_m2,
        usable_area_ratio=usable_ratio,
        panel_power_density_kw_m2=panel_density,
        installable_area_m2=installable_area_m2,
        capacity_kw=capacity_kw,
    )
