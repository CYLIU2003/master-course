#!/usr/bin/env python3
import glob
import json
import time
from datetime import date, timedelta

import requests

BASE_URL = "http://127.0.0.1:8000/api"
SCENARIO_ID = "237d5623-aa94-4f72-9da1-17b9070264be"
DEPOT_ID = "tsurumaki"
SERVICE_ID = "WEEKDAY"


def weekday_dates(start_ymd: str, days: int) -> list[str]:
    y, m, d = [int(x) for x in start_ymd.split("-")]
    cur = date(y, m, d)
    out: list[str] = []
    while len(out) < days:
        if cur.weekday() < 5:
            out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def known_good_route_ids() -> list[str]:
    paths = sorted(
        glob.glob(
            "C:/master-course/output/2025-08-04/scenario/237d5623-aa94-4f72-9da1-17b9070264be/"
            "mode_milp_only/tsurumaki/WEEKDAY/run_*/optimization_audit.json"
        )
    )
    if not paths:
        return []
    latest = paths[-1]
    with open(latest, "r", encoding="utf-8") as fh:
        audit = json.load(fh)
    route_ids = list((audit.get("prepared_scope_summary") or {}).get("route_ids") or [])
    return sorted(set(str(r) for r in route_ids if str(r).strip()))


def put_quick_setup(mode: str, service_dates: list[str], route_ids: list[str]) -> None:
    payload = {
        "selectedDepotIds": [DEPOT_ID],
        "selectedRouteIds": route_ids,
        "serviceDate": service_dates[0],
        "serviceDates": service_dates,
        "planningDays": len(service_dates),
        "dayType": SERVICE_ID,
        "solverMode": mode,
        "objectiveMode": "total_cost",
        "fixedRouteBandMode": True,
        "allowPartialService": False,
        "startTime": "05:00",
        "endTime": "23:00",
        "planningHorizonHours": 24.0 * float(len(service_dates)),
        "weatherMode": "actual_date_profile",
        "pvProfileId": "actual_date_profile",
        "timeLimitSeconds": 180,
        "mipGap": 0.01,
        "alnsIterations": 500,
        "randomSeed": 42,
    }
    r = requests.put(f"{BASE_URL}/scenarios/{SCENARIO_ID}/quick-setup", json=payload, timeout=60)
    r.raise_for_status()


def run_prepare(mode: str, service_dates: list[str], route_ids: list[str]) -> dict:
    body = {
        "selected_depot_ids": [DEPOT_ID],
        "selected_route_ids": route_ids,
        "day_type": SERVICE_ID,
        "service_date": service_dates[0],
        "service_dates": service_dates,
        "simulation_settings": {
            "vehicle_count": 120,
            "charger_count": 15,
            "use_selected_depot_vehicle_inventory": False,
            "use_selected_depot_charger_inventory": False,
            "solver_mode": mode,
            "objective_mode": "total_cost",
            "service_date": service_dates[0],
            "service_dates": service_dates,
            "planning_days": len(service_dates),
            "start_time": "05:00",
            "end_time": "23:00",
            "planning_horizon_hours": 24.0 * float(len(service_dates)),
            "fixed_route_band_mode": True,
            "allow_partial_service": False,
            "weather_mode": "actual_date_profile",
            "pv_profile_id": "actual_date_profile",
            "time_limit_seconds": 180,
            "mip_gap": 0.01,
            "alns_iterations": 500,
            "random_seed": 42,
        },
    }
    r = requests.post(f"{BASE_URL}/scenarios/{SCENARIO_ID}/simulation/prepare", json=body, timeout=180)
    r.raise_for_status()
    return r.json()


def run_optimization(mode: str, prepared_input_id: str) -> dict:
    payload = {
        "mode": mode,
        "service_id": SERVICE_ID,
        "depot_id": DEPOT_ID,
        "prepared_input_id": prepared_input_id,
        "rebuild_dispatch": False,
        "use_existing_duties": False,
        "time_limit_seconds": 180,
        "mip_gap": 0.01,
        "alns_iterations": 500,
        "no_improvement_limit": 100,
        "destroy_fraction": 0.25,
        "random_seed": 42,
    }
    r = requests.post(f"{BASE_URL}/scenarios/{SCENARIO_ID}/run-optimization", json=payload, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"run-optimization failed: status={r.status_code} body={r.text[:500]}")
    job = r.json()
    job_id = str(job.get("job_id") or "")
    if not job_id:
        raise RuntimeError("job_id missing")

    for _ in range(240):
        j = requests.get(f"{BASE_URL}/jobs/{job_id}", timeout=20)
        j.raise_for_status()
        st = j.json()
        status = str(st.get("status") or "")
        if status in {"completed", "failed", "cancelled"}:
            if status != "completed":
                raise RuntimeError(f"job {job_id} status={status} message={st.get('message')}")
            break
        time.sleep(5)

    rr = requests.get(f"{BASE_URL}/scenarios/{SCENARIO_ID}/optimization", timeout=300)
    rr.raise_for_status()
    return rr.json()


def extract_metrics(result: dict) -> dict:
    summary = result.get("summary") or {}
    cb = result.get("cost_breakdown") or {}
    extra = result.get("extra") or {}
    served = int(result.get("served_trip_count") or summary.get("trip_count_served") or 0)
    unserved = int(result.get("unserved_trip_count") or summary.get("trip_count_unserved") or 0)
    total = int(result.get("trip_count") or (served + unserved))
    return {
        "solver_status": result.get("solver_status"),
        "objective": result.get("objective_value"),
        "served": served,
        "unserved": unserved,
        "total": total,
        "penalty_unserved": cb.get("penalty_unserved"),
        "energy_cost": cb.get("energy_cost"),
        "grid_to_bus_kwh": extra.get("grid_to_bus_kwh"),
        "grid_to_bess_kwh": extra.get("grid_to_bess_kwh"),
        "grid_import_total_kwh": extra.get("grid_import_total_kwh"),
        "output_dir": result.get("output_dir"),
    }


def main() -> None:
    service_dates = weekday_dates("2025-08-04", 5)
    route_ids = known_good_route_ids()
    if not route_ids:
        raise RuntimeError("known good route_ids not found from prior optimization_audit")

    modes = ["mode_milp_only", "mode_alns_only", "mode_ga_only", "mode_abc_only"]
    all_metrics: dict[str, dict] = {}

    for mode in modes:
        print(f"\n=== {mode} ===")
        put_quick_setup(mode, service_dates, route_ids)
        prep = run_prepare(mode, service_dates, route_ids)
        print("prepare ready=", prep.get("ready"), "tripCount=", prep.get("tripCount"), "planningDays=", prep.get("planningDays"))
        prepared_input_id = str(prep.get("preparedInputId") or "")
        if not prepared_input_id:
            raise RuntimeError("preparedInputId missing")
        result = run_optimization(mode, prepared_input_id)
        metrics = extract_metrics(result)
        all_metrics[mode] = metrics
        print(json.dumps(metrics, ensure_ascii=False, indent=2))

    print("\n=== FINAL SUMMARY ===")
    print(json.dumps(all_metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

