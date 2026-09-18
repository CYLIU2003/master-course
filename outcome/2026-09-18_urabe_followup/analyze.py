"""Recalculate advisor-response evidence from immutable executed plans."""
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import json
import math

ROOT = Path('C:/master-course')
OUT = ROOT / 'outcome/2026-09-18_urabe_followup'
REPORT = ROOT / 'docs/notes/SHIBU21_23_MONTHLY_PHASE_SEARCH_RESULTS_20260915.json'
FLOW_FIELDS = ('grid_to_bus', 'grid_to_bess', 'pv_to_bus', 'pv_to_bess', 'pv_curtail', 'bess_to_bus')

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def close(a, b):
    assert abs(a-b) <= 1e-6, (a,b)

def episodes(values, threshold):
    spans=[]; start=None
    for i, value in enumerate(values+[0.]):
        if value > threshold and start is None:
            start=i
        elif value <= threshold and start is not None:
            spans.append({'start_slot':start,'end_exclusive_slot':i,'hours':(i-start)*0.25,
                          'grid_kwh':math.fsum(values[start:i])*0.25})
            start=None
    return spans

report=read(REPORT)
assert report['source_git_sha']=='7c7c2334040d54722d2f1c354634269d35f8d1de'
assert digest(report['independent_audit']['path'])==report['independent_audit']['sha256']
hashes={str(REPORT):digest(REPORT),report['independent_audit']['path']:report['independent_audit']['sha256']}
weeks=[]
for row in report['weeks']:
    for evidence in row['source_evidence'].values():
        assert digest(evidence['path'])==evidence['sha256']
        hashes[evidence['path']]=evidence['sha256']
    assert row['hourly_steps_accepted']==168 and row['quarter_hour_slots']==672 and row['physical_violations']==0
    plan=read(row['source_evidence']['executed_plan']['path'])
    ledger=read(row['source_evidence']['executed_day_accounting']['path'])
    assert ledger['eligible'] and ledger['executed_slot_count']==672
    close(ledger['cost_breakdown']['total_cost'],row['total_cost'])
    flow={f:[math.fsum(float(v.get(str(i),0)) for v in plan[f+'_kwh_by_depot_slot'].values()) for i in range(672)] for f in FLOW_FIELDS}
    grid=[a+b for a,b in zip(flow['grid_to_bus'],flow['grid_to_bess'])]
    kw=[v*4 for v in grid]
    pv=[sum(v) for v in zip(flow['pv_to_bus'],flow['pv_to_bess'],flow['pv_curtail'])]
    charge=[sum(v) for v in zip(flow['grid_to_bus'],flow['pv_to_bus'],flow['bess_to_bus'])]
    close(math.fsum(grid),row['grid_import_kwh']);close(max(kw),row['peak_grid_kw'])
    close(math.fsum(pv),row['pv_generated_kwh'])
    excess=[max(0.,v-200.)*.25 for v in kw]
    close(math.fsum(excess),row['contract_over_limit_kwh'])
    close(math.fsum(excess)*500,row['contract_overage_cost'])
    close(math.fsum(grid)*30,row['electricity_cost'])
    components={k:row[k] for k in ('vehicle_usage_cost','electricity_cost','fuel_cost','co2_cost','contract_overage_cost')}
    close(math.fsum(components.values()),row['total_cost'])
    close(math.fsum(d['total_cost_jpy'] for d in plan['daily_cost_ledger']),row['total_cost'])
    daily=[]
    for day in range(7):
        lo,hi=day*96,(day+1)*96
        daily.append({'date':(datetime.fromisoformat(row['week'])+timedelta(days=day)).date().isoformat(),
                      'grid_kwh':math.fsum(grid[lo:hi]),'peak_grid_kw':max(kw[lo:hi]),
                      'pv_kwh':math.fsum(pv[lo:hi]),'overage_kwh':math.fsum(excess[lo:hi]),
                      'overage_cost_jpy':math.fsum(excess[lo:hi])*500,
                      'import_hours_gt_1kw':sum(v>1 for v in kw[lo:hi])*.25})
    peak=kw.index(max(kw)); peak_at=datetime.fromisoformat(row['week'])+timedelta(minutes=peak*15)
    runs=episodes(kw,1.)
    bins=[sum(v<=1 for v in kw),sum(1<v<=100 for v in kw),sum(100<v<=200+1e-6 for v in kw),sum(v>200+1e-6 for v in kw)]
    assert sum(bins)==672
    top4=sorted(grid,reverse=True)[:4]
    soc=[row['bess_terminal']['initial_soc_kwh']]+[float(plan['bess_soc_kwh_by_depot_slot']['tsurumaki'][str(i)]) for i in range(672)]
    w={'month':row['month'],'week':row['week'],'grid_kwh':math.fsum(grid),'weekly_mean_grid_kw':math.fsum(grid)/168,
       'peak_grid_kw':max(kw),'peak_to_mean':max(kw)/(math.fsum(grid)/168),
       'import_hours_gt_1kw':sum(v>1 for v in kw)*.25,'import_hours_gt_epsilon':sum(v>1e-6 for v in kw)*.25,
       'overage_hours_gt_200kw':bins[-1]*.25,'hours_ge_190kw':sum(v>=190 for v in kw)*.25,
       'top_four_slots_kwh':math.fsum(top4),'top_four_slots_share_pct':math.fsum(top4)/math.fsum(grid)*100,
       'hours_bins_0_1_100_200_plus':[n*.25 for n in bins],
       'episode_count_gt_1kw':len(runs),'longest_episode_gt_1kw':max(runs,key=lambda e:e['hours']),
       'largest_day_share_pct':max(x['grid_kwh'] for x in daily)/math.fsum(grid)*100,
       'cost_components':components,'total_cost':row['total_cost'],'non_usage_cost':row['non_vehicle_usage_cost_jpy'],
       'cost_per_trip':row['total_cost']/1704,'non_usage_cost_per_trip':row['non_vehicle_usage_cost_jpy']/1704,
       'cost_per_scheduled_km':row['total_cost']/row['scheduled_trip_distance_km'],
       'vehicle_days':row['used_vehicle_day_count'],'trip_count':row['trip_count'],
       'used_types':dict(Counter(d['vehicle_type'] for d in plan['duties'])),
       'trip_types':dict(Counter(t for d in plan['duties'] for t in [d['vehicle_type']]*len(d['trip_ids']))),
       'stage1_gap':row['stage1_gap'],'overage_kwh':math.fsum(excess),
       'pv_generated_kwh':row['pv_generated_kwh'],'pv_used_kwh':row['pv_used_total_kwh'],
       'pv_curtailed_kwh':row['pv_curtailed_kwh'],'bess_inventory_drawdown_kwh':row['bess_inventory_drawdown_kwh'],
       'charge_kwh':math.fsum(charge),'daily':daily,
       'peak':{'slot':peak,'at_jst':peak_at.isoformat(),'grid_kw':kw[peak],
               'charge_kw':charge[peak]*4,'pv_available_kw':pv[peak]*4,
               'pv_to_bus_kw':flow['pv_to_bus'][peak]*4,'bess_to_bus_kw':flow['bess_to_bus'][peak]*4,
               'bess_start_kwh':soc[peak],'bess_end_kwh':soc[peak+1],
               'charging_buses':sum(s['slot_index']==peak and s['charge_kw']>1e-6 for s in plan['charging_schedule'])}}
    if row['month'] in (3,11):
        w['series']={'grid_kw':kw,'pv_available_kw':[v*4 for v in pv],'charge_kw':[v*4 for v in charge],
                     'bess_to_bus_kw':[v*4 for v in flow['bess_to_bus']],'pv_to_bus_kw':[v*4 for v in flow['pv_to_bus']],
                     'bess_soc_kwh':soc,'excess_kwh':excess,'cumulative_grid_kwh':[math.fsum(grid[:i]) for i in range(673)]}
        w['episodes_gt_1kw']=runs
    weeks.append(w)
