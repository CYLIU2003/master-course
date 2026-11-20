"""Pillar B (rc43): rule vs optimized battery, tariff A. DIAGNOSTIC.

Reads each collected case (weekly_operator collect) of
output/midterm_20261128/rc43/<e{o,r}{b,i}NNN>/<week>/ and writes
rc43_comparison.json and rc43_comparison.md next to this script.

Reported total (same as the pillar-A deck, plus the battery term):
  total_cost_fuel_consumed - CO2 kg x 1 JPY/kg + weekly basic charge
  + 17.43 x (BESS energy at the start - at the end of the executed week)
The last term is added to both modes, so a battery drawn down is not free
energy. It is computed here from the executed plan; the executed accounting
JSON is not changed.
"""
import collections
import glob
import json
from pathlib import Path

OPS = Path("C:/master-course/output/midterm_20261128/rc43")
HERE = Path(__file__).resolve().parent
PRICE = 17.43
SEASON = {"2025-01-06": "winter", "2025-04-07": "spring", "2025-07-07": "summer"}
BASIC = lambda kw: kw * 2530 * 0.85 * 12 / 52  # noqa: E731  JPY/week, as in the pillar-A deck


def run_dir(case_dir):
    runs = glob.glob(str(case_dir / "original/output/*/run_*"))
    return Path(runs[0]) if len(runs) == 1 else None


def bess_start_end(run):
    plan = json.loads((run / "rolling_hourly_chain/executed_plan.json").read_text(encoding="utf-8"))
    soc = plan["bess_soc_kwh_by_depot_slot"]
    out = 0.0, 0.0
    for depot, by_slot in soc.items():
        slots = sorted(by_slot, key=int)
        first = slots[0]
        out_flow = plan["bess_to_bus_kwh_by_depot_slot"].get(depot, {}).get(first, 0.0)
        in_flow = plan["pv_to_bess_kwh_by_depot_slot"].get(depot, {}).get(first, 0.0)
        # bess_soc is the inventory after the slot (rc42: 3000 - 83.5/0.95 = 2912.1 after slot 0).
        start = by_slot[first] + out_flow / 0.95 - 0.95 * in_flow
        out = (out[0] + start, out[1] + by_slot[slots[-1]])
    return out


def read_case(case_dir):
    name, week = case_dir.parent.name, case_dir.name
    mode = {"o": "optimized", "r": "rule"}[name[1]]
    row = {"case": f"{name}/{week}", "mode": mode, "grid_limit_kw": int(name[3:]), "week": week,
           "season": SEASON[week], "start": {"b": "bev", "i": "ice"}[name[2]], "status": "NOT_COLLECTED"}
    summary, run = case_dir / "results/weekly_summary.json", run_dir(case_dir)
    if not summary.exists() or run is None:
        return row
    w = json.loads(summary.read_text(encoding="utf-8"))
    roll = json.loads((run / "rolling_hourly_chain/rolling_chain_summary.json").read_text(encoding="utf-8"))
    phys = json.loads((run / "physical_schedule_validation.json").read_text(encoding="utf-8"))
    duties = json.loads((run / "rolling_hourly_chain/executed_plan.json").read_text(encoding="utf-8"))["duties"]
    steps = collections.Counter(str(json.loads(Path(f).read_text(encoding="utf-8")).get("stage2_solver_status"))
                                for f in glob.glob(str(run / "rolling_hourly_chain/step_*/hourly_summary.json")))
    acct = json.loads((run / "rolling_hourly_chain/executed_day_accounting.json").read_text(encoding="utf-8"))["cost_breakdown"]
    ok = (str(w.get("evaluation_status", "")).startswith("VERIFIED") and roll.get("chain_accepted")
          and phys.get("status") == "VALID")
    trips = sum(len(d["trip_ids"]) for d in duties)
    bev = sum(len(d["trip_ids"]) for d in duties if d["vehicle_type"] == "BEV")
    start_kwh, end_kwh = bess_start_end(run)
    row.update({k: w[k] for k in ("total_cost", "vehicle_usage_cost", "electricity_cost", "fuel_cost",
                                  "contract_overage_cost", "contract_over_limit_kwh", "grid_import_kwh", "peak_grid_kw",
                                  "pv_generated_kwh", "pv_used_total_kwh", "pv_curtailed_kwh", "ice_fuel_consumed_l",
                                  "total_co2_kg", "used_vehicle_day_count")})
    row.update(status="VERIFIED" if ok else "NOT_ACCEPTED", trips=trips, bev_trip_share_pct=100 * bev / trips,
               bess_to_bus_kwh=acct["bess_to_bus_kwh"], pv_to_bess_kwh=acct["pv_to_bess_kwh"],
               grid_to_bess_kwh=acct["grid_to_bess_kwh"], bess_start_kwh=start_kwh, bess_end_kwh=end_kwh,
               rolling_steps=sum(steps.values()), rolling_time_limit_steps=steps.get("time_limit", 0))
    row["total_cost_fuel_consumed"] = w["total_cost"] - w["fuel_cost"] + w["ice_fuel_consumed_l"] * 150.0
    row["basic_charge_week_jpy"] = BASIC(row["grid_limit_kw"])
    row["bess_inventory_cost_jpy"] = PRICE * (start_kwh - end_kwh)
    row["total_cost_reported"] = (row["total_cost_fuel_consumed"] - row["total_co2_kg"] * 1.0
                                  + row["basic_charge_week_jpy"] + row["bess_inventory_cost_jpy"])
    return row


