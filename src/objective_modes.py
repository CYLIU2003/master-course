from __future__ import annotations

from typing import Any, Dict


SUPPORTED_OBJECTIVE_MODES: tuple[str, ...] = (
    "total_cost",
    "co2",
    "balanced",
    "utilization",
)

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
    "utilization",
}


def normalize_objective_mode(mode: Any) -> str:
    normalized = str(mode or "").strip().lower()
    alias_map = {
        "cost": "total_cost",
        "cost_min": "total_cost",
        "cost_minimize": "total_cost",
        "min_cost": "total_cost",
        "minimize_cost": "total_cost",
        "total_cost": "total_cost",
        "co2": "co2",
        "co2_min": "co2",
        "co2_emission": "co2",
        "co2_emissions": "co2",
        "emission": "co2",
        "emissions": "co2",
        "balanced": "balanced",
        "balance": "balanced",
        "utilization": "utilization",
        "util": "utilization",
        "operation_rate": "utilization",
        "operating_rate": "utilization",
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
    elif normalized == "utilization":
        weights = {
            "vehicle_fixed_cost": 0.3,
            "electricity_cost": 0.7,
            "demand_charge_cost": 0.5,
            "fuel_cost": 0.7,
            "deadhead_cost": 0.0,
            "battery_degradation_cost": 0.1,
            "emission_cost": 0.2,
            "unserved_penalty": float(unserved_penalty),
            "slack_penalty": 1000000.0,
        }
    elif normalized == "balanced":
        weights = {
            "vehicle_fixed_cost": 0.5,
            "electricity_cost": 1.0,
            "demand_charge_cost": 1.0,
            "fuel_cost": 1.0,
            "deadhead_cost": 0.0,
            "battery_degradation_cost": 0.2,
            "emission_cost": 0.5,
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
            "utilization": 0.0,
        }
    elif normalized == "utilization":
        weights = {
            "electricity_cost": 0.7,
            "demand_charge_cost": 0.5,
            "vehicle_fixed_cost": 0.3,
            "unserved_penalty": float(unserved_penalty),
            "deviation_cost": 0.0,
            "switch_cost": 0.0,
            "degradation": 0.1,
            "utilization": 1.0,
        }
    elif normalized == "balanced":
        weights = {
            "electricity_cost": 1.0,
            "demand_charge_cost": 1.0,
            "vehicle_fixed_cost": 0.5,
            "unserved_penalty": float(unserved_penalty),
            "deviation_cost": 0.0,
            "switch_cost": 0.0,
            "degradation": 0.2,
            "utilization": 0.2,
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
            "utilization": 0.0,
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
    utilization_score: float = 0.0,
    objective_weights: Dict[str, Any] | None = None,
) -> float:
    normalized = normalize_objective_mode(objective_mode)
    if normalized == "co2":
        return (
            float(total_co2_kg)
            + float(unserved_penalty)
            + float(switch_cost)
            + float(degradation_cost)
            + float(deviation_cost)
        )
    if normalized in {"balanced", "utilization"}:
        weights = canonical_objective_weights_for_mode(
            objective_mode=normalized,
            unserved_penalty=float(unserved_penalty),
            explicit_weights=objective_weights or {},
        )
        utilization_term = max(0.0, 1.0 - float(utilization_score))
        return (
            float(total_cost)
            + float(weights.get("degradation", 0.0)) * float(degradation_cost)
            + float(weights.get("switch_cost", 0.0)) * float(switch_cost)
            + float(weights.get("deviation_cost", 0.0)) * float(deviation_cost)
            + float(weights.get("utilization", 0.0)) * utilization_term
        )
    return float(total_cost)
