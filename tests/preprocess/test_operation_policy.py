from src.preprocess.weather.daily_weather_schema import WeatherProxyForecast
from src.preprocess.weather.operation_policy import (
    OPERATION_PROFILES,
    build_operation_profile,
    heat_load_score_from_weather,
    operation_mode_from_scores,
    rain_risk_from_weather,
    sun_score_from_weather,
)


def _forecast(operation_mode: str) -> WeatherProxyForecast:
    return WeatherProxyForecast(
        version="historical_analog_v1",
        forecast_type="historical_analog_v1",
        service_date="2025-08-21",
        station_id="44132",
        station_name="東京",
        analog_date="2024-08-22",
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
        operation_mode=operation_mode,
        no_future_leakage=True,
    )


def test_weather_scores_and_modes_match_v1_thresholds():
    assert operation_mode_from_scores(0.8, 0.1) == "aggressive"
    assert operation_mode_from_scores(0.4, 0.2) == "normal"
    assert operation_mode_from_scores(0.2, 0.1) == "conservative"
    assert operation_mode_from_scores(0.8, 0.7) == "conservative"


def test_weather_scores_are_clamped_and_can_fallback_to_label():
    assert sun_score_from_weather(sunshine_hours=99.0, weather_label=None) == 1.0
    assert rain_risk_from_weather(precipitation_mm=99.0, weather_label=None) == 1.0
    assert sun_score_from_weather(sunshine_hours=None, weather_label="曇り時々雨") == 0.15
    assert rain_risk_from_weather(precipitation_mm=None, weather_label="大雨") == 1.0
    assert heat_load_score_from_weather(50.0) == 1.0


def test_operation_profile_defaults_keep_pv_marginal_cost_zero():
    profile = build_operation_profile(_forecast("conservative"))

    assert profile == OPERATION_PROFILES["conservative"]
    assert profile.pv_marginal_charge_cost_yen_per_kwh == 0.0
