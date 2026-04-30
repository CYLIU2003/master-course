import json
from pathlib import Path

import pytest

from src.preprocess.weather.daily_weather_schema import (
    FORECAST_TYPE_SOLCAST_PV_PROXY_V1,
    WeatherSchemaError,
)
from src.preprocess.weather.solcast_pv_proxy import (
    build_solcast_pv_proxy_forecast,
    default_forecast_issue_date,
)
from src.preprocess.weather.weather_proxy_builder import (
    load_weather_proxy_forecast_json,
    write_weather_proxy_forecast_json,
)


def _write_profile(
    path: Path,
    *,
    service_date: str = "2025-08-21",
    capacity_factor_by_slot: list[float] | None = None,
) -> None:
    factors = capacity_factor_by_slot or [
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.02,
        0.12,
        0.30,
        0.49,
        0.65,
        0.75,
        0.79,
        0.76,
        0.67,
        0.54,
        0.22,
        0.09,
        0.04,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    ]
    path.write_text(
        json.dumps(
            {
                "depot_id": "aobadai",
                "date": service_date,
                "slot_minutes": 60,
                "source_csv": "data/external/solcast_raw/aobadai_2025_08_60min.csv",
                "capacity_kw": 200.0,
                "capacity_factor_by_slot": factors,
                "metadata": {"mode": "gti"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_build_solcast_pv_proxy_forecast_from_capacity_factors(tmp_path: Path) -> None:
    profile_path = tmp_path / "aobadai_2025-08-21_60min.json"
    _write_profile(profile_path)

    forecast = build_solcast_pv_proxy_forecast(
        service_date="2025-08-21",
        station_id="aobadai",
        station_name="青葉台営業所",
        pv_profile_json_path=profile_path,
        forecast_issue_date="2025-08-20",
    )

    assert forecast.forecast_type == FORECAST_TYPE_SOLCAST_PV_PROXY_V1
    assert forecast.version == FORECAST_TYPE_SOLCAST_PV_PROXY_V1
    assert forecast.analog_date == "2025-08-20"
    assert forecast.no_future_leakage is True
    assert forecast.sun_score >= 0.70
    assert forecast.rain_risk <= 0.20
    assert forecast.operation_mode == "aggressive"
    assert forecast.metadata["forecast_issue_date"] == "2025-08-20"
    assert forecast.metadata["rain_risk_source"] == "inferred_from_low_pv_recovery"


def test_solcast_pv_proxy_round_trips_as_weather_proxy_json(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    _write_profile(profile_path)
    forecast = build_solcast_pv_proxy_forecast(
        service_date="2025-08-21",
        station_id="aobadai",
        station_name="青葉台営業所",
        pv_profile_json_path=profile_path,
    )
    out = tmp_path / "forecast.json"

    write_weather_proxy_forecast_json(out, forecast)
    loaded = load_weather_proxy_forecast_json(out)

    assert loaded.forecast_type == FORECAST_TYPE_SOLCAST_PV_PROXY_V1
    assert loaded.analog_date == default_forecast_issue_date("2025-08-21")
    assert loaded.metadata["pv_profile_date"] == "2025-08-21"


def test_solcast_pv_proxy_rejects_issue_date_future_leakage(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    _write_profile(profile_path)

    with pytest.raises(WeatherSchemaError, match="forecast_issue_date"):
        build_solcast_pv_proxy_forecast(
            service_date="2025-08-21",
            station_id="aobadai",
            station_name="青葉台営業所",
            pv_profile_json_path=profile_path,
            forecast_issue_date="2025-08-21",
        )


def test_solcast_pv_proxy_rejects_profile_date_mismatch(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    _write_profile(profile_path, service_date="2025-08-20")

    with pytest.raises(WeatherSchemaError, match="date mismatch"):
        build_solcast_pv_proxy_forecast(
            service_date="2025-08-21",
            station_id="aobadai",
            station_name="青葉台営業所",
            pv_profile_json_path=profile_path,
            forecast_issue_date="2025-08-20",
        )


def test_low_solcast_recovery_maps_to_conservative(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.json"
    _write_profile(profile_path, capacity_factor_by_slot=[0.0] * 24)

    forecast = build_solcast_pv_proxy_forecast(
        service_date="2025-08-21",
        station_id="aobadai",
        station_name="青葉台営業所",
        pv_profile_json_path=profile_path,
        forecast_issue_date="2025-08-20",
    )

    assert forecast.sun_score == 0.0
    assert forecast.rain_risk == 1.0
    assert forecast.operation_mode == "conservative"
