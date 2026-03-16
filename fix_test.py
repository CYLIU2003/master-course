import json, urllib.request, time

def call_api(method, path, data=None):
    req = urllib.request.Request(f"http://localhost:8000/api{path}", method=method)
    if data:
        req.add_header('Content-Type', 'application/json')
        req.data = json.dumps(data).encode('utf-8')
    try:
        return json.loads(urllib.request.urlopen(req).read().decode())
    except Exception as e:
        print(f"Error {path}: {e}")
        return None

scenario_id = 'fac6a4e0-e6ff-45d2-9246-17230e4b383f'
b = call_api('GET', f'/scenarios/{scenario_id}/editor-bootstrap')

depot = next(d['depotId'] for d in b['depotRouteSummary'] if '目黒' in d['name'])
route_ids = [r for r in b['depotRouteIndex'][depot] if [rt for rt in b['routes'] if rt['id'] == r][0].get('name', '') in ['東98', '渋41', '黒01', '黒02']]

templates = {t['name']: t['id'] for t in b['vehicleTemplates']}
fleet = [
    {'vehicle_template_id': templates['BYD K8 2.0（冷房起動時カタログ値）'], 'vehicle_count': 20},
    {'vehicle_template_id': templates['いすゞ エルガEV 都市型'], 'vehicle_count': 20},
    {'vehicle_template_id': templates['いすゞ エルガ ディーゼル AMT'], 'vehicle_count': 20},
    {'vehicle_template_id': templates['三菱ふそう エアロスター ディーゼル AT'], 'vehicle_count': 20}
]

# Run ONE test and see what happens!
solver = 'mode_milp_only'
obj = 'total_cost'

print("Preparing...")
res = call_api('POST', f'/scenarios/{scenario_id}/simulation/prepare', {
    'selected_depot_ids': [depot],
    'selected_route_ids': route_ids,
    'day_type': 'WEEKDAY',
    'simulation_settings': {
        'fleet_templates': fleet,
        'solver_mode': solver,
        'objective_mode': obj,
        'time_limit_seconds': 30,
        'unserved_penalty': 10000,
        'mip_gap': 0.05,
        'alns_iterations': 100,
    }
})

print("Prepare status:", res['ready'], "trips:", res.get('tripCount'))

if res['ready']:
    print("Running optimization...")
    job = call_api('POST', f'/scenarios/{scenario_id}/run-optimization', {
        'mode': solver,
        'time_limit_seconds': 30,
        'mip_gap': 0.05,
        'alns_iterations': 100,
        'service_id': 'WEEKDAY',
        'depot_id': depot,
    })
    job_id = job['job_id']
    while True:
        j = call_api('GET', f'/jobs/{job_id}')
        if j['status'] in ['completed', 'failed']:
            print("Done:", j['status'], j.get('error'))
            break
        print(f"Progress: {j.get('progress')}% - {j.get('message')}")
        time.sleep(5)
