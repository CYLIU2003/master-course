from pathlib import Path

import pytest

from bff.routers import master_data
from bff.services.route_family import derive_route_family_metadata, enrich_routes_with_family
from bff.store import scenario_store


@pytest.fixture()
def temp_store_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store_dir = tmp_path / "scenarios"
    monkeypatch.setattr(scenario_store, "_STORE_DIR", store_dir)
    return store_dir


def test_route_family_keeps_main_pair_when_terminal_is_depot_like():
    routes = [
        {
            "id": "r-out",
            "name": "園01 (田園調布駅 -> 瀬田営業所)",
            "routeCode": "園０１",
            "startStop": "田園調布駅",
            "endStop": "瀬田営業所",
            "stopSequence": ["田園調布駅", "中間", "瀬田営業所"],
            "distanceKm": 12.0,
            "tripCount": 32,
        },
        {
            "id": "r-in",
            "name": "園01 (瀬田営業所 -> 田園調布駅)",
            "routeCode": "園01",
            "startStop": "瀬田営業所",
            "endStop": "田園調布駅",
            "stopSequence": ["瀬田営業所", "中間", "田園調布駅"],
            "distanceKm": 12.0,
            "tripCount": 31,
        },
        {
            "id": "r-depot",
            "name": "園01 入庫",
            "routeCode": "園01",
            "startStop": "中間",
            "endStop": "瀬田営業所",
            "stopSequence": ["中間", "別経路", "瀬田営業所"],
            "distanceKm": 4.0,
            "tripCount": 2,
        },
    ]

    metadata = derive_route_family_metadata(routes)

    assert metadata["r-out"].route_variant_type == "main_outbound"
    assert metadata["r-in"].route_variant_type == "main_inbound"
    assert metadata["r-out"].classification_confidence == pytest.approx(0.95)
    assert metadata["r-depot"].route_variant_type == "depot_in"
    assert metadata["r-depot"].classification_confidence >= 0.6
    assert "end contains depot-like keyword" in metadata["r-depot"].classification_reasons


def test_route_family_does_not_classify_keyword_only_route_as_depot():
    routes = [
        {
            "id": "r-main-out",
            "name": "園01 本線",
            "routeCode": "園01",
            "startStop": "A駅",
            "endStop": "B駅",
            "stopSequence": ["A駅", "中間", "B駅"],
            "distanceKm": 10.0,
            "tripCount": 20,
        },
        {
            "id": "r-main-in",
            "name": "園01 本線 逆",
            "routeCode": "園01",
            "startStop": "B駅",
            "endStop": "A駅",
            "stopSequence": ["B駅", "中間", "A駅"],
            "distanceKm": 10.0,
            "tripCount": 18,
        },
        {
            "id": "r-weak",
            "name": "園01 営業所",
            "routeCode": "園01",
            "startStop": "A駅",
            "endStop": "B営業所",
            "stopSequence": ["A駅", "別中間", "B営業所"],
            "distanceKm": 9.5,
            "tripCount": 12,
        },
    ]

    metadata = derive_route_family_metadata(routes)
    weak = metadata["r-weak"]

    assert weak.route_variant_type == "unknown"
    assert weak.classification_confidence == pytest.approx(0.1)
    assert "end contains depot-like keyword" in weak.classification_reasons
    assert any("below threshold" in reason for reason in weak.classification_reasons)


