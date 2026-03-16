import urllib.request
import json
import unicodedata

def call_api(path):
    url = f"http://localhost:8000/api{path}"
    req = urllib.request.Request(url, method='GET')
    res = urllib.request.urlopen(req)
    return json.loads(res.read().decode())

scenarios = call_api('/scenarios')
s_id = scenarios['items'][-1]['id']

opt_res = call_api(f'/scenarios/{s_id}/optimization')
trips = opt_res['solver_result'].get('assignment', {})
# the assignment maps vehicle_id to list of task_ids (trip_ids)
# let's fetch the problem data to map trip_id to route_id

bootstrap = call_api(f'/scenarios/{s_id}/editor-bootstrap')

target_names = ['東98', '渋41', '黒01', '黒02']
route_map = {}
for r in bootstrap['routes']:
    name = r.get('displayName') or r.get('routeCode') or r.get('name') or ''
    norm_name = unicodedata.normalize('NFKC', name)
    for t in target_names:
        if t in norm_name:
            route_map[r['id']] = t

with open('counts2.json', 'w', encoding='utf-8') as f:
    json.dump(route_map, f, ensure_ascii=False, indent=2)
