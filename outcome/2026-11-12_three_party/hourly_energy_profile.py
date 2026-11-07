"""Executed energy flows and BEV depot presence by hour of day, summed over the week (DIAGNOSTIC).

Answers "are BEVs charged while the sun shines, and could they be?" for one extracted result archive.
Executed flows: the first 60 min (4 slots) of each hourly rolling step's hourly_execution_result.json
(*_kwh_by_depot_slot), the same convention as rolling_overage_by_step.py. Depot presence: the fixed
assignment's vehicle_timelines.csv (rolling never changes the assignment), counting BEVs whose
15-min slot is not a service trip or deadhead.
Usage: python hourly_energy_profile.py <extracted_dir>
"""
import csv
import glob
import json
import re
import sys
from collections import defaultdict
from datetime import datetime

root = sys.argv[1]
run = glob.glob(root + '/output/*/run_*')[0]
flows = ('pv_to_bus', 'grid_to_bus', 'bess_to_bus', 'pv_to_bess', 'grid_to_bess', 'pv_curtail', 'contract_over_limit')
by_hour = defaultdict(lambda: defaultdict(float))
steps = sorted(glob.glob(run + '/rolling_hourly_chain/step_*'), key=lambda d: int(re.search(r'step_(\d+)_', d).group(1)))
for d in steps:
    k = int(re.search(r'step_(\d+)_', d).group(1))
    e = json.load(open(d + '/hourly_execution_result.json', encoding='utf-8'))
    hour = k % 24
    for f in flows:
        m = e.get(f + '_kwh_by_depot_slot') or {}
        for v in m.values():
            vals = [v[x] for x in sorted(v, key=int)][:4] if isinstance(v, dict) else v[:4]
            by_hour[hour][f] += sum(vals)

# BEV depot presence from the fixed assignment
present = defaultdict(set)   # (day, hour) -> BEV ids at depot during the whole hour
busy = defaultdict(set)
bevs = set()
with open(run + '/vehicle_timelines.csv', encoding='utf-8') as fh:
    for r in csv.DictReader(fh):
        if r['vehicle_type'] != 'BEV':
            continue
        bevs.add(r['vehicle_id'])
        s = datetime.fromisoformat(r['start_time']); t = datetime.fromisoformat(r['end_time'])
        if r['is_service'] == 'True' or r['is_deadhead'] == 'True' or r['is_depot_move'] == 'True':
            m = s
            while m < t:
                busy[(m.date(), m.hour)].add(r['vehicle_id']); m = m.replace(minute=0) if False else m.__class__.fromtimestamp(m.timestamp() + 900)
days = sorted({d for d, _ in busy})
print(f"BEVs in the assignment: {len(bevs)}; days {days[0]}..{days[-1]}")
print("hour | PV->bus PV->BESS curtail | grid->bus grid->BESS | BESS->bus | overage | BEVs at depot (mean over days)")
for h in range(24):
    f = by_hour[h]
    at_depot = sum(len(bevs - busy[(d, h)]) for d in days) / len(days)
    print(f"{h:02d}   | {f['pv_to_bus']:7.0f} {f['pv_to_bess']:7.0f} {f['pv_curtail']:7.0f} | {f['grid_to_bus']:7.0f} {f['grid_to_bess']:7.0f} | {f['bess_to_bus']:7.0f} | {f['contract_over_limit']:6.0f} | {at_depot:5.1f}")
tot = defaultdict(float)
for h in by_hour:
    for f in flows:
        tot[f] += by_hour[h][f]
print('week totals:', {f: round(v) for f, v in tot.items()})
day_bus = sum(by_hour[h][f] for h in range(9, 16) for f in ('pv_to_bus', 'grid_to_bus', 'bess_to_bus'))
all_bus = sum(by_hour[h][f] for h in range(24) for f in ('pv_to_bus', 'grid_to_bus', 'bess_to_bus'))
print(f"bus charging 09-16h: {day_bus:.0f} of {all_bus:.0f} kWh ({100*day_bus/max(all_bus,1):.0f}%)")
