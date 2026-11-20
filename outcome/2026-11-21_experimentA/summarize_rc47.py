"""Experiment A (rc47, ef1685c6, hourly re-plan 600 s): value of PV forecast information, assignment fixed. DIAGNOSTIC.

Each case holds the rc42 adopted 400 kW assignment of its season fixed (phase1_charging_only),
uses the rule battery and tariff A, and changes only the PV the day-ahead plan and the hourly
re-plans see: F0 climatology, F1 weather class known (oracle), F2 actual (hindsight).
Execution always uses the Solcast actuals.

Reads output/midterm_20261128/rc47/af{0,1,2}_{200,400}_r600/<week>/ (weekly_operator collect) and
writes rc47_experimentA.json and rc47_experimentA.md next to this script.

Reported cost excludes vehicle usage (identical under a fixed assignment, checked per case):
  total_cost - vehicle_usage_cost - fuel_cost + fuel consumed x 150 - CO2 kg x 1 + basic charge
The BESS drawdown (start - end of the executed week) is shown valued at 0 JPY/kWh (PV unit cost,
researcher 11/21) and at 17.43 JPY/kWh (tariff A energy rate); neither changes the accounting JSON.
"""
import collections
import glob
import json
from pathlib import Path

OPS = Path("C:/master-course/output/midterm_20261128")
HERE = Path(__file__).resolve().parent
SEASON = {"2025-01-06": "winter", "2025-04-07": "spring", "2025-07-07": "summer"}
INFO = {"af0": "F0 climatology", "af1": "F1 class known (oracle)", "af2": "F2 actual (hindsight)"}
BASIC = lambda kw: kw * 2530 * 0.85 * 12 / 52  # noqa: E731  JPY/week, as in the pillar-A deck
VALUES = (0.0, 17.43)


def run_dir(case_dir):
    runs = glob.glob(str(case_dir / "original/output/*/run_*"))
    return Path(runs[0]) if len(runs) == 1 else None


def bess_start_end(plan):
    start = end = 0.0
    for depot, by_slot in plan["bess_soc_kwh_by_depot_slot"].items():
        slots = sorted(by_slot, key=int)
        first = slots[0]
        out_flow = plan["bess_to_bus_kwh_by_depot_slot"].get(depot, {}).get(first, 0.0)
        in_flow = plan["pv_to_bess_kwh_by_depot_slot"].get(depot, {}).get(first, 0.0)
        # bess_soc is the inventory after the slot.
        start += by_slot[first] + out_flow / 0.95 - 0.95 * in_flow
        end += by_slot[slots[-1]]
    return start, end


def assignment_key(duties):
    """Multiset of (vehicle type, ordered trip ids); duty and vehicle ids may be renamed."""
    def trips(d):
        return tuple(d["trip_ids"]) if "trip_ids" in d else tuple(leg["trip_id"] for leg in d["legs"])
    return collections.Counter((d["vehicle_type"], trips(d)) for d in duties)


def shortfall_kwh(acct):
    total = 0.0
    for vehicle in acct.get("bev_executed_target_audit", {}).get("vehicles", {}).values():
        total += sum(float(d.get("shortfall_to_target_kwh") or 0.0)
                     for d in (vehicle.get("daily_deadlines") or {}).values())
    return total


