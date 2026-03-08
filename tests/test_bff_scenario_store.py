from pathlib import Path

import pytest

from bff.store import scenario_store


@pytest.fixture()
def temp_store_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store_dir = tmp_path / "scenarios"
    monkeypatch.setattr(scenario_store, "_STORE_DIR", store_dir)
    return store_dir


def test_replace_routes_from_source_preserves_manual_routes_and_tracks_meta(
    temp_store_dir: Path,
):
    meta = scenario_store.create_scenario("ODPT test", "", "thesis_mode")
    scenario_id = meta["id"]

    manual_route = scenario_store.create_route(
        scenario_id,
        {
            "name": "Manual",
            "startStop": "A",
            "endStop": "B",
            "distanceKm": 1.0,
            "durationMin": 5,
            "color": "#111111",
            "enabled": True,
        },
    )

    scenario_store.set_depot_route_permissions(
        scenario_id,
        [
            {"depotId": "D1", "routeId": "odpt-old", "allowed": True},
            {"depotId": "D1", "routeId": manual_route["id"], "allowed": True},
        ],
    )
    scenario_store.set_vehicle_route_permissions(
        scenario_id,
        [
            {"vehicleId": "V1", "routeId": "odpt-old", "allowed": True},
            {"vehicleId": "V1", "routeId": manual_route["id"], "allowed": True},
        ],
    )
    scenario_store.replace_routes_from_source(
        scenario_id,
        "odpt",
        [{"id": "odpt-old", "name": "Old", "source": "odpt"}],
    )

    routes = scenario_store.replace_routes_from_source(
        scenario_id,
        "odpt",
        [{"id": "odpt-new", "name": "New", "source": "odpt"}],
        import_meta={"source": "odpt", "quality": {"routeCount": 1}},
    )

    route_ids = {route["id"] for route in routes}
    assert manual_route["id"] in route_ids
    assert "odpt-new" in route_ids
    assert "odpt-old" not in route_ids

    depot_permissions = scenario_store.get_depot_route_permissions(scenario_id)
    vehicle_permissions = scenario_store.get_vehicle_route_permissions(scenario_id)
    assert depot_permissions == [
        {"depotId": "D1", "routeId": manual_route["id"], "allowed": True}
    ]
    assert vehicle_permissions == [
        {"vehicleId": "V1", "routeId": manual_route["id"], "allowed": True}
    ]

    import_meta = scenario_store.get_route_import_meta(scenario_id, "odpt")
    assert import_meta == {"source": "odpt", "quality": {"routeCount": 1}}


