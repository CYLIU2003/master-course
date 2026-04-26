"""Historical weather proxy preprocessing helpers."""

from .daily_weather_schema import (
    DailyWeatherObservation,
    WeatherProxyForecast,
    daily_observation_from_dict,
    daily_observation_to_dict,
    weather_proxy_forecast_from_dict,
    weather_proxy_forecast_to_dict,
)
from .historical_analog import NoAnalogCandidateError, select_historical_analog
from .operation_policy import (
    OPERATION_PROFILES,
    WeatherOperationProfile,
    apply_initial_soc_policy,
    apply_weather_policy_to_problem,
    build_operation_profile,
)
from .weather_proxy_builder import build_weather_proxy_forecast

__all__ = [
    "DailyWeatherObservation",
    "WeatherProxyForecast",
    "WeatherOperationProfile",
    "OPERATION_PROFILES",
    "NoAnalogCandidateError",
    "apply_initial_soc_policy",
    "apply_weather_policy_to_problem",
    "build_operation_profile",
    "build_weather_proxy_forecast",
    "daily_observation_from_dict",
    "daily_observation_to_dict",
    "select_historical_analog",
    "weather_proxy_forecast_from_dict",
    "weather_proxy_forecast_to_dict",
]
