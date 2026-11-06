"""Executed contract overage of each hourly rolling step, split by the Stage 2 status of that step.

Used for the 11/12 deck slide "超過は実行のどの時間に出るか" (rc23, DIAGNOSTIC). Input: one or more
directories holding an extracted rc23 result archive (state/<job>.zip). For every
rolling_hourly_chain/step_*, the executed hour is the first 60 min of contract_over_limit_kwh_by_depot_slot
in hourly_execution_result.json; the status is stage2_solver_status in hourly_summary.json.
The per-step sums reproduce the weekly contract overage of the evaluated case (133 / 308 / 1,396 kWh).
Usage: python rolling_overage_by_step.py <extracted_dir> [...]
"""
import json,glob,sys,os,re
for root in sys.argv[1:]:
    agg={'time_limit':[0,0.0],'optimal':[0,0.0]}; lines=[]
    steps=sorted(glob.glob(root+'/**/rolling_hourly_chain/step_*',recursive=True), key=lambda d:int(re.search(r'step_(\d+)_',d).group(1)))
    for d in steps:
        s=json.load(open(d+'/hourly_summary.json',encoding='utf-8'))
        e=json.load(open(d+'/hourly_execution_result.json',encoding='utf-8'))
        ts=s.get('timestep_min') or 15; k=int(60/ts)
        m=e.get('contract_over_limit_kwh_by_depot_slot') or {}
        ex=0.0
        for dep,v in m.items():
            if isinstance(v,dict): vals=[v[x] for x in sorted(v,key=int)][:k]
            else: vals=v[:k]
            ex+=sum(vals)
        st=s.get('stage2_solver_status'); key='optimal' if st=='optimal' else 'time_limit'
        agg[key][0]+=1; agg[key][1]+=ex
        if ex>0.05: lines.append(f"step{int(re.search(r'step_(\d+)_',d).group(1)):4d} day{int(re.search(r'step_(\d+)_',d).group(1))//24} {st:10s} executed_over={ex:6.1f}")
    print(f"== {root}: executed overage  time_limit steps n={agg['time_limit'][0]} -> {agg['time_limit'][1]:.0f} kWh | optimal steps n={agg['optimal'][0]} -> {agg['optimal'][1]:.0f} kWh")
    print('\n'.join(lines))
