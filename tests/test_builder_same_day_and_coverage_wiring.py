from __future__ import annotations

from src.optimization.common.builder import ProblemBuilder


def _scenario() -> dict:
    return {
        "meta": {"id": "builder-wiring"},
        "simulation_config": {
            "allow_same_day_depot_cycles": True,
            "max_depot_cycles_per_vehicle_per_day": 3,
            "service_coverage_mode": "strict",
        },
        "scenario_overlay": {
            "solver_config": {},
            "charging_constraints": {},
            "cost_coefficients": {},
        },
        "depots": [{"id": "dep-1", "name": "Depot 1"}],
        "routes": [{"id": "r1", "route_id": "r1"}],
        "vehicles": [
            {
                "id": "veh-1",
                "depotId": "dep-1",
                "type": "ICE",
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


def test_builder_wires_same_day_coverage_and_band_defaults() -> None:
    problem = ProblemBuilder().build_from_scenario(
        _scenario(),
        depot_id="dep-1",
        service_id="WEEKDAY",
        planning_days=1,
    )

    assert problem.metadata["daily_fragment_limit"] >= 2
    assert problem.metadata["service_coverage_mode"] == "strict"
    assert problem.metadata["allow_partial_service"] is False
    assert problem.metadata["fixed_route_band_mode"] is False


def test_builder_prefers_explicit_service_coverage_mode_over_allow_partial_service() -> None:
    scenario = _scenario()
    scenario["simulation_config"] = {
        **scenario["simulation_config"],
        "service_coverage_mode": "strict",
        "allow_partial_service": True,
    }

    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id="dep-1",
        service_id="WEEKDAY",
        planning_days=1,
    )

    assert problem.metadata["service_coverage_mode"] == "strict"
    assert problem.metadata["allow_partial_service"] is False


def test_builder_falls_back_to_allow_partial_service_when_coverage_mode_is_missing() -> None:
    scenario = _scenario()
    scenario["simulation_config"] = {
        key: value
        for key, value in scenario["simulation_config"].items()
        if key != "service_coverage_mode"
    }
    scenario["simulation_config"]["allow_partial_service"] = True

    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id="dep-1",
        service_id="WEEKDAY",
        planning_days=1,
    )

    assert problem.metadata["service_coverage_mode"] == "penalized"
    assert problem.metadata["allow_partial_service"] is True
