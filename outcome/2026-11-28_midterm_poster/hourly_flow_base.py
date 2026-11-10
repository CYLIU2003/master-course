"""Hourly executed energy flows (sum over the week) for the 900 kW winter pair, for poster Fig. 6 (DIAGNOSTIC).

Same convention as ../2026-11-12_three_party/hourly_energy_profile.py: the first 60 min (4 slots) of each
hourly rolling step's hourly_execution_result.json. Cases: rc33 g900 (BEV-heavy start) and h900 (ICE-heavy).
Usage: python hourly_flow_base.py  -> hourly_flow_900_winter.json
"""
import glob
import json
import re
from pathlib import Path

OPS = Path(__file__).resolve().parents[2] / "output" / "midterm_20261128"
FLOWS = ("pv_to_bus", "grid_to_bus", "bess_to_bus", "pv_to_bess", "grid_to_bess", "pv_curtail", "contract_over_limit")


def by_hour(case):
    run = glob.glob(str(OPS / case / "2025-01-06" / "original" / "output" / "*" / "run_*"))[0]
    out = [{f: 0.0 for f in FLOWS} for _ in range(24)]
    for d in glob.glob(run + "/rolling_hourly_chain/step_*"):
        k = int(re.search(r"step_(\d+)_", d).group(1))
        e = json.load(open(d + "/hourly_execution_result.json", encoding="utf-8"))
        for f in FLOWS:
            for v in (e.get(f + "_kwh_by_depot_slot") or {}).values():
                vals = [v[x] for x in sorted(v, key=int)][:4] if isinstance(v, dict) else v[:4]
                out[k % 24][f] += sum(vals)
    return run, [{f: round(h[f], 1) for f in FLOWS} for h in out]


res = {}
for key, case in (("bev", "rc33/g900"), ("ice", "rc33/h900")):
    run, hours = by_hour(case)
    res[key] = {"case": case, "run": Path(run).name, "hours": hours,
                "totals": {f: round(sum(h[f] for h in hours), 1) for f in FLOWS}}
res["note"] = "kWh per hour of day, summed over 2025-01-06..12; first 60 min of each rolling step; DIAGNOSTIC"
Path(__file__).with_name("hourly_flow_900_winter.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
print({k: v["totals"] for k, v in res.items() if k != "note"})
