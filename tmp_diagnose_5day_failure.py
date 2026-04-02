#!/usr/bin/env python3
"""Diagnose why 5-day MILP serves 0 trips"""
import requests
import json

BASE = 'http://127.0.0.1:8000/api'
sid = '237d5623-aa94-4f72-9da1-17b9070264be'

# Fetch scenario and prepared data
scn_r = requests.get(f'{BASE}/scenarios/{sid}', timeout=60).json()
prep_r = requests.get(f'{BASE}/scenarios/{sid}/prepared', timeout=60).json()

print("=== Scenario Scope ===")
print("dates:", prep_r.get('prepared_scope_summary',{}).get('dates'))
print("routes:", prep_r.get('prepared_scope_summary',{}).get('route_count'))
print("vehicles:", prep_r.get('prepared_scope_summary',{}).get('vehicle_count'))

# Extract prepared data
trips = prep_r.get('trips', [])
connections = prep_r.get('feasible_connections', [])
vehicles = prep_r.get('vehicles', [])

print(f"\nTotal trips: {len(trips)}, connections: {len(connections)}, vehicles: {len(vehicles)}")

# Check builder metadata
builder_config = scn_r.get('simulationSettings', {})
print("\n=== Builder Config ===")
print("start_time:", builder_config.get('startTime'))
print("end_time:", builder_config.get('endTime'))
print("planning_days:", builder_config.get('planningDays'))
print("planningHorizonHours:", builder_config.get('planningHorizonHours'))

# Key question: are trip IDs properly prefixed with day index?
trip_ids = [t['trip_id'] for t in trips[:30]]
print("\n=== Trip ID Prefixes (first 30) ===")
prefixed = sum(1 for tid in trip_ids if 'd' in tid[:5])
print(f"Prefixed: {prefixed}/{len(trip_ids)}")
for tid in trip_ids[:10]:
    prefix_check = "✓" if 'd' in tid[:5] else "✗"
    print(f"  {prefix_check} {tid}")

# Check vehicle types
veh_types = set(v.get('vehicle_type') for v in vehicles)
print(f"\n=== Vehicles ({len(vehicles)} total) ===")
print(f"Types: {veh_types}")
for v in vehicles[:3]:
    print(f"  {v.get('vehicle_id')}: type={v.get('vehicle_type')} home={v.get('home_depot_id')}")

# Check trip vehicle types
trip_veh_types = {}
for t in trips[:20]:
    avail = t.get('allowed_vehicle_types', [])
    for av in avail:
        trip_veh_types[av] = trip_veh_types.get(av, 0) + 1
print(f"\nTrip allowed_vehicle_types distribution (first 20 trips):")
for vt, count in trip_veh_types.items():
    print(f"  {vt}: {count}")

# Check charger coverage
chargers = prep_r.get('chargers', [])
print(f"\nChargers: {len(chargers)}")
for c in chargers[:3]:
    print(f"  {c.get('charger_id')}: location={c.get('location_name')} slots={c.get('available_slots')}")

print("\n=== Connections Sample ===")
for conn in connections[:5]:
    print(f"  {conn.get('from_trip')} -> {conn.get('to_trip')} (feasible={conn.get('is_feasible')})")

# Check if any connection exists span across days
cross_day_conns = [c for c in connections if 'd' in c.get('from_trip', '')[:5] and 'd' in c.get('to_trip', '')[:5]]
same_day_flag = sum(1 for c in cross_day_conns if c.get('from_trip', '').split('_')[0] != c.get('to_trip', '').split('_')[0])

print(f"\nConnections with day prefix: {len([c for c in connections if 'd' in c.get('from_trip','')[:5]])}")
print(f"Cross-day connections: {same_day_flag}")
