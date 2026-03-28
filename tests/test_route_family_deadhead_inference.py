from __future__ import annotations

from unittest import mock

from bff.mappers.scenario_to_problemdata import build_problem_data_from_scenario
from bff.routers import graph as graph_router
from src.dispatch.graph_builder import ConnectionGraphBuilder
from src.route_family_runtime import merge_deadhead_metrics, normalize_variant_type, route_variant_bucket


def _family_scenario() -> dict:
    return {
        "meta": {
            "id": "scenario-route-family",
            "updatedAt": "2026-03-22T09:00:00+09:00",
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
            "effectiveRouteIds": ["route-out", "route-in"],
            "routeSelection": {
                "includeRouteIds": ["route-out", "route-in"],
            },
            "tripSelection": {
                "includeShortTurn": True,
                "includeDepotMoves": True,
                "includeDeadhead": True,
            },
        },
        "depots": [{"id": "dep1", "name": "Depot 1"}],
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
                "id": "route-out",
                "routeCode": "黒01",
                "routeFamilyCode": "黒01",
                "routeVariantType": "main_outbound",
                "canonicalDirection": "outbound",
                "depotId": "dep1",
            },
            {
                "id": "route-in",
                "routeCode": "黒01",
                "routeFamilyCode": "黒01",
                "routeVariantType": "main_inbound",
                "canonicalDirection": "inbound",
                "depotId": "dep1",
            },
        ],
        "timetable_rows": [
            {
                "trip_id": "trip-1",
                "route_id": "route-out",
                "service_id": "WEEKDAY",
                "direction": "outbound",
                "routeVariantType": "main_outbound",
                "routeFamilyCode": "黒01",
                "origin": "Depot Bay",
                "destination": "Station Bay 1",
                "origin_stop_id": "stop-a",
                "destination_stop_id": "stop-b-out",
                "departure": "08:00",
                "arrival": "08:30",
                "distance_km": 6.0,
                "allowed_vehicle_types": ["BEV"],
            },
            {
                "trip_id": "trip-2",
                "route_id": "route-in",
                "service_id": "WEEKDAY",
                "direction": "inbound",
                "routeVariantType": "main_inbound",
                "routeFamilyCode": "黒01",
                "origin": "Station Bay 2",
                "destination": "Depot Bay",
                "origin_stop_id": "stop-b-in",
                "destination_stop_id": "stop-a",
                "departure": "08:45",
                "arrival": "09:15",
                "distance_km": 6.0,
                "allowed_vehicle_types": ["BEV"],
            },
        ],
        "trips": [],
        "stops": [
            {"id": "stop-a", "name": "Depot Bay", "lat": 35.0000, "lon": 139.0000},
            {"id": "stop-b-out", "name": "Station Bay 1", "lat": 35.0010, "lon": 139.0010},
            {"id": "stop-b-in", "name": "Station Bay 2", "lat": 35.0012, "lon": 139.0011},
        ],
        "turnaround_rules": [
            {"stop_id": "stop-a", "min_turnaround_min": 5},
            {"stop_id": "stop-b-out", "min_turnaround_min": 5},
            {"stop_id": "stop-b-in", "min_turnaround_min": 5},
        ],
        "deadhead_rules": [],
        "vehicle_route_permissions": [],
        "route_depot_assignments": [
            {"routeId": "route-out", "depotId": "dep1"},
            {"routeId": "route-in", "depotId": "dep1"},
        ],
        "depot_route_permissions": [
            {"depotId": "dep1", "routeId": "route-out", "allowed": True},
            {"depotId": "dep1", "routeId": "route-in", "allowed": True},
        ],
    }


def test_variant_normalization_preserves_directional_family_variants() -> None:
    assert normalize_variant_type("main", direction="outbound") == "main_outbound"
    assert normalize_variant_type("main", direction="inbound") == "main_inbound"
    assert normalize_variant_type("depot", direction="inbound") == "depot_in"
    assert route_variant_bucket("depot_out") == "depot"


