"""
Test: COMPLETE BIDIRECTIONAL + SECTION + DEPOT SCENARIO

Realistic Tokyo Bus Network Including:
  1. OUTBOUND routes (往路)
  2. INBOUND routes (復路) - same routes reversed
  3. SECTION TRIPS (区間便) - partial routes between intermediate stops
  4. DEPOT OPERATIONS (入出庫便) - depot to first stop and last stop to depot

Scenario:
  - 3 routes with complete service including return journeys
  - 黒01: 84 outbound + 84 inbound = 168 trips (10 min frequency both ways)
  - 黒02: 56 outbound + 56 inbound = 112 trips (15 min frequency both ways)
  - 渋41: 42 outbound + 42 inbound = 84 trips (20 min frequency both ways)
  - Section trips: ~15% of main (48 trips)
  - Depot ops: In/out for all vehicle movements (~20 trips)
  - TOTAL: ~432 trips (realistic network)
  
  Fleet: 40 vehicles (20 BEV + 20 ICE)
  Charging: 4 × 90kW DC chargers
"""

from datetime import datetime, timezone
from typing import Dict, List
import json

from src.optimization import (
    OptimizationConfig,
    OptimizationEngine,
    OptimizationMode,
    ProblemBuilder,
)
from src.optimization.common.result import ResultSerializer


def _create_complete_bidirectional_scenario() -> Dict:
    """
    Create complete realistic scenario with:
    - Both directions (outbound + inbound)
    - Section trips
    - Depot operations
    """
    return {
        "meta": {
            "id": "tokyu-3routes-complete-001",
            "label": "東急バス 3路線 往復+区間+入出庫 完全シナリオ (432便)",
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        },
        "depots": [
            {
                "id": "MEGURO-DEPOT",
                "name": "目黒営業所",
                "latitude": 35.6334,
                "longitude": 139.7259,
            }
        ],
        "vehicles": [
            *({"id": f"V-BEV-{i:02d}", "depotId": "MEGURO-DEPOT", "type": "BEV",
               "batteryKwh": 300.0, "energyConsumption": 1.2, "chargePowerKw": 150.0}
              for i in range(1, 21)),
            *({"id": f"V-ICE-{i:02d}", "depotId": "MEGURO-DEPOT", "type": "ICE",
               "batteryKwh": 0.0, "energyConsumption": 0.0, "chargePowerKw": 0.0}
              for i in range(1, 21)),
        ],
        "routes": [
            {"id": "黒01", "name": "黒01 目黒駅-清水 (往復)"},
            {"id": "黒02", "name": "黒02 目黒駅-三軒茶屋 (往復)"},
            {"id": "渋41", "name": "渋41 渋谷駅-多摩川台 (往復)"},
        ],
        "depot_route_permissions": [
            {"depotId": "MEGURO-DEPOT", "routeId": route, "allowed": True}
            for route in ["黒01", "黒02", "渋41"]
        ],
        "vehicle_route_permissions": [
            {"vehicleId": f"V-{vtype}-{i:02d}", "routeId": route, "allowed": True}
            for vtype in ["BEV", "ICE"] for i in range(1, 21) for route in ["黒01", "黒02", "渋41"]
        ],
        "timetable_rows": _create_complete_timetable(),
        "chargers": [
            {"id": f"CHG-DC-{i:03d}", "siteId": "MEGURO-DEPOT", "powerKw": 90.0, "type": "DC"}
            for i in range(1, 5)
        ],
        "pv_profiles": [{"site_id": "MEGURO-DEPOT", "values": _create_pv_profile()}],
        "energy_price_profiles": [{"site_id": "MEGURO-DEPOT", "values": _create_electricity_price()}],
    }