def test_create_vehicle_batch_duplicate_and_template_flow(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Vehicle helpers", "", "thesis_mode")
    scenario_id = meta["id"]

    created = scenario_store.create_vehicle_batch(
        scenario_id,
        {
            "depotId": "D1",
            "type": "BEV",
            "modelName": "BYD K9",
            "capacityPassengers": 70,
            "batteryKwh": 300.0,
            "fuelTankL": None,
            "energyConsumption": 1.2,
            "chargePowerKw": 150.0,
            "minSoc": 0.2,
            "maxSoc": 0.9,
            "acquisitionCost": 30_000_000.0,
            "enabled": True,
        },
        quantity=3,
    )

    assert [item["modelName"] for item in created] == [
        "BYD K9 #1",
        "BYD K9 #2",
        "BYD K9 #3",
    ]

    scenario_store.set_vehicle_route_permissions(
        scenario_id,
        [{"vehicleId": created[0]["id"], "routeId": "R1", "allowed": True}],
    )
    duplicated = scenario_store.duplicate_vehicle(scenario_id, created[0]["id"])
    assert duplicated["modelName"] == "BYD K9 #1 (copy)"

    permissions = scenario_store.get_vehicle_route_permissions(scenario_id)
    assert permissions == [
        {"vehicleId": created[0]["id"], "routeId": "R1", "allowed": True},
        {"vehicleId": duplicated["id"], "routeId": "R1", "allowed": True},
    ]

    duplicated_many = scenario_store.duplicate_vehicle_batch(
        scenario_id,
        created[1]["id"],
        quantity=2,
    )
    assert [item["modelName"] for item in duplicated_many] == [
        "BYD K9 #2 (copy)",
        "BYD K9 #2 (copy 2)",
    ]

    scenario_store.delete_vehicle(scenario_id, created[0]["id"])
    assert scenario_store.get_vehicle_route_permissions(scenario_id) == [
        {"vehicleId": duplicated["id"], "routeId": "R1", "allowed": True}
    ]

    template = scenario_store.create_vehicle_template(
        scenario_id,
        {
            "name": "Standard EV 300kWh",
            "type": "BEV",
            "modelName": "BYD K9",
            "capacityPassengers": 70,
            "batteryKwh": 300.0,
            "fuelTankL": None,
            "energyConsumption": 1.2,
            "chargePowerKw": 150.0,
            "minSoc": 0.2,
            "maxSoc": 0.9,
            "acquisitionCost": 30_000_000.0,
            "enabled": True,
        },
    )
    assert scenario_store.get_vehicle_template(scenario_id, template["id"])["name"] == (
        "Standard EV 300kWh"
    )

    updated_template = scenario_store.update_vehicle_template(
        scenario_id,
        template["id"],
        {"name": "Standard EV 2026"},
    )
    assert updated_template["name"] == "Standard EV 2026"
    assert (
        scenario_store.list_vehicle_templates(scenario_id)[0]["name"]
        == "Standard EV 2026"
    )

    scenario_store.delete_vehicle_template(scenario_id, template["id"])
    assert scenario_store.list_vehicle_templates(scenario_id) == []


def test_duplicate_vehicle_batch_to_target_depot_filters_route_permissions(
    temp_store_dir: Path,
):
    meta = scenario_store.create_scenario("Cross depot duplicate", "", "thesis_mode")
    scenario_id = meta["id"]

    source_depot = scenario_store.create_depot(
        scenario_id,
        {"name": "Source depot", "location": "A"},
    )
    target_depot = scenario_store.create_depot(
        scenario_id,
        {"name": "Target depot", "location": "B"},
    )

    vehicle = scenario_store.create_vehicle(
        scenario_id,
        {
            "depotId": source_depot["id"],
            "type": "BEV",
            "modelName": "Cross Depot Bus",
            "capacityPassengers": 70,
            "batteryKwh": 300.0,
            "fuelTankL": None,
            "energyConsumption": 1.2,
            "chargePowerKw": 150.0,
            "minSoc": 0.2,
            "maxSoc": 0.9,
            "acquisitionCost": 30_000_000.0,
            "enabled": True,
        },
    )

    scenario_store.set_depot_route_permissions(
        scenario_id,
        [
            {"depotId": source_depot["id"], "routeId": "R1", "allowed": True},
            {"depotId": source_depot["id"], "routeId": "R2", "allowed": True},
            {"depotId": target_depot["id"], "routeId": "R1", "allowed": True},
            {"depotId": target_depot["id"], "routeId": "R2", "allowed": False},
        ],
    )
    scenario_store.set_vehicle_route_permissions(
        scenario_id,
        [
            {"vehicleId": vehicle["id"], "routeId": "R1", "allowed": True},
            {"vehicleId": vehicle["id"], "routeId": "R2", "allowed": True},
        ],
    )

    duplicated = scenario_store.duplicate_vehicle_batch(
        scenario_id,
        vehicle["id"],
        quantity=2,
        target_depot_id=target_depot["id"],
    )

    assert [item["modelName"] for item in duplicated] == [
        "Cross Depot Bus (copy)",
        "Cross Depot Bus (copy 2)",
    ]
    assert all(item["depotId"] == target_depot["id"] for item in duplicated)

    permissions = scenario_store.get_vehicle_route_permissions(scenario_id)
    duplicated_ids = {item["id"] for item in duplicated}
    duplicated_permissions = [
        permission
        for permission in permissions
        if permission["vehicleId"] in duplicated_ids
    ]
    assert duplicated_permissions == [
        {"vehicleId": duplicated[0]["id"], "routeId": "R1", "allowed": True},
        {"vehicleId": duplicated[1]["id"], "routeId": "R1", "allowed": True},
    ]


def test_create_scenario_seeds_v1_2_backend_fields(temp_store_dir: Path):
    meta = scenario_store.create_scenario("v1.2 defaults", "", "thesis_mode")

    doc = scenario_store._load(meta["id"])

    assert doc["deadhead_rules"] == []
    assert doc["turnaround_rules"] == []
    assert doc["charger_sites"] == []
    assert doc["chargers"] == []
    assert doc["pv_profiles"] == []
    assert doc["energy_price_profiles"] == []
    assert doc["experiment_case_type"] is None
    assert doc["problemdata_build_audit"] is None
    assert doc["optimization_audit"] is None
    assert doc["simulation_audit"] is None


def test_rule_updates_invalidate_dispatch_artifacts_and_roundtrip(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Rule roundtrip", "", "thesis_mode")
    scenario_id = meta["id"]

    scenario_store.set_field(
        scenario_id,
        "trips",
        [{"trip_id": "T1"}],
    )
    scenario_store.set_field(
        scenario_id,
        "graph",
        {"arcs": []},
    )
    scenario_store.set_field(
        scenario_id,
        "duties",
        [{"duty_id": "D1"}],
    )
    scenario_store.set_field(
        scenario_id,
        "problemdata_build_audit",
        {"ok": True},
    )
    scenario_store.set_field(
        scenario_id,
        "optimization_audit",
        {"ok": True},
    )
    scenario_store.set_field(
        scenario_id,
        "simulation_audit",
        {"ok": True},
    )

    deadhead = scenario_store.set_deadhead_rules(
        scenario_id,
        [
            {
                "from_stop": "A",
                "to_stop": "B",
                "travel_time_min": 12,
                "distance_km": 3.4,
                "energy_kwh_bev": 4.5,
                "fuel_l_ice": 0.8,
            }
        ],
    )
    turnaround = scenario_store.set_turnaround_rules(
        scenario_id,
        [{"stop_id": "B", "min_turnaround_min": 8}],
    )

    doc = scenario_store._load(scenario_id)

    assert deadhead == scenario_store.get_deadhead_rules(scenario_id)
    assert turnaround == scenario_store.get_turnaround_rules(scenario_id)
    assert doc["trips"] is None
    assert doc["graph"] is None
    assert doc["duties"] is None
    assert doc["problemdata_build_audit"] is None
    assert doc["optimization_audit"] is None
    assert doc["simulation_audit"] is None


def test_upsert_timetable_rows_from_source_preserves_manual_rows(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Timetable import", "", "thesis_mode")
    scenario_id = meta["id"]

    scenario_store.set_field(
        scenario_id,
        "timetable_rows",
        [
            {
                "route_id": "manual-route",
                "service_id": "WEEKDAY",
                "direction": "outbound",
                "trip_index": 0,
                "origin": "A",
                "destination": "B",
                "departure": "08:00",
                "arrival": "08:10",
                "distance_km": 1.0,
                "allowed_vehicle_types": ["BEV"],
            }
        ],
    )

    rows = scenario_store.upsert_timetable_rows_from_source(
        scenario_id,
        "odpt",
        [
            {
                "trip_id": "trip-1",
                "route_id": "odpt-route",
                "service_id": "WEEKDAY",
                "direction": "outbound",
                "trip_index": 0,
                "origin": "S",
                "destination": "T",
                "departure": "09:00",
                "arrival": "09:15",
                "distance_km": 2.0,
                "allowed_vehicle_types": ["BEV", "ICE"],
                "source": "odpt",
            }
        ],
        replace_existing_source=True,
    )

    assert len(rows) == 2
    assert any(row.get("route_id") == "manual-route" for row in rows)
    assert any(row.get("trip_id") == "trip-1" for row in rows)


def test_upsert_stop_timetables_from_source_tracks_meta(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Stop timetable import", "", "thesis_mode")
    scenario_id = meta["id"]

    items = scenario_store.upsert_stop_timetables_from_source(
        scenario_id,
        "odpt",
        [
            {
                "id": "stop-tt-1",
                "stopId": "S1",
                "stopName": "Stop 1",
                "service_id": "weekday",
                "items": [{"index": 1, "departure": "08:00"}],
            }
        ],
        replace_existing_source=True,
    )
    scenario_store.set_stop_timetable_import_meta(
        scenario_id,
        "odpt",
        {"source": "odpt", "quality": {"stopTimetableCount": 1}},
    )

    assert items[0]["source"] == "odpt"
    assert scenario_store.get_stop_timetable_import_meta(scenario_id, "odpt") == {
        "source": "odpt",
        "quality": {"stopTimetableCount": 1},
    }


def test_import_meta_helpers_preserve_progress_and_resource_type(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Import meta", "", "thesis_mode")
    scenario_id = meta["id"]

    timetable_meta = {
        "source": "odpt",
        "resourceType": "BusTimetable",
        "progress": {
            "cursor": 25,
            "nextCursor": 50,
            "totalChunks": 80,
            "complete": False,
        },
        "warnings": ["BusTimetable skipped 1 chunk(s)"],
        "quality": {"rowCount": 120},
    }
    stop_timetable_meta = {
        "source": "odpt",
        "resourceType": "BusstopPoleTimetable",
        "progress": {
            "cursor": 50,
            "nextCursor": 80,
            "totalChunks": 80,
            "complete": True,
        },
        "warnings": [],
        "quality": {"stopTimetableCount": 12},
    }

    scenario_store.set_timetable_import_meta(scenario_id, "odpt", timetable_meta)
    scenario_store.set_stop_timetable_import_meta(
        scenario_id, "odpt", stop_timetable_meta
    )

    assert (
        scenario_store.get_timetable_import_meta(scenario_id, "odpt") == timetable_meta
    )
    assert (
        scenario_store.get_stop_timetable_import_meta(scenario_id, "odpt")
        == stop_timetable_meta
    )


def test_route_depot_assignments_filter_routes_and_preserve_unresolved(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Route assignments", "", "thesis_mode")
    scenario_id = meta["id"]

    depot_a = scenario_store.create_depot(scenario_id, {"name": "Depot A", "location": "A"})
    depot_b = scenario_store.create_depot(scenario_id, {"name": "Depot B", "location": "B"})
    route_a = scenario_store.create_route(
        scenario_id,
        {
            "name": "Tokyu Assigned",
            "startStop": "S1",
            "endStop": "S2",
            "distanceKm": 1.0,
            "durationMin": 5,
            "color": "#111111",
            "enabled": True,
            "source": "odpt",
            "tripCount": 4,
            "stopSequence": ["S1", "S2"],
        },
    )
    route_b = scenario_store.create_route(
        scenario_id,
        {
            "name": "Toei Assigned",
            "startStop": "T1",
            "endStop": "T2",
            "distanceKm": 2.0,
            "durationMin": 8,
            "color": "#222222",
            "enabled": True,
            "source": "gtfs",
            "tripCount": 6,
            "stopSequence": ["T1", "T2", "T3"],
        },
    )
    route_unassigned = scenario_store.create_route(
        scenario_id,
        {
            "name": "Unassigned",
            "startStop": "U1",
            "endStop": "U2",
            "distanceKm": 3.0,
            "durationMin": 9,
            "color": "#333333",
            "enabled": True,
            "source": "odpt",
        },
    )

    scenario_store.upsert_route_depot_assignment(
        scenario_id,
        route_a["id"],
        {
          "depotId": depot_a["id"],
          "assignmentType": "manual_override",
          "confidence": 1.0,
          "reason": "Assigned in test",
        },
    )
    scenario_store.upsert_route_depot_assignment(
        scenario_id,
        route_b["id"],
        {
          "depotId": depot_b["id"],
          "assignmentType": "official",
          "confidence": 0.9,
          "reason": "Official feed",
        },
    )

    tokyo_routes = scenario_store.list_routes(
        scenario_id,
        depot_id=depot_a["id"],
        operator="tokyu",
    )
    assert [route["id"] for route in tokyo_routes] == [route_a["id"]]
    assert tokyo_routes[0]["depotId"] == depot_a["id"]

    unresolved = scenario_store.list_route_depot_assignments(
        scenario_id,
        operator="tokyu",
        unresolved_only=True,
    )
    assert [item["routeId"] for item in unresolved] == [route_unassigned["id"]]
    assert unresolved[0]["depotId"] is None
