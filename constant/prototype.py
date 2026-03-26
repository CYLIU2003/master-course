#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prototype: Route-profile driven EV/Engine bus operation + cost calculation.

- Reads input.json (schema in ev_route_cost.schema.json)
- Greedy trip assignment (replaceable with MILP/ALNS later)
- SOC simulation for EVs, fuel consumption for engine buses
- Charging during idle at depot with site/charger limits
- Cost:
    capex (dailyized) + diesel + TOU electricity + demand charge + contract penalty (optional)

Outputs (in ./outputs by default):
  - vehicle_operation_timeline.csv
  - vehicle_soc_timeline.csv
  - charging_power_timeline.csv
  - grid_power_timeline.csv
  - cost_breakdown.json
  - trip_assignment.json
  - simulation_summary.md
"""

import json
from pathlib import Path
from datetime import datetime, timedelta

try:
    import pandas as pd
except ImportError as e:
    raise SystemExit("pandas is required. Install: pip install pandas") from e


def parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def dt_range(start: datetime, end: datetime, delta: timedelta):
    t = start
    while t < end:
        yield t
        t += delta


def overlaps(a_start, a_end, b_start, b_end) -> bool:
    return not (a_end <= b_start or b_end <= a_start)


def effective_trip_distance(trip: dict) -> float:
    return float(trip.get("deadhead_distance_before_km", 0) or 0) + float(trip["distance_km"]) + float(trip.get("deadhead_distance_after_km", 0) or 0)


def build_price_series(timestamps, tou_blocks):
    blocks = [(parse_dt(b["start_time"]), parse_dt(b["end_time"]), float(b["price_yen_per_kWh"])) for b in tou_blocks]
    prices = {}
    for t in timestamps:
        p = None
        for s, e, pp in blocks:
            if s <= t < e:
                p = pp
                break
        if p is None:
            p = blocks[-1][2] if blocks else 0.0
        prices[t] = p
    return prices


def vehicle_daily_capex(v: dict) -> float:
    pc = float(v.get("purchase_cost_yen", 0))
    life = float(v.get("lifetime_year", 0) or 0)
    days = float(v.get("operation_days_per_year", 0) or 0)
    rv = float(v.get("residual_value_yen", 0) or 0)
    if life > 0 and days > 0:
        return max(0.0, (pc - rv) / (life * days))
    return 0.0


def compatible(vehicle: dict, trip: dict) -> bool:
    req = trip.get("required_bus_type", "any")
    if req != "any" and vehicle["vehicle_type"] != req:
        return False
    compat = vehicle.get("route_compatibility")
    if compat and trip["route_id"] not in set(compat):
        return False
    return True


def main(input_path="input.json", out_dir="outputs"):
    input_path = Path(input_path)
    data = json.loads(input_path.read_text(encoding="utf-8"))

    settings = data["simulation_settings"]
    delta = timedelta(minutes=int(settings["delta_t_min"]))
    t0 = parse_dt(settings["start_time"])
    t1 = parse_dt(settings["end_time"])
    timestamps = list(dt_range(t0, t1, delta))
    delta_h = delta.total_seconds() / 3600.0

    fleet = data["fleet"]
    trips = data["route_profile"]
    tariffs = data["tariffs"]

    tou_prices = build_price_series(timestamps, tariffs["tou_price_yen_per_kWh"])
    diesel_price = float(tariffs["diesel_price_yen_per_L"])
    demand_charge = float(tariffs["demand_charge_yen_per_kW_month"])
    grid_basic = float(tariffs.get("grid_basic_charge_yen", 0.0))

    # PV series (kWh per slot)
    pv_kWh = {t: 0.0 for t in timestamps}
    for rec in tariffs.get("pv_generation_kWh", []) or []:
        tt = parse_dt(rec["time"])
        if tt in pv_kWh:
            pv_kWh[tt] = float(rec["kWh"])

    trips_sorted = sorted(trips, key=lambda x: parse_dt(x["start_time"]))
    trip_map = {tr["trip_id"]: tr for tr in trips}

    # vehicle occupied intervals: vid -> list[(start,end,trip_id)]
    vehicle_jobs = {v["vehicle_id"]: [] for v in fleet}

    # simple state for feasibility (prototype): initial SOC only (no pre-charging before first trip)
    soc_now = {}
    for v in fleet:
        if v["vehicle_type"] == "ev_bus":
            soc_now[v["vehicle_id"]] = float(v.get("initial_soc", 1.0))

    trip_assignment = {}

    # --- Greedy trip assignment (incremental cost) ---
    for trip in trips_sorted:
        ts = parse_dt(trip["start_time"])
        te = parse_dt(trip["end_time"])
        dist = effective_trip_distance(trip)

        candidates = []
        for v in fleet:
            vid = v["vehicle_id"]
            if not compatible(v, trip):
                continue
            if any(overlaps(ts, te, js, je) for js, je, _ in vehicle_jobs[vid]):
                continue

            feasible = True
            inc_cost = 0.0

            if v["vehicle_type"] == "engine_bus":
                if v.get("diesel_consumption_L_per_km") is not None:
                    lpkm = float(v["diesel_consumption_L_per_km"])
                else:
                    fe = float(v.get("fuel_economy_km_per_L", 0))
                    if fe <= 0:
                        feasible = False
                    else:
                        lpkm = 1.0 / fe
                if feasible:
                    inc_cost = dist * lpkm * diesel_price

            else:  # EV
                kwh_per_km = float(v["energy_consumption_kWh_per_km_base"])
                trip_kWh = dist * kwh_per_km
                usable = float(v["usable_battery_capacity_kWh"])
                min_soc = float(v["min_soc"])
                if usable <= 0:
                    feasible = False
                else:
                    soc_after = soc_now[vid] - (trip_kWh / usable)
                    if soc_after < min_soc - 1e-9:
                        feasible = False
                    else:
                        slot_ts = [t for t in timestamps if ts <= t < te]
                        avg_price = (sum(tou_prices[t] for t in slot_ts) / len(slot_ts)) if slot_ts else list(tou_prices.values())[0]
                        inc_cost = trip_kWh * avg_price

            if feasible:
                candidates.append((inc_cost, v))

        if not candidates:
            raise SystemExit(f"No feasible vehicle for trip {trip['trip_id']} ({trip['route_id']}) {trip['start_time']}")

        candidates.sort(key=lambda x: x[0])
        chosen = candidates[0][1]
        cvid = chosen["vehicle_id"]
        trip_assignment[trip["trip_id"]] = cvid
        vehicle_jobs[cvid].append((ts, te, trip["trip_id"]))

        # update feasibility-only SOC baseline
        if chosen["vehicle_type"] == "ev_bus":
            trip_kWh = dist * float(chosen["energy_consumption_kWh_per_km_base"])
            soc_now[cvid] -= trip_kWh / float(chosen["usable_battery_capacity_kWh"])

    # --- Build time-slot operation timeline ---
    op_rows = []
    ev_running_kWh = {v["vehicle_id"]: {t: 0.0 for t in timestamps} for v in fleet if v["vehicle_type"] == "ev_bus"}
    engine_running_L = {v["vehicle_id"]: {t: 0.0 for t in timestamps} for v in fleet if v["vehicle_type"] == "engine_bus"}

    for v in fleet:
        vid = v["vehicle_id"]
        jobs = vehicle_jobs[vid]
        for t in timestamps:
            state = "idle"
            trip_id = ""
            for js, je, jid in jobs:
                if js <= t < je:
                    state = "running"
                    trip_id = jid
                    break

            op_rows.append({
                "time": t.isoformat(timespec="minutes"),
                "vehicle_id": vid,
                "vehicle_type": v["vehicle_type"],
                "state": state,
                "trip_id": trip_id
            })

            if state == "running" and trip_id:
                tr = trip_map[trip_id]
                dist = effective_trip_distance(tr)
                duration_h = max(1e-9, (parse_dt(tr["end_time"]) - parse_dt(tr["start_time"])).total_seconds() / 3600.0)

                if v["vehicle_type"] == "ev_bus":
                    kwh = dist * float(v["energy_consumption_kWh_per_km_base"]) * (delta_h / duration_h)
                    ev_running_kWh[vid][t] += kwh
                else:
                    if v.get("diesel_consumption_L_per_km") is not None:
                        lpkm = float(v["diesel_consumption_L_per_km"])
                    else:
                        lpkm = 1.0 / float(v["fuel_economy_km_per_L"])
                    L = dist * lpkm * (delta_h / duration_h)
                    engine_running_L[vid][t] += L

    op_df = pd.DataFrame(op_rows)

    # --- Charging policy (simple): charge lowest SOC first during idle, limited by chargers/site/contract ---
    charger_site_limit = float(settings.get("charger_site_limit_kW", 1e18))
    num_chargers = int(settings.get("num_chargers", 10**9))
    contract_mode = settings["contract_mode"]
    contract_limit = float(settings.get("contract_power_limit_kW", charger_site_limit))
    penalty_yen_per_kW = float(settings.get("penalty_yen_per_kW", 0.0))

    ev_soc = {vid: {} for vid in ev_running_kWh.keys()}
    charging_power = {vid: {t: 0.0 for t in timestamps} for vid in ev_soc.keys()}

    # initialize soc
    for v in fleet:
        if v["vehicle_type"] == "ev_bus":
            ev_soc[v["vehicle_id"]][timestamps[0]] = float(v.get("initial_soc", 1.0))

    for idx, t in enumerate(timestamps[:-1]):
        # idle EVs
        idle_evs = []
        for v in fleet:
            if v["vehicle_type"] != "ev_bus":
                continue
            vid = v["vehicle_id"]
            matched = op_df[(op_df["time"] == t.isoformat(timespec="minutes")) & (op_df["vehicle_id"] == vid)]
            if matched.empty:
                continue
            row = matched.iloc[0]
            if row["state"] == "idle":
                idle_evs.append(v)

        # pick up to num_chargers with lowest SOC
        scored = sorted([(ev_soc[v["vehicle_id"]][t], v) for v in idle_evs], key=lambda x: x[0])
        selected = [v for _, v in scored[:num_chargers]]

        provisional = {}
        for v in selected:
            vid = v["vehicle_id"]
            cur = ev_soc[vid][t]
            max_soc = float(v["max_soc"])
            usable = float(v["usable_battery_capacity_kWh"])
            headroom_kWh = max(0.0, (max_soc - cur) * usable)
            max_p = float(v["charging_power_max_kW"])
            eff = float(v["charging_efficiency"])
            p_headroom = headroom_kWh / (eff * delta_h) if eff * delta_h > 0 else 0.0
            provisional[vid] = max(0.0, min(max_p, p_headroom))

        total_p = sum(provisional.values())

        hard_limit = charger_site_limit
        if contract_mode == "hard_limit":
            hard_limit = min(hard_limit, contract_limit)

        if total_p > hard_limit and total_p > 0:
            scale = hard_limit / total_p
            for vid in provisional:
                provisional[vid] *= scale
            total_p = hard_limit

        for vid, p in provisional.items():
            charging_power[vid][t] = p

        # SOC update
        for v in fleet:
            if v["vehicle_type"] != "ev_bus":
                continue
            vid = v["vehicle_id"]
            cur = ev_soc[vid][t]
            usable = float(v["usable_battery_capacity_kWh"])
            eff = float(v["charging_efficiency"])
            run_kWh = ev_running_kWh[vid][t]
            chg_to_batt_kWh = charging_power[vid][t] * eff * delta_h
            next_soc = cur + (chg_to_batt_kWh - run_kWh) / usable if usable > 0 else cur
            next_soc = max(0.0, min(1.0, next_soc))
            ev_soc[vid][timestamps[idx + 1]] = next_soc

    # --- Grid aggregation ---
    total_chg_power = {t: sum(charging_power[vid][t] for vid in charging_power) for t in timestamps}

    net_grid_power = {}
    net_grid_energy = {}
    for t in timestamps:
        pv_power = pv_kWh[t] / delta_h if delta_h > 0 else 0.0
        net_grid_power[t] = max(0.0, total_chg_power[t] - pv_power)
        net_grid_energy[t] = net_grid_power[t] * delta_h

    peak_kW = max(net_grid_power.values()) if net_grid_power else 0.0

    # --- Costs ---
    electricity_cost = sum(net_grid_energy[t] * tou_prices[t] for t in timestamps)

    total_engine_L = 0.0
    for vid in engine_running_L:
        total_engine_L += sum(engine_running_L[vid][t] for t in timestamps)
    fuel_cost = total_engine_L * diesel_price

    demand_cost = peak_kW * demand_charge

    contract_excess_cost = 0.0
    if contract_mode == "soft_penalty":
        excess = max(0.0, max(total_chg_power[t] - contract_limit for t in timestamps))
        contract_excess_cost = excess * penalty_yen_per_kW

    vehicle_capex = sum(vehicle_daily_capex(v) for v in fleet)
    total_cost = vehicle_capex + fuel_cost + electricity_cost + demand_cost + contract_excess_cost + grid_basic

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    op_df.to_csv(out_dir / "vehicle_operation_timeline.csv", index=False)

    soc_rows = []
    for vid in ev_soc:
        for t in timestamps:
            soc_rows.append({"time": t.isoformat(timespec="minutes"), "vehicle_id": vid, "soc": ev_soc[vid].get(t, None)})
    pd.DataFrame(soc_rows).to_csv(out_dir / "vehicle_soc_timeline.csv", index=False)

    chg_rows = []
    for vid in charging_power:
        for t in timestamps:
            chg_rows.append({"time": t.isoformat(timespec="minutes"), "vehicle_id": vid, "charging_power_kW": charging_power[vid][t]})
    pd.DataFrame(chg_rows).to_csv(out_dir / "charging_power_timeline.csv", index=False)

    grid_rows = []
    for t in timestamps:
        grid_rows.append({
            "time": t.isoformat(timespec="minutes"),
            "total_charging_power_kW": total_chg_power[t],
            "pv_energy_kWh": pv_kWh[t],
            "net_grid_purchase_power_kW": net_grid_power[t],
            "net_grid_purchase_energy_kWh": net_grid_energy[t],
            "tou_price_yen_per_kWh": tou_prices[t],
        })
    pd.DataFrame(grid_rows).to_csv(out_dir / "grid_power_timeline.csv", index=False)

    cost_breakdown = {
        "time_basis": settings["time_basis"],
        "vehicle_capex_cost_yen": vehicle_capex,
        "fuel_cost_yen": fuel_cost,
        "electricity_cost_yen": electricity_cost,
        "demand_charge_yen": demand_cost,
        "contract_excess_cost_yen": contract_excess_cost,
        "grid_basic_charge_yen": grid_basic,
        "total_cost_yen": total_cost,
        "peak_demand_kW": peak_kW,
        "total_grid_purchase_kWh": sum(net_grid_energy.values()),
        "total_fuel_consumption_L": total_engine_L,
    }
    (out_dir / "cost_breakdown.json").write_text(json.dumps(cost_breakdown, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "trip_assignment.json").write_text(json.dumps(trip_assignment, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_lines = [
        "# Simulation Summary",
        "",
        "## Settings",
        f"- delta_t_min: {settings['delta_t_min']}",
        f"- start_time: {settings['start_time']}",
        f"- end_time: {settings['end_time']}",
        f"- contract_mode: {settings['contract_mode']}",
        "",
        "## Cost Breakdown (Yen)",
    ]
    for k in ["vehicle_capex_cost_yen", "fuel_cost_yen", "electricity_cost_yen", "demand_charge_yen", "contract_excess_cost_yen", "grid_basic_charge_yen", "total_cost_yen"]:
        summary_lines.append(f"- {k}: {cost_breakdown[k]:,.2f}")
    summary_lines += [
        "",
        "## Energy / Fuel",
        f"- peak_demand_kW: {peak_kW:.3f}",
        f"- total_grid_purchase_kWh: {cost_breakdown['total_grid_purchase_kWh']:.3f}",
        f"- total_fuel_consumption_L: {total_engine_L:.3f}",
        "",
        "## Output Files",
    ]
    for f in ["vehicle_operation_timeline.csv", "vehicle_soc_timeline.csv", "charging_power_timeline.csv", "grid_power_timeline.csv", "cost_breakdown.json", "trip_assignment.json"]:
        summary_lines.append(f"- {f}")
    (out_dir / "simulation_summary.md").write_text("\n".join(summary_lines), encoding="utf-8")

    print("OK")
    print(f"Outputs written to: {out_dir.resolve()}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="input.json", help="Path to input JSON")
    ap.add_argument("--out", default="outputs", help="Output directory")
    args = ap.parse_args()
    main(args.input, args.out)
