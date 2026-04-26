import pytest

from src.preprocess.weather.daily_weather_schema import DailyWeatherObservation
from src.preprocess.weather.historical_analog import (
    NoAnalogCandidateError,
    select_historical_analog,
)


def _obs(day: str, *, station_id: str = "44132", tmax=30.0, tmin=22.0, sun=5.0, rain=0.0):
    return DailyWeatherObservation(
        date=day,
        station_id=station_id,
        station_name="東京",
        source="jma",
        weather_label="晴れ",
        tmax_c=tmax,
        tmin_c=tmin,
        mean_temp_c=None,
        sunshine_hours=sun,
        precipitation_mm=rain,
    )


def test_select_historical_analog_uses_previous_day_features_and_no_future_leakage():
    observations = [
        _obs("2024-08-20", tmax=34.0, tmin=26.0, sun=8.0, rain=0.0),
        _obs("2024-08-21", tmax=33.0, tmin=25.0, sun=7.8, rain=0.0),
        _obs("2024-08-22", tmax=32.0, tmin=24.0, sun=7.5, rain=0.0),
        _obs("2025-08-20", tmax=33.1, tmin=25.1, sun=7.7, rain=0.0),
        _obs("2025-08-21", tmax=10.0, tmin=5.0, sun=0.0, rain=50.0),
    ]

    selection = select_historical_analog(
        service_date="2025-08-21",
        station_id="44132",
        observations=observations,
    )

    assert selection.observation.date < "2025-08-21"
    assert selection.observation.date != "2025-08-21"
    assert "prev_tmax_c" in selection.metadata["features_used"]
    assert selection.metadata["no_future_leakage"] is True


def test_select_historical_analog_falls_back_when_previous_day_missing():
    observations = [
        _obs("2024-08-21"),
        _obs("2024-08-22"),
    ]

    selection = select_historical_analog(
        service_date="2025-08-21",
        station_id="44132",
        observations=observations,
    )

    assert selection.metadata["analog_fallback_reason"] == "missing_previous_day_actual"
    assert selection.observation.date < "2025-08-21"


def test_select_historical_analog_raises_when_no_candidate():
    with pytest.raises(NoAnalogCandidateError):
        select_historical_analog(
            service_date="2025-08-21",
            station_id="44132",
            observations=[_obs("2025-08-22")],
        )
