from __future__ import annotations

from bff.routers import scenarios
from bff.routers.scenarios import _quick_route_items, _quick_setup_route_selection_patch


def _summary_entry(
    service_id: str,
    label: str,
    *,
    family_count: int,
    route_count: int,
    trip_count: int,
    selected: bool,
    main_route_count: int = 0,
    main_trip_count: int = 0,
    short_turn_route_count: int = 0,
    short_turn_trip_count: int = 0,
    depot_route_count: int = 0,
    depot_trip_count: int = 0,
    branch_route_count: int = 0,
    branch_trip_count: int = 0,
    unknown_route_count: int = 0,
    unknown_trip_count: int = 0,
) -> dict[str, int | str | bool]:
    return {
        "serviceId": service_id,
        "label": label,
        "familyCount": family_count,
        "routeCount": route_count,
        "tripCount": trip_count,
        "mainRouteCount": main_route_count,
        "mainTripCount": main_trip_count,
        "shortTurnRouteCount": short_turn_route_count,
        "shortTurnTripCount": short_turn_trip_count,
        "depotRouteCount": depot_route_count,
        "depotTripCount": depot_trip_count,
        "branchRouteCount": branch_route_count,
        "branchTripCount": branch_trip_count,
        "unknownRouteCount": unknown_route_count,
        "unknownTripCount": unknown_trip_count,
        "selected": selected,
    }


def test_quick_setup_route_selection_turns_unchecked_routes_into_excludes() -> None:
    doc = {
        "routes": [
            {"id": "route-a", "depotId": "dep1"},
            {"id": "route-b", "depotId": "dep1"},
            {"id": "route-c", "depotId": "dep2"},
        ],
        "route_depot_assignments": [],
    }
    current_scope = {
        "routeSelection": {
            "mode": "include",
            "includeRouteIds": ["route-a"],
            "excludeRouteIds": [],
            "includeRouteFamilyCodes": ["黒01"],
            "excludeRouteFamilyCodes": [],
        }
    }

    route_selection = _quick_setup_route_selection_patch(
        doc,
        current_scope,
        selected_depot_ids=["dep1"],
        selected_route_ids=["route-a"],
    )

    assert route_selection["mode"] == "refine"
    assert route_selection["includeRouteIds"] == []
    assert route_selection["excludeRouteIds"] == ["route-b"]
    assert route_selection["includeRouteFamilyCodes"] == []
    assert route_selection["excludeRouteFamilyCodes"] == []


def test_quick_setup_route_selection_keeps_routes_outside_selected_depot_as_includes() -> None:
    doc = {
        "routes": [
            {"id": "route-a", "depotId": "dep1"},
            {"id": "route-b", "depotId": "dep1"},
            {"id": "route-c", "depotId": "dep2"},
        ],
        "route_depot_assignments": [],
    }

    route_selection = _quick_setup_route_selection_patch(
        doc,
        current_scope={"routeSelection": {}},
        selected_depot_ids=["dep1"],
        selected_route_ids=["route-a", "route-c"],
    )

    assert route_selection["includeRouteIds"] == ["route-c"]
    assert route_selection["excludeRouteIds"] == ["route-b"]


def test_quick_route_items_filter_by_selected_depot_assignment() -> None:
    doc = {
        "routes": [
            {
                "id": "route-a",
                "depotId": "",
                "routeCode": "黒01",
                "routeFamilyCode": "黒01",
                "name": "黒01 系統",
            },
            {
                "id": "route-b",
                "depotId": "dep2",
                "routeCode": "黒02",
                "routeFamilyCode": "黒02",
                "name": "黒02 系統",
            },
        ],
        "route_depot_assignments": [
            {"routeId": "route-a", "depotId": "dep1"},
            {"routeId": "route-b", "depotId": "dep2"},
        ],
    }

    items = _quick_route_items(
        doc,
        selected_depot_ids=["dep1"],
        selected_route_ids=["route-a"],
        selected_day_type="WEEKDAY",
        route_trip_counts_by_day_type={},
        route_limit=20,
    )

    assert [item["id"] for item in items] == ["route-a"]
    assert items[0]["selected"] is True


