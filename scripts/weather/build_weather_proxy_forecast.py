from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.preprocess.weather.weather_proxy_builder import (
    build_weather_proxy_forecast,
    write_weather_proxy_forecast_json,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build historical analog weather proxy forecast JSON.")
    parser.add_argument("--service-date", required=True)
    parser.add_argument("--station-id", required=True)
    parser.add_argument("--station-name", required=True)
    parser.add_argument("--daily-weather-csv", required=True)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    forecast = build_weather_proxy_forecast(
        service_date=args.service_date,
        station_id=args.station_id,
        station_name=args.station_name,
        daily_weather_csv_path=args.daily_weather_csv,
        random_seed=args.random_seed,
    )
    write_weather_proxy_forecast_json(args.out, forecast)
    print(f"wrote weather proxy forecast to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
