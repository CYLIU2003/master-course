from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


_DEFAULT_IRRADIANCE_COLUMNS: Tuple[str, ...] = (
    "gti",
    "gti_fixed",
    "gti_tracking",
    "ghi",
)

_DEFAULT_TIME_COLUMNS: Tuple[str, ...] = (
    "period_end",
    "period_end_local",
    "period_end_utc",
    "period_start",
    "timestamp",
    "time",
)


@dataclass(frozen=True)
class DepotCoordinate:
    depot_id: str
    name: str
    lat: float
    lon: float


def parse_utc_offset(offset_text: str) -> timezone:
    text = str(offset_text or "").strip()
    if not text:
        raise ValueError("timezone offset is required, e.g. +09:00")
    if text.upper() == "UTC":
        return timezone.utc
    m = re.fullmatch(r"([+-])(\d{2}):(\d{2})", text)
    if not m:
        raise ValueError(f"invalid timezone offset: {text}")
    sign = 1 if m.group(1) == "+" else -1
    hours = int(m.group(2))
    minutes = int(m.group(3))
    delta = timedelta(hours=hours, minutes=minutes) * sign
    return timezone(delta)


def _parse_dt(raw: str, *, fallback_tz: timezone) -> Optional[datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=fallback_tz)
    return dt


def _normalize_csv_row(row: Mapping[str, Any]) -> Dict[str, Any]:
    return {str(k).strip().lower(): v for k, v in row.items()}


def _pick_column(candidates: Iterable[str], row: Mapping[str, Any]) -> Optional[str]:
    row_keys = {str(k).strip().lower() for k in row.keys()}
    for col in candidates:
        key = str(col).strip().lower()
        if key in row_keys:
            return key
    return None


def _parse_minutes_from_period(raw: Any) -> Optional[int]:
    text = str(raw or "").strip().upper()
    if not text:
        return None
    # Solcast commonly uses ISO8601 duration format such as PT60M.
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?", text)
    if not m:
        return None
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    total = hours * 60 + minutes
    return total if total > 0 else None


def load_depot_coordinates(master_path: Path) -> List[DepotCoordinate]:
    with master_path.open("r", encoding="utf-8") as f:
        doc = json.load(f)

    depots = list(doc.get("depots") or [])
    out: List[DepotCoordinate] = []
    for depot in depots:
        if not isinstance(depot, dict):
            continue
        depot_id = str(depot.get("depot_id") or depot.get("id") or "").strip()
        if not depot_id:
            continue
        lat = depot.get("lat")
        if lat is None:
            lat = depot.get("latitude")
        lon = depot.get("lon")
        if lon is None:
            lon = depot.get("longitude")
        if lat is None or lon is None:
            continue
        out.append(
            DepotCoordinate(
                depot_id=depot_id,
                name=str(depot.get("name") or depot_id),
                lat=float(lat),
                lon=float(lon),
            )
        )
    return out


