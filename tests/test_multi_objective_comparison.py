"""
Test: Multi-Objective Multi-Solver Comparison

Scenario: 3 Tokyu Bus routes with realistic frequencies
  - 黒01: 84 trips (10 min frequency)
  - 黒02: 56 trips (15 min frequency)
  - 渋41: 42 trips (20 min frequency)
  - Total: 182 trips
  - Fleet: 20 BEV + 20 ICE (40 vehicles)
  
Objectives:
  1. Cost Minimization (energy + operational only, no capital costs)
  2. CO2 Minimization
  3. Balanced (minimize both cost and CO2 with equal weights)

Solvers:
  1. MILP (Gurobi direct)
  2. MILP+ALNS (Hybrid approach)
  3. ALNS (pure heuristic)
  4. GA (Genetic Algorithm - if available)
  5. ABC (Artificial Bee Colony - if available)
"""

from datetime import datetime, timezone
from typing import Dict, List, Tuple
import json

from src.dispatch.models import (
    DispatchContext,
    Trip,
    TurnaroundRule,
    VehicleProfile,
)
from src.optimization import (
    OptimizationConfig,
    OptimizationEngine,
    OptimizationMode,
    ProblemBuilder,
)
from src.optimization.common.result import ResultSerializer


def _create_realistic_large_scenario() -> Dict:
    """
    Create realistic scenario with actual Tokyu Bus frequencies:
    - 黒01: 84 trips (10 min frequency, 07:00-21:00)
    - 黒02: 56 trips (15 min frequency)
    - 渋41: 42 trips (20 min frequency)
    Total: 182 trips
    """
    return {
        "meta": {
            "id": "tokyu-3routes-realistic-001",
            "label": "東急バス 3路線 実際運行ダイヤ (182便) 混合艦隊40台",
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
        "vehicles": _create_vehicle_fleet_40units(),
        "routes": [
            {"id": "黒01", "name": "黒01 目黒駅→清水"},
            {"id": "黒02", "name": "黒02 目黒駅→三軒茶屋"},
            {"id": "渋41", "name": "渋41 渋谷駅→多摩川台"},
        ],
        "depot_route_permissions": [
            {"depotId": "MEGURO-DEPOT", "routeId": route, "allowed": True}
            for route in ["黒01", "黒02", "渋41"]
        ],
        "vehicle_route_permissions": _create_vehicle_permissions_40(),
        "timetable_rows": _create_realistic_timetable(),
        "chargers": [
            {"id": f"CHG-DC-{i:03d}", "siteId": "MEGURO-DEPOT", "powerKw": 90.0, "type": "DC"}
            for i in range(1, 5)
        ],
        "pv_profiles": [
            {"site_id": "MEGURO-DEPOT", "values": _create_pv_profile()}
        ],
        "energy_price_profiles": [
            {"site_id": "MEGURO-DEPOT", "values": _create_electricity_price()}
        ],
    }


def _create_vehicle_fleet_40units() -> List[Dict]:
    """Fleet: 20 BEV + 20 ICE"""
    vehicles = []
    for i in range(1, 21):
        vehicles.append({
            "id": f"V-BEV-{i:02d}",
            "depotId": "MEGURO-DEPOT",
            "type": "BEV",
            "batteryKwh": 300.0,
            "energyConsumption": 1.2,
            "chargePowerKw": 150.0,
        })
    for i in range(1, 21):
        vehicles.append({
            "id": f"V-ICE-{i:02d}",
            "depotId": "MEGURO-DEPOT",
            "type": "ICE",
            "batteryKwh": 0.0,
            "energyConsumption": 0.0,
            "chargePowerKw": 0.0,
        })
    return vehicles


def _create_vehicle_permissions_40() -> List[Dict]:
    """All vehicles can serve all routes"""
    permissions = []
    for i in range(1, 21):
        for route in ["黒01", "黒02", "渋41"]:
            permissions.append({"vehicleId": f"V-BEV-{i:02d}", "routeId": route, "allowed": True})
            permissions.append({"vehicleId": f"V-ICE-{i:02d}", "routeId": route, "allowed": True})
    return permissions


def _create_realistic_timetable() -> List[Dict]:
    """
    Create realistic timetable:
    - 黒01: 84 trips (10 min frequency, 7:00-21:00)
    - 黒02: 56 trips (15 min frequency)
    - 渋41: 42 trips (20 min frequency)
    """
    trips = []

    # 黒01: 84 trips (10 min frequency)
    for trip_idx in range(1, 85):
        minutes_since_start = (trip_idx - 1) * 10
        hour = 7 + minutes_since_start // 60
        minute = minutes_since_start % 60
        if hour >= 21:
            break
        
        dep_time = f"{hour:02d}:{minute:02d}"
        arr_min = minute + 20
        arr_hour = hour
        if arr_min >= 60:
            arr_min -= 60
            arr_hour += 1
        arr_time = f"{arr_hour:02d}:{arr_min:02d}"

        trips.append({
            "trip_id": f"黒01-{trip_idx:03d}",
            "route_id": "黒01",
            "service_id": "WEEKDAY",
            "origin": "目黒駅",
            "destination": "清水",
            "departure": dep_time,
            "arrival": arr_time,
            "distance_km": 12.0,
            "allowed_vehicle_types": ["BEV", "ICE"],
        })

    # 黒02: 56 trips (15 min frequency)
    for trip_idx in range(1, 57):
        minutes_since_start = (trip_idx - 1) * 15
        hour = 7 + minutes_since_start // 60
        minute = minutes_since_start % 60
        if hour >= 21:
            break
        
        dep_time = f"{hour:02d}:{minute:02d}"
        arr_min = minute + 15
        arr_hour = hour
        if arr_min >= 60:
            arr_min -= 60
            arr_hour += 1
        arr_time = f"{arr_hour:02d}:{arr_min:02d}"

        trips.append({
            "trip_id": f"黒02-{trip_idx:03d}",
            "route_id": "黒02",
            "service_id": "WEEKDAY",
            "origin": "目黒駅",
            "destination": "三軒茶屋",
            "departure": dep_time,
            "arrival": arr_time,
            "distance_km": 8.0,
            "allowed_vehicle_types": ["BEV", "ICE"],
        })

    # 渋41: 42 trips (20 min frequency)
    for trip_idx in range(1, 43):
        minutes_since_start = (trip_idx - 1) * 20
        hour = 7 + minutes_since_start // 60
        minute = minutes_since_start % 60
        if hour >= 21:
            break
        
        dep_time = f"{hour:02d}:{minute:02d}"
        arr_min = minute + 25
        arr_hour = hour
        if arr_min >= 60:
            arr_min -= 60
            arr_hour += 1
        arr_time = f"{arr_hour:02d}:{arr_min:02d}"

        trips.append({
            "trip_id": f"渋41-{trip_idx:03d}",
            "route_id": "渋41",
            "service_id": "WEEKDAY",
            "origin": "渋谷駅",
            "destination": "多摩川台",
            "departure": dep_time,
            "arrival": arr_time,
            "distance_km": 15.0,
            "allowed_vehicle_types": ["BEV", "ICE"],
        })

    return trips


def _create_pv_profile() -> List[float]:
    """PV generation profile"""
    profile = []
    for i in range(80):
        slot_hour = 5 + (i * 15) / 60
        if 10 <= slot_hour <= 16:
            solar_fraction = min((slot_hour - 10) / 3, 1.0) if slot_hour < 13 else (16 - slot_hour) / 3
            profile.append(100.0 * solar_fraction)
        else:
            profile.append(0.0)
    return profile


def _create_electricity_price() -> List[float]:
    """TOU pricing"""
    profile = []
    for i in range(80):
        slot_hour = 5 + (i * 15) / 60
        if 9 <= slot_hour <= 11 or 17 <= slot_hour <= 20:
            profile.append(35.0)
        elif 23 <= slot_hour or slot_hour < 6:
            profile.append(20.0)
        else:
            profile.append(28.0)
    return profile


def test_cost_minimization_all_solvers():
    """
    Objective 1: Cost Minimization (no capital costs, only operational)
    
    Test with all available solvers:
    - MILP
    - HYBRID (MILP + ALNS)
    - ALNS
    """
    print("\n" + "=" * 100)
    print("OBJECTIVE 1: COST MINIMIZATION (Operational Costs Only)")
    print("=" * 100)
    
    scenario = _create_realistic_large_scenario()
    
    print("\nScenario Summary:")
    print(f"  Routes: 3 (黒01: 84 trips, 黒02: 56 trips, 渋41: 42 trips)")
    print(f"  Total trips: {len(scenario['timetable_rows'])}")
    print(f"  Fleet: 20 BEV + 20 ICE (40 vehicles)")
    print(f"  Chargers: 4 × 90kW DC (360 kW total)")
    
    # Build problem
    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id="MEGURO-DEPOT",
        service_id="WEEKDAY",
        config=OptimizationConfig(mode=OptimizationMode.HYBRID),
    )
    
    print(f"\nProblem size:")
    print(f"  Trips: {len(problem.trips)}")
    print(f"  Vehicle types: {len(problem.vehicle_types)}")
    print(f"  Feasible connections: {len(problem.feasible_connections)}")
    
    engine = OptimizationEngine()
    
    results = {}
    
    # Test 1: MILP
    print("\n[Solver 1/3: MILP]")
    milp_config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        time_limit_sec=180,
        mip_gap=0.02,
    )
    milp_result = engine.solve(problem, milp_config)
    milp_payload = ResultSerializer.serialize_result(milp_result)
    
    print(f"  Status: {milp_result.solver_status}")
    print(f"  Feasible: {milp_payload['feasible']}")
    print(f"  Cost: {milp_payload.get('objective_value', 'N/A')} JPY")
    print(f"  Served: {len(milp_payload['served_trip_ids'])}/{len(problem.trips)}")
    
    results['MILP'] = {
        'cost': milp_payload.get('objective_value', float('inf')),
        'feasible': milp_payload['feasible'],
        'served': len(milp_payload['served_trip_ids']),
    }
    
    # Test 2: HYBRID
    print("\n[Solver 2/3: HYBRID (MILP + ALNS)]")
    hybrid_config = OptimizationConfig(
        mode=OptimizationMode.HYBRID,
        time_limit_sec=120,
        alns_iterations=100,
    )
    hybrid_result = engine.solve(problem, hybrid_config)
    hybrid_payload = ResultSerializer.serialize_result(hybrid_result)
    
    print(f"  Status: {hybrid_result.solver_status}")
    print(f"  Feasible: {hybrid_payload['feasible']}")
    print(f"  Cost: {hybrid_payload.get('objective_value', 'N/A')} JPY")
    print(f"  Served: {len(hybrid_payload['served_trip_ids'])}/{len(problem.trips)}")
    
    results['HYBRID'] = {
        'cost': hybrid_payload.get('objective_value', float('inf')),
        'feasible': hybrid_payload['feasible'],
        'served': len(hybrid_payload['served_trip_ids']),
    }
    
    # Test 3: ALNS
    print("\n[Solver 3/3: ALNS]")
    alns_config = OptimizationConfig(
        mode=OptimizationMode.ALNS,
        time_limit_sec=90,
        alns_iterations=150,
    )
    alns_result = engine.solve(problem, alns_config)
    alns_payload = ResultSerializer.serialize_result(alns_result)
    
    print(f"  Status: {alns_result.solver_status}")
    print(f"  Feasible: {alns_payload['feasible']}")
    print(f"  Cost: {alns_payload.get('objective_value', 'N/A')} JPY")
    print(f"  Served: {len(alns_payload['served_trip_ids'])}/{len(problem.trips)}")
    
    results['ALNS'] = {
        'cost': alns_payload.get('objective_value', float('inf')),
        'feasible': alns_payload['feasible'],
        'served': len(alns_payload['served_trip_ids']),
    }
    
    # Summary
    print("\n[COST MINIMIZATION RESULTS SUMMARY]")
    print("-" * 80)
    print(f"{'Solver':<15} {'Cost (JPY)':<20} {'Feasible':<12} {'Coverage':<12}")
    print("-" * 80)
    
    for solver_name in ['MILP', 'HYBRID', 'ALNS']:
        r = results[solver_name]
        cost_str = f"{r['cost']:,.0f}" if r['cost'] < float('inf') else "N/A"
        feasible_str = "Yes" if r['feasible'] else "No"
        coverage_str = f"{r['served']}/{len(problem.trips)}"
        print(f"{solver_name:<15} {cost_str:<20} {feasible_str:<12} {coverage_str:<12}")
    
    # Winner
    costs = {k: v['cost'] for k, v in results.items() if v['cost'] < float('inf')}
    if costs:
        winner = min(costs, key=costs.get)
        print("-" * 80)
        print(f"WINNER (Cost Minimization): {winner} ({costs[winner]:,.0f} JPY)")
    
    return problem, results


def test_realistic_scenario_summary():
    """Print realistic scenario summary"""
    print("\n" + "=" * 100)
    print("REALISTIC TOKYU BUS SCENARIO SUMMARY")
    print("=" * 100)
    
    scenario = _create_realistic_large_scenario()
    trips = scenario['timetable_rows']
    
    print("\nRoute Details:")
    for route_id in ["黒01", "黒02", "渋41"]:
        route_trips = [t for t in trips if t['route_id'] == route_id]
        if route_trips:
            distance = route_trips[0]['distance_km']
            freq_min = int(14 * 60 / len(route_trips))
            print(f"  {route_id}: {len(route_trips)} trips ({freq_min} min freq), {distance} km")
    
    print(f"\nTotal Trips: {len(trips)}")
    print(f"Fleet: 20 BEV + 20 ICE")
    print(f"Charging: 4 × 90kW DC chargers (360 kW total)")
    print(f"Operating hours: 07:00 - 21:00 (14 hours)")


if __name__ == "__main__":
    test_realistic_scenario_summary()
    test_cost_minimization_all_solvers()
    
    print("\n" + "=" * 100)
    print("MULTI-OBJECTIVE COMPARISON TEST COMPLETED")
    print("=" * 100)
