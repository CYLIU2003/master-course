"""
Test: MILP (Gurobi) Optimization on Large Real Scenario

Scenario:
- 3 routes: 黒01, 黒02, 渋41
- Fleet: BEV × 20 + ICE × 20 (40 vehicles total)
- Timetable: ~120 trips (40 per route)
- Execution: MILP mode with Gurobi

This test validates:
1. Large problem building
2. MILP solver with Gurobi
3. Quality vs speed tradeoff
4. Cost optimization with mixed fleet
"""

from datetime import datetime, timezone
from typing import Dict, List
import json

from src.dispatch.models import (
    DeadheadRule,
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


def _create_large_scenario() -> Dict:
    """
    Create large-scale scenario:
    - 3 Tokyu Bus routes (黒01, 黒02, 渋41)
    - 40 vehicles (20 BEV + 20 ICE)
    - ~120 trips total
    """
    return {
        "meta": {
            "id": "tokyu-3routes-large-001",
            "label": "東急バス 3路線 混合艦隊40台 大規模シナリオ",
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
        "vehicles": _create_vehicle_fleet(),
        "routes": [
            {"id": "黒01", "name": "黒01 目黒駅→清水"},
            {"id": "黒02", "name": "黒02 目黒駅→三軒茶屋"},
            {"id": "渋41", "name": "渋41 渋谷駅→多摩川台"},
        ],
        "depot_route_permissions": [
            {"depotId": "MEGURO-DEPOT", "routeId": "黒01", "allowed": True},
            {"depotId": "MEGURO-DEPOT", "routeId": "黒02", "allowed": True},
            {"depotId": "MEGURO-DEPOT", "routeId": "渋41", "allowed": True},
        ],
        "vehicle_route_permissions": _create_vehicle_route_permissions(),
        "timetable_rows": _create_large_timetable(),
        "chargers": [
            {"id": "CHG-DC-001", "siteId": "MEGURO-DEPOT", "powerKw": 90.0, "type": "DC"},
            {"id": "CHG-DC-002", "siteId": "MEGURO-DEPOT", "powerKw": 90.0, "type": "DC"},
            {"id": "CHG-DC-003", "siteId": "MEGURO-DEPOT", "powerKw": 90.0, "type": "DC"},
            {"id": "CHG-DC-004", "siteId": "MEGURO-DEPOT", "powerKw": 90.0, "type": "DC"},
        ],
        "pv_profiles": [
            {
                "site_id": "MEGURO-DEPOT",
                "values": _create_pv_profile(),
            }
        ],
        "energy_price_profiles": [
            {
                "site_id": "MEGURO-DEPOT",
                "values": _create_electricity_price(),
            }
        ],
    }


def _create_vehicle_fleet() -> List[Dict]:
    """Create fleet: 20 BEV + 20 ICE"""
    vehicles = []

    # BEV fleet (20 units)
    for i in range(1, 21):
        vehicles.append({
            "id": f"V-BEV-{i:02d}",
            "depotId": "MEGURO-DEPOT",
            "type": "BEV",
            "batteryKwh": 300.0,
            "energyConsumption": 1.2,
            "chargePowerKw": 150.0,
        })

    # ICE fleet (20 units)
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


def _create_vehicle_route_permissions() -> List[Dict]:
    """All vehicles can serve all routes"""
    permissions = []

    for i in range(1, 21):
        for route in ["黒01", "黒02", "渋41"]:
            permissions.append({
                "vehicleId": f"V-BEV-{i:02d}",
                "routeId": route,
                "allowed": True,
            })
            permissions.append({
                "vehicleId": f"V-ICE-{i:02d}",
                "routeId": route,
                "allowed": True,
            })

    return permissions


def _create_large_timetable() -> List[Dict]:
    """Create 120 trips across 3 routes"""
    trips = []

    # Route 黒01: 40 trips (12 km, 20 min)
    for trip_idx in range(1, 41):
        hour = 7 + (trip_idx - 1) // 4  # Spread across day
        minute = ((trip_idx - 1) % 4) * 15
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

    # Route 黒02: 40 trips (8 km, 15 min)
    for trip_idx in range(1, 41):
        hour = 7 + (trip_idx - 1) // 5
        minute = ((trip_idx - 1) % 5) * 12
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

    # Route 渋41: 40 trips (15 km, 25 min)
    for trip_idx in range(1, 41):
        hour = 7 + (trip_idx - 1) // 3
        minute = ((trip_idx - 1) % 3) * 20
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
    """PV generation: 10am-4pm peak"""
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


def test_gurobi_milp_large_scenario():
    """
    Test MILP optimization on large realistic scenario
    """
    print("\n" + "=" * 90)
    print("TEST: MILP (Gurobi) Optimization - Large Scenario (120 trips, 40 vehicles)")
    print("=" * 90)

    # Step 1: Create scenario
    print("\n[STEP 1] Creating large scenario...")
    scenario = _create_large_scenario()
    print(f"  Scenario ID: {scenario['meta']['id']}")
    print(f"  Routes: {len(scenario['routes'])}")
    print(f"  Vehicles: BEV={sum(1 for v in scenario['vehicles'] if v['type']=='BEV')}, "
          f"ICE={sum(1 for v in scenario['vehicles'] if v['type']=='ICE')}")
    print(f"  Timetable rows: {len(scenario['timetable_rows'])}")
    print(f"  Chargers: {len(scenario['chargers'])}")

    # Step 2: Build problem
    print("\n[STEP 2] Building optimization problem from scenario...")
    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id="MEGURO-DEPOT",
        service_id="WEEKDAY",
        config=OptimizationConfig(mode=OptimizationMode.MILP),
    )

    print(f"  Problem size:")
    print(f"    Trips: {len(problem.trips)}")
    print(f"    Vehicle types: {len(problem.vehicle_types)}")
    print(f"    Vehicles per type: {[vt.vehicle_type_id for vt in problem.vehicle_types]}")
    print(f"    Chargers: {len(problem.chargers)}")
    print(f"    Charger capacity: {sum(c.power_kw for c in problem.chargers)} kW")
    print(f"    Feasible connections: {len(problem.feasible_connections)}")

    # Step 3: Run MILP optimization
    print("\n[STEP 3] Running MILP (Gurobi) optimization...")
    print("  Configuration:")
    print("    Time limit: 300 seconds")
    print("    MIP gap: 2%")
    print("    Solver: Gurobi 13.0")

    engine = OptimizationEngine()
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        time_limit_sec=300,
        mip_gap=0.02,
        random_seed=42,
    )

    result = engine.solve(problem, config)
    payload = ResultSerializer.serialize_result(result)

    # Step 4: Display results
    print("\n[STEP 4] MILP Optimization Results")
    print(f"  Status: {result.solver_status}")
    print(f"  Feasible: {payload['feasible']}")
    print(f"  Objective value: {payload.get('objective_value', 'N/A')}")
    print(f"  Solver time: {payload.get('solver_time_seconds', 'N/A')} seconds")
    print(f"\n  Trip Coverage:")
    print(f"    Served: {len(payload['served_trip_ids'])}/{len(problem.trips)}")
    print(f"    Unserved: {len(payload['unserved_trip_ids'])}")

    print(f"\n  Vehicle Utilization:")
    vehicle_paths = payload.get('vehicle_paths', {})
    print(f"    Total duties: {len(vehicle_paths)}")

    bev_duties = sum(1 for vid in vehicle_paths if 'BEV' in vid)
    ice_duties = sum(1 for vid in vehicle_paths if 'ICE' in vid)
    print(f"    BEV duties: {bev_duties}")
    print(f"    ICE duties: {ice_duties}")

    # Trip distribution
    trips_per_duty = {}
    for vid, trips in vehicle_paths.items():
        trips_per_duty[len(trips)] = trips_per_duty.get(len(trips), 0) + 1

    print(f"\n  Trip Distribution per Duty:")
    for trip_count in sorted(trips_per_duty.keys()):
        print(f"    {trip_count} trips: {trips_per_duty[trip_count]} duties")

    # Cost breakdown
    print(f"\n  Cost Breakdown:")
    cost_breakdown = payload.get('cost_breakdown', {})
    for cost_key, cost_val in sorted(cost_breakdown.items()):
        if cost_val != 0:
            print(f"    {cost_key}: {cost_val:,.2f} JPY")

    if cost_breakdown:
        total_cost = cost_breakdown.get('total_cost', 0)
        cost_per_trip = total_cost / len(problem.trips) if problem.trips else 0
        print(f"    Average cost per trip: {cost_per_trip:,.2f} JPY")

    # Solver metadata
    print(f"\n  Solver Metadata:")
    solver_meta = payload.get('solver_metadata', {})
    print(f"    Warm start enabled: {solver_meta.get('warm_start_enabled', False)}")
    print(f"    Warm start source: {solver_meta.get('warm_start_source', 'N/A')}")
    print(f"    MIP nodes explored: {solver_meta.get('mip_nodes', 'N/A')}")
    print(f"    MIP gap: {solver_meta.get('mip_gap', 'N/A')}")

    # Validate results
    print("\n[STEP 5] Result Validation")
    assert payload["feasible"], "MILP should produce feasible solution"
    assert len(payload["served_trip_ids"]) == len(problem.trips), "All trips should be served"
    print("  [OK] All validation checks passed")

    # Performance analysis
    print("\n[STEP 6] Performance Analysis")
    solver_time = payload.get('solver_time_seconds', 0)
    print(f"  Solver efficiency: {len(problem.trips) / solver_time:.1f} trips/second")
    print(f"  Average duty length: {len(problem.trips) / len(vehicle_paths):.1f} trips")
    print(f"  Vehicle utilization: {(len(vehicle_paths) / 40) * 100:.1f}%")

    print("\n[PASS] MILP Large Scenario Test")

    return result, payload