def test_quick_route_items_apply_route_limit_after_day_type_filtering() -> None:
    doc = {
        "routes": [
            {
                "id": "route-a",
                "depotId": "dep1",
                "routeCode": "黒01",
                "routeFamilyCode": "黒01",
                "name": "黒01 系統",
            },
            {
                "id": "route-b",
                "depotId": "dep1",
                "routeCode": "黒02",
                "routeFamilyCode": "黒02",
                "name": "黒02 系統",
            },
        ],
        "route_depot_assignments": [],
    }

    items = _quick_route_items(
        doc,
        selected_depot_ids=["dep1"],
        selected_route_ids=["route-b"],
        selected_day_type="WEEKDAY",
        route_trip_counts_by_day_type={
            "route-a": {"SAT": 7},
            "route-b": {"WEEKDAY": 3, "SAT": 1},
        },
        route_limit=1,
    )

    assert [item["id"] for item in items] == ["route-b"]
    assert items[0]["tripCount"] == 3
    assert items[0]["tripCountTotal"] == 4
    assert items[0]["tripCountsByDayType"] == {"WEEKDAY": 3, "SAT": 1}


def test_build_quick_setup_payload_preserves_selected_routes_without_link_filtering() -> None:
    doc = {
        "depots": [{"id": "dep1", "name": "Depot 1"}],
        "routes": [
            {
                "id": "route-a",
                "depotId": "dep1",
                "routeCode": "黒01",
                "routeFamilyCode": "黒01",
                "name": "黒01",
                "tripCount": 3,
                "routeVariantType": "main",
            },
            {
                "id": "route-b",
                "depotId": "dep1",
                "routeCode": "黒02",
                "routeFamilyCode": "黒02",
                "name": "黒02",
                "routeVariantType": "depot_in",
            },
        ],
        "route_depot_assignments": [],
        "vehicles": [],
        "chargers": [],
        "vehicle_templates": [],
        "scenario_overlay": {},
        "simulation_config": {},
    }
    scenario = {
        "id": "scenario-1",
        "name": "Scenario 1",
        "operatorId": "tokyu",
        "datasetVersion": "v1",
        "datasetId": "tokyu_full",
        "status": "draft",
        "feedContext": {},
        "stats": {},
    }
    dispatch_scope = {
        "serviceId": "WEEKDAY",
        "effectiveRouteIds": ["route-a", "route-b"],
        "depotSelection": {"depotIds": ["dep1"], "primaryDepotId": "dep1"},
        "routeSelection": {"mode": "refine", "includeRouteIds": [], "excludeRouteIds": []},
        "serviceSelection": {"serviceIds": ["WEEKDAY"]},
        "tripSelection": {"includeDeadhead": True},
    }

    payload = scenarios._build_quick_setup_payload(
        scenario,
        doc,
        dispatch_scope,
        selected_depot_ids=["dep1"],
        route_limit=20,
    )

    assert payload["selectedRouteIds"] == ["route-a", "route-b"]
    assert [item["id"] for item in payload["routes"]] == ["route-a", "route-b"]
    assert payload["routes"][0]["tripCount"] == 3


