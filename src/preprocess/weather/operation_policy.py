"""Convert weather proxy forecasts into optimization-readable policy metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Dict, Mapping

from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    DepotEnergyAsset,
    PVSlot,
)
from .daily_weather_schema import (
    FORECAST_TYPE_SOLCAST_PV_PROXY_V1,
    FORECAST_TYPE_SOLCAST_TYPICAL_PV_PROXY_V1,
    WeatherProxyForecast,
    weather_proxy_forecast_to_dict,
)

PV_MARGINAL_COST_POLICY = (
    "pv_to_bus_and_pv_to_bess_marginal_cost_zero_assets_reported_separately"
)


@dataclass(frozen=True)
class WeatherOperationProfile:
    operation_mode: str
    final_soc_floor_percent: float | None
    final_soc_target_percent: float | None
    final_soc_target_tolerance_percent: float | None
    initial_soc_mode: str
    initial_soc_min_percent: float | None
    initial_soc_max_percent: float | None
    midday_charge_priority: float | None
    bev_duty_bias: float | None
    ice_backup_bias: float | None
    grid_risk_penalty_multiplier: float | None
    pv_marginal_charge_cost_yen_per_kwh: float


OPERATION_PROFILES = {
    "aggressive": WeatherOperationProfile(
        operation_mode="aggressive",
        final_soc_floor_percent=None,
        final_soc_target_percent=None,
        final_soc_target_tolerance_percent=None,
        initial_soc_mode="unchanged",
        initial_soc_min_percent=None,
        initial_soc_max_percent=None,
        midday_charge_priority=None,
        bev_duty_bias=None,
        ice_backup_bias=None,
        grid_risk_penalty_multiplier=None,
        pv_marginal_charge_cost_yen_per_kwh=0.0,
    ),
    "normal": WeatherOperationProfile(
        operation_mode="normal",
        final_soc_floor_percent=None,
        final_soc_target_percent=None,
        final_soc_target_tolerance_percent=None,
        initial_soc_mode="unchanged",
        initial_soc_min_percent=None,
        initial_soc_max_percent=None,
        midday_charge_priority=None,
        bev_duty_bias=None,
        ice_backup_bias=None,
        grid_risk_penalty_multiplier=None,
        pv_marginal_charge_cost_yen_per_kwh=0.0,
    ),
    "conservative": WeatherOperationProfile(
        operation_mode="conservative",
        final_soc_floor_percent=None,
        final_soc_target_percent=None,
        final_soc_target_tolerance_percent=None,
        initial_soc_mode="unchanged",
        initial_soc_min_percent=None,
        initial_soc_max_percent=None,
        midday_charge_priority=None,
        bev_duty_bias=None,
        ice_backup_bias=None,
        grid_risk_penalty_multiplier=None,
        pv_marginal_charge_cost_yen_per_kwh=0.0,
    ),
}


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return min(max(float(value), lower), upper)


def sun_score_from_weather(
    *,
    sunshine_hours: float | None,
    weather_label: str | None,
) -> float:
    if sunshine_hours is not None:
        return clamp(float(sunshine_hours) / 8.0)
    label = str(weather_label or "")
    if "晴れ時々曇" in label or "晴時々曇" in label:
        return 0.7
    if "曇り時々晴" in label or "曇時々晴" in label:
        return 0.5
    if "曇り時々雨" in label or "曇時々雨" in label:
        return 0.15
    if "大雨" in label or "雨" in label:
        return 0.05
    if "曇" in label:
        return 0.3
    if "晴" in label:
        return 0.9
    return 0.3


def rain_risk_from_weather(
    *,
    precipitation_mm: float | None,
    weather_label: str | None,
) -> float:
    if precipitation_mm is not None:
        return clamp(float(precipitation_mm) / 20.0)
    label = str(weather_label or "")
    if "大雨" in label:
        return 1.0
    if "曇り時々雨" in label or "曇時々雨" in label:
        return 0.55
    if "雨" in label:
        return 0.85
    if "曇" in label:
        return 0.20
    if "晴" in label:
        return 0.05
    return 0.20


def heat_load_score_from_weather(tmax_c: float | None) -> float:
    if tmax_c is None:
        return 0.0
    return clamp((float(tmax_c) - 25.0) / 10.0)


def midday_recovery_expectation(sun_score: float, rain_risk: float) -> str:
    if sun_score >= 0.70 and rain_risk <= 0.20:
        return "high"
    if sun_score >= 0.35 and rain_risk <= 0.50:
        return "medium"
    return "low"


def operation_mode_from_scores(sun_score: float, rain_risk: float) -> str:
    if sun_score >= 0.70 and rain_risk <= 0.20:
        return "aggressive"
    if sun_score < 0.25 or rain_risk >= 0.60:
        return "conservative"
    return "normal"


def build_operation_profile(forecast: WeatherProxyForecast) -> WeatherOperationProfile:
    return OPERATION_PROFILES[forecast.operation_mode]


def weather_operation_profile_to_dict(profile: WeatherOperationProfile) -> Dict[str, Any]:
    return asdict(profile)


def _weather_proxy_metadata(forecast: WeatherProxyForecast) -> Dict[str, Any]:
    raw = weather_proxy_forecast_to_dict(forecast)
    raw["metadata"] = dict(raw.get("metadata") or {})
    return raw


def _parse_hhmm_to_min(value: str | None) -> int:
    try:
        hh_text, mm_text = str(value or "00:00").split(":", 1)
        return (int(hh_text) * 60 + int(mm_text)) % (24 * 60)
    except (TypeError, ValueError):
        return 0


def _slot_capacity_factor(
    representative_cf: tuple[float, ...],
    *,
    representative_slot_minutes: int,
    horizon_start_min: int,
    timestep_min: int,
    slot_index: int,
) -> float:
    if not representative_cf:
        return 0.0
    slot_minutes = max(int(representative_slot_minutes or 60), 1)
    minute_of_day = (int(horizon_start_min) + int(slot_index) * max(int(timestep_min), 1)) % (24 * 60)
    representative_index = (minute_of_day // slot_minutes) % len(representative_cf)
    return clamp(representative_cf[int(representative_index)])


def _align_representative_capacity_factors(
    problem: CanonicalOptimizationProblem,
    representative_cf: tuple[float, ...],
    representative_slot_minutes: int,
) -> tuple[float, ...]:
    slot_count = len(problem.price_slots)
    if slot_count <= 0:
        return ()
    horizon_start_min = int(
        (problem.metadata or {}).get("horizon_start_min")
        or _parse_hhmm_to_min(problem.scenario.horizon_start)
    )
    timestep_min = max(int(problem.scenario.timestep_min or 60), 1)
    return tuple(
        _slot_capacity_factor(
            representative_cf,
            representative_slot_minutes=representative_slot_minutes,
            horizon_start_min=horizon_start_min,
            timestep_min=timestep_min,
            slot_index=slot_idx,
        )
        for slot_idx in range(slot_count)
    )


def _apply_pv_proxy_curve_to_problem(
    problem: CanonicalOptimizationProblem,
    forecast: WeatherProxyForecast,
    metadata: Dict[str, Any],
) -> CanonicalOptimizationProblem:
    if forecast.forecast_type not in {
        FORECAST_TYPE_SOLCAST_PV_PROXY_V1,
        FORECAST_TYPE_SOLCAST_TYPICAL_PV_PROXY_V1,
    }:
        return problem
    forecast_meta = dict(forecast.metadata or {})
    raw_cf = forecast_meta.get("capacity_factor_by_slot")
    if not isinstance(raw_cf, (list, tuple)) or not raw_cf:
        metadata["weather_pv_forecast_applied"] = False
        metadata["weather_pv_forecast_skip_reason"] = "missing_capacity_factor_by_slot"
        return problem
    representative_cf = tuple(clamp(value) for value in raw_cf)
    representative_slot_minutes = int(forecast_meta.get("slot_minutes") or 60)
    aligned_cf = _align_representative_capacity_factors(
        problem,
        representative_cf,
        representative_slot_minutes,
    )
    if not aligned_cf:
        metadata["weather_pv_forecast_applied"] = False
        metadata["weather_pv_forecast_skip_reason"] = "empty_problem_price_slots"
        return problem

    timestep_h = max(int(problem.scenario.timestep_min or 60), 1) / 60.0
    updated_assets: Dict[str, DepotEnergyAsset] = {}
    aggregate_kwh_by_slot = [0.0 for _ in aligned_cf]
    applied_depots: list[str] = []
    for depot_id, asset in (problem.depot_energy_assets or {}).items():
        if not getattr(asset, "pv_enabled", False) or float(asset.pv_capacity_kw or 0.0) <= 0.0:
            updated_assets[str(depot_id)] = asset
            continue
        generation = tuple(
            round(max(float(asset.pv_capacity_kw or 0.0), 0.0) * cf * timestep_h, 6)
            for cf in aligned_cf
        )
        for idx, value in enumerate(generation):
            aggregate_kwh_by_slot[idx] += value
        applied_depots.append(str(depot_id))
        updated_assets[str(depot_id)] = replace(
            asset,
            pv_generation_kwh_by_slot=generation,
            capacity_factor_by_slot=aligned_cf,
            pv_case_id=(
                f"solcast_pv_proxy_{forecast_meta.get('typical_weather_class', forecast_meta.get('weather_label', 'unknown'))}"
                if forecast.forecast_type == FORECAST_TYPE_SOLCAST_TYPICAL_PV_PROXY_V1
                else f"solcast_pv_proxy_{forecast.service_date}"
            ),
        )

    if not applied_depots:
        metadata["weather_pv_forecast_applied"] = False
        metadata["weather_pv_forecast_skip_reason"] = "no_pv_enabled_depot_with_capacity"
        return problem

    updated_pv_slots = tuple(
        PVSlot(slot_index=idx, pv_available_kw=round(kwh / timestep_h, 6))
        for idx, kwh in enumerate(aggregate_kwh_by_slot)
    )
    metadata["weather_pv_forecast_applied"] = True
    metadata["weather_pv_representative_curve"] = {
        "version": forecast_meta.get("representative_curve_version"),
        "forecast_type": forecast.forecast_type,
        "typical_weather_class": forecast_meta.get("typical_weather_class"),
        "requested_weather_class": forecast_meta.get("requested_weather_class"),
        "weather_class_selection_reason": forecast_meta.get("weather_class_selection_reason"),
        "source_dates": list(forecast_meta.get("source_dates") or ()),
        "source_profile_count": int(forecast_meta.get("source_profile_count") or 0),
        "classification": dict(forecast_meta.get("classification") or {}),
        "representative_slot_minutes": representative_slot_minutes,
        "problem_timestep_min": int(problem.scenario.timestep_min),
        "problem_horizon_start": str(problem.scenario.horizon_start or "00:00"),
        "applied_depot_ids": tuple(sorted(applied_depots)),
        "capacity_factor_by_representative_slot": representative_cf,
        "capacity_factor_by_problem_slot": aligned_cf,
        "pv_curve_shape_source": "solcast_capacity_factor_shape_only",
        "pv_capacity_scale_policy": "existing_depot_area_m2_times_usable_area_ratio_times_panel_power_density",
    }
    return replace(
        problem,
        depot_energy_assets=updated_assets,
        pv_slots=updated_pv_slots,
    )


def apply_weather_policy_to_problem(
    problem: CanonicalOptimizationProblem,
    forecast: WeatherProxyForecast,
    profile: WeatherOperationProfile,
    *,
    random_seed: int,
) -> CanonicalOptimizationProblem:
    if not forecast.no_future_leakage:
        raise ValueError("WEATHER_PROXY_FUTURE_LEAKAGE: no_future_leakage must be true")
    if forecast.analog_date >= forecast.service_date:
        raise ValueError(
            "WEATHER_PROXY_FUTURE_LEAKAGE: analog_date/forecast_issue_date must be before service_date"
        )
    original_vehicles = tuple(problem.vehicles or ())
    updated_vehicles = original_vehicles
    initial_soc_policy = {
        "mode": profile.initial_soc_mode,
        "seed": int(random_seed),
        "vehicle_initial_soc_ratio": {},
        "initial_soc_randomized": False,
    }
    metadata = dict(problem.metadata or {})
    profile_payload = weather_operation_profile_to_dict(profile)
    pv_marginal_charge_cost_yen_per_kwh = float(
        metadata.get(
            "pv_marginal_charge_cost_yen_per_kwh",
            profile.pv_marginal_charge_cost_yen_per_kwh,
        )
        or 0.0
    )
    metadata.update(
        {
            "weather_proxy": _weather_proxy_metadata(forecast),
            "weather_operation_profile": profile_payload,
            "weather_initial_soc_policy": initial_soc_policy,
            "pv_marginal_charge_cost_yen_per_kwh": pv_marginal_charge_cost_yen_per_kwh,
            "pv_marginal_charge_cost_policy": PV_MARGINAL_COST_POLICY,
        }
    )
    pv_adjusted_problem = _apply_pv_proxy_curve_to_problem(problem, forecast, metadata)
    return replace(pv_adjusted_problem, vehicles=updated_vehicles, metadata=metadata)
