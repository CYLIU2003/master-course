#!/usr/bin/env python3
"""Complete 5-day MILP validation with correct endpoints"""
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
    
print("[STEP 1-3] Configure 5-day scenario...")

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

r = requests.put(f'{BASE}/scenarios/{scenario_id}/quick-setup', json=quick_setup_payload, timeout=60)
assert r.status_code == 200, f"Quick setup failed: {r.status_code} {r.text[:200]}"
print(f"✓ Quick setup saved")

# Step 2: POST prepare
prepare_payload = {
    "selected_depot_ids": ["TokyuBusDepotShimoshinjo"],
    "selected_route_ids": route_ids,
    "simulation_settings": {
        "vehicle_count": 60,
        "charger_count": 15,
        "start_time": "08:00",
        "end_time": "23:00",
        "planning_days": 5
    }
}

r = requests.post(f'{BASE}/scenarios/{scenario_id}/simulation/prepare', json=prepare_payload, timeout=60)
assert r.status_code == 200, f"Prepare failed: {r.status_code} {r.text[:200]}"
prep = r.json()
print(f"✓ Prepare successful: {prep.get('tripCount')} trips, {prep.get('vehicleCount')} vehicles, planning_days={prep.get('planningDays')}")

# Step 3: Run MILP optimization
print(f"\n[STEP 4] Run MILP optimization...")
run_payload = {
    "prepared_input_id": prep.get('preparedInputId'),
    "source": "duties"
}

r = requests.post(f'{BASE}/scenarios/{scenario_id}/simulation/run', json=run_payload, timeout=60)
assert r.status_code == 200, f"Run simulation failed: {r.status_code} {r.text[:200]}"
run_result = r.json()
job_id = run_result.get('jobId')
print(f"✓ Job submitted: {job_id}")

# Step 4: Poll for completion
print(f"\nPolling for completion...")
start_time = time.time()
for attempt in range(300):  # 300 * 5s = 25 minutes
    time.sleep(5)
    r = requests.get(f'{BASE}/scenarios/{scenario_id}/optimization/{job_id}', timeout=60)
    if r.status_code == 200:
        result = r.json()
        status = result.get('status')
        print(f"  [{attempt+1:3d}] status={status}")
        if status == 'completed':
            print(f"✓ Completed in {time.time()-start_time:.1f}s")
            break
    elif r.status_code == 404:
        print(f"  [{attempt+1:3d}] not ready")

# Step 5: Fetch final result
print(f"\n[STEP 5] Fetch final result...")
r = requests.get(f'{BASE}/scenarios/{scenario_id}/optimization/{job_id}', timeout=300)
if r.status_code == 200:
    result = r.json()
    summary = result.get('summary', {})
    cost_breakdown = result.get('cost_breakdown', {})
    
    print(f"✓ Final result retrieved")
    print(f"\n  Solver Status: {result.get('solver_status')}")
    print(f"  Objective Value: {result.get('objective_value'):.0f}")
    print(f"  Served Trips: {summary.get('trip_count_served')} / {summary.get('trip_count_total')}")
    print(f"  Unserved Trips: {summary.get('trip_count_unserved')}")
    print(f"  Unserved Penalty: {cost_breakdown.get('penalty_unserved'):.0f}")
    
    # Check if multi-day was applied
    audit = result.get('audit', {})
    scope = audit.get('prepared_scope_summary', {})
    print(f"\n  Input Planning Days: {scope.get('planning_days')}")
    print(f"  Input Connections: {audit.get('input_counts', {}).get('travel_connections')}")
    
    if summary.get('trip_count_served', 0) > 0:
        print(f"\n✅ Multi-day MILP working! Served {summary.get('trip_count_served')} trips.")
    else:
        print(f"\n❌ Multi-day MILP NOT working. Still serving 0 trips.")
else:
    print(f"✗ Failed to fetch result: {r.status_code} {r.text[:200]}")

print("\n[DONE]")
