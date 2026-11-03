"""Pillar A: share of trips served by diesel buses, by departure-hour band, for the rc18 cases.

Reads each verified case's executed rolling plan (rolling_hourly_chain/executed_plan.json),
takes the departure time from the trailing HHMM of each trip id, and counts trips by band.
Run from the repository root:
  .venv/Scripts/python.exe outcome/2026-11-12_three_party/ice_by_hour.py
"""
import collections
import glob
import json
import re
from pathlib import Path

ROOT = Path("output/midterm_20261128/rc18")
OUT = Path(__file__).with_name("ice_by_hour_rc18.json")
BANDS = (("05-06", 0, 7), ("07-21", 7, 22), ("22-", 22, 48))


def band_of(hour: int) -> str:
    return next(name for name, lo, hi in BANDS if lo <= hour < hi)


def main() -> None:
    rows = []
    for limit in (90, 200, 400, 800):
        for week in ("2025-01-06", "2025-04-07", "2025-07-07"):
            plan = glob.glob(str(ROOT / f"wk{limit:03d}" / week / "original/output/*/*/rolling_hourly_chain/executed_plan.json"))
            if len(plan) != 1:
                raise SystemExit(f"expected one executed plan for {limit} {week}, found {len(plan)}")
            duties = json.loads(Path(plan[0]).read_text(encoding="utf-8"))["duties"]
            total, diesel = collections.Counter(), collections.Counter()
            for duty in duties:
                for trip in duty["trip_ids"]:
                    m = re.search(r"\.(\d{2})(\d{2})$", trip)
                    if not m:
                        raise SystemExit(f"no departure time in trip id {trip}")
                    b = band_of(int(m.group(1)))
                    total[b] += 1
                    if duty["vehicle_type"] != "BEV":
                        diesel[b] += 1
            rows.append({"grid_limit_kw": limit, "week": week, "plan": plan[0],
                         "bands": {b: {"diesel": diesel[b], "total": total[b]} for b, _, _ in BANDS}})
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT, len(rows))


if __name__ == "__main__":
    main()
