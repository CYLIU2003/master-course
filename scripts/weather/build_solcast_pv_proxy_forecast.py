from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.preprocess.weather.solcast_pv_proxy import build_solcast_pv_proxy_forecast
from src.preprocess.weather.weather_proxy_builder import write_weather_proxy_forecast_json


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a WeatherProxyForecast JSON from a local Solcast PV profile."
    )
    parser.add_argument("--service-date", required=True)
    parser.add_argument("--station-id", required=True)
    parser.add_argument("--station-name", required=True)
    parser.add_argument("--pv-profile-json", required=True)
    parser.add_argument(
        "--forecast-issue-date",
        default=None,
        help="YYYY-MM-DD. Defaults to service_date - 1 day; must be before service_date.",
    )
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    forecast = build_solcast_pv_proxy_forecast(
        service_date=args.service_date,
        station_id=args.station_id,
        station_name=args.station_name,
        pv_profile_json_path=args.pv_profile_json,
        forecast_issue_date=args.forecast_issue_date,
    )
    write_weather_proxy_forecast_json(args.out, forecast)
    print(f"wrote Solcast PV proxy forecast to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
