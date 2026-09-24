"""Incrementally export accepted executed-week artifacts from audited archives."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta
import json
import math
from pathlib import Path
import zipfile

from tools.research.weekly_results import FLOWS, require_close, require_coverage, render_week, write_csv, write_json


def collect_week(prepared: dict, item: dict, directory: Path, audit: dict) -> dict:
    if audit["unverified"] or not all(t.get("physical_feasibility_claim_eligible") for t in audit["tasks"]):
        raise ValueError("Collection requires verified artifacts and physical eligibility")
    archive_path = directory / "state" / item["artifacts"]
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        accounts = [n for n in names if n.endswith("/rolling_hourly_chain/executed_day_accounting.json")]
        if len(accounts) != 1:
            raise ValueError("Expected exactly one executed weekly accounting source")
        prefix = accounts[0].removesuffix("executed_day_accounting.json")
        accounting = json.loads(archive.read(accounts[0]))
        plan = json.loads(archive.read(prefix + "executed_plan.json"))
        physical = json.loads(archive.read(prefix + "physical_validation.json"))
        bundle = json.loads(archive.read("bundle.json"))
        inputs = json.loads(base64.b64decode(bundle["prepared_base64"]))
        # Preserve the worker's complete original output; all member paths and
        # required hashes were checked by audit_batch before this function.
        original = directory / "original"
        original.mkdir(exist_ok=True)
        archive.extractall(original)
    slots = 672 + int(prepared["overnight"]["extra_slots"])
    if (not accounting["eligible"] or not physical["accepted"] or physical["violations"]
            or accounting["executed_slot_count"] != slots or accounting["missing_slots"] or accounting["duplicate_slots"]):
        raise ValueError("Weekly execution plus paid overnight coverage/physical/accounting did not pass")
    trips = {t["trip_id"]: t for t in inputs["trips"]}
    if len(trips) != len(inputs["trips"]):
        raise ValueError("Duplicate Prepared trip ID")
    assignments = require_coverage(trips, plan)
    costs = accounting["cost_breakdown"]
    ledger = plan["daily_cost_ledger"]
    require_close(math.fsum(d["total_cost_jpy"] for d in ledger), costs["total_cost"], "daily ledger including overnight")
    flows = {key: [math.fsum(float(values.get(str(s), 0)) for field in fields
                           for values in plan[field].values()) for s in range(slots)]
             for key, fields in FLOWS.items()}
    for key, values in flows.items():
        require_close(math.fsum(values), costs[key], key)
    charge = [0.] * slots
    for c in plan["charging_schedule"]:
        s = int(c["slot_index"])
        if not 0 <= s < slots:
            raise ValueError("Charging outside accepted execution horizon")
        charge[s] += float(c["charge_kw"]) * .25
    if any(float(v) != 0 for x in plan["grid_to_bess_kwh_by_depot_slot"].values() for v in x.values()):
        raise ValueError("Auxiliary BESS cannot charge from grid")
    bess = plan["bess_soc_kwh_by_depot_slot"]["tsurumaki"]
    start = datetime.fromisoformat(prepared["week"])
    times = []
    for s in range(slots):
        require_close(flows["grid_import_kwh"][s] + flows["pv_to_bus_kwh"][s] + flows["bess_to_bus_kwh"][s],
                      charge[s], "bus charging balance")
        times.append({"slot": s, "interval_start_jst": (start + timedelta(minutes=15*s)).isoformat(),
                      "period": "service_week" if s < 672 else "paid_final_overnight",
                      **{k: v[s] for k, v in flows.items()}, "bus_charge_kwh": charge[s], "bess_soc_end_kwh": bess[str(s)]})
    vehicles = {v["id"]: v for v in inputs["vehicles"]}
    soc = [{"vehicle_id": v, "state_index": int(s), "soc_kwh": value,
            "soc_percent": 100 * float(value) / vehicles[v]["batteryKwh"]}
           for v, values in plan["vehicle_soc_kwh_by_vehicle_slot"].items() for s, value in values.items()]
    output = directory / "results"
    write_csv(output / "energy_15min.csv", times)
    write_csv(output / "vehicle_soc.csv", soc)
    write_csv(output / "vehicle_schedule.csv", [{"vehicle_id": assignments[t], **trip} for t, trip in trips.items()])
    write_csv(output / "charging_schedule.csv", plan["charging_schedule"])
    write_csv(output / "daily_summary.csv", ledger)
    distance = math.fsum(t["distance_km"] for t in trips.values())
    row = {"week": prepared["week"], "git_sha": prepared["source_git"]["sha"],
           "job_id": item["job_id"], "worker_id": item["worker_id"], "trips": len(trips), "service_km": distance,
           **costs, "cost_per_service_km_jpy": costs["total_cost"] / distance,
           "cost_per_trip_jpy": costs["total_cost"] / len(trips), "executed_slots_including_overnight": slots,
           "bess_terminal": accounting["bess_terminal_soc_by_depot"], "integrated_weekly_gap": None,
           "evaluation_status": "VERIFIED_CONDITIONAL_WEEKLY_EVALUATION", "original_research_verdict": audit["tasks"][0],
           "figure_title": f"渋21〜23 / {prepared['week']} / 7日間＋最終翌朝の充電・受電・費用\n電費一定・BESS補助運用・翌朝運用SOC上限（統合最適性は未証明）"}
    write_json(output / "weekly_summary.json", row)
    render_week(output, row, times, soc)
    return row
