from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict


def _coerce_nonnegative_float(value: Any) -> float:
    try:
        return max(float(value or 0.0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _first_float(values: Mapping[str, Any], *keys: str) -> float:
    for key in keys:
        if key in values:
            return _coerce_nonnegative_float(values.get(key))
    return 0.0


def compute_pv_curtail_kwh(
    pv_generation_kwh: float,
    pv_to_bus_kwh: float = 0.0,
    pv_to_bess_kwh: float = 0.0,
) -> float:
    return max(
        0.0,
        _coerce_nonnegative_float(pv_generation_kwh)
        - _coerce_nonnegative_float(pv_to_bus_kwh)
        - _coerce_nonnegative_float(pv_to_bess_kwh),
    )


def compute_pv_utilization_rate(
    pv_generation_kwh: float,
    pv_to_bus_kwh: float = 0.0,
    pv_to_bess_kwh: float = 0.0,
) -> float:
    generation = _coerce_nonnegative_float(pv_generation_kwh)
    if generation <= 1.0e-9:
        return 0.0
    used = _coerce_nonnegative_float(pv_to_bus_kwh) + _coerce_nonnegative_float(pv_to_bess_kwh)
    return min(max(used / generation, 0.0), 1.0)


def normalize_pv_energy_breakdown(values: Mapping[str, Any]) -> Dict[str, float]:
    pv_generation_kwh = _first_float(values, "pv_generated_kwh", "pv_generation_kwh")
    pv_to_bus_kwh = _first_float(values, "pv_to_bus_kwh", "pv_used_direct_kwh")
    pv_to_bess_kwh = _coerce_nonnegative_float(values.get("pv_to_bess_kwh"))
    pv_used_total_kwh = pv_to_bus_kwh + pv_to_bess_kwh

    raw_pv_curtail_kwh = None
    for key in ("pv_curtailed_kwh", "pv_curtail_kwh"):
        if key in values:
            raw_pv_curtail_kwh = _coerce_nonnegative_float(values.get(key))
            break

    has_balance_inputs = "pv_generated_kwh" in values or "pv_generation_kwh" in values
    has_any_pv_input = any(
        key in values
        for key in (
            "pv_generated_kwh",
            "pv_generation_kwh",
            "pv_to_bus_kwh",
            "pv_used_direct_kwh",
            "pv_to_bess_kwh",
        )
    )
    balance_pv_curtail_kwh = (
        compute_pv_curtail_kwh(pv_generation_kwh, pv_to_bus_kwh, pv_to_bess_kwh)
        if has_any_pv_input
        else 0.0
    )
    pv_curtail_kwh = (
        balance_pv_curtail_kwh
        if has_balance_inputs or raw_pv_curtail_kwh is None
        else raw_pv_curtail_kwh
    )

    return {
        "pv_generated_kwh": pv_generation_kwh,
        "pv_to_bus_kwh": pv_to_bus_kwh,
        "pv_to_bess_kwh": pv_to_bess_kwh,
        "pv_used_total_kwh": pv_used_total_kwh,
        "pv_curtail_balance_kwh": balance_pv_curtail_kwh,
        "pv_curtail_reported_raw_kwh": raw_pv_curtail_kwh if raw_pv_curtail_kwh is not None else 0.0,
        "pv_curtailed_kwh": pv_curtail_kwh,
        "pv_curtail_kwh": pv_curtail_kwh,
        "pv_utilization_rate": compute_pv_utilization_rate(
            pv_generation_kwh,
            pv_to_bus_kwh,
            pv_to_bess_kwh,
        ),
    }
