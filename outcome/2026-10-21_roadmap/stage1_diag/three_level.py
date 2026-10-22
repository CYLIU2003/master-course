import csv, json, glob, os, sys, collections
base = sys.argv[1]
print('case\tS1_grid\tS1_pv2bus\tS2_grid\tS2_pv2bus\tS2_curt\tEX_grid\tEX_pv2bus\tEX_curt\tPVfc_day\tPVact_day')
for run in sorted(glob.glob(os.path.join(base, 'rc8/fsoft*/2025-*/original/output/*/run_*'))):
    case = '/'.join(run.replace(chr(92), '/').split('/')[-6:-4])
    a = json.load(open(os.path.join(run, 'assignment_economic_audit.json'), encoding='utf8'))['stage1_source_flows_kwh']
    s2 = collections.Counter()
    for r in csv.DictReader(open(os.path.join(run, 'depot_energy_flows.csv'), encoding='utf8')):
        for f in ('grid_to_bus_kwh', 'grid_to_bess_kwh', 'pv_to_bus_kwh', 'pv_curtail_kwh'): s2[f] += float(r[f] or 0)
    ex = collections.Counter()
    for r in csv.DictReader(open(os.path.join(run, 'rolling_hourly_chain/hourly_energy_flow_chart.csv'), encoding='utf8')):
        for f in ('grid_to_bus_kwh', 'grid_to_bess_kwh', 'pv_to_bus_kwh', 'pv_curtailed_kwh'): ex[f] += float(r[f] or 0)
    fc = json.load(open(os.path.join(run, 'effective_pv_profiles.json'), encoding='utf8'))['forecast_by_depot']['tsurumaki']
    act = json.load(open(os.path.join(run, 'pv_actuals_for_execution.json'), encoding='utf8'))['depot_profiles']['tsurumaki']
    daily = lambda xs: [round(sum(xs[d*96:(d+1)*96])) for d in range(7)]
    print(case, round(a['grid_to_bus_kwh'] + a['grid_to_bess_kwh']), round(a['pv_to_bus_kwh']),
          round(s2['grid_to_bus_kwh'] + s2['grid_to_bess_kwh']), round(s2['pv_to_bus_kwh']), round(s2['pv_curtail_kwh']),
          round(ex['grid_to_bus_kwh'] + ex['grid_to_bess_kwh']), round(ex['pv_to_bus_kwh']), round(ex['pv_curtailed_kwh']),
          daily(fc), daily(act), sep='\t')
