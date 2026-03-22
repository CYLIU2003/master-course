from __future__ import annotations

from bff.routers.scenarios import _quick_setup_route_selection_patch


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
