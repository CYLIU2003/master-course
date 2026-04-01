from __future__ import annotations

from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.evaluator import CostEvaluator


def _scenario(
    *,
    cost_component_flags: dict | None = None,
) -> dict:
    return {
        "meta": {"updatedAt": "2026-03-31T00:00:00Z"},
        "simulation_config": {
            "default_turnaround_min": 10,
            "objective_mode": "total_cost",
            "cost_component_flags": dict(cost_component_flags or {}),
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
            cost_component_flags={
                "vehicle_fixed_cost": False,
                "driver_cost": False,
                "electricity_cost": False,
                "fuel_cost": False,
                "demand_charge_cost": False,
                "unserved_penalty": False,
                "battery_degradation_cost": False,
                "co2_cost": False,
                "contract_overage_penalty": False,
                "charge_session_start_penalty": False,
                "slot_concurrency_penalty": False,
                "early_charge_penalty": False,
                "soc_upper_buffer_penalty": False,
                "final_soc_target_penalty": False,
                "grid_to_bus_priority_penalty": False,
                "grid_to_bess_priority_penalty": False,
            },
        ),
        depot_id="dep-1",
        service_id="WEEKDAY",
    )
    assert toggled_problem.baseline_plan is not None
    toggled_breakdown = evaluator.evaluate(toggled_problem, toggled_problem.baseline_plan)

    assert toggled_problem.metadata["cost_component_flags"]["vehicle_fixed_cost"] is False
    assert toggled_problem.metadata["cost_component_flags"]["driver_cost"] is False
    assert toggled_problem.metadata["cost_component_flags"]["electricity_cost"] is False
    assert toggled_problem.metadata["cost_component_flags"]["fuel_cost"] is False
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
    assert toggled_breakdown.total_co2_kg >= 0.0
