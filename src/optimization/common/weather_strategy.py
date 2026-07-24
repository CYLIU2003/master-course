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


def weather_decision_policy_audit(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Describe the *effective* weather decision controls without inference.

    ``operation_mode`` is a weather-provenance classification.  It is not
    evidence that the optimizer received a different operational policy.  This
    audit therefore reports the actual numerical assignment terms and the
    non-assignment controls that reach the canonical problem.  It is used in
    run artifacts so a zero-valued policy cannot be mistaken for an active
    weather dispatch strategy.
    """

    metadata_map = dict(metadata or {})
    profile = metadata_map.get("weather_operation_profile")
    profile_map = dict(profile) if isinstance(profile, Mapping) else {}
    policy_enabled = weather_policy_enabled(metadata_map)
    bias_base = weather_strategy_bias_base(metadata_map)
    bev_bias = _bias_value(metadata_map, "bev_duty_bias", 1.0)
    ice_bias = _bias_value(metadata_map, "ice_backup_bias", 1.0)
    effective_assignment_bias = {
        "BEV": weather_assignment_objective_bias(metadata_map, "BEV"),
        "ICE": weather_assignment_objective_bias(metadata_map, "ICE"),
    }
    operational_control_keys = (
        "final_soc_floor_percent",
        "final_soc_target_percent",
        "final_soc_target_tolerance_percent",
        "initial_soc_min_percent",
        "initial_soc_max_percent",
        "midday_charge_priority",
        "grid_risk_penalty_multiplier",
    )
    applied_operational_controls = {
        key: profile_map.get(key, metadata_map.get(key))
        for key in operational_control_keys
        if profile_map.get(key, metadata_map.get(key)) not in (None, "")
    }
    assignment_bias_active = any(
        abs(value) > 1.0e-9 for value in effective_assignment_bias.values()
    )
    scope = (
        "weather_dispatch_policy"
        if assignment_bias_active or applied_operational_controls
        else "pv_curve_only"
        if policy_enabled
        else "not_enabled"
    )
    return {
        "weather_policy_enabled": policy_enabled,
        "operation_mode": profile_map.get("operation_mode"),
        "operation_mode_is_provenance_label_only": bool(
            policy_enabled
            and not assignment_bias_active
            and not applied_operational_controls
        ),
        "policy_scope": scope,
        "assignment_bias_base_jpy_per_trip": bias_base if policy_enabled else 0.0,
        "assignment_bias_multiplier_by_vehicle_type": {
            "BEV": bev_bias,
            "ICE": ice_bias,
        },
        "effective_assignment_bias_jpy_per_trip_by_vehicle_type": (
            effective_assignment_bias
        ),
        "assignment_bias_active": assignment_bias_active,
        "applied_operational_controls": applied_operational_controls,
        "accounting_cost_treatment": (
            "Weather assignment bias is an objective-only policy term and is "
            "not an accounting electricity, fuel, PV, or BESS cost."
        ),
    }


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
