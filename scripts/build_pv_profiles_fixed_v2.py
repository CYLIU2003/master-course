#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

DEFAULT_DEPOT_CAPACITY_KW: Dict[str, float] = {
    "awashima": 234.5,
    "shimouma": 200.0,
    "tsurumaki": 675.9,
    "seta": 405.1,
    "meguro": 480.8,
    "ebara": 200.0,
    "ikegami": 200.0,
    "takatsu": 200.0,
    "nippa": 200.0,
    "aobadai": 200.0,
    "nijigaoka": 200.0,
    "higashiyamata": 200.0,
}

@dataclass(frozen=True)
class BuildConfig:
    raw_dir: Path
    out_dir: Path
    slot_minutes: int
    mode: str
    system_efficiency: float
    capacity_default_kw: float
    capacity_map: Dict[str, float]
    dates: Optional[List[str]]
    overwrite: bool

def read_capacity_map(path: Optional[Path]) -> Dict[str, float]:
    if path is None:
        return dict(DEFAULT_DEPOT_CAPACITY_KW)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("capacity-map JSON must be an object mapping depot_id -> capacity_kw")
    return {str(k): float(v) for k, v in data.items()}

def iter_raw_csvs(raw_dir: Path) -> Iterable[Path]:
    yield from sorted(raw_dir.glob("*_60min.csv"))

def parse_iso_dt(text: str) -> datetime:
    return datetime.fromisoformat(text.strip())

def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))

def compute_cf(row: Dict[str, str], mode: str, efficiency: float) -> float:
    source_key = "gti" if mode == "gti" else "ghi"
    irradiance = float((row.get(source_key) or 0.0) or 0.0)
    cf = (irradiance / 1000.0) * efficiency
    return clamp(cf, 0.0, 1.0)

def depot_id_from_csv_name(path: Path) -> str:
    parts = path.stem.split("_")
    if len(parts) < 4:
        raise ValueError(f"Unexpected raw CSV filename: {path.name}")
    return "_".join(parts[:-3])

def group_rows_by_date(csv_path: Path) -> Dict[str, List[Dict[str, str]]]:
    text = csv_path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(text.splitlines())
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for row in reader:
        period_end = (row.get("period_end") or "").strip()
        if not period_end:
            continue
        date_key = parse_iso_dt(period_end).date().isoformat()
        grouped.setdefault(date_key, []).append(row)
    return grouped

def build_daily_profile(
    depot_id: str,
    date_key: str,
    rows: List[Dict[str, str]],
    csv_path: Path,
    cfg: BuildConfig,
) -> Dict[str, object]:
    rows_sorted = sorted(rows, key=lambda r: parse_iso_dt(r["period_end"]))
    delta_h = cfg.slot_minutes / 60.0
    capacity_kw = float(cfg.capacity_map.get(depot_id, cfg.capacity_default_kw))

    capacity_factor_by_slot: List[float] = []
    pv_generation_kwh_by_slot: List[float] = []

    for row in rows_sorted:
        cf = compute_cf(row, cfg.mode, cfg.system_efficiency)
        pv_kwh = capacity_kw * cf * delta_h
        capacity_factor_by_slot.append(round(cf, 6))
        pv_generation_kwh_by_slot.append(round(pv_kwh, 6))

    return {
        "depot_id": depot_id,
        "date": date_key,
        "slot_minutes": cfg.slot_minutes,
        "source_csv": str(csv_path),
        "capacity_kw": capacity_kw,
        "capacity_factor_by_slot": capacity_factor_by_slot,
        "pv_generation_kwh_by_slot": pv_generation_kwh_by_slot,
        "metadata": {
            "mode": cfg.mode,
            "system_efficiency": cfg.system_efficiency,
            "source_columns": ["period_end", cfg.mode, "air_temp"],
            "note": "PV generation estimated from Solcast irradiance using a simple capacity-factor model."
        },
    }

def write_json(path: Path, data: Dict[str, object], overwrite: bool) -> str:
    if path.exists() and not overwrite:
        return "exists"
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return "written"

def main() -> int:
    parser = argparse.ArgumentParser(description="Build daily PV profile JSON files from Solcast CSVs.")
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path(r"C:\master-course\data\external\solcast_raw"),
        help=r"Folder containing renamed Solcast raw CSV files. Default: C:\master-course\data\external\solcast_raw",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(r"C:\master-course\data\derived\pv_profiles"),
        help=r"Output folder for daily JSON profiles. Default: C:\master-course\data\derived\pv_profiles",
    )
    parser.add_argument("--slot-minutes", type=int, default=60)
    parser.add_argument("--mode", choices=["gti", "ghi"], default="gti")
    parser.add_argument("--system-efficiency", type=float, default=0.85)
    parser.add_argument("--capacity-default-kw", type=float, default=1.0)
    parser.add_argument("--capacity-map", type=Path, default=None)
    parser.add_argument("--dates", nargs="*", default=None)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    capacity_map = read_capacity_map(args.capacity_map)
    cfg = BuildConfig(
        raw_dir=args.raw_dir,
        out_dir=args.out_dir,
        slot_minutes=args.slot_minutes,
        mode=args.mode,
        system_efficiency=float(args.system_efficiency),
        capacity_default_kw=float(args.capacity_default_kw),
        capacity_map=capacity_map,
        dates=list(args.dates) if args.dates else None,
        overwrite=bool(args.overwrite),
    )

    cfg.out_dir.mkdir(parents=True, exist_ok=True)

    if not cfg.raw_dir.exists():
        print(f"[ERROR] Raw CSV folder not found: {cfg.raw_dir}")
        return 1

    total_written = 0
    total_exists = 0
    total_csv = 0

    for csv_path in iter_raw_csvs(cfg.raw_dir):
        total_csv += 1
        depot_id = depot_id_from_csv_name(csv_path)
        grouped = group_rows_by_date(csv_path)

        for date_key, rows in sorted(grouped.items()):
            if cfg.dates and date_key not in cfg.dates:
                continue
            daily = build_daily_profile(
                depot_id=depot_id,
                date_key=date_key,
                rows=rows,
                csv_path=csv_path,
                cfg=cfg,
            )
            out_name = f"{depot_id}_{date_key}_{cfg.slot_minutes}min.json"
            out_path = cfg.out_dir / out_name
            status = write_json(out_path, daily, overwrite=cfg.overwrite)
            if status == "written":
                total_written += 1
            else:
                total_exists += 1
            print(f"[{status.upper()}] {csv_path.name} -> {out_path.name}")

    print()
    print(f"Raw CSV files found: {total_csv}")
    print(f"JSON files written: {total_written}")
    print(f"JSON files skipped (already existed): {total_exists}")
    print(f"Output folder: {cfg.out_dir}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
