"""Historical weather proxy preprocessing helpers."""

from .daily_weather_schema import (
    FORECAST_TYPE_HISTORICAL_ANALOG_V1,
    FORECAST_TYPE_SOLCAST_PV_PROXY_V1,
    FORECAST_TYPE_SOLCAST_TYPICAL_PV_PROXY_V1,
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
from .solcast_pv_proxy import build_solcast_pv_proxy_forecast
from .solcast_typical.forecast import build_solcast_typical_proxy_forecast
from .weather_proxy_builder import build_weather_proxy_forecast

__all__ = [
    "FORECAST_TYPE_HISTORICAL_ANALOG_V1",
    "FORECAST_TYPE_SOLCAST_PV_PROXY_V1",
    "FORECAST_TYPE_SOLCAST_TYPICAL_PV_PROXY_V1",
    "DailyWeatherObservation",
    "WeatherProxyForecast",
    "WeatherOperationProfile",
    "OPERATION_PROFILES",
    "NoAnalogCandidateError",
    "apply_initial_soc_policy",
    "apply_weather_policy_to_problem",
    "build_operation_profile",
    "build_solcast_pv_proxy_forecast",
    "build_solcast_typical_proxy_forecast",
    "build_weather_proxy_forecast",
    "daily_observation_from_dict",
    "daily_observation_to_dict",
    "select_historical_analog",
    "weather_proxy_forecast_from_dict",
    "weather_proxy_forecast_to_dict",
]
