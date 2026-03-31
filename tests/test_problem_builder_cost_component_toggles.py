from __future__ import annotations

from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.evaluator import CostEvaluator


def _scenario(
    *,
    enable_vehicle_cost: bool = True,
    enable_driver_cost: bool = True,
    enable_other_cost: bool = True,
) -> dict:
    return {
        "meta": {"updatedAt": "2026-03-31T00:00:00Z"},
        "simulation_config": {
            "default_turnaround_min": 10,
            "objective_mode": "total_cost",
            "enable_vehicle_cost": enable_vehicle_cost,
            "enable_driver_cost": enable_driver_cost,
            "enable_other_cost": enable_other_cost,
        },
        "scenario_overlay": {
            "solver_config": {},
            "cost_coefficients": {
                "diesel_price_per_l": 145.0,
                "grid_flat_price_per_kwh": 30.0,
            },
            "charging_constraints": {},
        },
        "routes": [{"id": "r1", "route_id": "r1"}],
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


def test_cost_component_toggles_flow_into_problem_and_cost_breakdown() -> None:
    builder = ProblemBuilder()
    evaluator = CostEvaluator()

    full_problem = builder.build_from_scenario(
        _scenario(),
        depot_id="dep-1",
        service_id="WEEKDAY",
    )
    assert full_problem.baseline_plan is not None
    full_breakdown = evaluator.evaluate(full_problem, full_problem.baseline_plan)

    assert full_breakdown.vehicle_cost > 0.0
    assert full_breakdown.driver_cost > 0.0
    assert full_breakdown.energy_cost > 0.0

    toggled_problem = builder.build_from_scenario(
        _scenario(
            enable_vehicle_cost=False,
            enable_driver_cost=False,
            enable_other_cost=False,
        ),
        depot_id="dep-1",
        service_id="WEEKDAY",
    )
    assert toggled_problem.baseline_plan is not None
    toggled_breakdown = evaluator.evaluate(toggled_problem, toggled_problem.baseline_plan)

    assert toggled_problem.metadata["cost_component_flags"] == {
        "vehicle": False,
        "driver": False,
        "other": False,
    }
    assert toggled_problem.objective_weights.vehicle == 0.0
    assert toggled_problem.objective_weights.energy == 0.0
    assert toggled_problem.objective_weights.demand == 0.0
    assert toggled_problem.objective_weights.unserved == 0.0
    assert toggled_breakdown.vehicle_cost == 0.0
    assert toggled_breakdown.driver_cost == 0.0
    assert toggled_breakdown.energy_cost == 0.0
    assert toggled_breakdown.demand_cost == 0.0
    assert toggled_breakdown.co2_cost == 0.0
    assert toggled_breakdown.total_cost == 0.0
    assert toggled_breakdown.total_cost_with_assets == 0.0
    assert toggled_breakdown.total_co2_kg >= 0.0
