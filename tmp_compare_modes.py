import json, time, urllib.request
from urllib.error import HTTPError

BASE='http://127.0.0.1:8771/api'
SID='bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f'
MODES=['mode_milp_only','mode_alns_only','ga','abc']


def post_json(url,obj):
    data=json.dumps(obj).encode('utf-8')
    req=urllib.request.Request(url,data=data,headers={'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))

def get_json(url):
    with urllib.request.urlopen(url,timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))

rows=[]
for mode in MODES:
    while True:
        body={'mode':mode,'time_limit_seconds':60,'mip_gap':0.05,'alns_iterations':120,'rebuild_dispatch':False}
        try:
            job=post_json(f'{BASE}/scenarios/{SID}/run-optimization',body)
            break
        except HTTPError as e:
            detail=e.read().decode('utf-8')
            if e.code==503 and 'EXECUTION_IN_PROGRESS' in detail:
                time.sleep(2)
                continue
            rows.append({'mode':mode,'error':f'HTTP {e.code}','detail':detail[:300]})
            job=None
            break
    if not job:
        continue
    jid=job.get('jobId') or job.get('job_id') or job.get('id')
    status='unknown'
    started=time.time()
    while time.time()-started < 600:
        j=get_json(f'{BASE}/jobs/{jid}')
        status=(j.get('status') or '').lower()
        if status in {'completed','failed','cancelled'}:
            break
        time.sleep(2)
    opt=get_json(f'{BASE}/scenarios/{SID}/optimization')
    sr=opt.get('solver_result') or {}
    plan = sr.get('plan') or {}
    unserved = sr.get('unserved_tasks') or sr.get('unserved_trip_ids') or plan.get('unservedTripIds') or []
    rows.append({
        'mode':mode,
        'job_status':status,
        'solver_status':sr.get('solver_status') or opt.get('solverStatus'),
        'objective':sr.get('objective_value') or sr.get('objective') or opt.get('objectiveValue'),
        'used_backend':sr.get('used_backend') or sr.get('usedBackend'),
        'unserved':len(unserved),
    })

out='outputs/mode_compare_20260317.json'
with open(out,'w',encoding='utf-8') as f:
    json.dump(rows,f,ensure_ascii=False,indent=2)
print('wrote',out)
for r in rows:
    print(r)
