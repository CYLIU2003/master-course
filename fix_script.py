import urllib.request, json, sys, unicodedata
sys.stdout.reconfigure(encoding='utf-8')
res = json.loads(urllib.request.urlopen('http://localhost:8000/api/scenarios/fac6a4e0-e6ff-45d2-9246-17230e4b383f/editor-bootstrap').read())
meguro_depot = next(d['depotId'] for d in res['depotRouteSummary'] if '目黒' in d['name'])
depot_routes = res['depotRouteIndex'][meguro_depot]

target_names = ['東98', '渋41', '黒01', '黒02']
target_route_ids = []

for r_id in depot_routes:
    r = next(rt for rt in res['routes'] if rt['id'] == r_id)
    name = r.get('displayName') or r.get('routeCode') or r.get('name')
    normalized_name = unicodedata.normalize('NFKC', name)
    if any(target in normalized_name for target in target_names):
        print(f"Matched: {normalized_name} (ID: {r_id}, Trips: {r.get('tripCount', 0)})")
        target_route_ids.append(r_id)

print(f"Total target route IDs: {len(target_route_ids)}")
