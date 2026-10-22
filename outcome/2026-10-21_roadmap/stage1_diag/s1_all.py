import glob, json, os, subprocess, sys, csv, collections, datetime as dt
sys.argv = sys.argv[:1] + sys.argv[1:]
base = sys.argv[1]
def find(o, key):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key: return v
            r = find(v, key)
            if r is not None: return r
def analyse(run):
    a = json.load(open(os.path.join(run, 'optimization_audit.json'), encoding='utf8'))
    cp = find(a, 'stage1_time_indexed_energy_recourse_result')['charge_power_kw_by_vehicle_slot']
    o = json.load(open(os.path.join(run, 'optimization_result.json'), encoding='utf8'))
    multi = set(find(o, 'vehicles_with_multiple_fragments') or [])
    date = run.replace(chr(92), '/').split('/')[-5]; t0 = dt.datetime.fromisoformat(date + 'T00:00:00')
    ev = collections.defaultdict(list)
    for r in csv.DictReader(open(os.path.join(run, 'graph/vehicle_timeline.csv'), encoding='utf-8-sig')):
        s = int((dt.datetime.fromisoformat(r['start_time']) - t0).total_seconds() // 60)
        e = int((dt.datetime.fromisoformat(r['end_time']) - t0).total_seconds() // 60)
        ev[r['vehicle_id']].append((s, e, r['state']))
    H = 8 * 1440
    moving = {}
    for v, es in ev.items():
        arr = bytearray(H)
        for s, e, st in es:
            if st in ('service', 'deadhead'):
                for m in range(max(s, 0), min(e, H)): arr[m] = 1
        moving[v] = arr
    tot = bad = bad_multi = 0.0
    for v, slots in cp.items():
        for s, p in slots.items():
            p = float(p)
            if p <= 1e-6: continue
            s = int(s); e = p * 0.25; tot += e
            if v in moving and sum(moving[v][s*15:(s+1)*15]) == 15:
                bad += e
                if v in multi: bad_multi += e
    nbev = len(cp); nmulti = len([v for v in multi if v in cp])
    return tot, bad, bad_multi, nbev, nmulti
print('case\tS1_charge_kWh\tcharge_while_moving_all15_kWh\tshare\tof_which_multi_fragment_vehicles\tBEV_with_multi_fragments')
for run in sorted(glob.glob(os.path.join(base, 'rc8/fsoft*/2025-*/original/output/*/run_*'))):
    case = '/'.join(run.replace(chr(92), '/').split('/')[-6:-4])
    tot, bad, bm, nb, nm = analyse(run)
    print(case, round(tot), round(bad), f'{100*bad/tot:.1f}%', f'{100*bm/max(bad,1e-9):.1f}%', f'{nm}/{nb}', sep='\t')
