from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException

from src.preprocess.weather.daily_weather_schema import (
    WeatherProxyForecast,
    WeatherSchemaError,
)
from src.preprocess.weather.operation_policy import (
    WeatherOperationProfile,
    build_operation_profile,
)
from src.preprocess.weather.weather_proxy_builder import load_weather_proxy_forecast_json


def configured_service_date(scenario: Dict[str, Any]) -> Optional[str]:
    sim = dict(scenario.get("simulation_config") or {})
    primary = str(sim.get("service_date") or "").strip()
    if primary:
        return primary[:10]
    dates = [str(v).strip() for v in list(sim.get("service_dates") or []) if str(v).strip()]
    if dates:
        return dates[0][:10]
    prepared = dict(scenario.get("prepared_scope_summary") or {})
    prepared_date = str(prepared.get("service_date") or "").strip()
    return prepared_date[:10] if prepared_date else None


def weather_proxy_http_error(
    status_code: int,
    code: str,
    message: str,
    **extra: Any,
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, **extra},
    )


def resolve_weather_proxy_path(raw_path: str) -> Path:
    text = str(raw_path or "").strip()
    if not text:
        raise FileNotFoundError("weather proxy forecast path is empty")
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate


def load_weather_proxy_for_bff(raw_path: str) -> WeatherProxyForecast:
    forecast_path = resolve_weather_proxy_path(raw_path)
    if not forecast_path.exists():
        raise FileNotFoundError(str(forecast_path))
    try:
        return load_weather_proxy_forecast_json(forecast_path)
    except WeatherSchemaError:
        raise
    except Exception as exc:
        raise WeatherSchemaError(str(exc)) from exc


def weather_policy_requested(
    scenario: Dict[str, Any],
    enable_weather_operation_policy: Optional[bool],
    weather_proxy_forecast_path: Optional[str],
) -> tuple[bool, Optional[str]]:
    sim_cfg = dict(scenario.get("simulation_config") or {})
    enabled_raw = (
        enable_weather_operation_policy
        if enable_weather_operation_policy is not None
        else sim_cfg.get("enable_weather_operation_policy", sim_cfg.get("enableWeatherOperationPolicy"))
    )
    path_raw = (
        weather_proxy_forecast_path
        or sim_cfg.get("weather_proxy_forecast_path")
        or sim_cfg.get("weatherProxyForecastPath")
    )
    return bool(enabled_raw), (str(path_raw).strip() if path_raw else None)


def preflight_weather_proxy_request(
    *,
    scenario: Dict[str, Any],
    enable_weather_operation_policy: Optional[bool] = None,
    weather_proxy_forecast_path: Optional[str] = None,
) -> None:
    enabled, effective_path = weather_policy_requested(
        scenario,
        enable_weather_operation_policy,
        weather_proxy_forecast_path,
    )
    if not enabled:
        return
    if enabled and not effective_path:
        raise weather_proxy_http_error(
            400,
            "WEATHER_PROXY_NOT_FOUND",
            "enableWeatherOperationPolicy is true but weatherProxyForecastPath is not set.",
        )
    if not effective_path:
        return
    try:
        forecast = load_weather_proxy_for_bff(effective_path)
    except FileNotFoundError as exc:
        raise weather_proxy_http_error(
            400,
            "WEATHER_PROXY_NOT_FOUND",
            f"Weather proxy forecast JSON was not found: {exc}",
        ) from exc
    except WeatherSchemaError as exc:
        raise weather_proxy_http_error(
            400,
            "WEATHER_PROXY_SCHEMA_INVALID",
            f"Weather proxy forecast JSON is invalid: {exc}",
        ) from exc
    configured_date = configured_service_date(scenario)
    if configured_date and configured_date != forecast.service_date:
        raise weather_proxy_http_error(
            409,
            "WEATHER_PROXY_SERVICE_DATE_MISMATCH",
            "Weather proxy service_date does not match scenario service_date.",
            scenario_service_date=configured_date,
            forecast_service_date=forecast.service_date,
        )
    if forecast.analog_date >= forecast.service_date or not forecast.no_future_leakage:
        raise weather_proxy_http_error(
            409,
            "WEATHER_PROXY_FUTURE_LEAKAGE",
            "Weather proxy analog_date/forecast_issue_date must be earlier than service_date.",
            service_date=forecast.service_date,
            analog_date=forecast.analog_date,
        )


