import json
import urllib.request

BASE='http://127.0.0.1:8000/api'
SCENARIO='41c6872a-717a-4357-81b0-87f5812bf06d'

with urllib.request.urlopen(f"{BASE}/scenarios/{SCENARIO}/quick-setup?routeLimit=1000", timeout=120) as r:
    quick=json.loads(r.read().decode('utf-8'))

routes=quick.get('routes') or []
depot_sums={}
for rt in routes:
    depot=str(rt.get('depotId') or '')
    tc=int(rt.get('tripCount') or 0)
    depot_sums[depot]=depot_sums.get(depot,0)+tc

name_by={str(d.get('id') or d.get('depotId') or ''):str(d.get('name') or '') for d in (quick.get('depots') or [])}
out=[]
for depot_id,count in sorted(depot_sums.items(), key=lambda x:x[1], reverse=True):
    out.append({'depotId':depot_id,'depotName':name_by.get(depot_id,''),'tripCountSum':count})

with open('tmp_quick_depot_trip_counts.json','w',encoding='utf-8') as f:
    json.dump(out,f,ensure_ascii=False,indent=2)
print('wrote tmp_quick_depot_trip_counts.json')
