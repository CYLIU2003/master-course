"""Audit (DIAGNOSTIC, read-only): how far the Stage 1 charging recourse departs from what Stage 2 can do.

For every verified rc18 case, read the day-ahead result and compare
  * Stage 1 recourse charging (charge_power_kw_by_vehicle_slot, 15-min slots) with the
    day-ahead vehicle timeline: energy placed in slots that the bus spends entirely on a
    service trip or deadhead (Stage 2 can never charge there),
  * Stage 1 recourse grid import / overage with the day-ahead Stage 2 plan.
Stage 1 is meant to be a relaxation of Stage 2, so charging in away slots is allowed by
the model where its away fraction is below 1 (e.g. fragments joined away from the depot);
this script measures how large that slack is. Nothing is solved or rewritten.
Run from the repository root:
  .venv/Scripts/python.exe outcome/2026-11-12_three_party/audit_stage1_recourse.py
"""
import csv
import datetime as dt
import glob
import json
from pathlib import Path

ROOT = Path("output/midterm_20261128/rc18")
OUT = Path(__file__).with_name("audit_stage1_recourse_rc18.json")
SLOT_MIN = 15


def day_ahead_dir(limit, week):
    runs = [Path(p).parent for p in glob.glob(str(ROOT / f"wk{limit:03d}" / week / "original/output/*/*/canonical_solver_result.json"))]
    if len(runs) != 1:
        raise SystemExit(f"expected one day-ahead run for {limit} {week}, found {len(runs)}")
    return runs[0]


def away_minutes(timeline_csv, start):
    """Minutes per (vehicle, slot) spent on service trips or deadheads in the day-ahead plan."""
    minutes = {}
    with open(timeline_csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["is_service"] != "True" and r["is_deadhead"] != "True":
                continue
            a = dt.datetime.fromisoformat(r["start_time"])
            b = dt.datetime.fromisoformat(r["end_time"])
            t = a
            while t < b:
                slot = int((t - start).total_seconds() // (SLOT_MIN * 60))
                slot_end = start + dt.timedelta(minutes=SLOT_MIN * (slot + 1))
                step = min(b, slot_end)
                key = (r["vehicle_id"], slot)
                minutes[key] = minutes.get(key, 0.0) + (step - t).total_seconds() / 60
                t = step
    return minutes


def depot_sum(by_depot_slot):
    return sum(v for slots in (by_depot_slot or {}).values() for v in slots.values())


def main():
    rows = []
    for limit in (90, 200, 400, 800):
        for week in ("2025-01-06", "2025-04-07", "2025-07-07"):
            run = day_ahead_dir(limit, week)
            result = json.loads((run / "canonical_solver_result.json").read_text(encoding="utf-8"))
            recourse = result["metadata"]["stage1_time_indexed_energy_recourse_result"]
            start = dt.datetime.fromisoformat(week)
            away = away_minutes(run / "vehicle_timelines.csv", start)
            total = full = partial = 0.0
            for vehicle, slots in recourse["charge_power_kw_by_vehicle_slot"].items():
                for slot, kw in slots.items():
                    kwh = kw * SLOT_MIN / 60
                    total += kwh
                    m = away.get((vehicle, int(slot)), 0.0)
                    if m >= SLOT_MIN - 1e-6:
                        full += kwh
                    elif m > 0:
                        partial += kwh
            s2_import = depot_sum(result.get("grid_to_bus_kwh_by_depot_slot")) + depot_sum(result.get("grid_to_bess_kwh_by_depot_slot"))
            rows.append({
                "grid_limit_kw": limit, "week": week, "run": str(run),
                "stage1_recourse_charge_kwh": total,
                "stage1_charge_in_fully_away_slots_kwh": full,
                "stage1_charge_in_partly_away_slots_kwh": partial,
                "fully_away_share": full / total if total else None,
                "stage1_recourse_grid_import_kwh": recourse.get("grid_import_kwh"),
                "stage1_recourse_overage_kwh": recourse.get("contract_overage_kwh"),
                "stage2_day_ahead_grid_import_kwh": s2_import,
                "stage2_day_ahead_overage_kwh": depot_sum(result.get("contract_over_limit_kwh_by_depot_slot")),
            })
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    print("limit week  S1charge  fullyAway(share)  partlyAway  S1import S2import  S1over S2over")
    for r in rows:
        print(f"{r['grid_limit_kw']:4d} {r['week']} {r['stage1_recourse_charge_kwh']:8.0f} {r['stage1_charge_in_fully_away_slots_kwh']:7.0f}({r['fully_away_share']:.1%}) "
              f"{r['stage1_charge_in_partly_away_slots_kwh']:7.0f} {r['stage1_recourse_grid_import_kwh']:8.0f} {r['stage2_day_ahead_grid_import_kwh']:8.0f} "
              f"{r['stage1_recourse_overage_kwh']:7.0f} {r['stage2_day_ahead_overage_kwh']:6.0f}")


if __name__ == "__main__":
    main()
