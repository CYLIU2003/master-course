import json
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


def test_scenario_save_uses_refs_and_split_artifacts(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Split scenario", "", "thesis_mode")
    scenario_id = meta["id"]

    scenario_store.set_field(
        scenario_id,
        "timetable_rows",
        [
            {
                "trip_id": "T1",
                "route_id": "R1",
                "service_id": "WEEKDAY",
                "source": "manual",
            }
        ],
    )

    saved_doc = json.loads(
        (temp_store_dir / f"{scenario_id}.json").read_text(encoding="utf-8")
    )
    assert "refs" in saved_doc
    assert "stats" in saved_doc
    assert "timetable_rows" not in saved_doc
    assert Path(saved_doc["refs"]["masterData"]).exists()
    assert Path(saved_doc["refs"]["artifactStore"]).exists()
    assert not Path(saved_doc["refs"]["timetableRows"]).exists()


def test_trip_and_duty_artifacts_write_parquet(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Parquet scenario", "", "thesis_mode")
    scenario_id = meta["id"]

    scenario_store.set_field(
        scenario_id,
        "trips",
        [{"trip_id": "T1", "route_id": "R1"}, {"trip_id": "T2", "route_id": "R2"}],
    )
    scenario_store.set_field(scenario_id, "duties", [{"duty_id": "D1", "legs": []}])

    saved_doc = json.loads(
        (temp_store_dir / f"{scenario_id}.json").read_text(encoding="utf-8")
    )
    assert Path(saved_doc["refs"]["tripSet"]).exists()
    assert Path(saved_doc["refs"]["duties"]).exists()
    assert scenario_store.count_field_rows(scenario_id, "trips") == 2
    assert (
        len(scenario_store.page_field_rows(scenario_id, "duties", limit=10, offset=0))
        == 1
    )


def test_graph_artifact_is_split_into_meta_and_arcs(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Graph split", "", "thesis_mode")
    scenario_id = meta["id"]

    scenario_store.set_field(
        scenario_id,
        "graph",
        {
            "trips": [{"trip_id": "T1"}],
            "arcs": [
                {"from_trip_id": "T1", "to_trip_id": "T2", "reason_code": "feasible"},
                {"from_trip_id": "T2", "to_trip_id": "T3", "reason_code": "turnaround"},
            ],
            "total_arcs": 2,
            "feasible_arcs": 1,
            "infeasible_arcs": 1,
            "reason_counts": {"feasible": 1, "turnaround": 1},
        },
    )

    graph_meta = scenario_store.get_graph_meta(scenario_id)
    graph_arcs = scenario_store.page_graph_arcs(scenario_id, limit=1, offset=0)

    assert graph_meta is not None
    assert "arcs" not in graph_meta
    assert graph_meta["total_arcs"] == 2
    assert len(graph_arcs) == 1
    assert scenario_store.count_graph_arcs(scenario_id) == 2
    assert scenario_store.count_graph_arcs(scenario_id, reason_code="feasible") == 1


def test_timetable_rows_use_sqlite_paging_and_summary(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Timetable split", "", "thesis_mode")
    scenario_id = meta["id"]

    rows = [
        {
            "trip_id": "T1",
            "route_id": "R1",
            "service_id": "WEEKDAY",
            "departure": "06:00",
            "arrival": "06:20",
            "distance_km": 5.0,
        },
        {
            "trip_id": "T2",
            "route_id": "R1",
            "service_id": "WEEKDAY",
            "departure": "07:00",
            "arrival": "07:20",
            "distance_km": 5.0,
        },
        {
            "trip_id": "T3",
            "route_id": "R2",
            "service_id": "SAT",
            "departure": "08:00",
            "arrival": "08:35",
            "distance_km": 8.0,
        },
    ]
    scenario_store.set_field(scenario_id, "timetable_rows", rows)

    weekday_rows = scenario_store.page_timetable_rows(
        scenario_id, service_id="WEEKDAY", limit=10, offset=0
    )
    summary = scenario_store.get_field_summary(scenario_id, "timetable_rows")

    assert len(weekday_rows) == 2
    assert scenario_store.count_timetable_rows(scenario_id, service_id="SAT") == 1
    assert summary is not None
    assert summary["totalRows"] == 3
    assert len(summary["byService"]) == 2


def test_artifacts_sqlite_roundtrip_for_simulation_and_optimization_results(
    temp_store_dir: Path,
):
    meta = scenario_store.create_scenario("Artifact roundtrip", "", "thesis_mode")
    scenario_id = meta["id"]

    simulation_result = {
        "scenario_id": scenario_id,
        "total_energy_kwh": 120.5,
        "total_distance_km": 87.2,
        "feasibility_violations": [],
        "audit": {
            "dataset_fingerprint": "tokyu:2026-03-15",
            "input_counts": {"tasks": 12},
        },
    }
    optimization_result = {
        "scenario_id": scenario_id,
        "solver_status": "OPTIMAL",
        "objective_value": 12345.6,
        "cost_breakdown": {"total_cost": 12345.6},
        "audit": {
            "dataset_fingerprint": "tokyu:2026-03-15",
            "input_counts": {"trips": 12},
        },
    }

    scenario_store.set_field(scenario_id, "simulation_result", simulation_result)
    scenario_store.set_field(scenario_id, "optimization_result", optimization_result)

    loaded_simulation = scenario_store.get_field(scenario_id, "simulation_result")
    loaded_optimization = scenario_store.get_field(scenario_id, "optimization_result")

    assert loaded_simulation["total_energy_kwh"] == 120.5
    assert loaded_simulation["audit"]["dataset_fingerprint"] == "tokyu:2026-03-15"
    assert loaded_optimization["objective_value"] == 12345.6
    assert loaded_optimization["audit"]["input_counts"]["trips"] == 12


def test_scenario_save_writes_complete_marker(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Complete marker", "", "thesis_mode")
    scenario_id = meta["id"]

    scenario_store.set_field(
        scenario_id, "timetable_rows", [{"trip_id": "T1", "service_id": "WEEKDAY"}]
    )

    artifact_dir = temp_store_dir / scenario_id
    assert (artifact_dir / "_COMPLETE").exists()
    assert not (artifact_dir / "_INCOMPLETE").exists()


def test_replace_routes_from_source_prunes_stale_permissions(
    temp_store_dir: Path,
):
    meta = scenario_store.create_scenario("ODPT route sync", "", "thesis_mode")
    scenario_id = meta["id"]

    depot = scenario_store.create_depot(
        scenario_id,
        {"name": "Depot A", "location": "A"},
    )
    vehicle = scenario_store.create_vehicle(
        scenario_id,
        {
            "depotId": depot["id"],
            "type": "BEV",
            "modelName": "K8",
            "capacityPassengers": 70,
            "batteryKwh": 300.0,
            "fuelTankL": None,
            "energyConsumption": 1.2,
            "chargePowerKw": 60.0,
            "minSoc": 0.2,
            "maxSoc": 0.95,
            "acquisitionCost": 0.0,
            "enabled": True,
        },
    )

    scenario_store.replace_routes_from_source(
        scenario_id, "odpt", [{"id": "r-old", "name": "Old", "source": "odpt"}]
    )
    scenario_store.set_depot_route_permissions(
        scenario_id,
        [{"depotId": depot["id"], "routeId": "r-old", "allowed": True}],
    )
    scenario_store.set_vehicle_route_permissions(
        scenario_id,
        [{"vehicleId": vehicle["id"], "routeId": "r-old", "allowed": True}],
    )

    scenario_store.replace_routes_from_source(
        scenario_id,
        "odpt",
        [{"id": "r-new", "name": "New", "source": "odpt"}],
    )

    assert scenario_store.get_depot_route_permissions(scenario_id) == []
    assert scenario_store.get_vehicle_route_permissions(scenario_id) == []


def test_upsert_route_depot_assignment_accepts_external_alias_ids(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Route alias", "", "thesis_mode")
    scenario_id = meta["id"]

    depot = scenario_store.create_depot(
        scenario_id,
        {"name": "Depot A", "location": "A"},
    )
    scenario_store.replace_routes_from_source(
        scenario_id,
        "seed",
        [
            {
                "id": "seed-route-123",
                "name": "A24 outbound",
                "source": "seed",
                "patternId": "route-pattern:A24.out",
                "routeExternalId": "route:A24",
            }
        ],
    )

    item = scenario_store.upsert_route_depot_assignment(
        scenario_id,
        "route-pattern:A24.out",
        {
            "depotId": depot["id"],
            "assignmentType": "manual_override",
            "confidence": 1.0,
        },
    )

    assert item["routeId"] == "seed-route-123"
    assert item["depotId"] == depot["id"]


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
    assert doc["feed_context"] is None
    assert meta["feedContext"] is None
    assert meta["operatorId"] == "tokyu"
    assert doc["dispatch_scope"]["operatorId"] == "tokyu"


def test_create_scenario_can_fix_operator_and_activation_updates_app_context(
    temp_store_dir: Path,
):
    meta = scenario_store.create_scenario(
        "Toei scenario",
        "",
        "thesis_mode",
        operator_id="toei",
    )

    assert meta["operatorId"] == "toei"

    context = scenario_store.set_active_scenario(meta["id"])

    assert context["activeScenarioId"] == meta["id"]
    assert context["selectedOperatorId"] == "toei"


def test_feed_context_roundtrip_is_exposed_in_scenario_meta(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Feed context", "", "thesis_mode")
    scenario_id = meta["id"]

    scenario_store.set_feed_context(
        scenario_id,
        {
            "feed_id": "tokyu_odpt_gtfs",
            "snapshot_id": "2026-03-09T180500Z",
            "dataset_id": "tokyu_odpt_gtfs:2026-03-09T180500Z",
            "source": "gtfs_runtime",
        },
    )

    reloaded = scenario_store.get_scenario(scenario_id)
    listed = scenario_store.list_scenarios()

    assert reloaded["feedContext"] == {
        "feedId": "tokyu_odpt_gtfs",
        "snapshotId": "2026-03-09T180500Z",
        "datasetId": "tokyu_odpt_gtfs:2026-03-09T180500Z",
        "datasetFingerprint": None,
        "manualRouteFamilyMapHash": None,
        "source": "gtfs_runtime",
    }
    assert listed[0]["feedContext"]["feedId"] == "tokyu_odpt_gtfs"


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


def test_route_depot_assignments_filter_routes_and_preserve_unresolved(
    temp_store_dir: Path,
):
    meta = scenario_store.create_scenario("Route assignments", "", "thesis_mode")
    scenario_id = meta["id"]

    depot_a = scenario_store.create_depot(
        scenario_id, {"name": "Depot A", "location": "A"}
    )
    depot_b = scenario_store.create_depot(
        scenario_id, {"name": "Depot B", "location": "B"}
    )
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
            "source": "seed",
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
            "source": "external",
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
            "source": "seed",
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


def test_dispatch_scope_supports_depot_route_and_trip_filters(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Analysis scope", "", "thesis_mode")
    scenario_id = meta["id"]

    depot_a = scenario_store.create_depot(
        scenario_id, {"name": "Depot A", "location": "A"}
    )
    depot_b = scenario_store.create_depot(
        scenario_id, {"name": "Depot B", "location": "B"}
    )
    route_main = scenario_store.create_route(
        scenario_id,
        {
            "id": "R_MAIN",
            "name": "Main",
            "startStop": "S1",
            "endStop": "S2",
            "distanceKm": 1.0,
            "durationMin": 5,
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
            "startStop": "S1",
            "endStop": "S3",
            "distanceKm": 1.0,
            "durationMin": 5,
            "color": "#222222",
            "enabled": True,
            "routeVariantType": "short_turn",
        },
    )
    scenario_store.create_route(
        scenario_id,
        {
            "id": "R_REMOTE",
            "name": "Remote",
            "startStop": "X1",
            "endStop": "X2",
            "distanceKm": 1.0,
            "durationMin": 5,
            "color": "#333333",
            "enabled": True,
            "routeVariantType": "main",
        },
    )

    scenario_store.upsert_route_depot_assignment(
        scenario_id,
        "R_MAIN",
        {
            "depotId": depot_a["id"],
            "assignmentType": "manual_override",
            "confidence": 1.0,
        },
    )
    scenario_store.upsert_route_depot_assignment(
        scenario_id,
        "R_SHORT",
        {
            "depotId": depot_a["id"],
            "assignmentType": "manual_override",
            "confidence": 1.0,
        },
    )
    scenario_store.upsert_route_depot_assignment(
        scenario_id,
        "R_REMOTE",
        {
            "depotId": depot_b["id"],
            "assignmentType": "manual_override",
            "confidence": 1.0,
        },
    )

    scope = scenario_store.set_dispatch_scope(
        scenario_id,
        {
            "scopeId": "tokyu-a-weekday",
            "depotSelection": {
                "depotIds": [depot_a["id"], depot_b["id"]],
                "primaryDepotId": depot_a["id"],
            },
            "routeSelection": {
                "mode": "refine",
                "includeRouteIds": [],
                "excludeRouteIds": ["R_REMOTE"],
            },
            "serviceSelection": {"serviceIds": ["WEEKDAY"]},
            "tripSelection": {
                "includeShortTurn": False,
                "includeDepotMoves": True,
                "includeDeadhead": True,
            },
        },
    )

    assert scope["depotId"] == depot_a["id"]
    assert scope["serviceId"] == "WEEKDAY"
    assert scope["candidateRouteIds"] == ["R_MAIN", "R_SHORT", "R_REMOTE"]
    assert scope["effectiveRouteIds"] == ["R_MAIN", "R_SHORT"]
    assert scope["tripSelection"]["includeShortTurn"] is False
