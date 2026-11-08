"""Collect the numbers the 11/12 deck and the poster read from the latest-version pillar A runs.

Latest version = rc33 (7dc38d95) and rc35 (9a0fe044) with planning_pv_forecast_scale 1.0; rc35 differs
from rc33 only by Stage 2 IntegralityFocus=1 (and the no-op scale 1.0). Every case records its version.
Each (grid limit, week) is solved from two Stage 1 start points (BEV-heavy "bev", ICE-heavy "ice");
the deck's main row is the cheaper of the two verified runs by `total_cost_fuel_consumed`, the same
basis as the deck's 11/8 tables (evaluate_multiface.py): the executed-day accounting total
(`total_cost` = executed_day_accounting) with diesel valued by the litres burnt (150 JPY/L) instead of
the litres bought, so fuel left in the tanks at week end is not a cost. This is a post-hoc view; the
accounting total is kept in every row as `total_cost`. Both start rows are kept.
600 kW is not run on the latest version.

Inputs (read-only): output/midterm_20261128/<rc33|rc35>/<case>/<week>/results/weekly_summary.json and the
run's rolling chain (executed_plan.json, step_*/hourly_summary.json, rolling_chain_summary.json),
physical_schedule_validation.json. Items that only exist for rc20 (all-diesel estimate, Stage 1 recourse
audits, hindsight runs) are copied from deck_data_rc20.json and stay labelled rc20 in the deck.
Output: deck_data_latest.json next to this file. Nothing is solved or rewritten. DIAGNOSTIC.
Run from the repository root:  .venv/Scripts/python.exe outcome/2026-11-12_three_party/prepare_deck_data_latest.py
"""
import collections
import glob
import json
import re
from pathlib import Path

OPS = Path("output/midterm_20261128")
HERE = Path(__file__).parent
W, S, U = "2025-01-06", "2025-04-07", "2025-07-07"
SEASON = {W: "冬", S: "春", U: "夏"}
LIMITS = (90, 200, 400, 900)
VERSION = {"rc33": "7dc38d95", "rc35": "9a0fe044"}
BANDS = (("05-06", 0, 7), ("07-21", 7, 22), ("22-", 22, 48))
# (limit, week, start) -> case directory relative to OPS. rc33 h090 spring stopped on the Stage 2
# trickle-flow defect fixed in 9a0fe044; its rerun is rc35 a090s10 (ICE-heavy seed, scale 1.0).
CASES = {}
for week in (W, S, U):
    CASES[(90, week, "bev")] = f"rc33/g090/{week}"
    CASES[(90, week, "ice")] = f"rc33/h090/{week}" if week != S else f"rc35/a090s10/{week}"
for limit in (200, 400, 900):
    CASES[(limit, W, "bev")] = f"rc33/g{limit}/{W}" if limit != 400 else f"rc35/a400s10/{W}"
    CASES[(limit, W, "ice")] = f"rc33/h{limit}/{W}"
    for week in (S, U):
        CASES[(limit, week, "bev")] = f"rc35/a{limit}s10/{week}"
        CASES[(limit, week, "ice")] = f"rc35/b{limit}s10/{week}"


def run_dir(case):
    runs = glob.glob(str(OPS / case / "original/output/*/run_*"))
    return Path(runs[0]) if len(runs) == 1 else None