def test_route_family_router_enriches_routes_and_returns_family_detail(
    temp_store_dir: Path,
):
    meta = scenario_store.create_scenario("Route family", "", "thesis_mode")
    scenario_id = meta["id"]

    scenario_store.replace_routes_from_source(
        scenario_id,
        "odpt",
        [
            {
                "id": "r-out",
                "name": "園０１ (田園調布駅 -> 瀬田営業所)",
                "routeCode": "園０１",
                "routeLabel": "園０１ (田園調布駅 -> 瀬田営業所)",
                "startStop": "田園調布駅",
                "endStop": "瀬田営業所",
                "stopSequence": ["S1", "S2", "S3"],
                "tripCount": 10,
                "color": "#0f766e",
                "source": "odpt",
            },
            {
                "id": "r-in",
                "name": "園０１ (瀬田営業所 -> 田園調布駅)",
                "routeCode": "園０１",
                "routeLabel": "園０１ (瀬田営業所 -> 田園調布駅)",
                "startStop": "瀬田営業所",
                "endStop": "田園調布駅",
                "stopSequence": ["S3", "S2", "S1"],
                "tripCount": 9,
                "color": "#0f766e",
                "source": "odpt",
            },
        ],
    )

    routes_body = master_data.list_routes(
        scenario_id,
        depot_id=None,
        operator=None,
        group_by_family=True,
    )
    assert routes_body["total"] == 2
    assert all(item["routeFamilyCode"] == "園01" for item in routes_body["items"])
    assert [item["routeVariantType"] for item in routes_body["items"]] == [
        "main_outbound",
        "main_inbound",
    ]

    families_body = master_data.list_route_families(scenario_id, operator=None)
    assert families_body["total"] == 1
    family = families_body["items"][0]
    assert family["routeFamilyCode"] == "園01"
    assert family["variantCount"] == 2
    assert family["mainVariantCount"] == 2

    detail_body = master_data.get_route_family(scenario_id, family["routeFamilyId"])
    detail = detail_body["item"]
    assert detail["canonicalMainPair"]["outboundRouteId"] == "r-out"
    assert detail["canonicalMainPair"]["inboundRouteId"] == "r-in"
    assert detail["timetableDiagnostics"]["rawRouteCount"] == 2


def test_route_list_summary_keeps_required_lightweight_fields(
    temp_store_dir: Path,
):
    meta = scenario_store.create_scenario("Route list summary", "", "thesis_mode")
    scenario_id = meta["id"]

    scenario_store.set_field(
        scenario_id,
        "timetable_rows",
        [
            {
                "trip_id": "trip-1",
                "route_id": "route-1",
                "service_id": "WEEKDAY",
                "origin": "A",
                "destination": "B",
                "departure": "08:00",
                "arrival": "08:20",
                "distance_km": 8.0,
                "allowed_vehicle_types": ["BEV"],
            },
            {
                "trip_id": "trip-2",
                "route_id": "route-1",
                "service_id": "SAT",
                "origin": "A",
                "destination": "B",
                "departure": "09:00",
                "arrival": "09:20",
                "distance_km": 8.0,
                "allowed_vehicle_types": ["BEV"],
            },
        ],
        invalidate_dispatch=True,
    )
    scenario_store.replace_routes_from_source(
        scenario_id,
        "odpt",
        [
            {
                "id": "route-1",
                "name": "園01 (A -> B)",
                "routeCode": "園01",
                "routeLabel": "園01 (A -> B)",
                "startStop": "A",
                "endStop": "B",
                "stopSequence": ["S1", "S2", "S3"],
                "source": "odpt",
                "tripCount": 2,
            }
        ],
    )

    routes_body = master_data.list_routes(
        scenario_id,
        depot_id=None,
        operator=None,
        group_by_family=True,
    )

    assert routes_body["total"] == 1
    item = routes_body["items"][0]
    assert item["id"] == "route-1"
    assert item["tripCount"] == 2
    assert item["serviceTypes"] == ["SAT", "WEEKDAY"]
    assert item["routeFamilyCode"] == "園01"
    assert "stopSequence" not in item
    assert "resolvedStops" not in item


def test_route_family_manual_override_takes_precedence():
    routes = [
        {
            "id": "r-1",
            "name": "園01 本線",
            "routeCode": "園01",
            "startStop": "A",
            "endStop": "B",
            "stopSequence": ["A", "X", "B"],
            "tripCount": 8,
            "routeVariantTypeManual": "branch",
        },
        {
            "id": "r-2",
            "name": "園01 逆",
            "routeCode": "園01",
            "startStop": "B",
            "endStop": "A",
            "stopSequence": ["B", "X", "A"],
            "tripCount": 7,
        },
    ]

    enriched = enrich_routes_with_family(routes)
    overridden = next(item for item in enriched if item["id"] == "r-1")

    assert overridden["routeVariantType"] == "branch"
    assert overridden["classificationSource"] == "manual_override"
    assert overridden["classificationConfidence"] == pytest.approx(1.0)
    assert overridden["classificationReasons"] == ["manual override: branch"]


