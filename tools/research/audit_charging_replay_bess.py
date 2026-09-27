"""Read-only BESS balance audit for a saved charging proposal (not execution)."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import zipfile

TOLERANCE_KWH = 1e-6


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Missing/nonfinite physical input")
    return float(value)


def audit(plan, assets, initial):
    metadata = plan["metadata"]
    start, stop = metadata["rolling_start_slot_index"], metadata["rolling_stop_slot_index"]
    if type(start) is not int or type(stop) is not int or stop <= start:
        raise ValueError("Invalid window bounds")
    hours = finite(metadata["timestep_min"]) / 60
    if hours <= 0:
        raise ValueError("Invalid timestep")
    rows = []
    for asset in assets:
        if not asset["bess_enabled"]:
            continue
        depot = asset["depot_id"]
        eta_c, eta_d = finite(asset["bess_charge_efficiency"]), finite(asset["bess_discharge_efficiency"])
        if not 0 < eta_c <= 1 or not 0 < eta_d <= 1:
            raise ValueError("Invalid BESS efficiency")
        lower, upper = finite(asset["bess_soc_min_kwh"]), finite(asset["bess_soc_max_kwh"])
        power = finite(asset["bess_power_kw"])
        if not 0 <= lower < upper or power <= 0:
            raise ValueError("Invalid BESS limits")
        previous = finite(initial[depot])
        maximum_residual = maximum_continuity = 0.0
        for slot in range(start, stop):
            key = str(slot)
            beginning = finite(metadata["bess_soc_start_kwh_by_depot_slot"][depot][key])
            ending = finite(metadata["bess_soc_end_kwh_by_depot_slot"][depot][key])
            trace = finite(plan["bess_soc_kwh_by_depot_slot"][depot][key])
            # Canonical source-flow maps omit zero entries; state traces may not.
            pv, grid, out = [finite(plan[field].get(depot, {}).get(key, 0)) for field in (
                "pv_to_bess_kwh_by_depot_slot", "grid_to_bess_kwh_by_depot_slot", "bess_to_bus_kwh_by_depot_slot")]
            residual = abs(ending - beginning - eta_c * (pv + grid) + out / eta_d)
            continuity = abs(beginning - previous)
            if (residual > TOLERANCE_KWH or continuity > TOLERANCE_KWH
                or abs(ending - trace) > TOLERANCE_KWH
                or min(beginning, ending) < lower - TOLERANCE_KWH
                or max(beginning, ending) > upper + TOLERANCE_KWH
                or min(pv, grid, out) < -TOLERANCE_KWH
                or max(pv + grid, out) > power * hours + TOLERANCE_KWH
                or not asset["allow_grid_to_bess"] and abs(grid) > TOLERANCE_KWH):
                raise ValueError(f"BESS balance/limits/continuity failed at {depot}/{slot}")
            maximum_residual = max(maximum_residual, residual)
            maximum_continuity = max(maximum_continuity, continuity)
            previous = ending
        rows.append({"depot": depot, "intervals": stop - start,
                     "initial_kwh": initial[depot], "end_kwh": previous,
                     "max_balance_residual_kwh": maximum_residual,
                     "max_continuity_residual_kwh": maximum_continuity})
    if not rows:
        raise ValueError("No enabled BESS to audit")
    return {"scope": "saved_proposal_bess_balance_only_not_executed_week", "accepted": True,
            "tolerance_kwh": TOLERANCE_KWH, "depots": rows,
            "not_checked": ["vehicle SOC", "trip coverage", "charger occupancy", "PV availability", "accounting", "terminal target"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--preflight", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    preflight = json.loads(args.preflight.read_bytes())
    with args.archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != preflight["source_archive_sha256"]:
            raise ValueError("Original archive hash mismatch")
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            loaded = {}
            for suffix in ("/effective_scenario.json", "/state_for_next_hour.json"):
                name, = [n for n in preflight["evidence_sha256"] if n.endswith(suffix)]
                data = archive.read(name)
                if hashlib.sha256(data).hexdigest() != preflight["evidence_sha256"][name]:
                    raise ValueError("Original audit input hash mismatch")
                loaded[suffix] = json.loads(data)
    data = args.result.read_bytes()
    result = json.loads(data)
    metadata = result["plan"]["metadata"]
    boundary = loaded["/state_for_next_hour.json"]
    if (boundary["current_min"] != preflight["current_min"]
        or metadata["rolling_start_slot_index"] * finite(metadata["timestep_min"]) != preflight["current_min"]):
        raise ValueError("Proposal and saved boundary refer to different window times")
    report = audit(result["plan"], loaded["/effective_scenario.json"]["simulation_config"]["depot_energy_assets"],
                   boundary["actual_bess_soc_kwh"])
    report.update(result_sha256=hashlib.sha256(data).hexdigest(),
                  source_archive_sha256=preflight["source_archive_sha256"])
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(report))


if __name__ == "__main__":
    main()