def test_build_quick_setup_payload_keeps_all_routes_visible_across_scenarios() -> None:
    doc = {
        "depots": [
            {"id": "dep1", "name": "Depot 1"},
            {"id": "dep2", "name": "Depot 2"},
        ],
        "routes": [
            {
                "id": "route-a",
                "depotId": "dep1",
                "routeCode": "東98",
                "routeFamilyCode": "東98",
                "routeFamilyLabel": "東98",
                "routeLabel": "東９８ (東京駅南口 -> 清水)",
                "startStop": "東京駅南口",
                "endStop": "清水",
                "tripCountsByDayType": {"WEEKDAY": 21, "SAT": 16},
                "tripCountTotal": 37,
                "routeVariantType": "main_outbound",
                "canonicalDirection": "outbound",
                "isPrimaryVariant": True,
            },
            {
                "id": "route-b",
                "depotId": "dep1",
                "routeCode": "東98",
                "routeFamilyCode": "東98",
                "routeFamilyLabel": "東98",
                "routeLabel": "東９８ (清水 -> 東京駅南口)",
                "startStop": "清水",
                "endStop": "東京駅南口",
                "tripCountsByDayType": {"WEEKDAY": 14, "SAT": 0},
                "tripCountTotal": 14,
                "routeVariantType": "main_inbound",
                "canonicalDirection": "inbound",
                "isPrimaryVariant": True,
            },
            {
                "id": "route-c",
                "depotId": "dep2",
                "routeCode": "渋42",
                "routeFamilyCode": "渋42",
                "routeFamilyLabel": "渋42",
                "routeLabel": "渋４２ (渋谷駅 -> 大崎駅西口)",
                "startStop": "渋谷駅",
                "endStop": "大崎駅西口",
                "tripCountsByDayType": {"WEEKDAY": 58, "SAT": 0},
                "tripCountTotal": 58,
                "routeVariantType": "main_outbound",
                "canonicalDirection": "outbound",
                "isPrimaryVariant": True,
            },
        ],
        "route_depot_assignments": [],
        "vehicles": [],
        "chargers": [],
        "vehicle_templates": [],
        "scenario_overlay": {},
        "simulation_config": {},
        "calendar": [
            {"service_id": "WEEKDAY", "name": "平日"},
            {"service_id": "SAT", "name": "土曜"},
        ],
    }
    scenario = {
        "id": "scenario-1",
        "name": "Scenario 1",
        "operatorId": "tokyu",
        "datasetVersion": "v1",
        "datasetId": "tokyu_full",
        "status": "draft",
        "feedContext": {},
        "stats": {},
    }
    dispatch_scope = {
        "serviceId": "WEEKDAY",
        "effectiveRouteIds": ["route-a"],
        "depotSelection": {"depotIds": ["dep1"], "primaryDepotId": "dep1"},
        "routeSelection": {"mode": "refine", "includeRouteIds": [], "excludeRouteIds": []},
        "serviceSelection": {"serviceIds": ["WEEKDAY"]},
        "tripSelection": {"includeDeadhead": True},
    }

    payload = scenarios._build_quick_setup_payload(
        scenario,
        doc,
        dispatch_scope,
        selected_depot_ids=["dep1"],
        route_limit=20,
    )

    assert [item["id"] for item in payload["routes"]] == ["route-a", "route-b", "route-c"]
    route_a = next(item for item in payload["routes"] if item["id"] == "route-a")
    route_b = next(item for item in payload["routes"] if item["id"] == "route-b")
    assert route_a["routeFamilyLabel"] == "東京駅南口 ⇔ 清水"
    assert route_b["routeFamilyLabel"] == "東京駅南口 ⇔ 清水"
    assert payload["selectedDepotIds"] == ["dep1"]
    assert [depot["selected"] for depot in payload["depots"]] == [True, False]


