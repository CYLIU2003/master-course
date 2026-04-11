from __future__ import annotations

from src.optimization.common.builder import ProblemBuilder


def _scenario(*, planning_days: int) -> dict:
    return {
        "meta": {"id": "builder-route-family"},
        "simulation_config": {
            "allow_same_day_depot_cycles": True,
            "max_depot_cycles_per_vehicle_per_day": 2,
            "service_coverage_mode": "strict",
            "planning_days": planning_days,
        },
        "scenario_overlay": {
            "solver_config": {},
            "charging_constraints": {},
            "cost_coefficients": {},
        },
        "depots": [{"id": "dep-1", "name": "Depot 1"}],
        "routes": [
            {
                "id": "route-variant-a",
                "route_id": "route-variant-a",
                "routeFamilyCode": "渋21",
            }
        ],
        "vehicles": [
            {
                "id": "veh-1",
                "depotId": "dep-1",
                "type": "ICE",
            }
        ],
        "timetable_rows": [
            {
                "trip_id": "trip-1",
                "route_id": "route-variant-a",
                "routeFamilyCode": "渋21",
                "origin": "A",
                "destination": "B",
                "departure": "08:00",
                "arrival": "08:30",
                "distance_km": 10.0,
                "service_id": "WEEKDAY",
                "allowed_vehicle_types": ["ICE"],
            }
        ],
        "deadhead_rules": [],
        "turnaround_rules": [],
    }


def test_builder_propagates_route_family_code_to_canonical_trips() -> None:
    problem = ProblemBuilder().build_from_scenario(
        _scenario(planning_days=1),
        depot_id="dep-1",
        service_id="WEEKDAY",
        planning_days=1,
    )

    trip_by_id = {trip.trip_id: trip for trip in problem.trips}
    assert trip_by_id["trip-1"].route_family_code == "渋21"


def test_builder_preserves_route_family_code_in_multi_day_replication() -> None:
    problem = ProblemBuilder().build_from_scenario(
        _scenario(planning_days=2),
        depot_id="dep-1",
        service_id="WEEKDAY",
        planning_days=2,
    )

    trip_by_id = {trip.trip_id: trip for trip in problem.trips}
    assert trip_by_id["trip-1"].route_family_code == "渋21"
    assert trip_by_id["d1_trip-1"].route_family_code == "渋21"
