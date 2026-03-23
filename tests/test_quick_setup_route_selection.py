from __future__ import annotations

from bff.routers import scenarios
from bff.routers.scenarios import _quick_route_items, _quick_setup_route_selection_patch


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
            },
            {
                "id": "route-b",
                "depotId": "dep1",
                "routeCode": "黒02",
                "routeFamilyCode": "黒02",
                "name": "黒02",
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
            },
            {
                "id": "route-b",
                "depotId": "dep1",
                "routeCode": "黒02",
                "routeFamilyCode": "黒02",
                "name": "黒02",
                "tripCount": 3,
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
            },
            {
                "id": "route-b",
                "depotId": "dep1",
                "routeCode": "黒02",
                "routeFamilyCode": "黒02",
                "name": "黒02",
                "tripCount": 999,
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
        {
            "serviceId": "WEEKDAY",
            "label": "平日",
            "routeCount": 2,
            "tripCount": 6,
            "selected": False,
        },
        {
            "serviceId": "SAT",
            "label": "土曜",
            "routeCount": 1,
            "tripCount": 2,
            "selected": True,
        },
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
            },
            {
                "id": "route-b",
                "depotId": "dep1",
                "routeCode": "黒02",
                "routeFamilyCode": "黒02",
                "name": "黒02",
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
        {
            "serviceId": "WEEKDAY",
            "label": "平日",
            "routeCount": 2,
            "tripCount": 6,
            "selected": False,
        },
        {
            "serviceId": "SAT",
            "label": "土曜",
            "routeCount": 1,
            "tripCount": 2,
            "selected": True,
        },
    ]
