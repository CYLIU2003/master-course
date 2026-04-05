from __future__ import annotations

from src.optimization.common.builder import ProblemBuilder


def _scenario(timestep_min: int) -> dict:
    return {
        "meta": {"id": "s-ts", "updatedAt": "2026-03-24T00:00:00Z"},
        "simulation_config": {
            "default_turnaround_min": 10,
            "timestep_min": timestep_min,
        },
        "scenario_overlay": {
            "solver_config": {},
            "cost_coefficients": {},
            "charging_constraints": {},
        },
        "depots": [{"id": "dep-1", "name": "Depot 1"}],
        "routes": [{"id": "r1", "route_id": "r1"}],
        "vehicles": [
            {
                "id": "bev-1",
                "depotId": "dep-1",
                "type": "BEV",
                "batteryKwh": 300.0,
                "energyConsumption": 1.2,
                "chargePowerKw": 60.0,
                "enabled": True,
            },
            {
                "id": "bev-2",
                "depotId": "dep-2",
                "type": "BEV",
                "batteryKwh": 280.0,
                "energyConsumption": 1.1,
                "chargePowerKw": 60.0,
                "enabled": True,
            }
        ],
        "timetable_rows": [
            {
                "trip_id": "t1",
                "route_id": "r1",
                "origin": "A",
                "destination": "B",
                "departure": "08:00",
                "arrival": "10:00",
                "distance_km": 10.0,
                "service_id": "WEEKDAY",
                "allowed_vehicle_types": ["BEV"],
            }
        ],
        "energy_price_profiles": [{"site_id": "dep-1", "values": [10.0, 20.0]}],
        "pv_profiles": [{"site_id": "dep-1", "values": [2.0, 4.0]}],
        "deadhead_rules": [],
        "turnaround_rules": [],
    }


def test_problem_builder_uses_configured_timestep_60() -> None:
    problem = ProblemBuilder().build_from_scenario(_scenario(60), depot_id="dep-1", service_id="WEEKDAY")

    assert problem.scenario.timestep_min == 60
    # Fallback conversion uses pv_available_kw * (timestep/60)
    assert problem.depot_energy_assets["dep-1"].pv_generation_kwh_by_slot == (2.0, 4.0)
    assert [vehicle.vehicle_id for vehicle in problem.vehicles] == ["bev-1"]
    assert [vehicle.home_depot_id for vehicle in problem.vehicles] == ["dep-1"]


def test_problem_builder_uses_configured_timestep_30() -> None:
    problem = ProblemBuilder().build_from_scenario(_scenario(30), depot_id="dep-1", service_id="WEEKDAY")

    assert problem.scenario.timestep_min == 30
    assert problem.depot_energy_assets["dep-1"].pv_generation_kwh_by_slot == (1.0, 2.0)


def test_problem_builder_preserves_explicit_zero_turnaround() -> None:
    scenario = _scenario(60)
    scenario["simulation_config"]["default_turnaround_min"] = 0

    problem = ProblemBuilder().build_from_scenario(scenario, depot_id="dep-1", service_id="WEEKDAY")

    assert problem.dispatch_context.default_turnaround_min == 0


def test_problem_builder_build_from_scenario_forwards_planning_days() -> None:
    problem = ProblemBuilder().build_from_scenario(
        _scenario(60),
        depot_id="dep-1",
        service_id="WEEKDAY",
        planning_days=2,
    )

    assert problem.scenario.planning_days == 2
    assert len(problem.trips) == 2
    assert problem.depot_energy_assets["dep-1"].pv_generation_kwh_by_slot == (2.0, 4.0, 2.0, 4.0)
