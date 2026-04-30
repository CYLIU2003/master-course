"""Build WeatherProxyForecast JSONs from Solcast representative PV curves."""

from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
from typing import Any, Mapping

from src.preprocess.weather.daily_weather_schema import (
    FORECAST_TYPE_SOLCAST_TYPICAL_PV_PROXY_V1,
    WeatherProxyForecast,
    WeatherSchemaError,
)
from src.preprocess.weather.operation_policy import (
    clamp,
    midday_recovery_expectation,
    operation_mode_from_scores,
)

from .aggregate import representative_curve_for_class
from .classify import WEATHER_CLASSES

SOLCAST_TYPICAL_PROXY_METHOD = "solcast_typical_capacity_factor_curve_v1"
REFERENCE_CLEAR_SKY_CF_HOURS = 6.0


def _parse_date(value: Any, field_name: str) -> str:
    text = str(value or "").strip()[:10]
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise WeatherSchemaError(f"{field_name} must be YYYY-MM-DD: {value!r}") from exc
    return text


def default_forecast_issue_date(service_date: str) -> str:
    service = date.fromisoformat(_parse_date(service_date, "service_date"))
    return (service - timedelta(days=1)).isoformat()


def load_representative_curve_payload(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise WeatherSchemaError("representative curve JSON must be an object")
    if payload.get("version") != "solcast_typical_pv_representative_curve_v1":
        raise WeatherSchemaError("representative curve version is not solcast_typical_pv_representative_curve_v1")
    return payload


def _select_weather_class(payload: Mapping[str, Any], requested: str) -> tuple[str, str]:
    requested_class = str(requested or "auto").strip().lower()
    if requested_class in WEATHER_CLASSES:
        return requested_class, "manual"
    if requested_class != "auto":
        raise WeatherSchemaError("weather_class must be sunny, cloudy, rainy, or auto")
    curves = payload.get("curves") if isinstance(payload, Mapping) else {}
    cloudy = curves.get("cloudy") if isinstance(curves, Mapping) else None
    if isinstance(cloudy, Mapping) and int(cloudy.get("source_profile_count") or 0) > 0:
        return "cloudy", "auto_default_cloudy"
    candidates: list[tuple[int, str]] = []
    if isinstance(curves, Mapping):
        for item_class, curve in curves.items():
            if str(item_class) not in WEATHER_CLASSES or not isinstance(curve, Mapping):
                continue
            candidates.append((int(curve.get("source_profile_count") or 0), str(item_class)))
    if not candidates:
        raise WeatherSchemaError("representative curve payload does not contain usable class curves")
    return sorted(candidates, key=lambda item: (-item[0], item[1]))[0][1], "auto_largest_source_count"


def _label_for_class(weather_class: str) -> str:
    return {
        "sunny": "Solcast代表晴れPV",
        "cloudy": "Solcast代表曇りPV",
        "rainy": "Solcast代表雨PV",
    }[weather_class]


def _curve_source_dates_before_service(curve: Mapping[str, Any], service_date: str) -> bool:
    for raw_date in curve.get("source_dates") or ():
        if _parse_date(raw_date, "source_dates[]") >= service_date:
            return False
    return True


def _classification_audit(payload: Mapping[str, Any]) -> dict[str, Any]:
    classification = payload.get("classification")
    if not isinstance(classification, Mapping):
        return {}
    return {
        "method": classification.get("method"),
        "thresholds": dict(classification.get("thresholds") or {}),
        "excluded_dates": list(classification.get("excluded_dates") or ()),
    }


def build_solcast_typical_proxy_forecast(
    *,
    service_date: str,
    station_id: str,
    station_name: str,
    representative_curve_json_path: str | Path,
    weather_class: str = "auto",
    forecast_issue_date: str | None = None,
) -> WeatherProxyForecast:
    service = _parse_date(service_date, "service_date")
    issue = _parse_date(forecast_issue_date or default_forecast_issue_date(service), "forecast_issue_date")
    if issue >= service:
        raise WeatherSchemaError("forecast_issue_date must be earlier than service_date")
    payload = load_representative_curve_payload(representative_curve_json_path)
    selected_class, selection_reason = _select_weather_class(payload, weather_class)
    curve = representative_curve_for_class(payload, selected_class)
    if int(curve.get("source_profile_count") or 0) <= 0:
        raise WeatherSchemaError(f"No representative source dates for weather_class={selected_class}")
    if not _curve_source_dates_before_service(curve, service):
        raise WeatherSchemaError(
            "representative source_dates must be earlier than service_date to avoid future leakage"
        )

    slot_minutes = int(curve.get("slot_minutes") or 60)
    capacity_factors = [clamp(value) for value in (curve.get("capacity_factor_by_slot") or ())]
    if not capacity_factors:
        raise WeatherSchemaError("selected representative curve has no capacity_factor_by_slot")
    cf_hours = sum(capacity_factors) * max(slot_minutes, 1) / 60.0
    sun_score = clamp(cf_hours / REFERENCE_CLEAR_SKY_CF_HOURS)
    rain_risk = clamp(1.0 - sun_score)
    metadata = {
        "source": "solcast_typical_representative_curve",
        "forecast_issue_date": issue,
        "representative_curve_json_path": str(representative_curve_json_path),
        "typical_weather_class": selected_class,
        "requested_weather_class": str(weather_class or "auto"),
        "weather_class_selection_reason": selection_reason,
        "slot_minutes": slot_minutes,
        "slot_count": len(capacity_factors),
        "capacity_factor_by_slot": [round(value, 6) for value in capacity_factors],
        "capacity_factor_stddev_by_slot": list(curve.get("capacity_factor_stddev_by_slot") or ()),
        "daily_cf_hours": round(cf_hours, 6),
        "source_dates": list(curve.get("source_dates") or ()),
        "source_profile_count": int(curve.get("source_profile_count") or 0),
        "representative_curve_version": payload.get("version"),
        "representative_curve_source": payload.get("source"),
        "representative_curve_source_date_start": payload.get("source_date_start"),
        "representative_curve_source_date_end": payload.get("source_date_end"),
        "classification": _classification_audit(payload),
        "sun_score_basis": "sum(representative_capacity_factor_by_slot * slot_hours) / 6.0",
        "rain_risk_basis": "inverse_typical_pv_recovery_proxy_not_observed_precipitation",
        "no_future_leakage_basis": "forecast_issue_date and selected source_dates are earlier than service_date",
    }
    return WeatherProxyForecast(
        version=FORECAST_TYPE_SOLCAST_TYPICAL_PV_PROXY_V1,
        forecast_type=FORECAST_TYPE_SOLCAST_TYPICAL_PV_PROXY_V1,
        service_date=service,
        station_id=str(station_id),
        station_name=str(station_name),
        analog_date=issue,
        analog_selection_score=0.0,
        analog_selection_method=SOLCAST_TYPICAL_PROXY_METHOD,
        weather_label=_label_for_class(selected_class),
        tmax_c=None,
        tmin_c=None,
        mean_temp_c=None,
        sunshine_hours=round(sun_score * 8.0, 3),
        precipitation_mm=None,
        sun_score=sun_score,
        rain_risk=rain_risk,
        heat_load_score=0.0,
        midday_recovery_expectation=midday_recovery_expectation(sun_score, rain_risk),
        operation_mode=operation_mode_from_scores(sun_score, rain_risk),
        no_future_leakage=True,
        metadata=metadata,
    )
