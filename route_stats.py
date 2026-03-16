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
if not scenarios:
    exit(1)
s_id = scenarios['items'][-1]['id']

scenario = call_api(f'/scenarios/{s_id}')
routes = scenario.get('routes', [])
trips = scenario.get('trips', [])
timetable_rows = scenario.get('timetable_rows', [])

target_names = ['東98', '渋41', '黒01', '黒02']
stats = {name: {'trips': 0, 'distance_km': 0.0, 'route_ids': []} for name in target_names}

for r in routes:
    name = r.get('displayName') or r.get('routeCode') or r.get('name') or ''
    norm_name = unicodedata.normalize('NFKC', name)
    for target in target_names:
        if target in norm_name:
            stats[target]['route_ids'].append(str(r['id']))
            dist = float(r.get('distanceKm') or r.get('distance_km') or 0.0)
            if dist > stats[target]['distance_km']:
                stats[target]['distance_km'] = dist

all_trips = trips if trips else timetable_rows

for t in all_trips:
    r_id = str(t.get('route_id', ''))
    for target in target_names:
        if r_id in stats[target]['route_ids']:
            stats[target]['trips'] += 1

print(json.dumps(stats, indent=2))