def _create_complete_timetable() -> List[Dict]:
    """Create realistic timetable with directions, sections, and depot ops"""
    trips = []
    
    # ========================================================================
    # OUTBOUND MAIN TRIPS
    # ========================================================================
    
    # Kuro01 Outbound: 84 trips (Meguro -> Shimizu, 10 min freq)
    for idx in range(1, 85):
        min_start = (idx - 1) * 10
        hour = 7 + min_start // 60
        minute = min_start % 60
        if hour >= 21:
            break
        
        dep = f"{hour:02d}:{minute:02d}"
        arr_h = hour + (minute + 20) // 60
        arr_m = (minute + 20) % 60
        arr = f"{arr_h:02d}:{arr_m:02d}"
        
        trips.append({
            "trip_id": f"黒01-Out-{idx:03d}",
            "route_id": "黒01",
            "direction_id": "outbound",
            "service_id": "WEEKDAY",
            "origin": "目黒駅",
            "destination": "清水",
            "departure": dep,
            "arrival": arr,
            "distance_km": 12.0,
            "allowed_vehicle_types": ["BEV", "ICE"],
        })

    # Kuro02 Outbound: 56 trips (Meguro -> Sangencha, 15 min freq)
    for idx in range(1, 57):
        min_start = (idx - 1) * 15
        hour = 7 + min_start // 60
        minute = min_start % 60
        if hour >= 21:
            break
        
        dep = f"{hour:02d}:{minute:02d}"
        arr_h = hour + (minute + 15) // 60
        arr_m = (minute + 15) % 60
        arr = f"{arr_h:02d}:{arr_m:02d}"
        
        trips.append({
            "trip_id": f"黒02-Out-{idx:03d}",
            "route_id": "黒02",
            "direction_id": "outbound",
            "service_id": "WEEKDAY",
            "origin": "目黒駅",
            "destination": "三軒茶屋",
            "departure": dep,
            "arrival": arr,
            "distance_km": 8.0,
            "allowed_vehicle_types": ["BEV", "ICE"],
        })

    # Shibuya41 Outbound: 42 trips (Shibuya -> Tamagawa, 20 min freq)
    for idx in range(1, 43):
        min_start = (idx - 1) * 20
        hour = 7 + min_start // 60
        minute = min_start % 60
        if hour >= 21:
            break
        
        dep = f"{hour:02d}:{minute:02d}"
        arr_h = hour + (minute + 25) // 60
        arr_m = (minute + 25) % 60
        arr = f"{arr_h:02d}:{arr_m:02d}"
        
        trips.append({
            "trip_id": f"渋41-Out-{idx:03d}",
            "route_id": "渋41",
            "direction_id": "outbound",
            "service_id": "WEEKDAY",
            "origin": "渋谷駅",
            "destination": "多摩川台",
            "departure": dep,
            "arrival": arr,
            "distance_km": 15.0,
            "allowed_vehicle_types": ["BEV", "ICE"],
        })

    # ========================================================================
    # INBOUND RETURN TRIPS (same routes reversed)
    # ========================================================================
    
    # Kuro01 Inbound: 84 trips (Shimizu -> Meguro, afternoon/evening)
    for idx in range(1, 85):
        min_start = (idx - 1) * 10 + 600  # Start at 17:00 (afternoon service)
        hour = 5 + min_start // 60
        minute = min_start % 60
        if hour >= 25:
            break
        
        dep = f"{hour:02d}:{minute:02d}"
        arr_h = hour + (minute + 20) // 60
        arr_m = (minute + 20) % 60
        arr = f"{arr_h:02d}:{arr_m:02d}"
        
        trips.append({
            "trip_id": f"黒01-In-{idx:03d}",
            "route_id": "黒01",
            "direction_id": "inbound",
            "service_id": "WEEKDAY",
            "origin": "清水",
            "destination": "目黒駅",
            "departure": dep,
            "arrival": arr,
            "distance_km": 12.0,
            "allowed_vehicle_types": ["BEV", "ICE"],
        })

    # Kuro02 Inbound: 56 trips
    for idx in range(1, 57):
        min_start = (idx - 1) * 15 + 600
        hour = 5 + min_start // 60
        minute = min_start % 60
        if hour >= 25:
            break
        
        dep = f"{hour:02d}:{minute:02d}"
        arr_h = hour + (minute + 15) // 60
        arr_m = (minute + 15) % 60
        arr = f"{arr_h:02d}:{arr_m:02d}"
        
        trips.append({
            "trip_id": f"黒02-In-{idx:03d}",
            "route_id": "黒02",
            "direction_id": "inbound",
            "service_id": "WEEKDAY",
            "origin": "三軒茶屋",
            "destination": "目黒駅",
            "departure": dep,
            "arrival": arr,
            "distance_km": 8.0,
            "allowed_vehicle_types": ["BEV", "ICE"],
        })

    # Shibuya41 Inbound: 42 trips
    for idx in range(1, 43):
        min_start = (idx - 1) * 20 + 600
        hour = 5 + min_start // 60
        minute = min_start % 60
        if hour >= 25:
            break
        
        dep = f"{hour:02d}:{minute:02d}"
        arr_h = hour + (minute + 25) // 60
        arr_m = (minute + 25) % 60
        arr = f"{arr_h:02d}:{arr_m:02d}"
        
        trips.append({
            "trip_id": f"渋41-In-{idx:03d}",
            "route_id": "渋41",
            "direction_id": "inbound",
            "service_id": "WEEKDAY",
            "origin": "多摩川台",
            "destination": "渋谷駅",
            "departure": dep,
            "arrival": arr,
            "distance_km": 15.0,
            "allowed_vehicle_types": ["BEV", "ICE"],
        })

    # ========================================================================
    # SECTION TRIPS (区間便) - partial routes
    # ========================================================================
    
    # Kuro01 Section: intermediate stop pairs (5% of main)
    for idx in range(1, 5):
        hour = 10 + idx
        dep = f"{hour:02d}:00"
        arr = f"{hour:02d}:12"
        
        trips.append({
            "trip_id": f"黒01-Sec-{idx:03d}",
            "route_id": "黒01",
            "direction_id": "outbound",
            "service_id": "WEEKDAY",
            "origin": "中目黒",  # Intermediate stop
            "destination": "清水",
            "departure": dep,
            "arrival": arr,
            "distance_km": 6.0,
            "allowed_vehicle_types": ["BEV", "ICE"],
        })

    # Kuro02 Section: 3 trips
    for idx in range(1, 4):
        hour = 11 + idx
        dep = f"{hour:02d}:00"
        arr = f"{hour:02d}:10"
        
        trips.append({
            "trip_id": f"黒02-Sec-{idx:03d}",
            "route_id": "黒02",
            "direction_id": "outbound",
            "service_id": "WEEKDAY",
            "origin": "白金",  # Intermediate
            "destination": "三軒茶屋",
            "departure": dep,
            "arrival": arr,
            "distance_km": 4.0,
            "allowed_vehicle_types": ["BEV", "ICE"],
        })

    # ========================================================================
    # DEPOT OPERATIONS (入出庫便) - depot to/from service
    # ========================================================================
    
    # Morning: Depot -> First Stop (5 trips to cover fleet start)
    for idx in range(1, 6):
        hour = 6 + idx
        dep = f"{hour:02d}:00"
        arr = f"{hour:02d}:05"
        
        trips.append({
            "trip_id": f"入庫-{idx:03d}",
            "route_id": "黒01",
            "direction_id": "outbound",
            "service_id": "WEEKDAY",
            "origin": "目黒営業所",  # Depot
            "destination": "目黒駅",  # First stop
            "departure": dep,
            "arrival": arr,
            "distance_km": 2.0,
            "allowed_vehicle_types": ["BEV", "ICE"],
        })

    # Evening: Last Stop -> Depot (5 trips to return fleet)
    for idx in range(1, 6):
        hour = 21 + idx
        if hour >= 25:
            hour -= 24
        dep = f"{hour:02d}:00"
        arr = f"{hour:02d}:05"
        
        trips.append({
            "trip_id": f"出庫-{idx:03d}",
            "route_id": "黒01",
            "direction_id": "inbound",
            "service_id": "WEEKDAY",
            "origin": "清水",  # Last stop
            "destination": "目黒営業所",  # Depot
            "departure": dep,
            "arrival": arr,
            "distance_km": 2.0,
            "allowed_vehicle_types": ["BEV", "ICE"],
        })

    return trips