def test_build_quick_setup_payload_surfaces_official_family_labels() -> None:
    doc = {
        "depots": [
            {"id": "dep1", "name": "Depot 1"},
            {"id": "dep2", "name": "Depot 2"},
        ],
        "routes": [
            {
                "id": "east98-main",
                "depotId": "dep1",
                "routeCode": "東98",
                "routeLabel": "東98 (東京駅南口 -> 清水)",
                "routeFamilyCode": "東98",
                "startStop": "東京駅南口",
                "endStop": "清水",
                "tripCountsByDayType": {"WEEKDAY": 5},
                "tripCountTotal": 5,
            },
            {
                "id": "shibu41-main",
                "depotId": "dep1",
                "routeCode": "渋41",
                "routeLabel": "渋41 (渋谷駅 -> 大井町駅)",
                "routeFamilyCode": "渋41",
                "startStop": "渋谷駅",
                "endStop": "大井町駅",
                "tripCountsByDayType": {"WEEKDAY": 3},
                "tripCountTotal": 3,
            },
            {
                "id": "shibu42-main",
                "depotId": "dep2",
                "routeCode": "渋42",
                "routeLabel": "渋42 (渋谷駅 -> 大崎駅西口)",
                "routeFamilyCode": "渋42",
                "startStop": "渋谷駅",
                "endStop": "大崎駅西口",
                "tripCountsByDayType": {"WEEKDAY": 2},
                "tripCountTotal": 2,
            },
        ],
        "route_depot_assignments": [],
        "vehicles": [],
        "chargers": [],
        "vehicle_templates": [],
        "scenario_overlay": {},
        "simulation_config": {},
        "calendar": [
            {"service_id": "WEEKDAY", "name": "平日"},
        ],
    }
    scenario = {
        "id": "scenario-official-family-label",
        "name": "Scenario Official",
        "operatorId": "tokyu",
        "datasetVersion": "v1",
        "datasetId": "tokyu_full",
        "status": "draft",
        "feedContext": {},
        "stats": {},
    }
    dispatch_scope = {
        "serviceId": "WEEKDAY",
        "effectiveRouteIds": ["east98-main"],
        "depotSelection": {"depotIds": ["dep1"], "primaryDepotId": "dep1"},
        "routeSelection": {"mode": "refine", "includeRouteIds": [], "excludeRouteIds": []},
        "serviceSelection": {"serviceIds": ["WEEKDAY"]},
        "tripSelection": {"includeDeadhead": True},
    }

    payload = scenarios._build_quick_setup_payload(
        scenario,
        doc,
        dispatch_scope,
        selected_depot_ids=["dep1"],
        route_limit=20,
    )

    labels = {item["routeFamilyCode"]: item["routeFamilyLabel"] for item in payload["routes"]}
    assert labels["東98"] == "東京駅南口 ⇔ 清水"
    assert labels["渋41"] == "渋谷駅 ⇔ 大井町駅"
    assert labels["渋42"] == "渋谷駅 ⇔ 大崎駅西口"


def test_build_quick_setup_payload_falls_back_to_route_trip_count_when_shards_unavailable(
    monkeypatch,
) -> None:
    """When shard runtime is not ready, routes use their tripCount field from the doc (no day-type filtering)."""
    doc = {
        "depots": [{"id": "dep1", "name": "Depot 1"}],
        "routes": [
            {
                "id": "route-a",
                "depotId": "dep1",
                "routeCode": "黒01",
                "routeFamilyCode": "黒01",
                "name": "黒01",
                "tripCount": 5,
                "routeVariantType": "main",
            },
            {
                "id": "route-b",
                "depotId": "dep1",
                "routeCode": "黒02",
                "routeFamilyCode": "黒02",
                "name": "黒02",
                "tripCount": 3,
                "routeVariantType": "depot_in",
            },
        ],
        "route_depot_assignments": [],
        "vehicles": [],
        "chargers": [],
        "vehicle_templates": [],
        "scenario_overlay": {"dataset_id": "tokyu_full"},
        "simulation_config": {},
        "calendar": [
            {"service_id": "WEEKDAY", "name": "平日"},
            {"service_id": "SAT", "name": "土曜"},
        ],
    }
    scenario = {
        "id": "scenario-fallback",
        "name": "Scenario Fallback",
        "operatorId": "tokyu",
        "datasetVersion": "v1",
        "datasetId": "tokyu_full",
        "status": "draft",
        "feedContext": {},
        "stats": {},
    }
    dispatch_scope = {
        "serviceId": "WEEKDAY",
        "effectiveRouteIds": ["route-a", "route-b"],
        "depotSelection": {"depotIds": ["dep1"], "primaryDepotId": "dep1"},
        "routeSelection": {"mode": "refine", "includeRouteIds": [], "excludeRouteIds": []},
        "serviceSelection": {"serviceIds": ["WEEKDAY"]},
        "tripSelection": {"includeDeadhead": True},
    }

    # Shards NOT available
    monkeypatch.setattr(scenarios, "shard_runtime_ready", lambda dataset_id: False)
    monkeypatch.setattr(scenarios, "tokyu_bus_data_ready", lambda dataset_id: False)

    payload = scenarios._build_quick_setup_payload(
        scenario,
        doc,
        dispatch_scope,
        selected_depot_ids=["dep1"],
        route_limit=20,
    )

    routes = payload["routes"]
    assert len(routes) == 2

    route_a = next(r for r in routes if r["id"] == "route-a")
    route_b = next(r for r in routes if r["id"] == "route-b")

    # Without shards, tripCount falls back to the route's tripCount field in the doc.
    # No per-day-type breakdown — tripCountsByDayType is empty.
    assert route_a["tripCount"] == 5
    assert route_a["tripCountTotal"] == 5
    assert route_a["tripCountsByDayType"] == {}

    assert route_b["tripCount"] == 3
    assert route_b["tripCountTotal"] == 3
    assert route_b["tripCountsByDayType"] == {}
    assert payload["dayTypeSummaries"] == [
        _summary_entry(
            "WEEKDAY",
            "平日",
            family_count=2,
            route_count=2,
            trip_count=8,
            selected=True,
            main_route_count=2,
            main_trip_count=8,
        ),
        _summary_entry(
            "SAT",
            "土曜",
            family_count=0,
            route_count=0,
            trip_count=0,
            selected=False,
        ),
    ]