def main():
    rows = [read_case(Path(p)) for p in sorted(glob.glob(str(OPS / "e[or][bi][0-9][0-9][0-9]" / "20*")))]
    (HERE / "rc43_comparison.json").write_text(json.dumps({"label": "DIAGNOSTIC rc43 1b8e663d tariff A",
                                                           "cases": rows}, ensure_ascii=False, indent=1) + "\n",
                                               encoding="utf-8")
    by = {(r["grid_limit_kw"], r["week"], r["mode"]): r for r in rows}
    lines = ["# 柱B① 蓄電池：規則と最適化（rc43、料金A、DIAGNOSTIC）", "",
             "総費用＝燃料は使った量×150円、CO₂の費用を除き、基本料金と蓄電池の残量の費用（17.43円×(最初−最後)）を足す。単位：万円/週。", "",
             "| 上限 | 季節 | 規則：総費用 | 最適化：総費用 | 差（最適化−規則） | 規則：買電 kWh | 最適化：買電 kWh | 規則：捨てた太陽光 | 最適化：捨てた太陽光 | 規則：残量 最初→最後 | 最適化：残量 最初→最後 | 状態 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for g in (90, 200, 400, 900):
        for w in SEASON:
            r, o = by.get((g, w, "rule")), by.get((g, w, "optimized"))
            def f(x, k, s=1e4, d=1):
                return f"{x[k] / s:,.{d}f}" if x and k in x else "—"
            diff = (f"{(o['total_cost_reported'] - r['total_cost_reported']) / 1e4:+.1f}"
                    if r and o and "total_cost_reported" in r and "total_cost_reported" in o else "—")
            soc = lambda x: f"{x['bess_start_kwh']:,.0f}→{x['bess_end_kwh']:,.0f}" if x and "bess_end_kwh" in x else "—"  # noqa: E731
            lines.append(f"| {g} | {SEASON[w]} | {f(r, 'total_cost_reported')} | {f(o, 'total_cost_reported')} | {diff} | "
                         f"{f(r, 'grid_import_kwh', 1, 0)} | {f(o, 'grid_import_kwh', 1, 0)} | {f(r, 'pv_curtailed_kwh', 1, 0)} | "
                         f"{f(o, 'pv_curtailed_kwh', 1, 0)} | {soc(r)} | {soc(o)} | "
                         f"{(r or {}).get('status', '—')}/{(o or {}).get('status', '—')} |")
    (HERE / "rc43_comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(collections.Counter((r["mode"], r["status"]) for r in rows))


if __name__ == "__main__":
    main()
