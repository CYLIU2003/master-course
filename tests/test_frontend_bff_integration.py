"""
Test: Frontend → BFF → Backend integration flow

This test simulates the complete data flow:
1. Frontend sends RunOptimizationRequest (like POST /scenarios/{id}/run-optimization)
2. BFF processes the request and builds problem
3. Optimization engine solves
4. Results are serialized back to frontend format
"""

from datetime import datetime, timezone
from typing import Any, Dict, List

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


# ============================================================================
# Frontend Data Models (TypeScript types → Python dataclasses)
# ============================================================================


class RunOptimizationRequest:
    """Request body sent from frontend (POST /scenarios/{id}/run-optimization)"""

    def __init__(
        self,
        mode: str = "hybrid",
        time_limit_seconds: int = 300,
        mip_gap: float = 0.02,
        random_seed: int = 42,
        service_id: str = "WEEKDAY",
        depot_id: str = "MEGURO-DEPOT",
        rebuild_dispatch: bool = True,
        alns_iterations: int = 50,
    ):
        self.mode = mode
        self.time_limit_seconds = time_limit_seconds
        self.mip_gap = mip_gap
        self.random_seed = random_seed
        self.service_id = service_id
        self.depot_id = depot_id
        self.rebuild_dispatch = rebuild_dispatch
        self.alns_iterations = alns_iterations


class OptimizationJobResponse:
    """Response when optimization job is submitted (async)"""

    def __init__(self, job_id: str, scenario_id: str, status: str = "queued"):
        self.job_id = job_id
        self.scenario_id = scenario_id
        self.status = status
        self.progress = 0
        self.message = "Optimization queued"


class OptimizationResultResponse:
    """Final optimization result response (GET /scenarios/{id}/optimization)"""

    def __init__(self, payload: Dict[str, Any]):
        self.payload = payload


# ============================================================================
# BFF Mapper Simulation
# ============================================================================


def simulate_bff_handler(
    scenario: Dict[str, Any],
    request: RunOptimizationRequest,
) -> Dict[str, Any]:
    """
    Simulates BFF optimization handler:
    - Validates request
    - Builds problem from scenario
    - Runs optimization
    - Serializes result
    """
    print(f"\n  [BFF] Received optimization request")
    print(f"    Mode: {request.mode}")
    print(f"    Time limit: {request.time_limit_seconds}s")
    print(f"    Service ID: {request.service_id}")
    print(f"    Depot ID: {request.depot_id}")

    # Step 1: Validate scenario
    print(f"\n  [BFF] Validating scenario...")
    assert scenario["meta"]["id"], "Scenario must have ID"
    assert scenario["depots"], "Scenario must have depots"
    assert scenario["vehicles"], "Scenario must have vehicles"
    assert scenario["timetable_rows"], "Scenario must have timetable"
    print(f"    Scenario {scenario['meta']['id']} is valid")

    # Step 2: Build problem (this is where BFF mapper is used)
    print(f"\n  [BFF] Building problem from scenario...")
    mode = {
        "hybrid": OptimizationMode.HYBRID,
        "alns": OptimizationMode.ALNS,
        "milp": OptimizationMode.MILP,
    }.get(request.mode, OptimizationMode.HYBRID)

    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id=request.depot_id,
        service_id=request.service_id,
        config=OptimizationConfig(mode=mode),
    )

    print(f"    Built problem:")
    print(f"      Trips: {len(problem.trips)}")
    print(f"      Vehicle types: {len(problem.vehicle_types)}")
    print(f"      Chargers: {len(problem.chargers)}")
    print(f"      Feasible connections: {len(problem.feasible_connections)}")

    # Step 3: Run optimization (in a real BFF, this would be async in a worker)
    print(f"\n  [BFF] Running {request.mode} optimization...")
    engine = OptimizationEngine()
    config = OptimizationConfig(
        mode=mode,
        time_limit_sec=request.time_limit_seconds,
        mip_gap=request.mip_gap,
        random_seed=request.random_seed,
        alns_iterations=request.alns_iterations,
    )

    result = engine.solve(problem, config)

    # Step 4: Serialize result
    print(f"\n  [BFF] Serializing result...")
    payload = ResultSerializer.serialize_result(result)

    print(f"    Result:")
    print(f"      Feasible: {payload['feasible']}")
    print(f"      Objective: {payload.get('objective_value', 'N/A')}")
    print(f"      Served trips: {len(payload['served_trip_ids'])}/{len(problem.trips)}")
    print(f"      Vehicle paths: {len(payload['vehicle_paths'])}")

    return payload


# ============================================================================
# Test Scenarios
# ============================================================================


