import urllib.request
import json
import unicodedata

def call_api(method, path, data=None):
    url = f"http://localhost:8000/api{path}"
    req = urllib.request.Request(url, method=method)
    if data is not None:
        req.add_header('Content-Type', 'application/json')
        req.data = json.dumps(data).encode('utf-8')
    res = urllib.request.urlopen(req)
    return json.loads(res.read().decode())

scenarios = call_api('GET', '/scenarios')
s_id = scenarios['items'][-1]['id']

bootstrap = call_api('GET', f'/scenarios/{s_id}/editor-bootstrap')

meguro_depot = None
for summary in bootstrap['depotRouteSummary']:
    if '目黒' in summary['name']:
        meguro_depot = summary['depotId']
        break

depot_routes = bootstrap['depotRouteIndex'][meguro_depot]
target_names = ['東98', '渋41', '黒01', '黒02']
route_ids = []

for r_id in depot_routes:
    r = next(rt for rt in bootstrap['routes'] if rt['id'] == r_id)
    name = r.get('displayName') or r.get('routeCode') or r.get('name') or ''
    norm_name = unicodedata.normalize('NFKC', name)
    for target in target_names:
        if target in norm_name:
            route_ids.append(r_id)

res = call_api('POST', f'/scenarios/{s_id}/simulation/prepare', {
    'selected_depot_ids': [meguro_depot],
    'selected_route_ids': route_ids,
    'day_type': 'WEEKDAY',
    'simulation_settings': {
        'solver_mode': 'mode_milp_only',
        'fleet_templates': []
    },
    'include_short_turn': True,
    'include_depot_moves': True,
    'include_deadhead': True,
})

print(f"Total trips: {res['tripCount']}")

# I want a breakdown by route. Let's look at the actual scenario document in duckdb/json?
