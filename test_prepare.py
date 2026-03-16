import urllib.request, json
req = urllib.request.Request('http://localhost:8000/api/scenarios/fac6a4e0-e6ff-45d2-9246-17230e4b383f/simulation/prepare', method='POST')
req.add_header('Content-Type', 'application/json')
data = {
    "selected_depot_ids": ["meguro"],
    "selected_route_ids": ["tokyu:meguro:黒01", "tokyu:meguro:黒02", "tokyu:meguro:東98", "tokyu:meguro:渋41"],
    "day_type": "WEEKDAY",
    "simulation_settings": {}
}
req.data = json.dumps(data).encode('utf-8')
res = json.loads(urllib.request.urlopen(req).read())
print(f"Trips: {res.get('tripCount')}, Routes: {res.get('routeCount')}")