def _create_simple_scenario() -> Dict[str, Any]:
    """Create simple test scenario with 12 trips"""
    return {
        "meta": {
            "id": "frontend-test-001",
            "updatedAt": datetime.now(timezone.utc).isoformat(),
        },
        "depots": [{"id": "DEPOT-001", "name": "Test Depot"}],
        "vehicles": [
            {"id": "V1", "depotId": "DEPOT-001", "type": "BEV", "batteryKwh": 300.0, "energyConsumption": 1.2, "chargePowerKw": 150.0},
            {"id": "V2", "depotId": "DEPOT-001", "type": "BEV", "batteryKwh": 300.0, "energyConsumption": 1.2, "chargePowerKw": 150.0},
            {"id": "V3", "depotId": "DEPOT-001", "type": "ICE", "batteryKwh": 0.0, "energyConsumption": 0.0, "chargePowerKw": 0.0},
        ],
        "routes": [
            {"id": "R1"},
            {"id": "R2"},
        ],
        "depot_route_permissions": [
            {"depotId": "DEPOT-001", "routeId": "R1", "allowed": True},
            {"depotId": "DEPOT-001", "routeId": "R2", "allowed": True},
        ],
        "vehicle_route_permissions": [
            {"vehicleId": "V1", "routeId": "R1", "allowed": True},
            {"vehicleId": "V1", "routeId": "R2", "allowed": True},
            {"vehicleId": "V2", "routeId": "R1", "allowed": True},
            {"vehicleId": "V2", "routeId": "R2", "allowed": True},
            {"vehicleId": "V3", "routeId": "R1", "allowed": True},
            {"vehicleId": "V3", "routeId": "R2", "allowed": True},
        ],
        "timetable_rows": [
            # Route R1: 6 trips
            {"trip_id": "T1", "route_id": "R1", "service_id": "WEEKDAY", "origin": "A", "destination": "B", "departure": "07:00", "arrival": "07:20", "distance_km": 10.0, "allowed_vehicle_types": ["BEV", "ICE"]},
            {"trip_id": "T2", "route_id": "R1", "service_id": "WEEKDAY", "origin": "B", "destination": "C", "departure": "07:35", "arrival": "08:00", "distance_km": 12.0, "allowed_vehicle_types": ["BEV", "ICE"]},
            {"trip_id": "T3", "route_id": "R1", "service_id": "WEEKDAY", "origin": "C", "destination": "A", "departure": "08:20", "arrival": "08:45", "distance_km": 15.0, "allowed_vehicle_types": ["BEV", "ICE"]},
            {"trip_id": "T4", "route_id": "R1", "service_id": "WEEKDAY", "origin": "A", "destination": "B", "departure": "09:00", "arrival": "09:20", "distance_km": 10.0, "allowed_vehicle_types": ["BEV", "ICE"]},
            {"trip_id": "T5", "route_id": "R1", "service_id": "WEEKDAY", "origin": "B", "destination": "C", "departure": "09:35", "arrival": "10:00", "distance_km": 12.0, "allowed_vehicle_types": ["BEV", "ICE"]},
            {"trip_id": "T6", "route_id": "R1", "service_id": "WEEKDAY", "origin": "C", "destination": "A", "departure": "10:20", "arrival": "10:45", "distance_km": 15.0, "allowed_vehicle_types": ["BEV", "ICE"]},
            # Route R2: 6 trips
            {"trip_id": "T7", "route_id": "R2", "service_id": "WEEKDAY", "origin": "X", "destination": "Y", "departure": "07:10", "arrival": "07:30", "distance_km": 8.0, "allowed_vehicle_types": ["BEV", "ICE"]},
            {"trip_id": "T8", "route_id": "R2", "service_id": "WEEKDAY", "origin": "Y", "destination": "Z", "departure": "07:45", "arrival": "08:10", "distance_km": 9.0, "allowed_vehicle_types": ["BEV", "ICE"]},
            {"trip_id": "T9", "route_id": "R2", "service_id": "WEEKDAY", "origin": "Z", "destination": "X", "departure": "08:30", "arrival": "08:55", "distance_km": 7.0, "allowed_vehicle_types": ["BEV", "ICE"]},
            {"trip_id": "T10", "route_id": "R2", "service_id": "WEEKDAY", "origin": "X", "destination": "Y", "departure": "09:10", "arrival": "09:30", "distance_km": 8.0, "allowed_vehicle_types": ["BEV", "ICE"]},
            {"trip_id": "T11", "route_id": "R2", "service_id": "WEEKDAY", "origin": "Y", "destination": "Z", "departure": "09:45", "arrival": "10:10", "distance_km": 9.0, "allowed_vehicle_types": ["BEV", "ICE"]},
            {"trip_id": "T12", "route_id": "R2", "service_id": "WEEKDAY", "origin": "Z", "destination": "X", "departure": "10:30", "arrival": "10:55", "distance_km": 7.0, "allowed_vehicle_types": ["BEV", "ICE"]},
        ],
        "chargers": [
            {"id": "CHG1", "siteId": "DEPOT-001", "powerKw": 150.0},
        ],
        "pv_profiles": [
            {"site_id": "DEPOT-001", "values": [0.0] * 80}
        ],
        "energy_price_profiles": [
            {"site_id": "DEPOT-001", "values": [25.0] * 80}
        ],
    }


