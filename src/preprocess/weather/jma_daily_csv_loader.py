"""Load and write normalized daily weather CSV files.

This module performs local file parsing only. It never reaches out to JMA or
any other network source during optimization.
"""

from __future__ import annotations

import csv
from datetime import date
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .daily_weather_schema import DailyWeatherObservation, daily_observation_to_dict

CSV_COLUMNS = [
    "date",
    "station_id",
    "station_name",
    "source",
    "weather_label",
    "tmax_c",
    "tmin_c",
    "mean_temp_c",
    "sunshine_hours",
    "precipitation_mm",
    "daylight_note",
    "quality_flag",
    "raw_url",
    "created_at",
    "updated_at",
]

_COLUMN_ALIASES: Dict[str, tuple[str, ...]] = {
    "date": ("date", "年月日", "日付"),
    "station_id": ("station_id", "地点番号", "station", "ame"),
    "station_name": ("station_name", "地点", "地点名", "観測所"),
    "source": ("source", "出典"),
    "weather_label": (
        "weather_label",
        "天気",
        "昼(06:00-18:00)天気",
        "天気概況(昼：06時～18時)",
        "天気概況(昼:06時～18時)",
    ),
    "tmax_c": ("tmax_c", "最高気温(℃)", "最高気温", "最高気温(度)"),
    "tmin_c": ("tmin_c", "最低気温(℃)", "最低気温", "最低気温(度)"),
    "mean_temp_c": ("mean_temp_c", "平均気温(℃)", "平均気温", "平均気温(度)"),
    "sunshine_hours": ("sunshine_hours", "日照時間(時間)", "日照時間"),
    "precipitation_mm": (
        "precipitation_mm",
        "降水量(mm)",
        "降水量の合計(mm)",
        "降水量",
    ),
    "quality_flag": ("quality_flag", "品質", "品質フラグ"),
    "daylight_note": ("daylight_note", "備考"),
    "raw_url": ("raw_url", "URL"),
    "created_at": ("created_at", "作成日時"),
    "updated_at": ("updated_at", "更新日時"),
}


def _read_text_with_fallback(path: Path) -> str:
    last_error: Optional[Exception] = None
    for encoding in ("utf-8-sig", "cp932", "shift_jis"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise UnicodeDecodeError(
        "weather_csv",
        b"",
        0,
        1,
        f"Unable to decode {path} as utf-8-sig, cp932, or shift_jis: {last_error}",
    )


def _header_lookup(fieldnames: Iterable[str]) -> Dict[str, str]:
    raw_by_normalized = {str(name).strip(): str(name) for name in fieldnames if name is not None}
    lookup: Dict[str, str] = {}
    for canonical, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in raw_by_normalized:
                lookup[canonical] = raw_by_normalized[alias]
                break
    return lookup


_NUMERIC_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


def _parse_optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"--", "///", "×", "NaN", "nan"}:
        return None
    match = _NUMERIC_RE.search(text.replace(",", ""))
    if match is None:
        return None
    return float(match.group(0))


def _value(row: Mapping[str, Any], lookup: Mapping[str, str], key: str) -> Any:
    raw_key = lookup.get(key)
    if raw_key is None:
        return None
    return row.get(raw_key)


def _normalize_date(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return text
    normalized = re.sub(r"[./]", "-", text)
    parts = normalized.split("-")
    if len(parts) >= 3 and all(part.strip().isdigit() for part in parts[:3]):
        return date(int(parts[0]), int(parts[1]), int(parts[2])).isoformat()
    return text[:10]


def load_jma_daily_csv(
    path: str | Path,
    *,
    station_id: str = "",
    station_name: str = "",
    source: str = "jma",
) -> List[DailyWeatherObservation]:
    csv_path = Path(path)
    text = _read_text_with_fallback(csv_path)
    reader = csv.DictReader(text.splitlines())
    if not reader.fieldnames:
        raise ValueError(f"JMA CSV has no header: {csv_path}")
    lookup = _header_lookup(reader.fieldnames)
    if "date" not in lookup:
        raise ValueError(f"JMA CSV missing date column: {csv_path}")
    observations: List[DailyWeatherObservation] = []
    for row in reader:
        row_station_id = str(_value(row, lookup, "station_id") or station_id).strip()
        row_station_name = str(_value(row, lookup, "station_name") or station_name).strip()
        if not row_station_id:
            raise ValueError(f"station_id missing in {csv_path}")
        if not row_station_name:
            raise ValueError(f"station_name missing in {csv_path}")
        observations.append(
            DailyWeatherObservation(
                date=_normalize_date(_value(row, lookup, "date")),
                station_id=row_station_id,
                station_name=row_station_name,
                source=str(_value(row, lookup, "source") or source).strip() or source,
                weather_label=str(_value(row, lookup, "weather_label") or "").strip() or None,
                tmax_c=_parse_optional_float(_value(row, lookup, "tmax_c")),
                tmin_c=_parse_optional_float(_value(row, lookup, "tmin_c")),
                mean_temp_c=_parse_optional_float(_value(row, lookup, "mean_temp_c")),
                sunshine_hours=_parse_optional_float(_value(row, lookup, "sunshine_hours")),
                precipitation_mm=_parse_optional_float(_value(row, lookup, "precipitation_mm")),
                daylight_note=str(_value(row, lookup, "daylight_note") or "").strip() or None,
                quality_flag=str(_value(row, lookup, "quality_flag") or "ok").strip() or "ok",
                raw_url=str(_value(row, lookup, "raw_url") or "").strip() or None,
                created_at=str(_value(row, lookup, "created_at") or "").strip() or None,
                updated_at=str(_value(row, lookup, "updated_at") or "").strip() or None,
            )
        )
    return observations


def write_daily_weather_csv(
    path: str | Path,
    observations: Iterable[DailyWeatherObservation],
) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for observation in observations:
            row = daily_observation_to_dict(observation)
            writer.writerow({key: row.get(key, "") for key in CSV_COLUMNS})