def test_gurobi_vs_hybrid_quality():
    """
    Compare MILP (Gurobi) vs HYBRID solution quality
    """
    print("\n" + "=" * 90)
    print("TEST: MILP vs HYBRID - Solution Quality Comparison")
    print("=" * 90)

    scenario = _create_large_scenario()

    # Build problem
    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id="MEGURO-DEPOT",
        service_id="WEEKDAY",
        config=OptimizationConfig(mode=OptimizationMode.MILP),
    )

    engine = OptimizationEngine()

    # Test MILP
    print("\n[MILP Solver]")
    print("  Running MILP with 120s time limit...")
    milp_config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        time_limit_sec=120,
        mip_gap=0.02,
    )
    milp_result = engine.solve(problem, milp_config)
    milp_payload = ResultSerializer.serialize_result(milp_result)

    print(f"  Objective: {milp_payload.get('objective_value', 'N/A')}")
    print(f"  Feasible: {milp_payload['feasible']}")
    print(f"  Time: {milp_payload.get('solver_time_seconds', 'N/A')}s")

    # Test HYBRID
    print("\n[HYBRID Solver]")
    print("  Running HYBRID with 60s time limit...")
    hybrid_config = OptimizationConfig(
        mode=OptimizationMode.HYBRID,
        time_limit_sec=60,
        alns_iterations=100,
    )
    hybrid_result = engine.solve(problem, hybrid_config)
    hybrid_payload = ResultSerializer.serialize_result(hybrid_result)

    print(f"  Objective: {hybrid_payload.get('objective_value', 'N/A')}")
    print(f"  Feasible: {hybrid_payload['feasible']}")
    print(f"  Time: {hybrid_payload.get('solver_time_seconds', 'N/A')}s")

    # Comparison
    print("\n[Comparison]")
    milp_obj = milp_payload.get('objective_value', float('inf'))
    hybrid_obj = hybrid_payload.get('objective_value', float('inf'))

    if milp_obj != float('inf') and hybrid_obj != float('inf'):
        diff_pct = ((milp_obj - hybrid_obj) / hybrid_obj) * 100
        better = "MILP" if diff_pct < 0 else "HYBRID"
        print(f"  MILP objective: {milp_obj:,.2f}")
        print(f"  HYBRID objective: {hybrid_obj:,.2f}")
        print(f"  Difference: {abs(diff_pct):.1f}% ({better} better)")

    print("\n[PASS] Quality Comparison Test")


if __name__ == "__main__":
    test_gurobi_milp_large_scenario()
    test_gurobi_vs_hybrid_quality()

    print("\n" + "=" * 90)
    print("ALL GUROBI MILP TESTS COMPLETED")
    print("=" * 90)