def test_route_detail_reports_timetable_and_stop_timetable_links(
    temp_store_dir: Path,
):
    meta = scenario_store.create_scenario("Route links", "", "thesis_mode")
    scenario_id = meta["id"]

    scenario_store.set_field(
        scenario_id,
        "stops",
        [
            {"id": "S1", "name": "Start", "lat": 35.0, "lon": 139.0},
            {"id": "S2", "name": "End", "lat": 35.1, "lon": 139.1},
        ],
    )
    scenario_store.replace_routes_from_source(
        scenario_id,
        "odpt",
        [
            {
                "id": "route-1",
                "name": "園01",
                "routeCode": "園01",
                "odptPatternId": "pattern-1",
                "startStop": "Start",
                "endStop": "End",
                "stopSequence": ["S1", "S2"],
                "source": "odpt",
            }
        ],
    )
    scenario_store.set_field(
        scenario_id,
        "timetable_rows",
        [
            {
                "trip_id": "trip-1",
                "route_id": "route-1",
                "service_id": "WEEKDAY",
                "origin": "Start",
                "destination": "End",
                "departure": "08:00",
                "arrival": "08:30",
                "distance_km": 10.0,
                "allowed_vehicle_types": ["BEV"],
                "source": "odpt",
            }
        ],
        invalidate_dispatch=True,
    )
    scenario_store.set_field(
        scenario_id,
        "stop_timetables",
        [
            {
                "id": "st-1",
                "stopId": "S1",
                "service_id": "WEEKDAY",
                "items": [
                    {
                        "index": 0,
                        "departure": "08:00",
                        "busroutePattern": "pattern-1",
                        "busTimetable": "trip-1",
                    }
                ],
                "source": "odpt",
            }
        ],
        invalidate_dispatch=True,
    )

    route = master_data.get_route(scenario_id, "route-1")

    assert route["linkState"] == "linked"
    assert route["linkStatus"]["stopsResolved"] == 2
    assert route["linkStatus"]["tripsLinked"] == 1
    assert route["linkStatus"]["stopTimetableEntriesLinked"] == 1
    assert route["serviceSummary"] == [
        {
            "serviceId": "WEEKDAY",
            "tripCount": 1,
            "firstDeparture": "08:00",
            "lastDeparture": "08:00",
        }
    ]


def test_explorer_depot_assignments_are_grouped_by_route_family(
    temp_store_dir: Path,
):
    meta = scenario_store.create_scenario("Explorer family sort", "", "thesis_mode")
    scenario_id = meta["id"]

    scenario_store.replace_routes_from_source(
        scenario_id,
        "odpt",
        [
            {
                "id": "b-out",
                "name": "B02 (A -> B)",
                "routeCode": "B02",
                "routeLabel": "B02 (A -> B)",
                "startStop": "A",
                "endStop": "B",
                "stopSequence": ["S1", "S2"],
                "tripCount": 5,
                "source": "odpt",
            },
            {
                "id": "a-out",
                "name": "A01 (X -> Y)",
                "routeCode": "A01",
                "routeLabel": "A01 (X -> Y)",
                "startStop": "X",
                "endStop": "Y",
                "stopSequence": ["S3", "S4"],
                "tripCount": 6,
                "source": "odpt",
            },
            {
                "id": "a-in",
                "name": "A01 (Y -> X)",
                "routeCode": "A01",
                "routeLabel": "A01 (Y -> X)",
                "startStop": "Y",
                "endStop": "X",
                "stopSequence": ["S4", "S3"],
                "tripCount": 4,
                "source": "odpt",
            },
        ],
    )

    body = master_data.list_explorer_depot_assignments(
        scenario_id,
        operator=None,
        unresolved_only=False,
    )

    assert [item["routeId"] for item in body["items"]] == ["a-out", "a-in", "b-out"]
    assert [item["routeFamilyCode"] for item in body["items"]] == ["A01", "A01", "B02"]
    assert [item["routeVariantType"] for item in body["items"]] == [
        "main_outbound",
        "main_inbound",
        "main",
    ]