march,nov=weeks[2],weeks[10]
delta={k:march['cost_components'][k]-nov['cost_components'][k] for k in march['cost_components']}
close(sum(delta.values()),march['total_cost']-nov['total_cost'])
comparison={'cost_delta_march_minus_november':march['total_cost']-nov['total_cost'],
            'delta_components':delta,'delta_as_pct_november':(march['total_cost']/nov['total_cost']-1)*100,
            'overage_share_of_delta_pct':delta['contract_overage_cost']/(march['total_cost']-nov['total_cost'])*100,
            'same_flow_price_sensitivity':[{'overage_yen_per_kwh':price,
                'march_total':march['total_cost']-march['cost_components']['contract_overage_cost']+price*march['overage_kwh'],
                'november_total':nov['total_cost']-nov['cost_components']['contract_overage_cost']+price*nov['overage_kwh'],
                'delta':sum(v for k,v in delta.items() if k!='contract_overage_cost')+price*(march['overage_kwh']-nov['overage_kwh'])}
                for price in (0,100,500)]}
result={'source_sha256':hashes,'source_git_sha':report['source_git_sha'],'weeks':weeks,'comparison':comparison,
        'definitions':{'time_step_hours':.25,'purchase_detection_threshold_kw':1,'overage_numerical_tolerance_kw':1e-6,
                       'daily_cost_scope':'Use daily grid/excess flows only. Published daily total_cost allocates other weekly costs equally; not independent daily outcomes.',
                       'price_sensitivity_scope':'Arithmetic revaluation of fixed executed flows; no reoptimization or feasible alternative implied.',
                       'claim_scope':'Descriptive comparison of selected weeks; no statistical significance, causal PV effect, or method superiority.'}}
(OUT/'analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
for w in (march,nov):
    print(json.dumps({k:v for k,v in w.items() if k not in ('series','episodes_gt_1kw')},ensure_ascii=True))
print(json.dumps(comparison,ensure_ascii=True))