def test_problem_data_build_infers_same_family_deadhead_from_terminal_coords() -> None:
    scenario = _family_scenario()

    data, report = build_problem_data_from_scenario(
        scenario,
        depot_id="dep1",
        service_id="WEEKDAY",
        mode="mode_milp_only",
    )

    task_by_id = {task.task_id: task for task in data.tasks}
    connection = next(
        item
        for item in data.travel_connections
        if item.from_task_id == "trip-1" and item.to_task_id == "trip-2"
    )

    assert task_by_id["trip-1"].route_variant_type == "main_outbound"
    assert task_by_id["trip-2"].route_variant_type == "main_inbound"
    assert task_by_id["trip-1"].destination_stop_id == "stop-b-out"
    assert task_by_id["trip-2"].origin_stop_id == "stop-b-in"
    assert connection.can_follow is True
    assert connection.deadhead_time_slot > 0
    assert connection.deadhead_distance_km > 0.0
    assert report.graph_edge_count > 0


def test_graph_context_uses_stop_ids_for_family_deadhead_inference() -> None:
    scenario = _family_scenario()
    fields = {
        "trips": [],
        "timetable_rows": scenario["timetable_rows"],
        "stops": scenario["stops"],
    }

    def _get_field(_scenario_id: str, field: str):
        return fields.get(field)

    with mock.patch.object(graph_router.store, "get_dispatch_scope", return_value=scenario["dispatch_scope"]), mock.patch.object(
        graph_router.store,
        "get_scenario_document_shallow",
        return_value={"dispatch_scope": scenario["dispatch_scope"]},
    ), mock.patch.object(
        graph_router.store,
        "_normalize_dispatch_scope",
        return_value=scenario["dispatch_scope"],
    ), mock.patch.object(
        graph_router.store,
        "effective_route_ids_for_scope",
        return_value=["route-out", "route-in"],
    ), mock.patch.object(graph_router.store, "get_field", side_effect=_get_field), mock.patch.object(
        graph_router.store,
        "list_routes",
        return_value=scenario["routes"],
    ), mock.patch.object(
        graph_router.store,
        "list_vehicles",
        return_value=scenario["vehicles"],
    ), mock.patch.object(
        graph_router.store,
        "get_vehicle_route_permissions",
        return_value=[],
    ), mock.patch.object(
        graph_router.store,
        "get_turnaround_rules",
        return_value=scenario["turnaround_rules"],
    ), mock.patch.object(
        graph_router.store,
        "get_deadhead_rules",
        return_value=[],
    ):
        context = graph_router._build_dispatch_context(
            "scenario-route-family",
            service_id="WEEKDAY",
            depot_id="dep1",
        )

    graph_payload = ConnectionGraphBuilder().build(context, "BEV")

    assert context.get_deadhead_min("stop-b-out", "stop-b-in") > 0
    assert context.trips_by_id()["trip-1"].destination_stop_id == "stop-b-out"
    assert context.trips_by_id()["trip-2"].origin_stop_id == "stop-b-in"
    assert "trip-2" in graph_payload["trip-1"]


def test_merge_deadhead_metrics_adds_zero_cost_rules_for_platform_aliases() -> None:
    metrics = merge_deadhead_metrics(
        existing_rules=[],
        trip_rows=[],
        routes=[],
        stops=[
            {
                "id": "odpt.BusstopPole:TokyuBus.Shibuyaeki.00240050.",
                "name": "渋谷駅",
                "lat": 35.0,
                "lon": 139.0,
            },
            {
                "id": "odpt.BusstopPole:TokyuBus.Shibuyaeki.00240050.4",
                "name": "渋谷駅 4番",
                "lat": 35.0,
                "lon": 139.0,
            },
        ],
    )

    forward = metrics[(
        "odpt.BusstopPole:TokyuBus.Shibuyaeki.00240050.",
        "odpt.BusstopPole:TokyuBus.Shibuyaeki.00240050.4",
    )]
    backward = metrics[(
        "odpt.BusstopPole:TokyuBus.Shibuyaeki.00240050.4",
        "odpt.BusstopPole:TokyuBus.Shibuyaeki.00240050.",
    )]

    assert forward.travel_time_min == 0
    assert backward.travel_time_min == 0
    assert forward.source == "stop_platform_alias"
    assert backward.source == "stop_platform_alias"
