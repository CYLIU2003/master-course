from pathlib import Path

import pytest

from bff.routers.graph import (
    _build_blocks_payload,
    _build_dispatch_context,
    _build_dispatch_plan_payload,
    _build_graph_payload,
)
from bff.store import scenario_store


@pytest.fixture()
def temp_store_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store_dir = tmp_path / "scenarios"
    monkeypatch.setattr(scenario_store, "_STORE_DIR", store_dir)
    return store_dir


def test_build_dispatch_context_uses_scenario_rules(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Dispatch rules", "", "thesis_mode")
    scenario_id = meta["id"]

    depot = scenario_store.create_depot(
        scenario_id,
        {"name": "Main depot", "location": "A"},
    )
    scenario_store.create_vehicle(
        scenario_id,
        {
            "depotId": depot["id"],
            "type": "BEV",
            "modelName": "EV-1",
            "batteryKwh": 300.0,
            "energyConsumption": 1.2,
        },
    )
    scenario_store.set_depot_route_permissions(
        scenario_id,
        [{"depotId": depot["id"], "routeId": "R1", "allowed": True}],
    )
    scenario_store.set_deadhead_rules(
        scenario_id,
        [{"from_stop": "B", "to_stop": "C", "travel_time_min": 15}],
    )
    scenario_store.set_turnaround_rules(
        scenario_id,
        [{"stop_id": "B", "min_turnaround_min": 7}],
    )
    scenario_store.set_field(
        scenario_id,
        "timetable_rows",
        [
            {
                "trip_id": "T1",
                "route_id": "R1",
                "service_id": "WEEKDAY",
                "origin": "A",
                "destination": "B",
                "departure": "07:00",
                "arrival": "07:30",
                "distance_km": 10.0,
                "allowed_vehicle_types": ["BEV", "ICE"],
            },
            {
                "trip_id": "T2",
                "route_id": "R1",
                "service_id": "WEEKDAY",
                "origin": "C",
                "destination": "D",
                "departure": "08:00",
                "arrival": "08:30",
                "distance_km": 9.0,
                "allowed_vehicle_types": ["BEV", "ICE"],
            },
        ],
        invalidate_dispatch=True,
    )

    context = _build_dispatch_context(scenario_id, "WEEKDAY", depot["id"])

    assert context.turnaround_rules["B"].min_turnaround_min == 7
    assert context.deadhead_rules[("B", "C")].travel_time_min == 15


def test_build_dispatch_context_filters_trip_vehicle_types_by_vehicle_route_permissions(
    temp_store_dir: Path,
):
    meta = scenario_store.create_scenario("Vehicle route filtering", "", "thesis_mode")
    scenario_id = meta["id"]

    depot = scenario_store.create_depot(
        scenario_id,
        {"name": "Main depot", "location": "A"},
    )
    bev = scenario_store.create_vehicle(
        scenario_id,
        {
            "depotId": depot["id"],
            "type": "BEV",
            "modelName": "EV-1",
            "batteryKwh": 300.0,
            "energyConsumption": 1.2,
        },
    )
    scenario_store.create_vehicle(
        scenario_id,
        {
            "depotId": depot["id"],
            "type": "ICE",
            "modelName": "ICE-1",
            "fuelTankL": 200.0,
        },
    )
    scenario_store.set_depot_route_permissions(
        scenario_id,
        [{"depotId": depot["id"], "routeId": "R1", "allowed": True}],
    )
    scenario_store.set_vehicle_route_permissions(
        scenario_id,
        [{"vehicleId": bev["id"], "routeId": "R1", "allowed": False}],
    )
    scenario_store.set_field(
        scenario_id,
        "timetable_rows",
        [
            {
                "trip_id": "T1",
                "route_id": "R1",
                "service_id": "WEEKDAY",
                "origin": "A",
                "destination": "B",
                "departure": "07:00",
                "arrival": "07:30",
                "distance_km": 10.0,
                "allowed_vehicle_types": ["BEV", "ICE"],
            }
        ],
        invalidate_dispatch=True,
    )

    context = _build_dispatch_context(scenario_id, "WEEKDAY", depot["id"])

    assert len(context.trips) == 1
    assert context.trips[0].allowed_vehicle_types == ("ICE",)


def test_build_graph_payload_returns_reasoned_arcs(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Graph payload", "", "thesis_mode")
    scenario_id = meta["id"]

    depot = scenario_store.create_depot(
        scenario_id,
        {"name": "Main depot", "location": "A"},
    )
    scenario_store.create_vehicle(
        scenario_id,
        {
            "depotId": depot["id"],
            "type": "BEV",
            "modelName": "EV-1",
            "batteryKwh": 300.0,
            "energyConsumption": 1.2,
        },
    )
    scenario_store.set_depot_route_permissions(
        scenario_id,
        [{"depotId": depot["id"], "routeId": "R1", "allowed": True}],
    )
    scenario_store.set_deadhead_rules(
        scenario_id,
        [{"from_stop": "B", "to_stop": "C", "travel_time_min": 15}],
    )
    scenario_store.set_turnaround_rules(
        scenario_id,
        [{"stop_id": "B", "min_turnaround_min": 5}],
    )
    scenario_store.set_field(
        scenario_id,
        "timetable_rows",
        [
            {
                "trip_id": "T1",
                "route_id": "R1",
                "service_id": "WEEKDAY",
                "origin": "A",
                "destination": "B",
                "departure": "07:00",
                "arrival": "07:30",
                "distance_km": 10.0,
                "allowed_vehicle_types": ["BEV"],
            },
            {
                "trip_id": "T2",
                "route_id": "R1",
                "service_id": "WEEKDAY",
                "origin": "C",
                "destination": "D",
                "departure": "08:00",
                "arrival": "08:30",
                "distance_km": 9.0,
                "allowed_vehicle_types": ["BEV"],
            },
            {
                "trip_id": "T3",
                "route_id": "R1",
                "service_id": "WEEKDAY",
                "origin": "C",
                "destination": "E",
                "departure": "07:40",
                "arrival": "08:10",
                "distance_km": 8.0,
                "allowed_vehicle_types": ["BEV"],
            },
        ],
        invalidate_dispatch=True,
    )

    graph = _build_graph_payload(scenario_id, "WEEKDAY", depot["id"])

    assert graph["total_arcs"] == 6
    assert graph["feasible_arcs"] == 1
    assert graph["infeasible_arcs"] == 5
    assert graph["reason_counts"]["feasible"] == 1
    assert graph["reason_counts"]["insufficient_time"] >= 1

    arc = next(
        item
        for item in graph["arcs"]
        if item["from_trip_id"] == "T1" and item["to_trip_id"] == "T2"
    )
    assert arc["vehicle_type"] == "BEV"
    assert arc["turnaround_time_min"] == 5
    assert arc["deadhead_time_min"] == 15
    assert arc["slack_min"] == 10
    assert arc["reason_code"] == "feasible"
    assert arc["reason"].startswith("OK:")


def test_build_dispatch_context_applies_analysis_scope_route_and_trip_filters(
    temp_store_dir: Path,
):
    meta = scenario_store.create_scenario("Analysis scope dispatch", "", "thesis_mode")
    scenario_id = meta["id"]

    depot = scenario_store.create_depot(
        scenario_id,
        {"name": "Main depot", "location": "A"},
    )
    scenario_store.create_vehicle(
        scenario_id,
        {
            "depotId": depot["id"],
            "type": "BEV",
            "modelName": "EV-1",
            "batteryKwh": 300.0,
            "energyConsumption": 1.2,
        },
    )
    scenario_store.create_route(
        scenario_id,
        {
            "id": "R_MAIN",
            "name": "Main",
            "startStop": "A",
            "endStop": "B",
            "distanceKm": 10.0,
            "durationMin": 30,
            "color": "#111111",
            "enabled": True,
            "routeVariantType": "main",
        },
    )
    scenario_store.create_route(
        scenario_id,
        {
            "id": "R_SHORT",
            "name": "Short",
            "startStop": "B",
            "endStop": "C",
            "distanceKm": 4.0,
            "durationMin": 15,
            "color": "#222222",
            "enabled": True,
            "routeVariantType": "short_turn",
        },
    )
    scenario_store.create_route(
        scenario_id,
        {
            "id": "R_DEPOT",
            "name": "Depot",
            "startStop": "C",
            "endStop": "D",
            "distanceKm": 2.0,
            "durationMin": 10,
            "color": "#333333",
            "enabled": True,
            "routeVariantType": "depot_out",
        },
    )
    scenario_store.upsert_route_depot_assignment(
        scenario_id,
        "R_MAIN",
        {"depotId": depot["id"], "assignmentType": "manual_override", "confidence": 1.0},
    )
    scenario_store.upsert_route_depot_assignment(
        scenario_id,
        "R_SHORT",
        {"depotId": depot["id"], "assignmentType": "manual_override", "confidence": 1.0},
    )
    scenario_store.upsert_route_depot_assignment(
        scenario_id,
        "R_DEPOT",
        {"depotId": depot["id"], "assignmentType": "manual_override", "confidence": 1.0},
    )
    scenario_store.set_dispatch_scope(
        scenario_id,
        {
            "depotSelection": {"depotIds": [depot["id"]], "primaryDepotId": depot["id"]},
            "routeSelection": {
                "mode": "refine",
                "includeRouteIds": [],
                "excludeRouteIds": ["R_DEPOT"],
            },
            "serviceSelection": {"serviceIds": ["WEEKDAY"]},
            "tripSelection": {
                "includeShortTurn": False,
                "includeDepotMoves": False,
                "includeDeadhead": True,
            },
        },
    )
    scenario_store.set_field(
        scenario_id,
        "timetable_rows",
        [
            {
                "trip_id": "T_MAIN",
                "route_id": "R_MAIN",
                "service_id": "WEEKDAY",
                "origin": "A",
                "destination": "B",
                "departure": "07:00",
                "arrival": "07:30",
                "distance_km": 10.0,
                "allowed_vehicle_types": ["BEV"],
            },
            {
                "trip_id": "T_SHORT",
                "route_id": "R_SHORT",
                "service_id": "WEEKDAY",
                "origin": "B",
                "destination": "C",
                "departure": "07:40",
                "arrival": "07:55",
                "distance_km": 4.0,
                "allowed_vehicle_types": ["BEV"],
            },
            {
                "trip_id": "T_DEPOT",
                "route_id": "R_DEPOT",
                "service_id": "WEEKDAY",
                "origin": "C",
                "destination": "D",
                "departure": "08:10",
                "arrival": "08:20",
                "distance_km": 2.0,
                "allowed_vehicle_types": ["BEV"],
            },
        ],
        invalidate_dispatch=True,
    )

    context = _build_dispatch_context(scenario_id)

    assert [trip.trip_id for trip in context.trips] == ["T_MAIN"]


def test_build_blocks_payload_groups_feasible_chains(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Block payload", "", "thesis_mode")
    scenario_id = meta["id"]

    depot = scenario_store.create_depot(
        scenario_id,
        {"name": "Main depot", "location": "A"},
    )
    scenario_store.create_vehicle(
        scenario_id,
        {
            "depotId": depot["id"],
            "type": "BEV",
            "modelName": "EV-1",
            "batteryKwh": 300.0,
            "energyConsumption": 1.2,
        },
    )
    scenario_store.set_depot_route_permissions(
        scenario_id,
        [{"depotId": depot["id"], "routeId": "R1", "allowed": True}],
    )
    scenario_store.set_deadhead_rules(
        scenario_id,
        [{"from_stop": "B", "to_stop": "C", "travel_time_min": 10}],
    )
    scenario_store.set_turnaround_rules(
        scenario_id,
        [{"stop_id": "B", "min_turnaround_min": 5}],
    )
    scenario_store.set_field(
        scenario_id,
        "timetable_rows",
        [
            {
                "trip_id": "T1",
                "route_id": "R1",
                "service_id": "WEEKDAY",
                "origin": "A",
                "destination": "B",
                "departure": "07:00",
                "arrival": "07:30",
                "distance_km": 10.0,
                "allowed_vehicle_types": ["BEV"],
            },
            {
                "trip_id": "T2",
                "route_id": "R1",
                "service_id": "WEEKDAY",
                "origin": "C",
                "destination": "D",
                "departure": "07:50",
                "arrival": "08:20",
                "distance_km": 9.0,
                "allowed_vehicle_types": ["BEV"],
            },
        ],
        invalidate_dispatch=True,
    )

    blocks = _build_blocks_payload(scenario_id, "BEV", "greedy", "WEEKDAY", depot["id"])

    assert len(blocks) == 1
    assert blocks[0]["vehicle_type"] == "BEV"
    assert blocks[0]["trip_ids"] == ["T1", "T2"]


def test_build_dispatch_plan_payload_contains_blocks_and_duties(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Dispatch plan payload", "", "thesis_mode")
    scenario_id = meta["id"]

    depot = scenario_store.create_depot(
        scenario_id,
        {"name": "Main depot", "location": "A"},
    )
    scenario_store.create_vehicle(
        scenario_id,
        {
            "depotId": depot["id"],
            "type": "BEV",
            "modelName": "EV-1",
            "batteryKwh": 300.0,
            "energyConsumption": 1.2,
        },
    )
    scenario_store.set_depot_route_permissions(
        scenario_id,
        [{"depotId": depot["id"], "routeId": "R1", "allowed": True}],
    )
    scenario_store.set_field(
        scenario_id,
        "timetable_rows",
        [
            {
                "trip_id": "T1",
                "route_id": "R1",
                "service_id": "WEEKDAY",
                "origin": "A",
                "destination": "B",
                "departure": "07:00",
                "arrival": "07:30",
                "distance_km": 10.0,
                "allowed_vehicle_types": ["BEV"],
            }
        ],
        invalidate_dispatch=True,
    )

    payload = _build_dispatch_plan_payload(
        scenario_id,
        "BEV",
        "greedy",
        "WEEKDAY",
        depot["id"],
    )

    assert payload["total_plans"] == 1
    assert payload["total_blocks"] == 1
    assert payload["total_duties"] == 1
    assert payload["plans"][0]["blocks"][0]["trip_ids"] == ["T1"]
    assert payload["plans"][0]["duties"][0]["legs"][0]["trip"]["trip_id"] == "T1"