def test_depot_route_family_permissions_aggregate_and_expand(
    temp_store_dir: Path,
):
    meta = scenario_store.create_scenario("Depot family permissions", "", "thesis_mode")
    scenario_id = meta["id"]

    depot = scenario_store.create_depot(
        scenario_id,
        {"name": "Meguro Depot", "location": "Meguro"},
    )
    other_depot = scenario_store.create_depot(
        scenario_id,
        {"name": "Seta Depot", "location": "Seta"},
    )

    scenario_store.replace_routes_from_source(
        scenario_id,
        "odpt",
        [
            {
                "id": "a-out",
                "name": "A01 (X -> Y)",
                "routeCode": "A01",
                "routeLabel": "A01 (X -> Y)",
                "startStop": "X",
                "endStop": "Y",
                "stopSequence": ["S1", "S2"],
                "tripCount": 6,
                "source": "odpt",
            },
            {
                "id": "a-in",
                "name": "A01 (Y -> X)",
                "routeCode": "A01",
                "routeLabel": "A01 (Y -> X)",
                "startStop": "Y",
                "endStop": "X",
                "stopSequence": ["S2", "S1"],
                "tripCount": 5,
                "source": "odpt",
            },
            {
                "id": "b-main",
                "name": "B02 (P -> Q)",
                "routeCode": "B02",
                "routeLabel": "B02 (P -> Q)",
                "startStop": "P",
                "endStop": "Q",
                "stopSequence": ["S3", "S4"],
                "tripCount": 4,
                "source": "odpt",
            },
        ],
    )
    scenario_store.set_depot_route_permissions(
        scenario_id,
        [
            {"depotId": depot["id"], "routeId": "a-out", "allowed": True},
            {"depotId": depot["id"], "routeId": "a-in", "allowed": False},
            {"depotId": depot["id"], "routeId": "b-main", "allowed": True},
            {"depotId": other_depot["id"], "routeId": "a-out", "allowed": True},
        ],
    )

    body = master_data.get_depot_route_family_permissions(scenario_id)
    items = {
        (item["depotId"], item["routeFamilyCode"]): item
        for item in body["items"]
    }

    partial = items[(depot["id"], "A01")]
    assert partial["totalRouteCount"] == 2
    assert partial["allowedRouteCount"] == 1
    assert partial["allowed"] is False
    assert partial["partiallyAllowed"] is True

    full = items[(depot["id"], "B02")]
    assert full["allowed"] is True
    assert full["partiallyAllowed"] is False

    updated = master_data.update_depot_route_family_permissions(
        scenario_id,
        master_data.UpdateDepotRouteFamilyPermissionsBody(
            permissions=[
                master_data.DepotRouteFamilyPermissionItem(
                    depotId=depot["id"],
                    routeFamilyId=partial["routeFamilyId"],
                    allowed=True,
                )
            ]
        ),
    )
    updated_items = {
        (item["depotId"], item["routeFamilyCode"]): item
        for item in updated["items"]
    }
    assert updated_items[(depot["id"], "A01")]["allowed"] is True
    assert updated_items[(depot["id"], "A01")]["allowedRouteCount"] == 2

    raw_permissions = sorted(
        scenario_store.get_depot_route_permissions(scenario_id),
        key=lambda item: (item["depotId"], item["routeId"]),
    )
    expected_permissions = sorted(
        [
            {"depotId": depot["id"], "routeId": "a-in", "allowed": True},
            {"depotId": depot["id"], "routeId": "a-out", "allowed": True},
            {"depotId": depot["id"], "routeId": "b-main", "allowed": True},
            {"depotId": other_depot["id"], "routeId": "a-out", "allowed": True},
        ],
        key=lambda item: (item["depotId"], item["routeId"]),
    )
    assert raw_permissions == expected_permissions


