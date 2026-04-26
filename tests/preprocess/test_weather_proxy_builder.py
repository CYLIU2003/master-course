import json
from pathlib import Path

from src.preprocess.weather.weather_proxy_builder import (
    build_weather_proxy_forecast,
    load_weather_proxy_forecast_json,
    write_weather_proxy_forecast_json,
)


def test_build_weather_proxy_forecast_from_daily_csv(tmp_path: Path):
    csv_path = tmp_path / "daily.csv"
    csv_path.write_text(
        "date,station_id,station_name,source,weather_label,tmax_c,tmin_c,mean_temp_c,"
        "sunshine_hours,precipitation_mm,daylight_note,quality_flag\n"
        "2024-08-21,44132,東京,jma,晴れ,33.0,25.0,28.0,8.0,0.0,,ok\n"
        "2025-08-20,44132,東京,jma,晴れ,33.1,25.1,28.1,8.1,0.0,,ok\n",
        encoding="utf-8",
    )

    forecast = build_weather_proxy_forecast(
        service_date="2025-08-21",
        station_id="44132",
        station_name="東京",
        daily_weather_csv_path=str(csv_path),
    )
    out = tmp_path / "forecast.json"
    write_weather_proxy_forecast_json(out, forecast)
    loaded = load_weather_proxy_forecast_json(out)

    assert loaded.forecast_type == "historical_analog_v1"
    assert loaded.analog_date == "2024-08-21"
    assert loaded.no_future_leakage is True
    assert loaded.metadata["candidate_count"] == 2
    assert json.loads(out.read_text(encoding="utf-8"))["operation_mode"] == "aggressive"
