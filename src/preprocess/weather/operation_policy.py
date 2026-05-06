"""Convert weather proxy forecasts into optimization-readable policy metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import hashlib
import random
from typing import Any, Dict, Mapping, Tuple

from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    DepotEnergyAsset,
    PVSlot,
    ProblemVehicle,
)
from src.optimization.common.weather_strategy import (
    DEFAULT_WEATHER_STRATEGY_BIAS_BASE_JPY_PER_TRIP,
)

from .daily_weather_schema import (
    FORECAST_TYPE_SOLCAST_TYPICAL_PV_PROXY_V1,
    WeatherProxyForecast,
    weather_proxy_forecast_to_dict,
)

ELECTRIC_POWERTRAINS = {"BEV", "PHEV", "FCEV"}
PV_MARGINAL_COST_POLICY = (
    "pv_to_bus_and_pv_to_bess_marginal_cost_zero_assets_reported_separately"
)


@dataclass(frozen=True)
class WeatherOperationProfile:
    operation_mode: str
    final_soc_floor_percent: float
    final_soc_target_percent: float
    initial_soc_mode: str
    initial_soc_min_percent: float
    initial_soc_max_percent: float
    midday_charge_priority: float
    bev_duty_bias: float
    ice_backup_bias: float
    grid_risk_penalty_multiplier: float
    pv_marginal_charge_cost_yen_per_kwh: float


OPERATION_PROFILES = {
    "aggressive": WeatherOperationProfile(
        operation_mode="aggressive",
        final_soc_floor_percent=20.0,
        final_soc_target_percent=35.0,
        initial_soc_mode="random_uniform",
        initial_soc_min_percent=55.0,
        initial_soc_max_percent=95.0,
        midday_charge_priority=1.20,
        bev_duty_bias=1.15,
        ice_backup_bias=0.90,
        grid_risk_penalty_multiplier=1.00,
        pv_marginal_charge_cost_yen_per_kwh=0.0,
    ),
    "normal": WeatherOperationProfile(
        operation_mode="normal",
        final_soc_floor_percent=30.0,
        final_soc_target_percent=45.0,
        initial_soc_mode="random_uniform",
        initial_soc_min_percent=60.0,
        initial_soc_max_percent=90.0,
        midday_charge_priority=1.00,
        bev_duty_bias=1.00,
        ice_backup_bias=1.00,
        grid_risk_penalty_multiplier=1.00,
        pv_marginal_charge_cost_yen_per_kwh=0.0,
    ),
    "conservative": WeatherOperationProfile(
        operation_mode="conservative",
        final_soc_floor_percent=45.0,
        final_soc_target_percent=60.0,
        initial_soc_mode="random_uniform",
        initial_soc_min_percent=65.0,
        initial_soc_max_percent=90.0,
        midday_charge_priority=0.90,
        bev_duty_bias=0.85,
        ice_backup_bias=1.20,
        grid_risk_penalty_multiplier=1.25,
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


def _deterministic_ratio(
    *,
    scenario_id: str,
    service_date: str,
    vehicle_id: str,
    random_seed: int,
    min_percent: float,
    max_percent: float,
) -> float:
    key = f"{scenario_id}|{service_date}|{vehicle_id}|{int(random_seed)}".encode("utf-8")
    seed_int = int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
    rng = random.Random(seed_int)
    lower = min(float(min_percent), float(max_percent))
    upper = max(float(min_percent), float(max_percent))
    return round(rng.uniform(lower, upper) / 100.0, 6)


def _is_electric_vehicle(vehicle: ProblemVehicle) -> bool:
    return str(vehicle.vehicle_type or "").strip().upper() in ELECTRIC_POWERTRAINS


def apply_initial_soc_policy(
    vehicles: tuple[ProblemVehicle, ...],
    profile: WeatherOperationProfile,
    *,
    scenario_id: str,
    service_date: str,
    random_seed: int,
    force: bool = False,
) -> tuple[ProblemVehicle, ...]:
    if profile.initial_soc_mode != "random_uniform":
        return tuple(vehicles)
    updated: list[ProblemVehicle] = []
    for vehicle in vehicles:
        if not _is_electric_vehicle(vehicle):
            updated.append(vehicle)
            continue
        if vehicle.initial_soc is not None and not force:
            updated.append(vehicle)
            continue
        ratio = _deterministic_ratio(
            scenario_id=scenario_id,
            service_date=service_date,
            vehicle_id=vehicle.vehicle_id,
            random_seed=random_seed,
            min_percent=profile.initial_soc_min_percent,
            max_percent=profile.initial_soc_max_percent,
        )
        updated.append(replace(vehicle, initial_soc=ratio))
    return tuple(updated)


def _initial_soc_policy_metadata(
    *,
    original_vehicles: tuple[ProblemVehicle, ...],
    updated_vehicles: tuple[ProblemVehicle, ...],
    profile: WeatherOperationProfile,
    random_seed: int,
) -> Dict[str, Any]:
    ratios: Dict[str, float] = {}
    original_by_id = {vehicle.vehicle_id: vehicle for vehicle in original_vehicles}
    for vehicle in updated_vehicles:
        original = original_by_id.get(vehicle.vehicle_id)
        if original is None:
            continue
        if original.initial_soc != vehicle.initial_soc and vehicle.initial_soc is not None:
            ratios[str(vehicle.vehicle_id)] = float(vehicle.initial_soc)
    return {
        "mode": profile.initial_soc_mode,
        "seed": int(random_seed),
        "min_percent": float(profile.initial_soc_min_percent),
        "max_percent": float(profile.initial_soc_max_percent),
        "vehicle_initial_soc_ratio": ratios,
        "initial_soc_randomized": bool(ratios),
    }


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


def _apply_typical_pv_curve_to_problem(
    problem: CanonicalOptimizationProblem,
    forecast: WeatherProxyForecast,
    metadata: Dict[str, Any],
) -> CanonicalOptimizationProblem:
    if forecast.forecast_type != FORECAST_TYPE_SOLCAST_TYPICAL_PV_PROXY_V1:
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
                f"solcast_typical_{forecast_meta.get('typical_weather_class') or 'unknown'}"
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
    updated_vehicles = apply_initial_soc_policy(
        original_vehicles,
        profile,
        scenario_id=problem.scenario.scenario_id,
        service_date=forecast.service_date,
        random_seed=random_seed,
    )
    initial_soc_policy = _initial_soc_policy_metadata(
        original_vehicles=original_vehicles,
        updated_vehicles=updated_vehicles,
        profile=profile,
        random_seed=random_seed,
    )
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
            "final_soc_floor_percent": float(profile.final_soc_floor_percent),
            "final_soc_target_percent": float(profile.final_soc_target_percent),
            "midday_charge_priority": float(profile.midday_charge_priority),
            "bev_duty_bias": float(profile.bev_duty_bias),
            "ice_backup_bias": float(profile.ice_backup_bias),
            "grid_risk_penalty_multiplier": float(profile.grid_risk_penalty_multiplier),
            "weather_strategy_bias_base_jpy_per_trip": (
                DEFAULT_WEATHER_STRATEGY_BIAS_BASE_JPY_PER_TRIP
            ),
            "pv_marginal_charge_cost_yen_per_kwh": pv_marginal_charge_cost_yen_per_kwh,
            "pv_marginal_charge_cost_policy": PV_MARGINAL_COST_POLICY,
        }
    )
    pv_adjusted_problem = _apply_typical_pv_curve_to_problem(problem, forecast, metadata)
    return replace(pv_adjusted_problem, vehicles=updated_vehicles, metadata=metadata)
