"""Build historical analog weather proxy forecasts from normalized CSV."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, List

from .daily_weather_schema import (
    FORECAST_TYPE_HISTORICAL_ANALOG_V1,
    DailyWeatherObservation,
    WeatherProxyForecast,
    daily_observation_from_dict,
    weather_proxy_forecast_from_dict,
    weather_proxy_forecast_to_dict,
)
from .historical_analog import select_historical_analog
from .jma_daily_csv_loader import load_jma_daily_csv
from .operation_policy import (
    heat_load_score_from_weather,
    midday_recovery_expectation,
    operation_mode_from_scores,
    rain_risk_from_weather,
    sun_score_from_weather,
)


def load_daily_weather_csv(path: str | Path) -> List[DailyWeatherObservation]:
    return load_jma_daily_csv(path)


def _forecast_from_observation(
    *,
    service_date: str,
    station_id: str,
    station_name: str,
    observation: DailyWeatherObservation,
    analog_selection_score: float,
    analog_selection_method: str,
    metadata: dict[str, Any],
) -> WeatherProxyForecast:
    sun_score = sun_score_from_weather(
        sunshine_hours=observation.sunshine_hours,
        weather_label=observation.weather_label,
    )
    rain_risk = rain_risk_from_weather(
        precipitation_mm=observation.precipitation_mm,
        weather_label=observation.weather_label,
    )
    heat_load_score = heat_load_score_from_weather(observation.tmax_c)
    return WeatherProxyForecast(
        version=FORECAST_TYPE_HISTORICAL_ANALOG_V1,
        forecast_type=FORECAST_TYPE_HISTORICAL_ANALOG_V1,
        service_date=service_date,
        station_id=station_id,
        station_name=station_name,
        analog_date=observation.date,
        analog_selection_score=float(analog_selection_score),
        analog_selection_method=analog_selection_method,
        weather_label=observation.weather_label,
        tmax_c=observation.tmax_c,
        tmin_c=observation.tmin_c,
        mean_temp_c=observation.mean_temp_c,
        sunshine_hours=observation.sunshine_hours,
        precipitation_mm=observation.precipitation_mm,
        sun_score=sun_score,
        rain_risk=rain_risk,
        heat_load_score=heat_load_score,
        midday_recovery_expectation=midday_recovery_expectation(sun_score, rain_risk),
        operation_mode=operation_mode_from_scores(sun_score, rain_risk),
        no_future_leakage=True,
        metadata=metadata,
    )


def build_weather_proxy_forecast(
    *,
    service_date: str,
    station_id: str,
    station_name: str,
    daily_weather_csv_path: str,
    random_seed: int = 42,
) -> WeatherProxyForecast:
    observations = load_daily_weather_csv(daily_weather_csv_path)
    selection = select_historical_analog(
        service_date=service_date,
        station_id=station_id,
        observations=observations,
    )
    metadata = dict(selection.metadata)
    metadata.update(
        {
            "daily_weather_csv_path": str(daily_weather_csv_path),
            "random_seed": int(random_seed),
            "source": selection.observation.source,
            "station": {"station_id": station_id, "station_name": station_name},
        }
    )
    return _forecast_from_observation(
        service_date=service_date,
        station_id=station_id,
        station_name=station_name,
        observation=selection.observation,
        analog_selection_score=float(metadata.get("analog_selection_score") or 0.0),
        analog_selection_method=str(
            metadata.get("analog_selection_method") or "calendar_plus_previous_day_weather_v1"
        ),
        metadata={
            **metadata,
            "candidate_count": int(metadata.get("candidate_count") or 0),
            "features_used": list(metadata.get("features_used") or []),
        },
    )


def write_weather_proxy_forecast_json(path: str | Path, forecast: WeatherProxyForecast) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(weather_proxy_forecast_to_dict(forecast), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_weather_proxy_forecast_json(path: str | Path) -> WeatherProxyForecast:
    forecast_path = Path(path)
    raw = json.loads(forecast_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("WEATHER_PROXY_SCHEMA_INVALID: forecast JSON must be an object")
    return weather_proxy_forecast_from_dict(raw)