def read_case(case_dir):
    name, week = case_dir.parent.name, case_dir.name
    row = {"case": f"{case_dir.parent.parent.name}/{name}/{week}", "info": INFO[name[:3]], "grid_limit_kw": int(name[4:7]), "week": week,
           "season": SEASON[week], "status": "NOT_COLLECTED"}
    summary, run = case_dir / "results/weekly_summary.json", run_dir(case_dir)
    if not summary.exists() or run is None:
        return row
    w = json.loads(summary.read_text(encoding="utf-8"))
    roll = json.loads((run / "rolling_hourly_chain/rolling_chain_summary.json").read_text(encoding="utf-8"))
    phys = json.loads((run / "physical_schedule_validation.json").read_text(encoding="utf-8"))
    plan = json.loads((run / "rolling_hourly_chain/executed_plan.json").read_text(encoding="utf-8"))
    acct = json.loads((run / "rolling_hourly_chain/executed_day_accounting.json").read_text(encoding="utf-8"))
    seed = json.loads((OPS / f"fixed_seed_rc42_etb400_{week}.json").read_text(encoding="utf-8"))
    steps = collections.Counter(str(json.loads(Path(f).read_text(encoding="utf-8")).get("stage2_solver_status"))
                                for f in glob.glob(str(run / "rolling_hourly_chain/step_*/hourly_summary.json")))
    fixed = assignment_key(plan["duties"]) == assignment_key(seed["duties"])
    ok = (str(w.get("evaluation_status", "")).startswith("VERIFIED") and roll.get("chain_accepted")
          and phys.get("status") == "VALID")
    start, end = bess_start_end(plan)
    row.update({k: w[k] for k in ("total_cost", "vehicle_usage_cost", "electricity_cost", "fuel_cost",
                                  "contract_overage_cost", "contract_over_limit_kwh", "grid_import_kwh", "peak_grid_kw",
                                  "pv_generated_kwh", "pv_used_total_kwh", "pv_curtailed_kwh", "ice_fuel_consumed_l",
                                  "total_co2_kg", "used_vehicle_day_count", "git_sha")})
    blocking = [] if ok else ["evaluation/rolling/physical gate not passed"]
    if not fixed:
        blocking.append("executed assignment differs from the fixed rc42 seed")
    row.update(status="VERIFIED" if not blocking else "DIAGNOSTIC", blocking=blocking, assignment_fixed=fixed,
               bess_start_kwh=start, bess_end_kwh=end, morning_shortfall_kwh=shortfall_kwh(acct),
               bess_to_bus_kwh=acct["cost_breakdown"]["bess_to_bus_kwh"],
               pv_to_bess_kwh=acct["cost_breakdown"]["pv_to_bess_kwh"],
               rolling_steps=sum(steps.values()), rolling_time_limit_steps=steps.get("time_limit", 0))
    base = (w["total_cost"] - w["vehicle_usage_cost"] - w["fuel_cost"] + w["ice_fuel_consumed_l"] * 150.0
            - w["total_co2_kg"] * 1.0 + BASIC(row["grid_limit_kw"]))
    row["cost_excl_vehicle_jpy"] = {f"bess_{v:g}": base + v * (start - end) for v in VALUES}
    return row


def main():
    rows = [read_case(Path(p)) for p in sorted(glob.glob(str(OPS / "rc47" / "af[012]_[0-9][0-9][0-9]_r600" / "20*")))]
    (HERE / "rc47_experimentA.json").write_text(
        json.dumps({"label": "DIAGNOSTIC rc47 (ef1685c6, hourly re-plan 600 s) experiment A, tariff A, assignment fixed to rc42 etb400",
                    "cases": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    by = {(r["grid_limit_kw"], r["week"], r["info"][:2]): r for r in rows}
    lines = ["# 実験A 太陽光の予報の情報の価値（rc47、ef1685c6、毎時の立て直し600秒、料金A、便割当固定、DIAGNOSTIC）", "",
             "費用は車両使用費を除く（燃料は使った量×150円、CO₂の費用を除き、基本料金を足す）。"
             "蓄電池の取り崩し（最初−最後）は0円と17.43円の両方で評価。単位：費用は万円/週、電力量は kWh。", "",
             "| 上限 | 季節 | 予報 | 費用(0円) | 費用(17.43円) | 買電 | 超過 | 最大受電 kW | 捨てた太陽光 | 蓄電池 最初→最後 | 朝の不足 | CO₂ kg | 状態 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for g in (200, 400):
        for w in SEASON:
            for f in ("F0", "F1", "F2"):
                r = by.get((g, w, f))
                if r is None or "cost_excl_vehicle_jpy" not in r:
                    lines.append(f"| {g} | {SEASON[w]} | {f} | — | — | — | — | — | — | — | — | — | {(r or {}).get('status', '—')} |")
                    continue
                c = r["cost_excl_vehicle_jpy"]
                lines.append(
                    f"| {g} | {SEASON[w]} | {f} | {c['bess_0'] / 1e4:,.1f} | {c['bess_17.43'] / 1e4:,.1f} | "
                    f"{r['grid_import_kwh']:,.0f} | {r['contract_over_limit_kwh']:,.0f} | {r['peak_grid_kw']:,.0f} | "
                    f"{r['pv_curtailed_kwh']:,.0f} | {r['bess_start_kwh']:,.0f}→{r['bess_end_kwh']:,.0f} | "
                    f"{r['morning_shortfall_kwh']:,.1f} | {r['total_co2_kg']:,.0f} | {r['status']} |")
    (HERE / "rc47_experimentA.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(collections.Counter(r["status"] for r in rows))


if __name__ == "__main__":
    main()