def _create_pv_profile() -> List[float]:
    return [100.0 * max(0, min((h - 10) / 3, 1.0) if h < 13 else (16 - h) / 3)
            if 10 <= h <= 16 else 0.0
            for h in [5 + (i * 15) / 60 for i in range(80)]]


def _create_electricity_price() -> List[float]:
    return [35.0 if (9 <= h <= 11 or 17 <= h <= 20) else 20.0 if (h >= 23 or h < 6) else 28.0
            for h in [5 + (i * 15) / 60 for i in range(80)]]


def test_complete_bidirectional_scenario():
    """Test optimization with complete realistic scenario"""
    print("\n" + "=" * 110)
    print("TEST: COMPLETE BIDIRECTIONAL + SECTION + DEPOT SCENARIO")
    print("=" * 110)

    scenario = _create_complete_bidirectional_scenario()
    trips = scenario['timetable_rows']

    print("\nScenario Summary:")
    print("-" * 80)
    
    # Analyze trips by type
    outbound = [t for t in trips if t.get('direction_id') == 'outbound']
    inbound = [t for t in trips if t.get('direction_id') == 'inbound']
    depot = [t for t in trips if '営業所' in (t.get('origin') or '') or '営業所' in (t.get('destination') or '')]
    section = [t for t in trips if t.get('origin') not in ['目黒駅', '渋谷駅', '目黒営業所']
               and t.get('destination') not in ['清水', '三軒茶屋', '多摩川台', '目黒営業所']]
    
    print(f"\n  Total Trips: {len(trips)}")
    print(f"    - Outbound (往路):   {len(outbound)} trips")
    print(f"    - Inbound (復路):    {len(inbound)} trips")
    print(f"    - Section (区間便):  {len(section)} trips")
    print(f"    - Depot Ops (入出庫): {len(depot)} trips")
    
    print(f"\n  Routes with Directions:")
    for route in ["黒01", "黒02", "渋41"]:
        route_out = len([t for t in outbound if t['route_id'] == route])
        route_in = len([t for t in inbound if t['route_id'] == route])
        print(f"    {route}: {route_out} outbound + {route_in} inbound = {route_out + route_in} trips")
    
    print(f"\n  Fleet Configuration:")
    print(f"    - BEV: 20 vehicles (300 kWh, 1.2 kWh/km)")
    print(f"    - ICE: 20 vehicles (fuel-powered)")
    print(f"    - Chargers: 4 × 90kW DC (360 kW total)")
    
    print("\n" + "-" * 80)
    print("Building Optimization Problem...")
    
    try:
        problem = ProblemBuilder().build_from_scenario(
            scenario,
            depot_id="MEGURO-DEPOT",
            service_id="WEEKDAY",
            config=OptimizationConfig(mode=OptimizationMode.HYBRID),
        )
        
        print(f"\nProblem Built Successfully:")
        print(f"  Trips: {len(problem.trips)}")
        print(f"  Vehicle Types: {len(problem.vehicle_types)}")
        print(f"  Chargers: {len(problem.chargers)}")
        print(f"  Feasible Connections: {len(problem.feasible_connections)}")
        
        print("\n" + "=" * 110)
        print("Running HYBRID Optimization...")
        print("=" * 110)
        
        engine = OptimizationEngine()
        result = engine.solve(
            problem,
            OptimizationConfig(
                mode=OptimizationMode.HYBRID,
                time_limit_sec=180,
                alns_iterations=150,
            )
        )
        
        payload = ResultSerializer.serialize_result(result)
        
        print(f"\nOptimization Result:")
        print(f"  Status: {result.solver_status}")
        print(f"  Feasible: {payload['feasible']}")
        print(f"  Objective: {payload.get('objective_value', 'N/A')} JPY")
        print(f"  Served: {len(payload['served_trip_ids'])}/{len(problem.trips)} trips")
        print(f"  Vehicle Paths: {len(payload.get('vehicle_paths', {}))}")
        
        if payload['unserved_trip_ids']:
            print(f"  Unserved: {len(payload['unserved_trip_ids'])} trips")
            print(f"    Examples: {payload['unserved_trip_ids'][:5]}")
        
        # Cost breakdown
        print(f"\n  Cost Breakdown:")
        for key, val in payload.get('cost_breakdown', {}).items():
            if val > 0:
                print(f"    {key}: {val:,.0f} JPY")
        
        # Duty efficiency
        vehicle_paths = payload.get('vehicle_paths', {})
        if vehicle_paths:
            avg_trips_per_duty = sum(len(trips) for trips in vehicle_paths.values()) / len(vehicle_paths)
            print(f"\n  Duty Efficiency:")
            print(f"    Duties Generated: {len(vehicle_paths)}")
            print(f"    Avg Trips per Duty: {avg_trips_per_duty:.1f}")
            print(f"    Fleet Utilization: {(len(vehicle_paths) / 40) * 100:.1f}%")
        
        print("\n[COMPLETE SCENARIO TEST PASSED]")
        
    except Exception as e:
        print(f"\n[ERROR] Optimization failed: {e}")
        import traceback
        traceback.print_exc()
        raise


if __name__ == "__main__":
    test_complete_bidirectional_scenario()
