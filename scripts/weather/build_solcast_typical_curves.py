from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.preprocess.weather.solcast_typical import (  # noqa: E402
    build_representative_curve_payload,
    load_solcast_daily_pv_profiles,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build sunny/cloudy/rainy representative PV curves from local Solcast profile JSONs."
    )
    parser.add_argument("--profile-dir", required=True, help="Directory containing daily Solcast PV profile JSONs.")
    parser.add_argument("--glob", default="*_60min.json", help="Glob pattern under --profile-dir.")
    parser.add_argument("--depot-id", default=None, help="Optional depot_id filter.")
    parser.add_argument("--station-id", default="", help="Station/audit id to store in the curve payload.")
    parser.add_argument("--station-name", default="", help="Station/audit name to store in the curve payload.")
    parser.add_argument("--out", required=True, help="Output representative curve JSON path.")
    args = parser.parse_args()

    profiles = load_solcast_daily_pv_profiles(
        profile_dir=args.profile_dir,
        glob_pattern=args.glob,
        depot_id=args.depot_id,
    )
    payload = build_representative_curve_payload(
        profiles,
        station_id=args.station_id,
        station_name=args.station_name,
        depot_id=args.depot_id,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote: {out_path}")
    for weather_class, curve in sorted(payload.get("curves", {}).items()):
        print(
            f"{weather_class}: source_count={curve.get('source_profile_count')} "
            f"daily_cf_hours_avg={curve.get('daily_cf_hours_avg')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
