from __future__ import annotations

from src.optimization.common.builder import ProblemBuilder


def _scenario() -> dict:
    return {
        "meta": {"id": "builder-available"},
        "simulation_config": {"service_coverage_mode": "strict"},
        "scenario_overlay": {"solver_config": {}, "charging_constraints": {}, "cost_coefficients": {}},
        "depots": [{"id": "dep-1", "name": "Depot"}],
        "routes": [{"id": "r1"}],
        "vehicles": [
            {"id": "veh-available", "type": "ICE", "depotId": "dep-1", "enabled": True},
            {"id": "veh-unavailable", "type": "ICE", "depotId": "dep-1", "enabled": False},
        ],
        "timetable_rows": [
            {
                "trip_id": "t1",
                "route_id": "r1",
                "origin": "A",
                "destination": "B",
                "departure": "08:00",
                "arrival": "08:10",
                "distance_km": 1.0,
                "service_id": "WEEKDAY",
                "allowed_vehicle_types": ["ICE"],
            }
        ],
    }


def test_builder_emits_available_vehicle_metadata_and_excludes_unavailable_baseline() -> None:
    problem = ProblemBuilder().build_from_scenario(
        _scenario(),
        depot_id="dep-1",
        service_id="WEEKDAY",
    )

    assert problem.metadata["available_vehicle_count_total"] == 1
    assert problem.metadata["unavailable_vehicle_count_total"] == 1
    assert problem.metadata["available_vehicle_ids"] == ("veh-available",)
    assert problem.metadata["unavailable_vehicle_ids"] == ("veh-unavailable",)
    assert problem.baseline_plan is not None
    assert "veh-unavailable" not in problem.baseline_plan.duties_by_vehicle()