def test_build_quick_setup_payload_uses_tokyu_bus_data_when_shards_unavailable(
    monkeypatch,
) -> None:
    doc = {
        "depots": [{"id": "dep1", "name": "Depot 1"}],
        "routes": [
            {
                "id": "route-a",
                "depotId": "dep1",
                "routeCode": "黒01",
                "routeFamilyCode": "黒01",
                "name": "黒01",
                "tripCount": 999,
                "routeVariantType": "main",
            },
            {
                "id": "route-b",
                "depotId": "dep1",
                "routeCode": "黒02",
                "routeFamilyCode": "黒02",
                "name": "黒02",
                "tripCount": 999,
                "routeVariantType": "depot_in",
            },
        ],
        "route_depot_assignments": [],
        "vehicles": [],
        "chargers": [],
        "vehicle_templates": [],
        "scenario_overlay": {"dataset_id": "tokyu_full"},
        "simulation_config": {},
        "calendar": [
            {"service_id": "WEEKDAY", "name": "平日"},
            {"service_id": "SAT", "name": "土曜"},
        ],
    }
    scenario = {
        "id": "scenario-bus-data",
        "name": "Scenario Bus Data",
        "operatorId": "tokyu",
        "datasetVersion": "v1",
        "datasetId": "tokyu_full",
        "status": "draft",
        "feedContext": {},
        "stats": {},
    }
    dispatch_scope = {
        "serviceId": "SAT",
        "effectiveRouteIds": ["route-a", "route-b"],
        "depotSelection": {"depotIds": ["dep1"], "primaryDepotId": "dep1"},
        "routeSelection": {"mode": "refine", "includeRouteIds": [], "excludeRouteIds": []},
        "serviceSelection": {"serviceIds": ["SAT"]},
        "tripSelection": {"includeDeadhead": True},
    }

    monkeypatch.setattr(scenarios, "shard_runtime_ready", lambda dataset_id: False)
    monkeypatch.setattr(scenarios, "tokyu_bus_data_ready", lambda dataset_id: dataset_id == "tokyu_full")
    monkeypatch.setattr(
        scenarios,
        "_build_timetable_summary_for_scope_from_tokyu_bus_data",
        lambda **_kwargs: {
            "routeServiceCounts": {
                "WEEKDAY": {"route-a": 5, "route-b": 1},
                "SAT": {"route-b": 2},
            },
            "byService": [
                {"serviceId": "WEEKDAY", "rowCount": 6, "routeCount": 2},
                {"serviceId": "SAT", "rowCount": 2, "routeCount": 1},
            ],
        },
    )

    payload = scenarios._build_quick_setup_payload(
        scenario,
        doc,
        dispatch_scope,
        selected_depot_ids=["dep1"],
        route_limit=20,
    )

    assert [item["id"] for item in payload["routes"]] == ["route-b"]
    assert payload["routes"][0]["tripCount"] == 2
    assert payload["routes"][0]["tripCountSelectedDay"] == 2
    assert payload["routes"][0]["tripCountTotal"] == 3
    assert payload["dayTypeSummaries"] == [
        _summary_entry(
            "WEEKDAY",
            "平日",
            family_count=2,
            route_count=2,
            trip_count=6,
            selected=False,
            main_route_count=2,
            main_trip_count=6,
        ),
        _summary_entry(
            "SAT",
            "土曜",
            family_count=1,
            route_count=1,
            trip_count=2,
            selected=True,
            main_route_count=1,
            main_trip_count=2,
        ),
    ]
    assert payload["depots"] == [
        {
            "id": "dep1",
            "name": "Depot 1",
            "location": "",
            "routeCount": 2,
            "familyCount": 2,
            "vehicleCount": 0,
            "visibleRouteCount": 1,
            "visibleFamilyCount": 1,
            "tripCountSelectedDay": 2,
            "selectedRouteCount": 1,
            "selectedFamilyCount": 1,
            "selectedTripCount": 2,
            "mainRouteCount": 1,
            "mainTripCount": 2,
            "shortTurnRouteCount": 0,
            "shortTurnTripCount": 0,
            "depotRouteCount": 0,
            "depotTripCount": 0,
            "branchRouteCount": 0,
            "branchTripCount": 0,
            "unknownRouteCount": 0,
            "unknownTripCount": 0,
            "selected": True,
        }
    ]


