from __future__ import annotations

from typing import Any, Dict


SUPPORTED_OBJECTIVE_MODES: tuple[str, ...] = ("total_cost", "co2")

_LEGACY_PRESERVED_WEIGHT_KEYS = {
    "battery_degradation_cost",
    "slack_penalty",
    "depot_charger_cost",
    "depot_detour_cost_per_km",
    "charger_daily_fixed_cost",
}
_CANONICAL_PRESERVED_WEIGHT_KEYS = {
    "deviation_cost",
    "switch_cost",
    "degradation",
}


def normalize_objective_mode(mode: Any) -> str:
    normalized = str(mode or "").strip().lower()
    alias_map = {
        "cost": "total_cost",
        "cost_min": "total_cost",
        "min_cost": "total_cost",
        "total_cost": "total_cost",
        "co2": "co2",
        "co2_min": "co2",
        "co2_emission": "co2",
        "co2_emissions": "co2",
        "emission": "co2",
        "emissions": "co2",
    }
    return alias_map.get(normalized, "total_cost")


def effective_co2_price_per_kg(
    objective_mode: Any,
    configured_price: Any,
) -> float:
    try:
        parsed = None if configured_price is None else float(configured_price)
    except (TypeError, ValueError):
        parsed = None
    if parsed is not None and parsed > 0.0:
        return parsed
    if normalize_objective_mode(objective_mode) == "co2":
        return 1.0
    return max(float(parsed or 0.0), 0.0)


def legacy_objective_weights_for_mode(
    *,
    objective_mode: Any,
    unserved_penalty: float,
    explicit_weights: Dict[str, Any] | None = None,
) -> Dict[str, float]:
    normalized = normalize_objective_mode(objective_mode)
    weights: Dict[str, float]
    if normalized == "co2":
        weights = {
            "vehicle_fixed_cost": 0.0,
            "electricity_cost": 0.0,
            "demand_charge_cost": 0.0,
            "fuel_cost": 0.0,
            "deadhead_cost": 0.0,
            "battery_degradation_cost": 0.0,
            "emission_cost": 1.0,
            "unserved_penalty": float(unserved_penalty),
            "slack_penalty": 1000000.0,
        }
    else:
        weights = {
            "vehicle_fixed_cost": 1.0,
            "electricity_cost": 1.0,
            "demand_charge_cost": 1.0,
            "fuel_cost": 1.0,
            "deadhead_cost": 0.0,
            "battery_degradation_cost": 0.0,
            "emission_cost": 0.0,
            "unserved_penalty": float(unserved_penalty),
            "slack_penalty": 1000000.0,
        }
    for key, value in dict(explicit_weights or {}).items():
        normalized_key = str(key)
        if normalized_key == "degradation":
            normalized_key = "battery_degradation_cost"
        if normalized_key not in _LEGACY_PRESERVED_WEIGHT_KEYS:
            continue
        try:
            weights[normalized_key] = float(value)
        except (TypeError, ValueError):
            continue
    return weights


def canonical_objective_weights_for_mode(
    *,
    objective_mode: Any,
    unserved_penalty: float,
    explicit_weights: Dict[str, Any] | None = None,
) -> Dict[str, float]:
    normalized = normalize_objective_mode(objective_mode)
    weights: Dict[str, float]
    if normalized == "co2":
        weights = {
            "electricity_cost": 0.0,
            "demand_charge_cost": 0.0,
            "vehicle_fixed_cost": 0.0,
            "unserved_penalty": float(unserved_penalty),
            "deviation_cost": 0.0,
            "switch_cost": 0.0,
            "degradation": 0.0,
        }
    else:
        weights = {
            "electricity_cost": 1.0,
            "demand_charge_cost": 1.0,
            "vehicle_fixed_cost": 1.0,
            "unserved_penalty": float(unserved_penalty),
            "deviation_cost": 0.0,
            "switch_cost": 0.0,
            "degradation": 0.0,
        }
    for key, value in dict(explicit_weights or {}).items():
        normalized_key = str(key)
        if normalized_key not in _CANONICAL_PRESERVED_WEIGHT_KEYS:
            continue
        try:
            weights[normalized_key] = float(value)
        except (TypeError, ValueError):
            continue
    return weights


def objective_value_for_mode(
    *,
    objective_mode: Any,
    total_cost: float,
    total_co2_kg: float,
    unserved_penalty: float = 0.0,
    switch_cost: float = 0.0,
    degradation_cost: float = 0.0,
    deviation_cost: float = 0.0,
) -> float:
    if normalize_objective_mode(objective_mode) == "co2":
        return (
            float(total_co2_kg)
            + float(unserved_penalty)
            + float(switch_cost)
            + float(degradation_cost)
            + float(deviation_cost)
        )
    return float(total_cost)
