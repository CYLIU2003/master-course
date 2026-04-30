"""Weather-policy soft objective terms.

These terms bias optimization choices but are intentionally not accounting
costs. They must not be mixed into electricity/fuel/asset ledgers.
"""

from __future__ import annotations

from typing import Any, Mapping

from .problem import AssignmentPlan, CanonicalOptimizationProblem

ELECTRIC_POWERTRAINS = {"BEV", "PHEV", "FCEV"}
DEFAULT_WEATHER_STRATEGY_BIAS_BASE_JPY_PER_TRIP = 300.0


def is_electric_vehicle_type(vehicle_type: Any) -> bool:
    return str(vehicle_type or "").strip().upper() in ELECTRIC_POWERTRAINS


def weather_policy_enabled(metadata: Mapping[str, Any] | None) -> bool:
    if not isinstance(metadata, Mapping):
        return False
    return bool(metadata.get("weather_operation_profile") or metadata.get("weather_proxy"))


def weather_strategy_bias_base(metadata: Mapping[str, Any] | None) -> float:
    if not weather_policy_enabled(metadata):
        return 0.0
    try:
        return max(
            float(
                (metadata or {}).get(
                    "weather_strategy_bias_base_jpy_per_trip",
                    DEFAULT_WEATHER_STRATEGY_BIAS_BASE_JPY_PER_TRIP,
                )
            ),
            0.0,
        )
    except (TypeError, ValueError):
        return DEFAULT_WEATHER_STRATEGY_BIAS_BASE_JPY_PER_TRIP


def _bias_value(metadata: Mapping[str, Any], key: str, default: float = 1.0) -> float:
    profile = metadata.get("weather_operation_profile")
    if isinstance(profile, Mapping) and profile.get(key) not in (None, ""):
        raw = profile.get(key)
    else:
        raw = metadata.get(key, default)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return float(default)


def weather_assignment_objective_bias(
    metadata: Mapping[str, Any] | None,
    vehicle_type: Any,
) -> float:
    if not weather_policy_enabled(metadata):
        return 0.0
    metadata_map = dict(metadata or {})
    base = weather_strategy_bias_base(metadata_map)
    if base <= 0.0:
        return 0.0
    bias = _bias_value(
        metadata_map,
        "bev_duty_bias" if is_electric_vehicle_type(vehicle_type) else "ice_backup_bias",
        1.0,
    )
    return round(base * (1.0 - bias), 6)


def weather_vehicle_type_sort_key(metadata: Mapping[str, Any] | None, vehicle_type: Any) -> float:
    return weather_assignment_objective_bias(metadata, vehicle_type)


def weather_strategy_objective_term(
    problem: CanonicalOptimizationProblem,
    plan: AssignmentPlan,
) -> float:
    metadata = dict(problem.metadata or {})
    if not weather_policy_enabled(metadata):
        return 0.0
    vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
    duty_vehicle_map = plan.duty_vehicle_map()
    total = 0.0
    for duty in plan.duties:
        vehicle_id = duty_vehicle_map.get(str(duty.duty_id), "")
        vehicle = vehicle_by_id.get(str(vehicle_id))
        vehicle_type = getattr(vehicle, "vehicle_type", duty.vehicle_type)
        trip_count = len(tuple(getattr(duty, "trip_ids", ()) or ()))
        total += weather_assignment_objective_bias(metadata, vehicle_type) * trip_count
    return round(total, 6)