def test_build_quick_setup_payload_filters_routes_by_selected_day_type_and_exposes_summaries(
    monkeypatch,
) -> None:
    doc = {
        "depots": [{"id": "dep1", "name": "Depot 1"}],
        "routes": [
            {
                "id": "route-a",
                "depotId": "dep1",
                "routeCode": "黒01",
                "routeFamilyCode": "黒01",
                "name": "黒01",
                "routeVariantType": "main",
            },
            {
                "id": "route-b",
                "depotId": "dep1",
                "routeCode": "黒02",
                "routeFamilyCode": "黒02",
                "name": "黒02",
                "routeVariantType": "depot_in",
            },
        ],
        "route_depot_assignments": [],
        "vehicles": [],
        "chargers": [],
        "vehicle_templates": [],
        "scenario_overlay": {"dataset_id": "tokyu_full"},
        "simulation_config": {},
        "calendar": [
            {"service_id": "WEEKDAY", "name": "平日"},
            {"service_id": "SAT", "name": "土曜"},
        ],
    }
    scenario = {
        "id": "scenario-1",
        "name": "Scenario 1",
        "operatorId": "tokyu",
        "datasetVersion": "v1",
        "datasetId": "tokyu_full",
        "status": "draft",
        "feedContext": {},
        "stats": {},
    }
    dispatch_scope = {
        "serviceId": "SAT",
        "effectiveRouteIds": ["route-a", "route-b"],
        "depotSelection": {"depotIds": ["dep1"], "primaryDepotId": "dep1"},
        "routeSelection": {"mode": "refine", "includeRouteIds": [], "excludeRouteIds": []},
        "serviceSelection": {"serviceIds": ["SAT"]},
        "tripSelection": {"includeDeadhead": True},
    }

    monkeypatch.setattr(scenarios, "shard_runtime_ready", lambda dataset_id: dataset_id == "tokyu_full")
    monkeypatch.setattr(
        scenarios,
        "build_timetable_summary_for_scope",
        lambda **_kwargs: {
            "routeServiceCounts": {
                "WEEKDAY": {"route-a": 5, "route-b": 1},
                "SAT": {"route-b": 2},
            },
            "byService": [
                {"serviceId": "WEEKDAY", "rowCount": 6, "routeCount": 2},
                {"serviceId": "SAT", "rowCount": 2, "routeCount": 1},
            ],
        },
    )

    payload = scenarios._build_quick_setup_payload(
        scenario,
        doc,
        dispatch_scope,
        selected_depot_ids=["dep1"],
        route_limit=20,
    )

    assert [item["id"] for item in payload["routes"]] == ["route-b"]
    assert payload["routes"][0]["tripCount"] == 2
    assert payload["routes"][0]["tripCountSelectedDay"] == 2
    assert payload["routes"][0]["tripCountTotal"] == 3
    assert payload["routes"][0]["tripCountsByDayType"] == {"WEEKDAY": 1, "SAT": 2}
    assert payload["dispatchScope"]["dayType"] == "SAT"
    assert payload["dayTypeSummaries"] == [
        _summary_entry(
            "WEEKDAY",
            "平日",
            family_count=2,
            route_count=2,
            trip_count=6,
            selected=False,
            main_route_count=2,
            main_trip_count=6,
        ),
        _summary_entry(
            "SAT",
            "土曜",
            family_count=1,
            route_count=1,
            trip_count=2,
            selected=True,
            main_route_count=1,
            main_trip_count=2,
        ),
    ]


