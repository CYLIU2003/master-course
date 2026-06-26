"""Build optimization weather-policy forecasts from Solcast PV profiles."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

from .daily_weather_schema import (
    FORECAST_TYPE_SOLCAST_PV_PROXY_V1,
    WeatherProxyForecast,
    WeatherSchemaError,
)
from .operation_policy import (
    clamp,
    midday_recovery_expectation,
    operation_mode_from_scores,
)

SOLCAST_PV_PROXY_METHOD = "solcast_pv_capacity_factor_proxy_v1"
_REFERENCE_CLEAR_SKY_CF_HOURS = 6.0


def _parse_date(value: str, field_name: str) -> str:
    text = str(value or "").strip()[:10]
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise WeatherSchemaError(f"{field_name} must be YYYY-MM-DD: {value!r}") from exc
    return text


def default_forecast_issue_date(service_date: str) -> str:
    service = date.fromisoformat(_parse_date(service_date, "service_date"))
    return (service - timedelta(days=1)).isoformat()


def _coerce_float_series(values: Iterable[Any], field_name: str) -> list[float]:
    series: list[float] = []
    for idx, value in enumerate(values):
        try:
            series.append(max(0.0, float(value)))
        except (TypeError, ValueError) as exc:
            raise WeatherSchemaError(f"{field_name}[{idx}] must be numeric") from exc
    if not series:
        raise WeatherSchemaError(f"{field_name} must not be empty")
    return series


def _capacity_factors_from_generation(raw: Mapping[str, Any]) -> list[float]:
    generation = _coerce_float_series(
        raw.get("pv_generation_kwh_by_slot") or (),
        "pv_generation_kwh_by_slot",
    )
    try:
        capacity_kw = float(raw.get("capacity_kw"))
        slot_minutes = float(raw.get("slot_minutes"))
    except (TypeError, ValueError) as exc:
        raise WeatherSchemaError(
            "capacity_factor_by_slot missing; capacity_kw and slot_minutes are required"
        ) from exc
    if capacity_kw <= 0.0 or slot_minutes <= 0.0:
        raise WeatherSchemaError("capacity_kw and slot_minutes must be positive")
    slot_hours = slot_minutes / 60.0
    return [clamp(kwh / (capacity_kw * slot_hours)) for kwh in generation]


def load_solcast_pv_profile_json(path: str | Path) -> dict[str, Any]:
    profile_path = Path(path)
    raw = json.loads(profile_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise WeatherSchemaError("Solcast PV profile JSON must be an object")
    return raw


def _capacity_factor_series(raw: Mapping[str, Any]) -> list[float]:
    values = raw.get("capacity_factor_by_slot")
    if values:
        return [clamp(value) for value in _coerce_float_series(values, "capacity_factor_by_slot")]
    return _capacity_factors_from_generation(raw)


def _slot_minutes(raw: Mapping[str, Any], series_len: int) -> int:
    value = raw.get("slot_minutes")
    if value not in (None, ""):
        try:
            minutes = int(value)
        except (TypeError, ValueError) as exc:
            raise WeatherSchemaError(f"slot_minutes must be integer: {value!r}") from exc
        if minutes <= 0:
            raise WeatherSchemaError("slot_minutes must be positive")
        return minutes
    if series_len > 0 and 1440 % series_len == 0:
        return 1440 // series_len
    raise WeatherSchemaError("slot_minutes is required when slot count does not divide 24h")


def _weather_label_from_sun_score(sun_score: float) -> str:
    if sun_score >= 0.70:
        return "PV発電見込み高"
    if sun_score >= 0.35:
        return "PV発電見込み中"
    return "PV発電見込み低"


def _build_metadata(
    *,
    raw: Mapping[str, Any],
    pv_profile_json_path: str | Path,
    capacity_factors: list[float],
    slot_minutes: int,
    cf_hours: float,
    sun_score: float,
    rain_risk: float,
    forecast_issue_date: str,
) -> dict[str, Any]:
    nonzero = [value for value in capacity_factors if value > 0.001]
    return {
        "source": "solcast_pv_profile",
        "analog_selection_method": SOLCAST_PV_PROXY_METHOD,
        "forecast_issue_date": forecast_issue_date,
        "pv_profile_json_path": str(pv_profile_json_path),
        "depot_id": raw.get("depot_id"),
        "pv_profile_date": raw.get("date"),
        "source_csv": raw.get("source_csv"),
        "slot_minutes": slot_minutes,
        "slot_count": len(capacity_factors),
        "capacity_factor_by_slot": [round(v, 6) for v in capacity_factors],
        "capacity_factor_sum_hours": round(cf_hours, 6),
        "capacity_factor_avg_all_day": round(sum(capacity_factors) / len(capacity_factors), 6),
        "capacity_factor_peak": round(max(capacity_factors), 6),
        "capacity_factor_nonzero_slots": len(nonzero),
        "sun_score_basis": "sum(capacity_factor_by_slot * slot_hours) / 6.0",
        "rain_risk_basis": "inverse_pv_recovery_proxy_not_observed_precipitation",
        "rain_risk_source": "inferred_from_low_pv_recovery",
        "no_future_leakage_basis": "forecast_issue_date < service_date",
        "solcast_profile_metadata": dict(raw.get("metadata") or {}),
        "sun_score": round(sun_score, 6),
        "rain_risk": round(rain_risk, 6),
    }


def build_solcast_pv_proxy_forecast(
    *,
    service_date: str,
    station_id: str,
    station_name: str,
    pv_profile_json_path: str | Path,
    forecast_issue_date: str | None = None,
) -> WeatherProxyForecast:
    """Convert a local Solcast-derived PV profile into a weather-policy forecast.

    The profile may target ``service_date``. To avoid future leakage, callers must
    provide an issue date earlier than the service date. The existing
    ``analog_date`` field is reused as that issue date for BFF compatibility.
    """

    service = _parse_date(service_date, "service_date")
    issue = _parse_date(forecast_issue_date or default_forecast_issue_date(service), "forecast_issue_date")
    if issue >= service:
        raise WeatherSchemaError("forecast_issue_date must be earlier than service_date")

    raw = load_solcast_pv_profile_json(pv_profile_json_path)
    profile_date = _parse_date(raw.get("date"), "pv_profile.date")
    if profile_date != service:
        raise WeatherSchemaError(
            f"PV profile date mismatch: service_date={service} profile_date={profile_date}"
        )

    capacity_factors = _capacity_factor_series(raw)
    slot_minutes = _slot_minutes(raw, len(capacity_factors))
    slot_hours = slot_minutes / 60.0
    cf_hours = sum(capacity_factors) * slot_hours
    sun_score = clamp(cf_hours / _REFERENCE_CLEAR_SKY_CF_HOURS)
    rain_risk = clamp(1.0 - sun_score)
    weather_label = _weather_label_from_sun_score(sun_score)
    metadata = _build_metadata(
        raw=raw,
        pv_profile_json_path=pv_profile_json_path,
        capacity_factors=capacity_factors,
        slot_minutes=slot_minutes,
        cf_hours=cf_hours,
        sun_score=sun_score,
        rain_risk=rain_risk,
        forecast_issue_date=issue,
    )
    sunshine_hours_proxy = round(sun_score * 8.0, 3)

    return WeatherProxyForecast(
        version=FORECAST_TYPE_SOLCAST_PV_PROXY_V1,
        forecast_type=FORECAST_TYPE_SOLCAST_PV_PROXY_V1,
        service_date=service,
        station_id=station_id,
        station_name=station_name,
        analog_date=issue,
        analog_selection_score=0.0,
        analog_selection_method=SOLCAST_PV_PROXY_METHOD,
        weather_label=weather_label,
        tmax_c=None,
        tmin_c=None,
        mean_temp_c=None,
        sunshine_hours=sunshine_hours_proxy,
        precipitation_mm=None,
        sun_score=sun_score,
        rain_risk=rain_risk,
        heat_load_score=0.0,
        midday_recovery_expectation=midday_recovery_expectation(sun_score, rain_risk),
        operation_mode=operation_mode_from_scores(sun_score, rain_risk),
        no_future_leakage=True,
        metadata=metadata,
    )
