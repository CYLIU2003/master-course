from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
from pathlib import Path
from typing import List, Tuple


def _parse_iso(ts: str) -> dt.datetime:
    ts = ts.strip().replace("Z", "+00:00")
    return dt.datetime.fromisoformat(ts)


def _pick_columns(header: List[str]) -> Tuple[str, str]:
    hmap = {h.lower(): h for h in header}
    time_candidates = ["period_end", "timestamp", "time", "datetime"]
    pv_candidates = ["pv_estimate", "pv_kw", "generation_kw", "power_kw"]
    t_col = next((hmap[k] for k in time_candidates if k in hmap), header[0])
    p_col = next((hmap[k] for k in pv_candidates if k in hmap), header[1] if len(header) > 1 else header[0])
    return t_col, p_col


def build_profile(source_csv: Path, date_str: str, slot_minutes: int) -> List[float]:
    target_date = dt.date.fromisoformat(date_str)
    day_values: List[float] = [0.0] * (24 * 60 // slot_minutes)
    with source_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return day_values
        t_col, p_col = _pick_columns(list(reader.fieldnames))
        for row in reader:
            try:
                t = _parse_iso(str(row.get(t_col) or ""))
            except Exception:
                continue
            # Input is expected in JST already; if timezone-aware, convert to JST.
            if t.tzinfo is not None:
                t = t.astimezone(dt.timezone(dt.timedelta(hours=9))).replace(tzinfo=None)
            if t.date() != target_date:
                continue
            kw = max(float(row.get(p_col) or 0.0), 0.0)
            idx = (t.hour * 60 + t.minute) // slot_minutes
            if 0 <= idx < len(day_values):
                day_values[idx] += kw

    # Convert kW sample sum to slot-energy [kWh] by assuming one sample per slot.
    return [round(v * (slot_minutes / 60.0), 6) for v in day_values]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build depot PV profile (kWh by slot) from Solcast-like CSV")
    parser.add_argument("--source-csv", required=True)
    parser.add_argument("--depot-id", required=True)
    parser.add_argument("--date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--slot-minutes", type=int, default=30)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    series = build_profile(Path(args.source_csv), args.date, args.slot_minutes)
    payload = {
        "depot_id": args.depot_id,
        "date": args.date,
        "slot_minutes": int(args.slot_minutes),
        "pv_generation_kwh_by_slot": series,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
