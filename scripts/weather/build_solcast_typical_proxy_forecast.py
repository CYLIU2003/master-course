from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.preprocess.weather.solcast_typical.forecast import (  # noqa: E402
    build_solcast_typical_proxy_forecast,
)
from src.preprocess.weather.weather_proxy_builder import write_weather_proxy_forecast_json  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build WeatherProxyForecast JSON from Solcast sunny/cloudy/rainy representative curves."
    )
    parser.add_argument("--service-date", required=True)
    parser.add_argument("--station-id", required=True)
    parser.add_argument("--station-name", required=True)
    parser.add_argument("--representative-curve-json", required=True)
    parser.add_argument(
        "--weather-class",
        default="auto",
        choices=["sunny", "cloudy", "rainy", "auto"],
    )
    parser.add_argument("--forecast-issue-date", default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    forecast = build_solcast_typical_proxy_forecast(
        service_date=args.service_date,
        station_id=args.station_id,
        station_name=args.station_name,
        representative_curve_json_path=args.representative_curve_json,
        weather_class=args.weather_class,
        forecast_issue_date=args.forecast_issue_date,
    )
    out_path = Path(args.out)
    write_weather_proxy_forecast_json(out_path, forecast)
    print(f"wrote: {out_path}")
    print(f"forecast_type: {forecast.forecast_type}")
    print(f"service_date: {forecast.service_date}")
    print(f"forecast_issue_date: {forecast.analog_date}")
    print(f"typical_weather_class: {forecast.metadata.get('typical_weather_class')}")
    print(f"operation_mode: {forecast.operation_mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