def test_depot_scoped_route_family_permissions_returns_single_depot(
    temp_store_dir: Path,
):
    meta = scenario_store.create_scenario("Depot scoped family permissions", "", "thesis_mode")
    scenario_id = meta["id"]

    depot = scenario_store.create_depot(
        scenario_id,
        {"name": "Meguro Depot", "location": "Meguro"},
    )
    other_depot = scenario_store.create_depot(
        scenario_id,
        {"name": "Seta Depot", "location": "Seta"},
    )

    scenario_store.replace_routes_from_source(
        scenario_id,
        "odpt",
        [
            {
                "id": "a-out",
                "name": "A01 (X -> Y)",
                "routeCode": "A01",
                "routeLabel": "A01 (X -> Y)",
                "startStop": "X",
                "endStop": "Y",
                "stopSequence": ["S1", "S2"],
                "tripCount": 6,
                "source": "odpt",
            },
            {
                "id": "a-in",
                "name": "A01 (Y -> X)",
                "routeCode": "A01",
                "routeLabel": "A01 (Y -> X)",
                "startStop": "Y",
                "endStop": "X",
                "stopSequence": ["S2", "S1"],
                "tripCount": 5,
                "source": "odpt",
            },
        ],
    )
    scenario_store.set_depot_route_permissions(
        scenario_id,
        [
            {"depotId": depot["id"], "routeId": "a-out", "allowed": True},
            {"depotId": other_depot["id"], "routeId": "a-out", "allowed": False},
        ],
    )

    scoped = master_data.get_depot_scoped_route_family_permissions(scenario_id, depot["id"])

    assert scoped["total"] > 0
    assert all(item["depotId"] == depot["id"] for item in scoped["items"])


def test_list_route_families_supports_depot_filter(temp_store_dir: Path):
    meta = scenario_store.create_scenario("Route family depot filter", "", "thesis_mode")
    scenario_id = meta["id"]

    depot_a = scenario_store.create_depot(
        scenario_id,
        {"name": "Depot A", "location": "A"},
    )
    depot_b = scenario_store.create_depot(
        scenario_id,
        {"name": "Depot B", "location": "B"},
    )

    scenario_store.replace_routes_from_source(
        scenario_id,
        "odpt",
        [
            {
                "id": "a-1",
                "name": "A01 (X -> Y)",
                "routeCode": "A01",
                "routeLabel": "A01 (X -> Y)",
                "startStop": "X",
                "endStop": "Y",
                "stopSequence": ["S1", "S2"],
                "tripCount": 4,
                "source": "odpt",
                "depotId": depot_a["id"],
            },
            {
                "id": "b-1",
                "name": "B02 (P -> Q)",
                "routeCode": "B02",
                "routeLabel": "B02 (P -> Q)",
                "startStop": "P",
                "endStop": "Q",
                "stopSequence": ["S3", "S4"],
                "tripCount": 3,
                "source": "odpt",
                "depotId": depot_b["id"],
            },
        ],
    )

    filtered = master_data.list_route_families(
        scenario_id,
        operator=None,
        depotId=depot_a["id"],
    )

    assert filtered["total"] == 1
    assert filtered["items"][0]["routeFamilyCode"] == "A01"


def test_depot_scoped_vehicle_route_family_permissions_returns_only_depot_vehicles(
    temp_store_dir: Path,
):
    meta = scenario_store.create_scenario("Depot scoped vehicle family permissions", "", "thesis_mode")
    scenario_id = meta["id"]

    depot_a = scenario_store.create_depot(
        scenario_id,
        {"name": "Depot A", "location": "A"},
    )
    depot_b = scenario_store.create_depot(
        scenario_id,
        {"name": "Depot B", "location": "B"},
    )

    vehicle_a = scenario_store.create_vehicle(
        scenario_id,
        {
            "depotId": depot_a["id"],
            "type": "BEV",
            "modelName": "A-vehicle",
            "capacityPassengers": 70,
            "batteryKwh": 300.0,
            "fuelTankL": None,
            "energyConsumption": 1.3,
            "chargePowerKw": 60.0,
            "minSoc": 0.2,
            "maxSoc": 0.95,
            "acquisitionCost": 0.0,
            "enabled": True,
        },
    )
    scenario_store.create_vehicle(
        scenario_id,
        {
            "depotId": depot_b["id"],
            "type": "BEV",
            "modelName": "B-vehicle",
            "capacityPassengers": 70,
            "batteryKwh": 300.0,
            "fuelTankL": None,
            "energyConsumption": 1.3,
            "chargePowerKw": 60.0,
            "minSoc": 0.2,
            "maxSoc": 0.95,
            "acquisitionCost": 0.0,
            "enabled": True,
        },
    )

    scenario_store.replace_routes_from_source(
        scenario_id,
        "odpt",
        [
            {
                "id": "a-out",
                "name": "A01 (X -> Y)",
                "routeCode": "A01",
                "routeLabel": "A01 (X -> Y)",
                "startStop": "X",
                "endStop": "Y",
                "stopSequence": ["S1", "S2"],
                "tripCount": 4,
                "source": "odpt",
                "depotId": depot_a["id"],
            }
        ],
    )

    scenario_store.set_vehicle_route_permissions(
        scenario_id,
        [
            {"vehicleId": vehicle_a["id"], "routeId": "a-out", "allowed": True},
        ],
    )

    scoped = master_data.get_depot_scoped_vehicle_route_family_permissions(
        scenario_id,
        depot_a["id"],
    )

    assert scoped["total"] > 0
    assert all(item["vehicleId"] == vehicle_a["id"] for item in scoped["items"])


