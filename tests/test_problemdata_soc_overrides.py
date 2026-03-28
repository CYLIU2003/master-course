from __future__ import annotations

from bff.mappers.scenario_to_problemdata import build_problem_data_from_scenario
from src.optimization.common.builder import ProblemBuilder


def _scenario() -> dict:
    return {
        "meta": {
            "id": "scenario-soc-overrides",
            "updatedAt": "2026-03-27T00:00:00+09:00",
        },
        "simulation_config": {
            "start_time": "05:00",
            "time_step_min": 15,
            "planning_horizon_hours": 20,
            "default_turnaround_min": 5,
            "initial_soc_percent": 50.0,
            "final_soc_floor_percent": 20.0,
            "final_soc_target_percent": 35.0,
            "objective_mode": "total_cost",
        },
        "scenario_overlay": {
            "solver_config": {},
            "cost_coefficients": {},
            "charging_constraints": {},
        },
        "dispatch_scope": {
            "depotId": "dep1",
            "serviceId": "WEEKDAY",
            "effectiveRouteIds": ["route-1"],
            "routeSelection": {"includeRouteIds": ["route-1"]},
            "tripSelection": {
                "includeShortTurn": True,
                "includeDepotMoves": True,
                "includeDeadhead": True,
            },
        },
        "depots": [{"id": "dep1", "name": "Depot 1"}],
        "routes": [
            {
                "id": "route-1",
                "depotId": "dep1",
                "routeCode": "R1",
                "routeFamilyCode": "R1",
                "routeVariantType": "main_outbound",
                "canonicalDirection": "outbound",
            }
        ],
        "vehicles": [
            {
                "id": "bev-1",
                "depotId": "dep1",
                "type": "BEV",
                "batteryKwh": 300.0,
                "energyConsumption": 1.2,
                "chargePowerKw": 90.0,
                "initialSoc": 0.9,
                "minSoc": 0.1,
                "maxSoc": 0.9,
                "targetEndSoc": 0.6,
                "enabled": True,
            }
        ],
        "chargers": [{"id": "chg-1", "siteId": "dep1", "powerKw": 90.0}],
        "timetable_rows": [
            {
                "trip_id": "trip-1",
                "route_id": "route-1",
                "service_id": "WEEKDAY",
                "direction": "outbound",
                "routeVariantType": "main_outbound",
                "routeFamilyCode": "R1",
                "origin": "Depot",
                "destination": "Terminal",
                "origin_stop_id": "stop-a",
                "destination_stop_id": "stop-b",
                "departure": "08:00",
                "arrival": "08:30",
                "distance_km": 6.0,
                "allowed_vehicle_types": ["BEV"],
            }
        ],
        "stops": [
            {"id": "stop-a", "name": "Depot", "lat": 35.0, "lon": 139.0},
            {"id": "stop-b", "name": "Terminal", "lat": 35.01, "lon": 139.01},
        ],
        "deadhead_rules": [],
        "turnaround_rules": [
            {"stop_id": "stop-a", "min_turnaround_min": 5},
            {"stop_id": "stop-b", "min_turnaround_min": 5},
        ],
        "vehicle_route_permissions": [],
        "route_depot_assignments": [{"routeId": "route-1", "depotId": "dep1"}],
        "depot_route_permissions": [{"depotId": "dep1", "routeId": "route-1", "allowed": True}],
    }


def test_problemdata_vehicle_soc_targets_follow_simulation_overrides() -> None:
    data, _report = build_problem_data_from_scenario(
        _scenario(),
        depot_id="dep1",
        service_id="WEEKDAY",
        mode="mode_ga_only",
    )

    vehicle = next(item for item in data.vehicles if item.vehicle_id == "bev-1")

    assert abs(float(vehicle.soc_init or 0.0) - 150.0) < 1.0e-9
    assert abs(float(vehicle.soc_min or 0.0) - 60.0) < 1.0e-9
    assert abs(float(vehicle.soc_target_end or 0.0) - 105.0) < 1.0e-9


def test_canonical_problem_builder_uses_saved_soc_overrides_for_vehicle_state() -> None:
    problem = ProblemBuilder().build_from_scenario(
        _scenario(),
        depot_id="dep1",
        service_id="WEEKDAY",
    )

    vehicle = next(item for item in problem.vehicles if item.vehicle_id == "bev-1")

    assert abs(float(vehicle.initial_soc or 0.0) - 150.0) < 1.0e-9
    assert abs(float(vehicle.reserve_soc or 0.0) - 60.0) < 1.0e-9
    assert problem.metadata.get("final_soc_target_percent") == 35.0
