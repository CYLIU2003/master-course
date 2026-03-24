from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from src.optimization.common.solcast_pv_profiles import inspect_csv_time_coverage


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


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def sync_registry(
    *,
    registry_path: Path,
    raw_dir: Path,
    timezone_offset: str,
    fallback_period_min: int,
    time_column: str,
    irradiance_column: str,
) -> Dict[str, int]:
    registry = _load_json(registry_path)
    depots = list(registry.get("depots") or [])

    updated = 0
    missing = 0
    cached = 0

    for item in depots:
        if not isinstance(item, dict):
            continue
        depot_id = str(item.get("depot_id") or "").strip()
        if not depot_id:
            continue

        try:
            csv_path = _resolve_csv_path(raw_dir, depot_id)
        except FileNotFoundError:
            item["acquisition_status"] = "missing_csv"
            item["acquired_at"] = ""
            item["raw_csv_path"] = item.get("raw_csv_path") or ""
            item["record_count"] = 0
            item["available_dates"] = []
            item["min_period_end"] = None
            item["max_period_end"] = None
            missing += 1
            updated += 1
            continue

        coverage = inspect_csv_time_coverage(
            csv_path,
            timezone_offset=timezone_offset,
            fallback_period_min=fallback_period_min,
            time_column=time_column.strip() or None,
            irradiance_column=irradiance_column.strip() or None,
        )
        item["raw_csv_path"] = csv_path.as_posix()
        item["acquisition_status"] = "cached"
        item["acquired_at"] = datetime.fromtimestamp(csv_path.stat().st_mtime, tz=timezone.utc).isoformat()
        item["record_count"] = int(coverage.get("record_count") or 0)
        item["available_dates"] = list(coverage.get("available_dates") or [])
        item["min_period_end"] = coverage.get("min_period_end")
        item["max_period_end"] = coverage.get("max_period_end")
        item["time_column"] = coverage.get("time_column")
        item["irradiance_column"] = coverage.get("irradiance_column")

        cached += 1
        updated += 1

    registry["last_synced_at"] = datetime.now(timezone.utc).isoformat()
    registry["raw_dir"] = raw_dir.as_posix()
    registry["sync_summary"] = {
        "updated_depots": updated,
        "cached_csv_depots": cached,
        "missing_csv_depots": missing,
    }

    _save_json(registry_path, registry)
    return registry["sync_summary"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Solcast acquisition registry by checking cached CSV files")
    parser.add_argument(
        "--registry",
        default="data/external/solcast_raw/solcast_acquisition_registry_tokyu_all.json",
        help="Registry JSON path",
    )
    parser.add_argument(
        "--raw-dir",
        default="data/external/solcast_raw",
        help="Directory containing Solcast CSV cache files",
    )
    parser.add_argument("--timezone", default="+09:00")
    parser.add_argument("--fallback-period-min", type=int, default=60)
    parser.add_argument("--time-column", default="")
    parser.add_argument("--irradiance-column", default="")
    args = parser.parse_args()

    summary = sync_registry(
        registry_path=Path(args.registry),
        raw_dir=Path(args.raw_dir),
        timezone_offset=str(args.timezone),
        fallback_period_min=int(args.fallback_period_min),
        time_column=str(args.time_column),
        irradiance_column=str(args.irradiance_column),
    )
    print(f"[ok] synced registry: {args.registry}")
    print(
        "[ok] updated={updated_depots}, cached={cached_csv_depots}, missing={missing_csv_depots}".format(
            **summary
        )
    )


if __name__ == "__main__":
    main()
