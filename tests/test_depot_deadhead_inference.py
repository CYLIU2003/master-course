from __future__ import annotations

from bff.mappers import scenario_to_problemdata as problemdata_module
from src.dispatch.feasibility import evaluate_startup_feasibility
from src.dispatch.models import Trip
from src.optimization.common import builder as builder_module
from src.optimization.common.builder import ProblemBuilder
from src.route_family_runtime import merge_deadhead_metrics


def _depot_inference_scenario() -> dict:
    return {
        "meta": {
            "id": "scenario-depot-deadhead",
            "updatedAt": "2026-04-11T09:00:00+09:00",
        },
        "simulation_config": {
            "start_time": "05:00",
            "time_step_min": 15,
            "planning_horizon_hours": 16,
            "default_turnaround_min": 5,
        },
        "scenario_overlay": {},
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
        "depots": [
            {
                "id": "dep1",
                "name": "Tsurumaki Depot",
                "lat": 35.0000,
                "lon": 139.0000,
            }
        ],
        "vehicles": [
            {
                "id": "veh-1",
                "depotId": "dep1",
                "type": "BEV",
                "batteryKwh": 300,
                "energyConsumption": 1.2,
                "chargePowerKw": 90,
                "initialSoc": 0.8,
                "minSoc": 0.2,
                "maxSoc": 0.9,
            }
        ],
        "routes": [
            {
                "id": "route-1",
                "routeCode": "渋21",
                "routeFamilyCode": "渋21/渋22",
                "routeVariantType": "main_outbound",
                "canonicalDirection": "outbound",
                "depotId": "dep1",
            }
        ],
        "timetable_rows": [
            {
                "trip_id": "trip-1",
                "route_id": "route-1",
                "service_id": "WEEKDAY",
                "direction": "outbound",
                "routeVariantType": "main_outbound",
                "routeFamilyCode": "渋21/渋22",
                "origin": "Kamimachieki",
                "destination": "Depot Bay A",
                "origin_stop_id": "stop-origin-1",
                "destination_stop_id": "stop-destination-1",
                "departure": "08:00",
                "arrival": "08:30",
                "distance_km": 6.0,
                "allowed_vehicle_types": ["BEV"],
            },
            {
                "trip_id": "trip-2",
                "route_id": "route-1",
                "service_id": "WEEKDAY",
                "direction": "outbound",
                "routeVariantType": "main_outbound",
                "routeFamilyCode": "渋21/渋22",
                "origin": "Kamimachieki Annex",
                "destination": "Depot Bay B",
                "origin_stop_id": "stop-origin-2",
                "destination_stop_id": "stop-destination-2",
                "departure": "09:00",
                "arrival": "09:30",
                "distance_km": 6.0,
                "allowed_vehicle_types": ["BEV"],
            },
        ],
        "stops": [
            {
                "id": "stop-origin-1",
                "name": "Kamimachieki",
                "lat": 35.0007,
                "lon": 139.0006,
            },
            {
                "id": "stop-destination-1",
                "name": "Depot Bay A",
                "lat": 35.0010,
                "lon": 139.0010,
            },
            {
                "id": "stop-origin-2",
                "name": "Kamimachieki Annex",
                "lat": 35.0012,
                "lon": 139.0011,
            },
            {
                "id": "stop-destination-2",
                "name": "Depot Bay B",
                "lat": 35.0014,
                "lon": 139.0013,
            },
        ],
        "turnaround_rules": [
            {"stop_id": "stop-origin-1", "min_turnaround_min": 5},
            {"stop_id": "stop-destination-1", "min_turnaround_min": 5},
            {"stop_id": "stop-origin-2", "min_turnaround_min": 5},
            {"stop_id": "stop-destination-2", "min_turnaround_min": 5},
        ],
        "deadhead_rules": [],
        "vehicle_route_permissions": [],
        "route_depot_assignments": [{"routeId": "route-1", "depotId": "dep1"}],
        "depot_route_permissions": [{"depotId": "dep1", "routeId": "route-1", "allowed": True}],
    }


