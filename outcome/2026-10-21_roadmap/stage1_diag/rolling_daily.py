import csv, sys, json, collections
rows = list(csv.DictReader(open(sys.argv[1], encoding='utf8')))
F = ['pv_generated_kwh','pv_to_bus_kwh','pv_to_bess_kwh','pv_curtailed_kwh','bess_to_bus_kwh','grid_to_bus_kwh','grid_to_bess_kwh']
day = collections.defaultdict(collections.Counter); hod = collections.defaultdict(collections.Counter); soc = collections.defaultdict(list)
tot = collections.Counter()
for r in rows:
    i = int(r['step_index']); d, h = divmod(i, 24)
    for f in F:
        v = float(r[f] or 0); day[d][f] += v; hod[h][f] += v; tot[f] += v
    soc[d].append(list(json.loads(r['bess_end_soc_kwh_by_depot']).values())[0])
print('TOTAL', {k: round(v) for k, v in tot.items()})
print('day', *[f[:-4] for f in F], 'soc_min soc_max soc_end', sep='\t')
for d in sorted(day): print(d, *[round(day[d][f]) for f in F], round(min(soc[d])), round(max(soc[d])), round(soc[d][-1]), sep='\t')
print('hour', *[f[:-4] for f in F], sep='\t')
for h in sorted(hod): print(h, *[round(hod[h][f]) for f in F], sep='\t')
