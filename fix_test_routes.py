import urllib.request, json
res = json.loads(urllib.request.urlopen('http://localhost:8000/api/scenarios/fac6a4e0-e6ff-45d2-9246-17230e4b383f/editor-bootstrap').read())
meguro_depot = next(d['depotId'] for d in res['depotRouteSummary'] if '目黒' in d['name'])
depot_routes = res['depotRouteIndex'][meguro_depot]
for r_id in depot_routes:
    r = next(rt for rt in res['routes'] if rt['id'] == r_id)
    name = r.get('displayName') or r.get('routeCode') or r.get('name')
    print(f"ID: {r_id}, Name: {name}")
