from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.preprocess.weather.weather_proxy_builder import load_weather_proxy_forecast_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect weather proxy forecast JSON.")
    parser.add_argument("--forecast-json", required=True)
    args = parser.parse_args()
    forecast = load_weather_proxy_forecast_json(args.forecast_json)
    print(f"service_date: {forecast.service_date}")
    print(f"analog_date: {forecast.analog_date}")
    print(f"weather_label: {forecast.weather_label or ''}")
    print(f"sunshine_hours: {forecast.sunshine_hours}")
    print(f"precipitation_mm: {forecast.precipitation_mm}")
    print(f"sun_score: {forecast.sun_score:.2f}")
    print(f"rain_risk: {forecast.rain_risk:.2f}")
    print(f"operation_mode: {forecast.operation_mode}")
    print(f"no_future_leakage: {str(forecast.no_future_leakage).lower()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