class _StartupContext:
    def __init__(self, deadheads: dict[tuple[str, str], int], known_locations: set[str]) -> None:
        self._deadheads = deadheads
        self._known_locations = known_locations

    def get_deadhead_min(self, from_stop: str, to_stop: str) -> int:
        return int(self._deadheads.get((from_stop, to_stop), 0))

    def locations_equivalent(self, left: str, right: str) -> bool:
        return left == right

    def has_location_data(self, stop: str) -> bool:
        return stop in self._known_locations


def test_merge_deadhead_metrics_adds_depot_start_and_return_rules() -> None:
    scenario = _depot_inference_scenario()

    metrics = merge_deadhead_metrics(
        existing_rules=[],
        trip_rows=scenario["timetable_rows"],
        routes=scenario["routes"],
        stops=scenario["stops"],
        depots=scenario["depots"],
    )

    startup_rule = metrics[("dep1", "stop-origin-1")]
    return_rule = metrics[("stop-destination-1", "dep1")]

    assert startup_rule.source == "depot_terminal_inference"
    assert startup_rule.travel_time_min > 0
    assert startup_rule.distance_km > 0.0
    assert return_rule.source == "depot_terminal_inference"
    assert return_rule.travel_time_min > 0
    assert return_rule.distance_km > 0.0


def test_startup_feasibility_becomes_feasible_via_inferred_depot_deadhead() -> None:
    scenario = _depot_inference_scenario()
    metrics = merge_deadhead_metrics(
        existing_rules=[],
        trip_rows=scenario["timetable_rows"],
        routes=scenario["routes"],
        stops=scenario["stops"],
        depots=scenario["depots"],
    )
    context = _StartupContext(
        {key: metric.travel_time_min for key, metric in metrics.items()},
        {"dep1", "stop-origin-1"},
    )
    trip = Trip(
        trip_id="trip-startup",
        route_id="route-1",
        origin="Kamimachieki",
        destination="Depot Bay A",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=6.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-origin-1",
        destination_stop_id="stop-destination-1",
        route_family_code="渋21/渋22",
    )

    result = evaluate_startup_feasibility(trip, context, "dep1")

    assert result.feasible is True
    assert result.reason_code == "feasible"
    assert result.deadhead_time_min > 0


def test_problem_builder_threads_depots_and_keeps_some_startups_feasible(monkeypatch) -> None:
    scenario = _depot_inference_scenario()
    captured: dict[str, list[dict[str, object]]] = {}
    original_merge = builder_module.merge_deadhead_metrics

    def _capture_merge(*args, **kwargs):
        captured["depots"] = list(kwargs.get("depots") or [])
        return original_merge(*args, **kwargs)

    monkeypatch.setattr(builder_module, "merge_deadhead_metrics", _capture_merge)

    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id="dep1",
        service_id="WEEKDAY",
    )

    assert captured["depots"] == scenario["depots"]
    assert problem.dispatch_context.get_deadhead_min("dep1", "stop-origin-1") > 0
    assert problem.dispatch_context.get_deadhead_min("stop-destination-1", "dep1") > 0

    startup_results = [
        evaluate_startup_feasibility(
            trip,
            problem.dispatch_context,
            problem.vehicles[0].home_depot_id,
        )
        for trip in problem.trips
    ]
    startup_infeasible_assignment_count = sum(1 for result in startup_results if not result.feasible)

    assert any(result.feasible for result in startup_results)
    assert startup_infeasible_assignment_count < len(problem.trips)


def test_problemdata_mapper_threads_depots_into_deadhead_merge(monkeypatch) -> None:
    scenario = _depot_inference_scenario()
    captured: dict[str, list[dict[str, object]]] = {}
    original_merge = problemdata_module.merge_deadhead_metrics

    def _capture_merge(*args, **kwargs):
        captured["depots"] = list(kwargs.get("depots") or [])
        return original_merge(*args, **kwargs)

    monkeypatch.setattr(problemdata_module, "merge_deadhead_metrics", _capture_merge)

    data, report = problemdata_module.build_problem_data_from_scenario(
        scenario,
        depot_id="dep1",
        service_id="WEEKDAY",
        mode="mode_milp_only",
    )

    assert captured["depots"] == scenario["depots"]
    assert report.graph_edge_count > 0
    assert data.travel_connections
