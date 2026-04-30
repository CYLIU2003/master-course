from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.preprocess.weather.daily_weather_schema import (
    FORECAST_TYPE_SOLCAST_TYPICAL_PV_PROXY_V1,
    WeatherSchemaError,
)
from src.preprocess.weather.solcast_typical import (
    build_representative_curve_payload,
    build_solcast_typical_proxy_forecast,
    classify_solcast_daily_profiles,
    load_solcast_daily_pv_profiles,
)
from src.preprocess.weather.weather_proxy_builder import (
    load_weather_proxy_forecast_json,
    write_weather_proxy_forecast_json,
)


def _write_profile(path: Path, *, day: str, value: float, depot_id: str = "DEPOT") -> None:
    path.write_text(
        json.dumps(
            {
                "depot_id": depot_id,
                "date": day,
                "slot_minutes": 60,
                "capacity_factor_by_slot": [float(value)] * 24,
            }
        ),
        encoding="utf-8",
    )


def test_solcast_typical_classification_excludes_all_zero_and_uses_fixed_fallback(tmp_path: Path) -> None:
    _write_profile(tmp_path / "DEPOT_2025-08-01_60min.json", day="2025-08-01", value=0.0)
    _write_profile(tmp_path / "DEPOT_2025-08-02_60min.json", day="2025-08-02", value=0.10)
    _write_profile(tmp_path / "DEPOT_2025-08-03_60min.json", day="2025-08-03", value=0.20)
    _write_profile(tmp_path / "DEPOT_2025-08-04_60min.json", day="2025-08-04", value=0.30)

    profiles = load_solcast_daily_pv_profiles(profile_dir=tmp_path)
    result = classify_solcast_daily_profiles(profiles)

    assert result.method == "fixed_threshold_daily_cf_hours_fallback"
    assert [item["date"] for item in result.excluded_dates] == ["2025-08-01"]
    by_date = {day.date: day.weather_class for day in result.classified_days}
    assert by_date["2025-08-02"] == "rainy"
    assert by_date["2025-08-03"] == "cloudy"
    assert by_date["2025-08-04"] == "sunny"


def test_solcast_typical_classification_uses_quantiles_with_enough_days(tmp_path: Path) -> None:
    for idx in range(15):
        _write_profile(
            tmp_path / f"DEPOT_2025-08-{idx + 1:02d}_60min.json",
            day=f"2025-08-{idx + 1:02d}",
            value=0.05 + idx * 0.02,
        )

    profiles = load_solcast_daily_pv_profiles(profile_dir=tmp_path)
    result = classify_solcast_daily_profiles(profiles)

    assert result.method == "quantile_33_67_by_daily_cf_hours"
    assert {day.weather_class for day in result.classified_days} == {"rainy", "cloudy", "sunny"}


def test_representative_curve_and_forecast_roundtrip_without_future_leakage(tmp_path: Path) -> None:
    for idx, value in enumerate((0.10, 0.20, 0.30), start=1):
        _write_profile(
            tmp_path / f"DEPOT_2025-08-{idx:02d}_60min.json",
            day=f"2025-08-{idx:02d}",
            value=value,
        )
    profiles = load_solcast_daily_pv_profiles(profile_dir=tmp_path)
    payload = build_representative_curve_payload(profiles, station_id="44132", station_name="東京", depot_id="DEPOT")
    curve_path = tmp_path / "typical_curve.json"
    curve_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    forecast = build_solcast_typical_proxy_forecast(
        service_date="2025-09-01",
        station_id="44132",
        station_name="東京",
        representative_curve_json_path=curve_path,
        weather_class="sunny",
        forecast_issue_date="2025-08-31",
    )
    out = tmp_path / "forecast.json"
    write_weather_proxy_forecast_json(out, forecast)
    loaded = load_weather_proxy_forecast_json(out)

    assert loaded.forecast_type == FORECAST_TYPE_SOLCAST_TYPICAL_PV_PROXY_V1
    assert loaded.analog_date == "2025-08-31"
    assert loaded.metadata["typical_weather_class"] == "sunny"
    assert loaded.metadata["source_profile_count"] == 1
    assert loaded.no_future_leakage is True


def test_solcast_typical_forecast_rejects_source_dates_on_or_after_service(tmp_path: Path) -> None:
    _write_profile(tmp_path / "DEPOT_2025-09-01_60min.json", day="2025-09-01", value=0.30)
    profiles = load_solcast_daily_pv_profiles(profile_dir=tmp_path)
    payload = build_representative_curve_payload(profiles, depot_id="DEPOT")
    curve_path = tmp_path / "typical_curve.json"
    curve_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(WeatherSchemaError, match="future leakage"):
        build_solcast_typical_proxy_forecast(
            service_date="2025-09-01",
            station_id="44132",
            station_name="東京",
            representative_curve_json_path=curve_path,
            weather_class="sunny",
            forecast_issue_date="2025-08-31",
        )