def read_case(limit, week, start, case):
    row = {"grid_limit_kw": limit, "week": week, "season": SEASON[week], "start": start, "case": case,
           "version": VERSION[case.split("/")[0]], "status": "NOT_COLLECTED"}
    summary, run = OPS / case / "results/weekly_summary.json", run_dir(case)
    if not summary.exists() or run is None:
        return row, None
    w = json.loads(summary.read_text(encoding="utf-8"))
    roll = json.loads((run / "rolling_hourly_chain/rolling_chain_summary.json").read_text(encoding="utf-8"))
    phys = json.loads((run / "physical_schedule_validation.json").read_text(encoding="utf-8"))
    duties = json.loads((run / "rolling_hourly_chain/executed_plan.json").read_text(encoding="utf-8"))["duties"]
    steps = collections.Counter(str(json.loads(Path(f).read_text(encoding="utf-8")).get("stage2_solver_status"))
                                for f in glob.glob(str(run / "rolling_hourly_chain/step_*/hourly_summary.json")))
    acct = json.loads((run / "rolling_hourly_chain/executed_day_accounting.json").read_text(encoding="utf-8"))["cost_breakdown"]
    trips = sum(len(d["trip_ids"]) for d in duties)
    bev = sum(len(d["trip_ids"]) for d in duties if d["vehicle_type"] == "BEV")
    ok = (str(w.get("evaluation_status", "")).startswith("VERIFIED") and roll.get("chain_accepted") and phys.get("status") == "VALID")
    row.update({k: w[k] for k in ("total_cost", "vehicle_usage_cost", "electricity_cost", "fuel_cost", "contract_overage_cost",
                                  "contract_over_limit_kwh", "grid_import_kwh", "peak_grid_kw", "pv_generated_kwh",
                                  "pv_used_total_kwh", "pv_curtailed_kwh", "ice_fuel_consumed_l", "total_co2_kg",
                                  "ice_co2_kg", "grid_electricity_co2_kg", "used_vehicle_day_count", "service_km")})
    row["total_cost_fuel_consumed"] = w["total_cost"] - w["fuel_cost"] + w["ice_fuel_consumed_l"] * 150.0
    row.update({"status": "VERIFIED" if ok else "NOT_ACCEPTED", "trips": trips, "bev_trip_share_pct": 100 * bev / trips,
                "bus_charging_kwh": acct["pv_to_bus_kwh"] + acct["bess_to_bus_kwh"] + acct["grid_to_bus_kwh"],
                "rolling_steps": sum(steps.values()), "rolling_time_limit_steps": steps.get("time_limit", 0),
                "stage2_solver_status": w.get("stage2_solver_status")})
    total, diesel = collections.Counter(), collections.Counter()
    for duty in duties:
        for trip in duty["trip_ids"]:
            hour = int(re.search(r"\.(\d{2})(\d{2})$", trip).group(1))
            band = next(name for name, lo, hi in BANDS if lo <= hour < hi)
            total[band] += 1
            diesel[band] += duty["vehicle_type"] != "BEV"
    bands = {b: {"diesel": diesel[b], "total": total[b]} for b, _, _ in BANDS}
    return row, bands


def main():
    pairs, bands = [], {}
    for (limit, week, start), case in sorted(CASES.items()):
        row, b = read_case(limit, week, start, case)
        pairs.append(row)
        bands[(limit, week, start)] = b
    cases, ice, rolling = [], [], []
    for limit in LIMITS:
        for week in (W, S, U):
            two = [r for r in pairs if r["grid_limit_kw"] == limit and r["week"] == week]
            done = [r for r in two if r["status"] == "VERIFIED"]
            if len(done) < 2:
                cases.append({"grid_limit_kw": limit, "week": week, "season": SEASON[week], "status": "PENDING",
                              "verified_starts": [r["start"] for r in done]})
                continue
            best = min(done, key=lambda r: r["total_cost_fuel_consumed"])
            other = next(r for r in done if r is not best)
            cases.append({**best, "selected_start": best["start"], "other_start_total_cost": other["total_cost"], "other_start_total_cost_fuel_consumed": other["total_cost_fuel_consumed"],
                          "other_start_total_co2_kg": other["total_co2_kg"],
                          "other_start_bev_trip_share_pct": other["bev_trip_share_pct"]})
            ice.append({"grid_limit_kw": limit, "week": week, "bands": bands[(limit, week, best["start"])]})
            rolling.append({"grid_limit_kw": limit, "week": week, "steps": best["rolling_steps"],
                            "time_limit": best["rolling_time_limit_steps"]})
    qf2 = []
    for week in (W, S, U):
        rs = [r for r in cases if r["week"] == week and r["status"] == "VERIFIED"]
        if not rs:
            continue
        mean = lambda k: sum(r[k] for r in rs) / len(rs)  # noqa: E731
        qf2.append({"season": SEASON[week], "n": len(rs), "pv_generated": mean("pv_generated_kwh"), "pv_used": mean("pv_used_total_kwh"),
                    "pv_curtailed": mean("pv_curtailed_kwh"), "grid_import": mean("grid_import_kwh"),
                    "bus_charging": mean("bus_charging_kwh"), "grid_share_pct": 100 * mean("grid_import_kwh") / mean("bus_charging_kwh")})
    old = json.loads((HERE / "deck_data_rc20.json").read_text(encoding="utf-8"))
    out = {"versions": VERSION, "limits": list(LIMITS), "cases": cases, "pairs": pairs, "ice_by_hour": ice, "rolling": rolling,
           "qf2": qf2, "diesel": old["diesel"], "audit": old["audit"], "hindsight": old["hindsight"], "first_attempt_failures": [],
           "rc20_only": ["diesel", "audit", "hindsight"]}
    (HERE / "deck_data_latest.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("pairs", sum(r["status"] == "VERIFIED" for r in pairs), "/", len(pairs), "cases",
          sum(r["status"] == "VERIFIED" for r in cases), "/", len(cases))
    for r in pairs:
        if r["status"] != "VERIFIED":
            print("  missing", r["case"], r["status"])


if __name__ == "__main__":
    main()
