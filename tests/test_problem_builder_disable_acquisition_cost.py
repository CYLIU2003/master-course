from __future__ import annotations

from src.optimization.common.builder import ProblemBuilder


def _scenario(disable: bool) -> dict:
    return {
        "meta": {"updatedAt": "2026-03-23T00:00:00Z"},
        "simulation_config": {
            "disable_vehicle_acquisition_cost": disable,
            "default_turnaround_min": 10,
        },
        "scenario_overlay": {
            "solver_config": {},
            "cost_coefficients": {},
            "charging_constraints": {},
        },
        "routes": [
            {"id": "r1", "route_id": "r1"},
        ],
        "vehicles": [
            {
                "id": "ice-1",
                "depotId": "dep-1",
                "type": "ICE",
                "acquisitionCost": 30000000.0,
                "residualValueYen": 6000000.0,
                "lifetimeYear": 12,
                "operationDaysPerYear": 365,
                "fuelConsumptionLPerKm": 0.4,
                "fuelTankL": 280.0,
            }
        ],
        "timetable_rows": [
            {
                "trip_id": "t1",
                "route_id": "r1",
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


def test_problem_builder_honors_disable_vehicle_acquisition_cost() -> None:
    builder = ProblemBuilder()

    enabled_problem = builder.build_from_scenario(_scenario(False), depot_id="dep-1", service_id="WEEKDAY")
    disabled_problem = builder.build_from_scenario(_scenario(True), depot_id="dep-1", service_id="WEEKDAY")

    enabled_cost = enabled_problem.vehicles[0].fixed_use_cost_jpy
    disabled_cost = disabled_problem.vehicles[0].fixed_use_cost_jpy

    assert enabled_cost > 0.0
    assert disabled_cost == 0.0
