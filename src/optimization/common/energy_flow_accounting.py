from __future__ import annotations

from collections.abc import Mapping, Sequence
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


def _coerce_slot_index(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_depot_slot_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _infer_value_from_mapping(row: Mapping[str, Any]) -> float:
    for key in (
        "value",
        "kwh",
        "kw",
        "pv_generation_kwh",
        "pv_to_bus_kwh",
        "pv_to_bess_kwh",
        "pv_curtailed_kwh",
        "bess_to_bus_kwh",
        "grid_to_bus_kwh",
        "grid_to_bess_kwh",
        "grid_total_kwh",
    ):
        if key in row:
            return _coerce_depot_slot_value(row.get(key))
    numeric_values = [
        _coerce_depot_slot_value(value)
        for value in row.values()
        if isinstance(value, (int, float)) or str(value).strip() not in {"", "None"}
    ]
    return numeric_values[0] if numeric_values else 0.0


def normalize_depot_slot_flow(raw: Any) -> Dict[str, Dict[int, float]]:
    """Normalize depot-slot flows into ``{depot_id: {slot_idx: value}}``.

    The helper accepts several legacy shapes:
    - ``{(depot_id, slot_idx): value}``
    - ``{depot_id: {slot_idx: value}}``
    - ``[{depot_id, slot_idx, value}]`` or rows with common value field names
    """

    if raw is None:
        return {}

    out: Dict[str, Dict[int, float]] = {}

    if isinstance(raw, Mapping):
        for key, value in raw.items():
            if isinstance(key, tuple) and len(key) >= 2:
                depot_id = str(key[0] or "")
                slot_idx = _coerce_slot_index(key[1])
                if depot_id and slot_idx is not None:
                    out.setdefault(depot_id, {})[slot_idx] = _coerce_depot_slot_value(value)
                continue
            depot_id = str(key or "")
            if not depot_id:
                continue
            if isinstance(value, Mapping):
                out.setdefault(depot_id, {}).update(
                    {
                        int(slot_idx): _coerce_depot_slot_value(slot_value)
                        for slot_idx, slot_value in value.items()
                        if _coerce_slot_index(slot_idx) is not None
                    }
                )
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                out.setdefault(depot_id, {}).update(
                    {
                        int(slot_idx): _coerce_depot_slot_value(slot_value)
                        for slot_idx, slot_value in enumerate(value)
                    }
                )
        return out

    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            depot_id = str(item.get("depot_id") or item.get("site_id") or "")
            slot_idx = _coerce_slot_index(
                item.get("slot_idx")
                if item.get("slot_idx") is not None
                else item.get("slot_index")
                if item.get("slot_index") is not None
                else item.get("time_idx")
            )
            if not depot_id or slot_idx is None:
                continue
            out.setdefault(depot_id, {})[slot_idx] = _infer_value_from_mapping(item)
        return out

    return {}


def get_depot_slot_flow(obj: Any, *attr_names: str) -> Dict[str, Dict[int, float]]:
    """Return the first available depot-slot flow from ``obj`` and normalize it."""

    if obj is None:
        return {}
    for attr_name in attr_names:
        if isinstance(obj, Mapping):
            if attr_name in obj:
                return normalize_depot_slot_flow(obj.get(attr_name))
            continue
        if hasattr(obj, attr_name):
            return normalize_depot_slot_flow(getattr(obj, attr_name))
    return {}


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