def export_depot_coordinates(master_path: Path, output_path: Path) -> Dict[str, Any]:
    coords = load_depot_coordinates(master_path)
    payload = {
        "source_master": str(master_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(coords),
        "coordinates": [
            {
                "depot_id": c.depot_id,
                "name": c.name,
                "lat": c.lat,
                "lon": c.lon,
            }
            for c in coords
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return payload


def _floor_to_slot(dt: datetime, slot_minutes: int) -> datetime:
    minute = (dt.minute // slot_minutes) * slot_minutes
    return dt.replace(minute=minute, second=0, microsecond=0)


def _read_solcast_records(
    csv_path: Path,
    *,
    local_tz: timezone,
    time_col: Optional[str],
    irradiance_col: Optional[str],
    fallback_period_min: int,
) -> Tuple[List[Tuple[datetime, float, int]], str, str]:
    records: List[Tuple[datetime, float, int]] = []
    selected_time_col: Optional[str] = time_col
    selected_irr_col: Optional[str] = irradiance_col

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row = _normalize_csv_row(raw)
            if selected_time_col is None:
                selected_time_col = _pick_column(_DEFAULT_TIME_COLUMNS, row)
            if selected_irr_col is None:
                selected_irr_col = _pick_column(_DEFAULT_IRRADIANCE_COLUMNS, row)
            if not selected_time_col or not selected_irr_col:
                continue
            dt = _parse_dt(str(row.get(selected_time_col) or ""), fallback_tz=local_tz)
            if dt is None:
                continue
            try:
                irr = float(row.get(selected_irr_col) or 0.0)
            except (TypeError, ValueError):
                continue
            if irr < 0.0:
                irr = 0.0
            period_min = _parse_minutes_from_period(row.get("period")) or fallback_period_min
            records.append((dt.astimezone(local_tz), irr, period_min))

    if not selected_time_col or not selected_irr_col:
        raise ValueError(
            f"could not infer required columns in {csv_path.name}; "
            "set explicit columns with --time-column / --irradiance-column"
        )
    return records, selected_time_col, selected_irr_col


def inspect_csv_time_coverage(
    csv_path: Path,
    *,
    timezone_offset: str,
    fallback_period_min: int,
    time_column: Optional[str] = None,
    irradiance_column: Optional[str] = None,
) -> Dict[str, Any]:
    local_tz = parse_utc_offset(timezone_offset)
    records, selected_time_col, selected_irr_col = _read_solcast_records(
        csv_path,
        local_tz=local_tz,
        time_col=time_column,
        irradiance_col=irradiance_column,
        fallback_period_min=fallback_period_min,
    )

    if not records:
        return {
            "record_count": 0,
            "time_column": selected_time_col,
            "irradiance_column": selected_irr_col,
            "min_period_end": None,
            "max_period_end": None,
            "available_dates": [],
        }

    min_dt = min(item[0] for item in records)
    max_dt = max(item[0] for item in records)
    dates = sorted(
        {
            (item[0] - timedelta(seconds=1)).date().isoformat()
            for item in records
        }
    )
    return {
        "record_count": len(records),
        "time_column": selected_time_col,
        "irradiance_column": selected_irr_col,
        "min_period_end": min_dt.isoformat(),
        "max_period_end": max_dt.isoformat(),
        "available_dates": dates,
    }


def _build_daily_profile(
    records: Sequence[Tuple[datetime, float, int]],
    *,
    target_date: str,
    slot_minutes: int,
    pv_capacity_kw: float,
) -> Dict[str, List[float]]:
    date_start = datetime.fromisoformat(f"{target_date}T00:00:00")
    if date_start.tzinfo is None:
        # records are already converted to local timezone; borrow tz from first record.
        if records:
            date_start = date_start.replace(tzinfo=records[0][0].tzinfo)
    date_end = date_start + timedelta(days=1)

    slot_count = int(24 * 60 / slot_minutes)
    weighted_cf = [0.0] * slot_count
    slot_hours = [0.0] * slot_count

    for dt_end, irradiance_wm2, period_min in records:
        if period_min <= 0:
            continue
        period_h = period_min / 60.0
        # Solcast period_end belongs to the preceding interval.
        interval_anchor = dt_end - timedelta(seconds=1)
        slot_start = _floor_to_slot(interval_anchor, slot_minutes)
        if slot_start < date_start or slot_start >= date_end:
            continue
        index = int((slot_start - date_start).total_seconds() // (slot_minutes * 60))
        if index < 0 or index >= slot_count:
            continue
        cf = max(0.0, min(irradiance_wm2 / 1000.0, 1.0))
        weighted_cf[index] += cf * period_h
        slot_hours[index] += period_h

    capacity_factor_by_slot: List[float] = []
    pv_generation_kwh_by_slot: List[float] = []
    for idx in range(slot_count):
        if slot_hours[idx] > 0:
            cf = weighted_cf[idx] / slot_hours[idx]
        else:
            cf = 0.0
        duration_h = slot_minutes / 60.0
        capacity_factor_by_slot.append(round(cf, 6))
        pv_generation_kwh_by_slot.append(round(max(pv_capacity_kw, 0.0) * cf * duration_h, 6))

    return {
        "capacity_factor_by_slot": capacity_factor_by_slot,
        "pv_generation_kwh_by_slot": pv_generation_kwh_by_slot,
    }


def build_daily_profiles_from_csv(
    *,
    depot_id: str,
    csv_path: Path,
    output_dir: Path,
    dates: Sequence[str],
    slot_minutes: int,
    timezone_offset: str,
    pv_capacity_kw: float,
    fallback_period_min: int,
    time_column: Optional[str] = None,
    irradiance_column: Optional[str] = None,
) -> List[Path]:
    local_tz = parse_utc_offset(timezone_offset)
    records, selected_time_col, selected_irr_col = _read_solcast_records(
        csv_path,
        local_tz=local_tz,
        time_col=time_column,
        irradiance_col=irradiance_column,
        fallback_period_min=fallback_period_min,
    )

    written: List[Path] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for date in dates:
        profile = _build_daily_profile(
            records,
            target_date=date,
            slot_minutes=slot_minutes,
            pv_capacity_kw=pv_capacity_kw,
        )
        payload = {
            "depot_id": depot_id,
            "date": date,
            "slot_minutes": int(slot_minutes),
            "timezone": timezone_offset,
            "source_csv": str(csv_path),
            "time_column": selected_time_col,
            "irradiance_column": selected_irr_col,
            "pv_capacity_kw": float(pv_capacity_kw),
            "capacity_factor_by_slot": profile["capacity_factor_by_slot"],
            "pv_generation_kwh_by_slot": profile["pv_generation_kwh_by_slot"],
        }
        out_path = output_dir / f"{depot_id}_{date}_{int(slot_minutes)}min.json"
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        written.append(out_path)
    return written


def parse_capacity_map(path: Optional[Path]) -> Dict[str, float]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as f:
        doc = json.load(f)
    out: Dict[str, float] = {}
    if isinstance(doc, dict):
        for k, v in doc.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
    return out
