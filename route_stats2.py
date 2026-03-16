import urllib.request
import json
import unicodedata

def call_api(path):
    url = f"http://localhost:8000/api{path}"
    req = urllib.request.Request(url, method='GET')
    try:
        res = urllib.request.urlopen(req)
        return json.loads(res.read().decode())
    except Exception as e:
        print(f"Error fetching {path}: {e}")
        return None

scenarios = call_api('/scenarios')
s_id = scenarios['items'][-1]['id']

bootstrap = call_api(f'/scenarios/{s_id}/editor-bootstrap')

meguro_depot = None
for summary in bootstrap['depotRouteSummary']:
    if '目黒' in summary['name']:
        meguro_depot = summary['depotId']
        break

depot_routes = bootstrap['depotRouteIndex'][meguro_depot]
target_names = ['東98', '渋41', '黒01', '黒02']
stats = {name: {'route_ids': [], 'names': set(), 'distance_km': 0.0} for name in target_names}

for r_id in depot_routes:
    r = next(rt for rt in bootstrap['routes'] if rt['id'] == r_id)
    name = r.get('displayName') or r.get('routeCode') or r.get('name') or ''
    norm_name = unicodedata.normalize('NFKC', name)
    for target in target_names:
        if target in norm_name:
            stats[target]['route_ids'].append(r_id)
            stats[target]['names'].add(norm_name)
            dist = float(r.get('distanceKm') or r.get('distance_km') or 0.0)
            if dist > stats[target]['distance_km']:
                stats[target]['distance_km'] = dist

# To get trip counts we might need to look at timetable_rows in the actual document or via another endpoint.
# Alternatively, since we ran optimization and it said "Prepared! Trip count: 655" and unserved_trips: 0, 
# we know the total trips for all 4 routes is exactly 655.
# Let's read the optimization result to see if we can extract trip counts by route.
opt_res = call_api(f'/scenarios/{s_id}/optimization')
if opt_res:
    build_report = opt_res.get('build_report', {})
    print(f"Build report trips: {build_report.get('trip_count')}")

# Instead, let's load the raw scenario json
import os
files = [f for f in os.listdir('data/scenarios') if f.endswith('.json')]
if files:
    with open(os.path.join('data/scenarios', files[-1]), 'r', encoding='utf-8') as f:
        doc = json.load(f)
        for t in doc.get('timetable_rows', []):
            if t.get('service_id') != 'WEEKDAY':
                continue
            r_id = t.get('route_id')
            for target, data in stats.items():
                if r_id in data['route_ids']:
                    data['trips'] = data.get('trips', 0) + 1

for k, v in stats.items():
    v['names'] = list(v['names'])
print(json.dumps(stats, indent=2, ensure_ascii=False))

