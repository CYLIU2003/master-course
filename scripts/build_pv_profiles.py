from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sys
from pathlib import Path
from typing import Dict, List

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from src.optimization.common.solcast_pv_profiles import (
    build_daily_profiles_from_csv,
    export_depot_coordinates,
    parse_capacity_map,
)


def _cmd_export_coordinates(args: argparse.Namespace) -> int:
    payload = export_depot_coordinates(
        master_path=Path(args.depot_master),
        output_path=Path(args.output),
    )
    print(f"[ok] exported coordinates: {args.output}")
    print(f"[ok] depot count: {payload.get('count', 0)}")
    return 0


def _load_coordinates(path: Path) -> List[Dict[str, object]]:
    with path.open("r", encoding="utf-8") as f:
        doc = json.load(f)
    if isinstance(doc, dict) and isinstance(doc.get("coordinates"), list):
        return [item for item in doc["coordinates"] if isinstance(item, dict)]
    if isinstance(doc, list):
        return [item for item in doc if isinstance(item, dict)]
    raise ValueError(f"invalid coordinate list format: {path}")


def _resolve_csv_path(raw_dir: Path, depot_id: str) -> Path:
    patterns = (
        f"{depot_id}.csv",
        f"{depot_id}_*.csv",
        f"*_{depot_id}.csv",
        f"*{depot_id}*.csv",
    )
    for pattern in patterns:
        candidates = sorted(raw_dir.glob(pattern))
        if candidates:
            return candidates[0]
    raise FileNotFoundError(f"no Solcast CSV found for depot_id={depot_id} in {raw_dir}")


def _cmd_build_daily(args: argparse.Namespace) -> int:
    coord_entries = _load_coordinates(Path(args.coordinates))
    raw_dir = Path(args.raw_dir)
    out_dir = Path(args.output_dir)
    capacity_map = parse_capacity_map(Path(args.capacity_map)) if args.capacity_map else {}

    missing: List[str] = []
    written_count = 0
    depot_count = 0

    for item in coord_entries:
        depot_id = str(item.get("depot_id") or "").strip()
        if not depot_id:
            continue
        depot_count += 1
        try:
            csv_path = _resolve_csv_path(raw_dir, depot_id)
        except FileNotFoundError:
            missing.append(depot_id)
            continue

        pv_capacity_kw = float(capacity_map.get(depot_id, args.default_pv_capacity_kw))
        files = build_daily_profiles_from_csv(
            depot_id=depot_id,
            csv_path=csv_path,
            output_dir=out_dir,
            dates=[str(d).strip() for d in args.dates.split(",") if str(d).strip()],
            slot_minutes=int(args.slot_minutes),
            timezone_offset=str(args.timezone),
            pv_capacity_kw=pv_capacity_kw,
            fallback_period_min=int(args.fallback_period_min),
            time_column=str(args.time_column).strip() if args.time_column else None,
            irradiance_column=str(args.irradiance_column).strip() if args.irradiance_column else None,
        )
        written_count += len(files)

    print(f"[ok] depots in coordinate list: {depot_count}")
    print(f"[ok] generated daily profile files: {written_count}")
    if missing:
        print(f"[warn] missing raw CSV for {len(missing)} depots: {', '.join(sorted(missing))}")
        if args.require_all_depots:
            return 2
    return 0


