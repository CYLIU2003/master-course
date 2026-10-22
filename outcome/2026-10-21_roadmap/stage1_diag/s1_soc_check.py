"""Replay Stage 1 per-vehicle charging against the FINAL schedule's trip/deadhead energy.
If Stage 1 assignment == final assignment, SOC must stay within [reserve, capacity]."""
import csv, json, os, sys, collections, datetime as dt
run = sys.argv[1]
a = json.load(open(os.path.join(run, 'optimization_audit.json'), encoding='utf8'))
def find(o, key):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key: return v
            r = find(v, key)
            if r is not None: return r
cp = find(a, 'stage1_time_indexed_energy_recourse_result')['charge_power_kw_by_vehicle_slot']
init = {r['vehicle_id']: (float(r['initial_soc_kwh']), float(r['battery_capacity_kwh'])) for r in csv.DictReader(open(os.path.join(run, 'graph/initial_soc_ledger.csv'), encoding='utf-8-sig'))}
date = run.replace(chr(92), '/').split('/')[-5]; t0 = dt.datetime.fromisoformat(date + 'T00:00:00')
load = collections.defaultdict(lambda: collections.Counter())
for r in csv.DictReader(open(os.path.join(run, 'graph/vehicle_timeline.csv'), encoding='utf-8-sig')):
    if r['state'] not in ('service', 'deadhead'): continue
    s = (dt.datetime.fromisoformat(r['start_time']) - t0).total_seconds() / 60
    e = (dt.datetime.fromisoformat(r['end_time']) - t0).total_seconds() / 60
    en = -float(r['energy_delta_kwh'] or 0)
    if en <= 0 or e <= s: continue
    m = s
    while m < e:
        slot = int(m // 15); nxt = min(e, (slot + 1) * 15)
        load[r['vehicle_id']][slot] += en * (nxt - m) / (e - s); m = nxt
eff = float(sys.argv[2]) if len(sys.argv) > 2 else 0.95
viol = []
for v, (soc0, cap) in sorted(init.items()):
    soc = soc0; lo = soc; hi = soc
    ch = cp.get(v, {})
    for slot in range(697):
        soc += float(ch.get(str(slot), 0)) * 0.25 * eff - load[v][slot]
        lo = min(lo, soc); hi = max(hi, soc)
    viol.append((v[:8], round(soc0), round(lo), round(hi), round(soc), cap))
print('vehicle init min max end cap   (eff=%s)' % eff)
for x in viol: print(*x)