def test_build_quick_setup_payload_hides_zero_trip_variants_seeded_from_route_metadata(
    monkeypatch,
) -> None:
    doc = {
        "depots": [{"id": "dep1", "name": "Depot 1"}],
        "routes": [
            {
                "id": "route-zero",
                "depotId": "dep1",
                "routeCode": "黒01",
                "routeFamilyCode": "黒01",
                "name": "黒01 zero",
                "tripCountsByDayType": {"WEEKDAY": 0, "SAT": 0, "SUN_HOL": 0},
                "tripCountTotal": 0,
            },
            {
                "id": "route-live",
                "depotId": "dep1",
                "routeCode": "黒01",
                "routeFamilyCode": "黒01",
                "name": "黒01 live",
                "tripCountsByDayType": {"WEEKDAY": 191, "SAT": 152, "SUN_HOL": 152},
                "tripCountTotal": 495,
            },
        ],
        "route_depot_assignments": [],
        "vehicles": [],
        "chargers": [],
        "vehicle_templates": [],
        "scenario_overlay": {"dataset_id": "tokyu_full"},
        "simulation_config": {},
        "calendar": [
            {"service_id": "WEEKDAY", "name": "平日"},
            {"service_id": "SAT", "name": "土曜"},
            {"service_id": "SUN_HOL", "name": "日曜・休日"},
        ],
    }
    scenario = {
        "id": "scenario-1",
        "name": "Scenario 1",
        "operatorId": "tokyu",
        "datasetVersion": "v1",
        "datasetId": "tokyu_full",
        "status": "draft",
        "feedContext": {},
        "stats": {},
    }
    dispatch_scope = {
        "serviceId": "WEEKDAY",
        "effectiveRouteIds": ["route-zero", "route-live"],
        "depotSelection": {"depotIds": ["dep1"], "primaryDepotId": "dep1"},
        "routeSelection": {"mode": "refine", "includeRouteIds": [], "excludeRouteIds": []},
        "serviceSelection": {"serviceIds": ["WEEKDAY"]},
        "tripSelection": {"includeDeadhead": True},
    }

    monkeypatch.setattr(scenarios, "shard_runtime_ready", lambda dataset_id: False)
    monkeypatch.setattr(scenarios, "tokyu_bus_data_ready", lambda dataset_id: dataset_id == "tokyu_full")
    monkeypatch.setattr(
        scenarios,
        "_build_timetable_summary_for_scope_from_tokyu_bus_data",
        lambda **_kwargs: {
            "routeServiceCounts": {
                "WEEKDAY": {"route-live": 191},
                "SAT": {"route-live": 152},
                "SUN_HOL": {"route-live": 152},
            },
            "byService": [
                {"serviceId": "WEEKDAY", "rowCount": 191, "routeCount": 1},
                {"serviceId": "SAT", "rowCount": 152, "routeCount": 1},
                {"serviceId": "SUN_HOL", "rowCount": 152, "routeCount": 1},
            ],
        },
    )

    payload = scenarios._build_quick_setup_payload(
        scenario,
        doc,
        dispatch_scope,
        selected_depot_ids=["dep1"],
        route_limit=20,
    )

    assert [item["id"] for item in payload["routes"]] == ["route-live"]
