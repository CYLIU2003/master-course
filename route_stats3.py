import urllib.request
import json
import unicodedata
import os

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
stats = {name: {'route_ids': [], 'names': set(), 'distance_km': 0.0, 'trips': 0} for name in target_names}

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

# Read trips from artifact file
trips_file = f"app/scenarios/{s_id}/timetable_rows.json"
if os.path.exists(trips_file):
    with open(trips_file, 'r', encoding='utf-8') as f:
        trips = json.load(f)
        for t in trips:
            if t.get('service_id') != 'WEEKDAY':
                continue
            r_id = t.get('route_id')
            for target, data in stats.items():
                if r_id in data['route_ids']:
                    data['trips'] += 1

for k, v in stats.items():
    v['names'] = list(v['names'])
print(json.dumps(stats, indent=2, ensure_ascii=False))

