"""Dataclasses and validation helpers for daily weather proxy inputs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Dict, Mapping, Optional

FORECAST_TYPE_HISTORICAL_ANALOG_V1 = "historical_analog_v1"
QUALITY_FLAGS = {"ok", "missing", "estimated", "partial"}
OPERATION_MODES = {"aggressive", "normal", "conservative"}


class WeatherSchemaError(ValueError):
    """Raised when weather proxy data violates the local schema contract."""


def _require_date(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    try:
        date.fromisoformat(text[:10])
    except ValueError as exc:
        raise WeatherSchemaError(f"{field_name} must be YYYY-MM-DD: {value!r}") from exc
    return text[:10]


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise WeatherSchemaError(f"Expected numeric value or null, got {value!r}") from exc


def _required_str(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise WeatherSchemaError(f"{field_name} is required")
    return text


@dataclass(frozen=True)
class DailyWeatherObservation:
    date: str
    station_id: str
    station_name: str
    source: str
    weather_label: Optional[str]
    tmax_c: Optional[float]
    tmin_c: Optional[float]
    mean_temp_c: Optional[float]
    sunshine_hours: Optional[float]
    precipitation_mm: Optional[float]
    quality_flag: str = "ok"
    daylight_note: Optional[str] = None
    raw_url: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "date", _require_date(self.date, "date"))
        object.__setattr__(self, "station_id", _required_str(self.station_id, "station_id"))
        object.__setattr__(self, "station_name", _required_str(self.station_name, "station_name"))
        object.__setattr__(self, "source", _required_str(self.source, "source"))
        flag = str(self.quality_flag or "ok").strip().lower()
        if flag not in QUALITY_FLAGS:
            raise WeatherSchemaError(f"quality_flag must be one of {sorted(QUALITY_FLAGS)}")
        object.__setattr__(self, "quality_flag", flag)


@dataclass(frozen=True)
class WeatherProxyForecast:
    version: str
    forecast_type: str
    service_date: str
    station_id: str
    station_name: str
    analog_date: str
    analog_selection_score: float
    analog_selection_method: str
    weather_label: Optional[str]
    tmax_c: Optional[float]
    tmin_c: Optional[float]
    mean_temp_c: Optional[float]
    sunshine_hours: Optional[float]
    precipitation_mm: Optional[float]
    sun_score: float
    rain_risk: float
    heat_load_score: float
    midday_recovery_expectation: str
    operation_mode: str
    no_future_leakage: bool
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        service_date = _require_date(self.service_date, "service_date")
        analog_date = _require_date(self.analog_date, "analog_date")
        object.__setattr__(self, "service_date", service_date)
        object.__setattr__(self, "analog_date", analog_date)
        object.__setattr__(self, "station_id", _required_str(self.station_id, "station_id"))
        object.__setattr__(self, "station_name", _required_str(self.station_name, "station_name"))
        object.__setattr__(self, "version", _required_str(self.version, "version"))
        if self.forecast_type != FORECAST_TYPE_HISTORICAL_ANALOG_V1:
            raise WeatherSchemaError(
                f"forecast_type must be {FORECAST_TYPE_HISTORICAL_ANALOG_V1!r}"
            )
        if analog_date >= service_date:
            raise WeatherSchemaError("analog_date must be earlier than service_date")
        if self.operation_mode not in OPERATION_MODES:
            raise WeatherSchemaError(f"operation_mode must be one of {sorted(OPERATION_MODES)}")
        if self.midday_recovery_expectation not in {"high", "medium", "low"}:
            raise WeatherSchemaError("midday_recovery_expectation must be high, medium, or low")
        for field_name in ("sun_score", "rain_risk", "heat_load_score"):
            value = float(getattr(self, field_name))
            if not 0.0 <= value <= 1.0:
                raise WeatherSchemaError(f"{field_name} must be in [0, 1]")
            object.__setattr__(self, field_name, value)
        object.__setattr__(self, "analog_selection_score", float(self.analog_selection_score))
        object.__setattr__(self, "no_future_leakage", bool(self.no_future_leakage))


def daily_observation_to_dict(observation: DailyWeatherObservation) -> Dict[str, Any]:
    return asdict(observation)


def daily_observation_from_dict(raw: Mapping[str, Any]) -> DailyWeatherObservation:
    return DailyWeatherObservation(
        date=_require_date(raw.get("date"), "date"),
        station_id=_required_str(raw.get("station_id"), "station_id"),
        station_name=_required_str(raw.get("station_name"), "station_name"),
        source=_required_str(raw.get("source"), "source"),
        weather_label=str(raw.get("weather_label") or "").strip() or None,
        tmax_c=_optional_float(raw.get("tmax_c")),
        tmin_c=_optional_float(raw.get("tmin_c")),
        mean_temp_c=_optional_float(raw.get("mean_temp_c")),
        sunshine_hours=_optional_float(raw.get("sunshine_hours")),
        precipitation_mm=_optional_float(raw.get("precipitation_mm")),
        quality_flag=str(raw.get("quality_flag") or "ok"),
        daylight_note=str(raw.get("daylight_note") or "").strip() or None,
        raw_url=str(raw.get("raw_url") or "").strip() or None,
        created_at=str(raw.get("created_at") or "").strip() or None,
        updated_at=str(raw.get("updated_at") or "").strip() or None,
    )


def weather_proxy_forecast_to_dict(forecast: WeatherProxyForecast) -> Dict[str, Any]:
    return asdict(forecast)


def weather_proxy_forecast_from_dict(raw: Mapping[str, Any]) -> WeatherProxyForecast:
    return WeatherProxyForecast(
        version=_required_str(raw.get("version"), "version"),
        forecast_type=_required_str(raw.get("forecast_type"), "forecast_type"),
        service_date=_require_date(raw.get("service_date"), "service_date"),
        station_id=_required_str(raw.get("station_id"), "station_id"),
        station_name=_required_str(raw.get("station_name"), "station_name"),
        analog_date=_require_date(raw.get("analog_date"), "analog_date"),
        analog_selection_score=float(raw.get("analog_selection_score")),
        analog_selection_method=_required_str(
            raw.get("analog_selection_method"), "analog_selection_method"
        ),
        weather_label=str(raw.get("weather_label") or "").strip() or None,
        tmax_c=_optional_float(raw.get("tmax_c")),
        tmin_c=_optional_float(raw.get("tmin_c")),
        mean_temp_c=_optional_float(raw.get("mean_temp_c")),
        sunshine_hours=_optional_float(raw.get("sunshine_hours")),
        precipitation_mm=_optional_float(raw.get("precipitation_mm")),
        sun_score=float(raw.get("sun_score")),
        rain_risk=float(raw.get("rain_risk")),
        heat_load_score=float(raw.get("heat_load_score")),
        midday_recovery_expectation=_required_str(
            raw.get("midday_recovery_expectation"), "midday_recovery_expectation"
        ),
        operation_mode=_required_str(raw.get("operation_mode"), "operation_mode"),
        no_future_leakage=bool(raw.get("no_future_leakage")),
        metadata=dict(raw.get("metadata") or {}),
    )