def prepare_weather_policy_for_scenario(
    scenario: Dict[str, Any],
    *,
    enable_weather_operation_policy: Optional[bool],
    weather_proxy_forecast_path: Optional[str],
) -> tuple[Dict[str, Any], Optional[WeatherProxyForecast], Optional[WeatherOperationProfile]]:
    enabled, path_raw = weather_policy_requested(
        scenario,
        enable_weather_operation_policy,
        weather_proxy_forecast_path,
    )
    if not enabled:
        return scenario, None, None
    if not path_raw:
        raise ValueError(
            "WEATHER_PROXY_NOT_FOUND: enableWeatherOperationPolicy is true but forecast path is not set"
        )
    try:
        forecast = load_weather_proxy_for_bff(path_raw)
    except FileNotFoundError as exc:
        raise ValueError(f"WEATHER_PROXY_NOT_FOUND: {exc}") from exc
    except WeatherSchemaError as exc:
        raise ValueError(f"WEATHER_PROXY_SCHEMA_INVALID: {exc}") from exc
    configured_date = configured_service_date(scenario)
    if configured_date and configured_date != forecast.service_date:
        raise ValueError(
            "WEATHER_PROXY_SERVICE_DATE_MISMATCH: "
            f"scenario={configured_date} forecast={forecast.service_date}"
        )
    if forecast.analog_date >= forecast.service_date or not forecast.no_future_leakage:
        raise ValueError(
            "WEATHER_PROXY_FUTURE_LEAKAGE: analog_date/forecast_issue_date must be before service_date"
        )
    profile = build_operation_profile(forecast)
    updated = dict(scenario)
    sim_cfg = dict(updated.get("simulation_config") or {})
    sim_cfg.update(
        {
            "enable_weather_operation_policy": True,
            "weather_proxy_forecast_path": path_raw,
            "weather_operation_mode": profile.operation_mode,
        }
    )
    updated["simulation_config"] = sim_cfg
    return updated, forecast, profile


def weather_policy_payload_from_problem_metadata(
    metadata: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    forecast = dict(metadata.get("weather_proxy") or {})
    if not forecast:
        return None
    profile = dict(metadata.get("weather_operation_profile") or {})
    initial_soc_policy = dict(metadata.get("weather_initial_soc_policy") or {})
    pv_curve = dict(metadata.get("weather_pv_representative_curve") or {})
    audit = {
        "enabled": True,
        "forecast_type": forecast.get("forecast_type"),
        "service_date": forecast.get("service_date"),
        "analog_date": forecast.get("analog_date"),
        "no_future_leakage": bool(forecast.get("no_future_leakage")),
        "operation_mode": forecast.get("operation_mode"),
        "initial_soc_randomized": bool(initial_soc_policy.get("initial_soc_randomized")),
        "vehicle_initial_soc_ratio": dict(
            initial_soc_policy.get("vehicle_initial_soc_ratio") or {}
        ),
        "optimizer_metadata_keys": [
            key
            for key in (
                "weather_proxy",
                "weather_operation_profile",
            )
            if key in metadata
        ],
        "pv_marginal_charge_cost_policy": metadata.get("pv_marginal_charge_cost_policy"),
        "weather_pv_forecast_applied": bool(metadata.get("weather_pv_forecast_applied")),
        "weather_pv_forecast_skip_reason": metadata.get("weather_pv_forecast_skip_reason"),
        "typical_weather_class": pv_curve.get("typical_weather_class"),
        "typical_pv_source_dates": list(pv_curve.get("source_dates") or ()),
        "typical_pv_thresholds": dict(
            (pv_curve.get("classification") or {}).get("thresholds") or {}
        ),
    }
    return {
        "enabled": True,
        "forecast": forecast,
        "operation_profile": profile,
        "initial_soc_policy": initial_soc_policy,
        "representative_curve": pv_curve,
        "audit": audit,
    }
