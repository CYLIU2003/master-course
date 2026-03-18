import json, urllib.request
from urllib.error import HTTPError
BASE='http://127.0.0.1:8771/api'
SID='bbe1e1bd-cd70-4fc0-9cca-6c5283b71a4f'
for mode in ['mode_milp_only','mode_alns_only','ga','abc']:
    body={'mode':mode,'time_limit_seconds':30,'mip_gap':0.05,'alns_iterations':50,'rebuild_dispatch':False}
    data=json.dumps(body).encode('utf-8')
    req=urllib.request.Request(f'{BASE}/scenarios/{SID}/run-optimization',data=data,headers={'Content-Type':'application/json'},method='POST')
    try:
        with urllib.request.urlopen(req,timeout=30) as r:
            print(mode,'OK',r.status)
    except HTTPError as e:
        print(mode,'HTTP',e.code,e.read().decode('utf-8')[:400])
