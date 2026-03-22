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
        route_trip_counts={},
        route_limit=20,
    )

    assert [item["id"] for item in items] == ["route-a"]
    assert items[0]["selected"] is True


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
