#!/usr/bin/env python3
"""CORRECTED 5-day MILP validation using proper endpoints"""
import requests
import json
import time
from datetime import datetime, timedelta

BASE = 'http://127.0.0.1:8000/api'

# Route file to extract known-good routes
audit_routes_file = 'c:\\master-course\\data\\derived\\audit_20250309_known_good_routes.json'
try:
    with open(audit_routes_file) as f:
        audit_data = json.load(f)
        route_ids = list(set(t.get('route_id') for r in audit_data.values() for t in r.get('trips', [])))[:10]
except:
    route_ids = ['TokyuBus-TRD0601', 'TokyuBus-CST0241', 'TokyuBus-SDT1306', 'TokyuBus-T2810', 'TokyuBus-YGT0401']
    
print("[STEP 1] Setting up 5-day scenario...")

# Scenario ID
scenario_id = "237d5623-aa94-4f72-9da1-17b9070264be"

# Generate 5 consecutive weekday dates (2025-08-04 to 2025-08-08)
base = datetime(2025, 8, 4)
weekday_dates = [base + timedelta(days=i) for i in range(5)]
date_strings = [d.strftime('%Y-%m-%d') for d in weekday_dates]
print(f"Dates: {date_strings}")

# Step 1: PUT quick setup
quick_setup_payload = {
    "date": date_strings[0],
    "depotIds": ["TokyuBusDepotShimoshinjo"],
    "routeIds": route_ids,
    "vehicleCountBev": 60,
    "vehicleCountIce": 60,
    "operatorId": "TokyuBus",
    "startTime": "08:00",
    "endTime": "23:00",
    "planningDays": 5
}

print(f"\n[STEP 2] PUT /scenarios/{scenario_id}/quick-setup")
print(f"Payload: dates={date_strings[0]}, routes={len(route_ids)}, bev={60}, ice={60}, startTime=08:00, endTime=23:00, planningDays=5")

r = requests.put(f'{BASE}/scenarios/{scenario_id}/quick-setup', json=quick_setup_payload, timeout=60)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    qs = r.json()
    print(f"  ✓ Quick setup saved")
    print(f"    - startTime: {qs.get('simulationSettings',{}).get('startTime')}")
    print(f"    - endTime: {qs.get('simulationSettings',{}).get('endTime')}")
    print(f"    - planningDays: {qs.get('simulationSettings',{}).get('planningDays')}")
else:
    print(f"  ✗ Error: {r.text[:200]}")

# Step 2: GET quick-setup to confirm settings saved (USE CORRECT ENDPOINT NOW!)
print(f"\n[STEP 3] GET /scenarios/{scenario_id}/quick-setup to verify settings")
qs_r = requests.get(f'{BASE}/scenarios/{scenario_id}/quick-setup', timeout=60)
print(f"Status: {qs_r.status_code}")
if qs_r.status_code == 200:
    qs = qs_r.json()
    sim_settings = qs.get('simulationSettings', {})
    print(f"  ✓ Quick setup loaded")
    print(f"    - startTime: {sim_settings.get('startTime')}")
    print(f"    - endTime: {sim_settings.get('endTime')}")
    print(f"    - planningDays: {sim_settings.get('planningDays')}")
    print(f"    - planningHorizonHours: {sim_settings.get('planningHorizonHours')}")
else:
    print(f"  ✗ Error: {qs_r.text[:300]}")

# Step 3: POST prepare with multi-day settings
print(f"\n[STEP 4] POST /scenarios/{scenario_id}/simulation/prepare with multi-day payload")
prepare_payload = {
    "start_time": "08:00",
    "end_time": "23:00",
    "planning_days": 5,
    "vehicle_inventory": {
        "TokyuBus_BEV": 60,
        "TokyuBus_ICE": 60
    },
    "charger_slots": 15,
    "depot_ids": ["TokyuBusDepotShimoshinjo"],
    "route_ids": route_ids,
    "mode": "create"
}

print(f"Prepare Payload: start={prepare_payload['start_time']}, end={prepare_payload['end_time']}, days={prepare_payload['planning_days']}")

r = requests.post(f'{BASE}/scenarios/{scenario_id}/simulation/prepare', json=prepare_payload, timeout=60)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    prep = r.json()
    summary = prep.get('prepared_scope_summary', {})
    print(f"  ✓ Prepare successful")
    print(f"    - trips: {summary.get('trip_count')}")
    print(f"    - vehicles: {summary.get('vehicle_count')}")
    print(f"    - planning_days: {summary.get('planning_days')}")
else:
    print(f"  ✗ Error: {r.text[:300]}")

# Step 4: GET prepared to verify multi-day structure
print(f"\n[STEP 5] GET /scenarios/{scenario_id}/simulation/prepared to inspect data")
prep_r = requests.get(f'{BASE}/scenarios/{scenario_id}/simulation/prepared', timeout=60)
print(f"Status: {prep_r.status_code}")
if prep_r.status_code == 200:
    prep = prep_r.json()
    trips = prep.get('trips', [])
    vehicles = prep.get('vehicles', [])
    connections = prep.get('feasible_connections', [])
    
    print(f"  trips: {len(trips)}")
    print(f"  vehicles: {len(vehicles)}")
    print(f"  connections: {len(connections)}")
    
    if trips:
        print(f"\n  Trip samples (first 5):")
        for t in trips[:5]:
            trip_id = t.get('trip_id', '')
            dept_min = t.get('departure_min_from_horizon_start', -1)
            print(f"    - {trip_id}: dept_min={dept_min}")
        
        # Check day prefixes
        prefixed = sum(1 for t in trips if 'd' in t.get('trip_id', '')[:5])
        print(f"\n  Day-prefixed trips: {prefixed}/{len(trips)}")
    
    if vehicles:
        print(f"\n  Vehicle samples (first 3):")
        for v in vehicles[:3]:
            print(f"    - {v.get('vehicle_id')}: type={v.get('vehicle_type')}")
    
    if connections:
        cross_day = sum(1 for c in connections if c.get('is_feasible') and 'd' in c.get('from_trip','')[:5])
        print(f"\n  Cross-day connections: {cross_day}/{len(connections)}")
else:
    print(f"  ✗ Error: {prep_r.text[:300]}")

print("\n[DONE]")
