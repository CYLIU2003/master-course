from __future__ import annotations

import argparse
import re
import sys
from dataclasses import replace
from pathlib import Path
from typing import Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.preprocess.weather.daily_weather_schema import DailyWeatherObservation
from src.preprocess.weather.jma_daily_csv_loader import load_jma_daily_csv, write_daily_weather_csv
from src.preprocess.weather.kishojin_diary_parser import (
    KishojinParseError,
    parse_kishojin_diary_file,
)


def _infer_year_month(path: Path) -> tuple[int, int] | None:
    match = re.search(r"((?:19|20)\d{2})(0[1-9]|1[0-2])", path.name)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _load_kishojin_dir(
    html_dir: Path | None,
    *,
    station_id: str,
    station_name: str,
) -> List[DailyWeatherObservation]:
    if html_dir is None or not html_dir.exists():
        return []
    observations: List[DailyWeatherObservation] = []
    for path in sorted(html_dir.glob("*.html")):
        ym = _infer_year_month(path)
        if ym is None:
            raise ValueError(f"Cannot infer YYYYMM from Kishojin HTML filename: {path}")
        try:
            observations.extend(
                parse_kishojin_diary_file(
                    path,
                    year=ym[0],
                    month=ym[1],
                    station_id=station_id,
                    station_name=station_name,
                )
            )
        except KishojinParseError as exc:
            raise ValueError(f"Failed to parse Kishojin HTML {path}: {exc}") from exc
    return observations


def _merge_by_date(
    *,
    jma_observations: Iterable[DailyWeatherObservation],
    kishojin_observations: Iterable[DailyWeatherObservation],
    station_id: str,
    station_name: str,
) -> List[DailyWeatherObservation]:
    jma_by_date = {obs.date: obs for obs in jma_observations}
    kishojin_by_date = {obs.date: obs for obs in kishojin_observations}
    merged: List[DailyWeatherObservation] = []
    for day in sorted(set(jma_by_date) | set(kishojin_by_date)):
        jma = jma_by_date.get(day)
        kishojin = kishojin_by_date.get(day)
        if jma and kishojin:
            merged.append(
                DailyWeatherObservation(
                    date=day,
                    station_id=station_id,
                    station_name=station_name,
                    source="kishojin+jma",
                    weather_label=kishojin.weather_label or jma.weather_label,
                    tmax_c=jma.tmax_c if jma.tmax_c is not None else kishojin.tmax_c,
                    tmin_c=jma.tmin_c if jma.tmin_c is not None else kishojin.tmin_c,
                    mean_temp_c=jma.mean_temp_c,
                    sunshine_hours=jma.sunshine_hours,
                    precipitation_mm=jma.precipitation_mm,
                    daylight_note=jma.daylight_note or kishojin.daylight_note,
                    quality_flag="ok"
                    if jma.quality_flag == "ok" and kishojin.quality_flag == "ok"
                    else "partial",
                    raw_url=jma.raw_url or kishojin.raw_url,
                    created_at=jma.created_at or kishojin.created_at,
                    updated_at=jma.updated_at or kishojin.updated_at,
                )
            )
        else:
            obs = jma or kishojin
            if obs is None:
                continue
            merged.append(replace(obs, station_id=station_id, station_name=station_name))
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="Build normalized daily weather CSV.")
    parser.add_argument("--kishojin-html-dir", default="")
    parser.add_argument("--jma-csv", default="")
    parser.add_argument("--station-id", required=True)
    parser.add_argument("--station-name", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    kishojin_dir = Path(args.kishojin_html_dir) if args.kishojin_html_dir else None
    jma_path = Path(args.jma_csv) if args.jma_csv else None
    if (kishojin_dir is None or not kishojin_dir.exists()) and (
        jma_path is None or not jma_path.exists()
    ):
        raise SystemExit("At least one local input is required: --kishojin-html-dir or --jma-csv")

    jma_observations = (
        load_jma_daily_csv(jma_path, station_id=args.station_id, station_name=args.station_name)
        if jma_path is not None and jma_path.exists()
        else []
    )
    kishojin_observations = _load_kishojin_dir(
        kishojin_dir,
        station_id=args.station_id,
        station_name=args.station_name,
    )
    merged = _merge_by_date(
        jma_observations=jma_observations,
        kishojin_observations=kishojin_observations,
        station_id=args.station_id,
        station_name=args.station_name,
    )
    write_daily_weather_csv(args.out, merged)
    print(f"wrote {len(merged)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
