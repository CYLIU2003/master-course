import pytest

from src.preprocess.weather.daily_weather_schema import (
    DailyWeatherObservation,
    WeatherProxyForecast,
    WeatherSchemaError,
    weather_proxy_forecast_to_dict,
)


def test_daily_weather_observation_validates_required_fields():
    obs = DailyWeatherObservation(
        date="2025-08-21",
        station_id="44132",
        station_name="東京",
        source="jma",
        weather_label="晴れ",
        tmax_c=34.0,
        tmin_c=26.0,
        mean_temp_c=29.0,
        sunshine_hours=8.1,
        precipitation_mm=0.0,
    )

    assert obs.quality_flag == "ok"


def test_weather_proxy_forecast_rejects_future_leakage():
    with pytest.raises(WeatherSchemaError):
        WeatherProxyForecast(
            version="historical_analog_v1",
            forecast_type="historical_analog_v1",
            service_date="2025-08-21",
            station_id="44132",
            station_name="東京",
            analog_date="2025-08-21",
            analog_selection_score=0.1,
            analog_selection_method="calendar_plus_previous_day_weather_v1",
            weather_label="晴れ",
            tmax_c=33.0,
            tmin_c=25.0,
            mean_temp_c=28.0,
            sunshine_hours=8.0,
            precipitation_mm=0.0,
            sun_score=1.0,
            rain_risk=0.0,
            heat_load_score=0.8,
            midday_recovery_expectation="high",
            operation_mode="aggressive",
            no_future_leakage=True,
        )


def test_weather_proxy_forecast_dict_contains_required_reproducibility_fields():
    forecast = WeatherProxyForecast(
        version="historical_analog_v1",
        forecast_type="historical_analog_v1",
        service_date="2025-08-21",
        station_id="44132",
        station_name="東京",
        analog_date="2024-08-22",
        analog_selection_score=0.183,
        analog_selection_method="calendar_plus_previous_day_weather_v1",
        weather_label="曇り時々晴れ",
        tmax_c=33.2,
        tmin_c=25.1,
        mean_temp_c=28.4,
        sunshine_hours=5.8,
        precipitation_mm=0.0,
        sun_score=0.725,
        rain_risk=0.0,
        heat_load_score=0.82,
        midday_recovery_expectation="high",
        operation_mode="aggressive",
        no_future_leakage=True,
        metadata={"candidate_count": 10, "features_used": ["month_distance"]},
    )

    payload = weather_proxy_forecast_to_dict(forecast)

    assert payload["version"] == "historical_analog_v1"
    assert payload["station_id"] == "44132"
    assert payload["analog_date"] == "2024-08-22"
    assert payload["metadata"]["candidate_count"] == 10