# ============================================================================
# Tests
# ============================================================================


def test_frontend_sends_hybrid_optimization_request():
    """
    Scenario: User clicks 'Optimize' button on frontend with HYBRID mode
    Expected: Optimization completes and result is returned with cost breakdown
    """
    print("\n" + "=" * 80)
    print("TEST: Frontend sends HYBRID optimization request")
    print("=" * 80)

    # Frontend creates scenario and request
    scenario = _create_simple_scenario()
    request = RunOptimizationRequest(
        mode="hybrid",
        time_limit_seconds=20,
        alns_iterations=30,
        service_id="WEEKDAY",
        depot_id="DEPOT-001",
    )

    # Simulate BFF handling
    result = simulate_bff_handler(scenario, request)

    # Validate result structure (what frontend expects)
    print("\n  [Frontend] Validating response structure...")
    assert "feasible" in result
    assert "solver_mode" in result
    assert "objective_value" in result
    assert "served_trip_ids" in result
    assert "unserved_trip_ids" in result
    assert "vehicle_paths" in result
    assert "cost_breakdown" in result

    print(f"    Response contains all expected fields")
    print(f"\n[PASS] Frontend HYBRID request test")


def test_frontend_sends_alns_only_request():
    """
    Scenario: User clicks 'Quick Optimize' using ALNS only
    Expected: Faster optimization with feasible result
    """
    print("\n" + "=" * 80)
    print("TEST: Frontend sends ALNS-only request")
    print("=" * 80)

    scenario = _create_simple_scenario()
    request = RunOptimizationRequest(
        mode="alns",
        time_limit_seconds=10,
        alns_iterations=20,
    )

    result = simulate_bff_handler(scenario, request)

    assert result["feasible"]
    assert len(result["served_trip_ids"]) == 12
    assert result["solver_mode"] == "alns"

    print(f"\n[PASS] Frontend ALNS request test")


def test_frontend_dispatch_scope_filtering():
    """
    Scenario: User selects specific depot/service before optimization
    The scenario is already scoped to that depot
    Expected: Optimization only covers trips for that scope
    """
    print("\n" + "=" * 80)
    print("TEST: Frontend dispatch scope filtering")
    print("=" * 80)

    scenario = _create_simple_scenario()

    # Frontend specifies scope
    request = RunOptimizationRequest(
        mode="hybrid",
        service_id="WEEKDAY",
        depot_id="DEPOT-001",  # Already in scenario
        time_limit_seconds=15,
    )

    print(f"\n  [Frontend] User selected:")
    print(f"    Depot: {request.depot_id}")
    print(f"    Service: {request.service_id}")

    result = simulate_bff_handler(scenario, request)

    print(f"\n  [Frontend] Optimization scoped correctly:")
    print(f"    Trips to optimize: {len(result['served_trip_ids'])}")

    assert len(result["served_trip_ids"]) == 12

    print(f"\n[PASS] Dispatch scope filtering test")


def test_frontend_receives_structured_result():
    """
    Scenario: Frontend receives optimization result and displays it
    Expected: All fields needed for UI display are present
    """
    print("\n" + "=" * 80)
    print("TEST: Frontend receives structured result")
    print("=" * 80)

    scenario = _create_simple_scenario()
    request = RunOptimizationRequest(mode="hybrid", time_limit_seconds=15)

    result = simulate_bff_handler(scenario, request)

    # Validate frontend display data
    print("\n  [Frontend] Processing result for display...")

    # Cost breakdown for summary card
    print(f"\n  Cost Breakdown:")
    for key, value in result.get("cost_breakdown", {}).items():
        if value > 0:
            print(f"    {key}: {value:.2f}")

    # Vehicle assignments
    print(f"\n  Vehicle Assignments:")
    for vehicle_id, trips in result.get("vehicle_paths", {}).items():
        print(f"    {vehicle_id}: {len(trips)} trips")

    # Trip coverage
    print(f"\n  Trip Coverage:")
    print(f"    Served: {len(result['served_trip_ids'])}")
    print(f"    Unserved: {len(result['unserved_trip_ids'])}")

    # Metadata
    if "solver_time_seconds" in result:
        print(f"\n  Solver Time: {result['solver_time_seconds']}s")

    print(f"\n[PASS] Frontend result display test")


if __name__ == "__main__":
    test_frontend_sends_hybrid_optimization_request()
    test_frontend_sends_alns_only_request()
    test_frontend_dispatch_scope_filtering()
    test_frontend_receives_structured_result()

    print("\n" + "=" * 80)
    print("ALL FRONTEND-BFF INTEGRATION TESTS PASSED")
    print("=" * 80)