def test_vehicle_route_family_permissions_aggregate_and_expand(
    temp_store_dir: Path,
):
    meta = scenario_store.create_scenario("Vehicle family permissions", "", "thesis_mode")
    scenario_id = meta["id"]

    depot = scenario_store.create_depot(
        scenario_id,
        {"name": "Meguro Depot", "location": "Meguro"},
    )
    vehicle = scenario_store.create_vehicle(
        scenario_id,
        {
            "depotId": depot["id"],
            "type": "BEV",
            "modelName": "BYD K8",
            "capacityPassengers": 70,
            "batteryKwh": 314.0,
            "fuelTankL": None,
            "energyConsumption": 1.3,
            "chargePowerKw": 60.0,
            "minSoc": 0.2,
            "maxSoc": 0.95,
            "acquisitionCost": 0.0,
            "enabled": True,
        },
    )

    scenario_store.replace_routes_from_source(
        scenario_id,
        "gtfs",
        [
            {
                "id": "c-out",
                "name": "C03 (M -> N)",
                "routeCode": "C03",
                "routeLabel": "C03 (M -> N)",
                "startStop": "M",
                "endStop": "N",
                "stopSequence": ["S1", "S2"],
                "tripCount": 8,
                "source": "gtfs",
            },
            {
                "id": "c-in",
                "name": "C03 (N -> M)",
                "routeCode": "C03",
                "routeLabel": "C03 (N -> M)",
                "startStop": "N",
                "endStop": "M",
                "stopSequence": ["S2", "S1"],
                "tripCount": 7,
                "source": "gtfs",
            },
        ],
    )
    scenario_store.set_vehicle_route_permissions(
        scenario_id,
        [
            {"vehicleId": vehicle["id"], "routeId": "c-out", "allowed": True},
            {"vehicleId": vehicle["id"], "routeId": "c-in", "allowed": False},
        ],
    )

    body = master_data.get_vehicle_route_family_permissions(scenario_id)
    item = body["items"][0]
    assert item["routeFamilyCode"] == "C03"
    assert item["allowedRouteCount"] == 1
    assert item["partiallyAllowed"] is True

    updated = master_data.update_vehicle_route_family_permissions(
        scenario_id,
        master_data.UpdateVehicleRouteFamilyPermissionsBody(
            permissions=[
                master_data.VehicleRouteFamilyPermissionItem(
                    vehicleId=vehicle["id"],
                    routeFamilyId=item["routeFamilyId"],
                    allowed=True,
                )
            ]
        ),
    )
    assert updated["items"][0]["allowed"] is True
    assert updated["items"][0]["allowedRouteCount"] == 2
    assert sorted(
        scenario_store.get_vehicle_route_permissions(scenario_id),
        key=lambda entry: entry["routeId"],
    ) == [
        {"vehicleId": vehicle["id"], "routeId": "c-in", "allowed": True},
        {"vehicleId": vehicle["id"], "routeId": "c-out", "allowed": True},
    ]
