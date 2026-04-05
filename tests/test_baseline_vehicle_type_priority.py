from __future__ import annotations

from src.optimization.alns.operators_repair import greedy_trip_insertion
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import AssignmentPlan


def _shared_fleet_scenario() -> dict:
    return {
        "meta": {"updatedAt": "2026-04-05T00:00:00Z"},
        "simulation_config": {
            "default_turnaround_min": 10,
            "max_start_fragments_per_vehicle": 4,
            "max_end_fragments_per_vehicle": 4,
        },
        "scenario_overlay": {
            "solver_config": {},
            "cost_coefficients": {},
            "charging_constraints": {},
        },
        "routes": [{"id": "r1", "route_id": "r1"}],
        "vehicles": [
            {
                "id": "bev-1",
                "depotId": "dep-1",
                "type": "BEV",
                "batteryKwh": 300.0,
                "energyConsumption": 1.0,
                "initialSoc": 0.9,
            },
            {
                "id": "ice-1",
                "depotId": "dep-1",
                "type": "ICE",
                "fuelTankL": 200.0,
                "fuelConsumptionLPerKm": 0.4,
            },
            {
                "id": "ice-2",
                "depotId": "dep-1",
                "type": "ICE",
                "fuelTankL": 200.0,
                "fuelConsumptionLPerKm": 0.4,
            },
        ],
        "timetable_rows": [
            {
                "trip_id": "t1",
                "route_id": "r1",
                "origin": "A",
                "destination": "B",
                "departure": "08:00",
                "arrival": "09:00",
                "distance_km": 8.0,
                "service_id": "WEEKDAY",
                "allowed_vehicle_types": ["BEV", "ICE"],
            },
            {
                "trip_id": "t2",
                "route_id": "r1",
                "origin": "A",
                "destination": "B",
                "departure": "08:00",
                "arrival": "09:00",
                "distance_km": 8.0,
                "service_id": "WEEKDAY",
                "allowed_vehicle_types": ["BEV", "ICE"],
            },
            {
                "trip_id": "t3",
                "route_id": "r1",
                "origin": "A",
                "destination": "B",
                "departure": "08:00",
                "arrival": "09:00",
                "distance_km": 8.0,
                "service_id": "WEEKDAY",
                "allowed_vehicle_types": ["BEV", "ICE"],
            },
        ],
        "deadhead_rules": [],
        "turnaround_rules": [],
    }


def test_baseline_plan_uses_shared_fleet_capacity_across_vehicle_types() -> None:
    problem = ProblemBuilder().build_from_scenario(
        _shared_fleet_scenario(),
        depot_id="dep-1",
        service_id="WEEKDAY",
    )

    assert problem.baseline_plan is not None
    assert set(problem.baseline_plan.served_trip_ids) == {"t1", "t2", "t3"}
    assert problem.baseline_plan.unserved_trip_ids == ()
    assert {duty.vehicle_type for duty in problem.baseline_plan.duties} == {"ICE", "BEV"}


def test_greedy_trip_insertion_uses_overflow_vehicle_types_for_shared_trips() -> None:
    problem = ProblemBuilder().build_from_scenario(
        _shared_fleet_scenario(),
        depot_id="dep-1",
        service_id="WEEKDAY",
    )

    empty_plan = AssignmentPlan(
        duties=(),
        charging_slots=(),
        refuel_slots=(),
        served_trip_ids=(),
        unserved_trip_ids=tuple(sorted(problem.eligible_trip_ids())),
        metadata={},
    )
    repaired = greedy_trip_insertion(problem, empty_plan)

    assert set(repaired.served_trip_ids) == {"t1", "t2", "t3"}
    assert repaired.unserved_trip_ids == ()