def _cmd_init_registry(args: argparse.Namespace) -> int:
    coord_entries = _load_coordinates(Path(args.coordinates))
    payload = {
        "registry_version": "2026-03-24",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_coordinates": str(args.coordinates),
        "solcast_dataset": {
            "provider": "Solcast",
            "product": "Historical Time Series",
            "granularity_minutes": int(args.slot_minutes),
            "timezone": str(args.timezone),
            "parameters": [str(p).strip() for p in str(args.parameters).split(",") if str(p).strip()],
        },
        "usage": {
            "raw_dir": "data/external/solcast_raw",
            "derived_dir": "data/derived/pv_profiles",
            "scenario_target": "simulation_config.depot_energy_assets[].pv_generation_kwh_by_slot",
        },
        "depots": [],
    }

    for item in coord_entries:
        depot_id = str(item.get("depot_id") or "").strip()
        if not depot_id:
            continue
        payload["depots"].append(
            {
                "depot_id": depot_id,
                "name": str(item.get("name") or depot_id),
                "lat": float(item.get("lat")),
                "lon": float(item.get("lon")),
                "raw_csv_path": f"data/external/solcast_raw/{depot_id}_YYYY_full_{int(args.slot_minutes)}min.csv",
                "acquisition_status": "pending_download",
                "acquired_at": "",
                "used_dates": [str(d).strip() for d in str(args.dates).split(",") if str(d).strip()],
            }
        )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[ok] wrote acquisition registry: {out}")
    print(f"[ok] depots recorded: {len(payload['depots'])}")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Export depot coordinates and build per-depot daily PV profiles from cached Solcast CSV files",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_export = sub.add_parser("export-coordinates", help="Export depot coordinate list from depot master JSON")
    p_export.add_argument(
        "--depot-master",
        default="tokyu_bus_depots_master_full.json",
        help="Depot master JSON path",
    )
    p_export.add_argument(
        "--output",
        default="data/external/solcast_raw/depot_coordinates_tokyu_all.json",
        help="Output coordinate list JSON",
    )
    p_export.set_defaults(func=_cmd_export_coordinates)

    p_build = sub.add_parser("build-daily", help="Build daily depot PV JSON files from cached Solcast CSV files")
    p_build.add_argument(
        "--coordinates",
        default="data/external/solcast_raw/depot_coordinates_tokyu_all.json",
        help="Coordinate list JSON generated by export-coordinates",
    )
    p_build.add_argument(
        "--raw-dir",
        default="data/external/solcast_raw",
        help="Directory containing Solcast CSV cache files",
    )
    p_build.add_argument(
        "--output-dir",
        default="data/derived/pv_profiles",
        help="Directory to write daily per-depot JSON files",
    )
    p_build.add_argument(
        "--dates",
        required=True,
        help="Comma-separated target dates (YYYY-MM-DD)",
    )
    p_build.add_argument("--slot-minutes", type=int, default=60, choices=[5, 10, 15, 30, 60])
    p_build.add_argument("--timezone", default="+09:00", help="Target timezone offset, e.g. +09:00")
    p_build.add_argument(
        "--default-pv-capacity-kw",
        type=float,
        default=1.0,
        help="Default PV capacity [kW] used to convert CF into kWh slots",
    )
    p_build.add_argument(
        "--capacity-map",
        default="",
        help="Optional JSON map {depot_id: pv_capacity_kw}",
    )
    p_build.add_argument(
        "--fallback-period-min",
        type=int,
        default=60,
        help="Record interval minutes when CSV period column is missing",
    )
    p_build.add_argument("--time-column", default="", help="Optional explicit timestamp column name")
    p_build.add_argument("--irradiance-column", default="", help="Optional explicit irradiance column name")
    p_build.add_argument(
        "--require-all-depots",
        action="store_true",
        help="Fail when any depot in coordinate list has no cached CSV",
    )
    p_build.set_defaults(func=_cmd_build_daily)

    p_registry = sub.add_parser("init-registry", help="Generate Solcast acquisition registry template for all depots")
    p_registry.add_argument(
        "--coordinates",
        default="data/external/solcast_raw/depot_coordinates_tokyu_all.json",
        help="Coordinate list JSON generated by export-coordinates",
    )
    p_registry.add_argument(
        "--output",
        default="data/external/solcast_raw/solcast_acquisition_registry_tokyu_all.json",
        help="Output registry JSON path",
    )
    p_registry.add_argument("--slot-minutes", type=int, default=60, choices=[5, 10, 15, 30, 60])
    p_registry.add_argument("--timezone", default="+09:00")
    p_registry.add_argument(
        "--parameters",
        default="gti,ghi,air_temp",
        help="Comma-separated Solcast parameters to request",
    )
    p_registry.add_argument(
        "--dates",
        default="",
        help="Comma-separated target dates used in derived daily JSON generation",
    )
    p_registry.set_defaults(func=_cmd_init_registry)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    exit_code = int(args.func(args))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
