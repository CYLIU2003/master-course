from __future__ import annotations

import pandas as pd

from src.runtime_scope import _filter_by_route, resolve_scope


def test_resolve_scope_exposes_route_selectors_from_selected_route_metadata() -> None:
    scenario_like = {
        "dispatch_scope": {
            "depotSelection": {
                "mode": "include",
                "depotIds": ["meguro"],
                "primaryDepotId": "meguro",
            },
            "routeSelection": {
                "mode": "include",
                "includeRouteIds": ["tokyu:meguro:さんまバス"],
            },
            "serviceSelection": {"serviceIds": ["WEEKDAY"]},
        },
        "routes": [
            {
                "id": "tokyu:meguro:さんまバス",
                "routeCode": "さんまバス",
                "routeLabel": "さんま (目黒区総合庁舎 -> 目黒駅前)",
                "name": "さんま (目黒区総合庁舎 -> 目黒駅前)",
                "depotId": "meguro",
            }
        ],
    }

    scope = resolve_scope(scenario_like, pd.DataFrame())

    assert scope.route_ids == ["tokyu:meguro:さんまバス"]
    assert "さんまバス" in scope.route_selectors
    assert "さんま (目黒区総合庁舎 -> 目黒駅前)" in scope.route_selectors
    assert "さんま" in scope.route_selectors


def test_filter_by_route_maps_ui_route_ids_to_built_route_ids() -> None:
    frame = pd.DataFrame(
        [
            {"route_id": "odpt-route-sanma", "trip_id": "trip-1"},
            {"route_id": "odpt-route-kuro01", "trip_id": "trip-2"},
            {"route_id": "odpt-route-other", "trip_id": "trip-3"},
        ]
    )
    routes_df = pd.DataFrame(
        [
            {
                "id": "odpt-route-sanma",
                "routeCode": "さんま",
                "routeLabel": "さんま (目黒区総合庁舎 -> 目黒駅前)",
                "name": "さんま (目黒区総合庁舎 -> 目黒駅前)",
                "depotId": "",
            },
            {
                "id": "odpt-route-kuro01",
                "routeCode": "黒０１",
                "routeLabel": "黒０１ (目黒駅前 -> 清水)",
                "name": "黒０１ (目黒駅前 -> 清水)",
                "depotId": "meguro",
            },
            {
                "id": "odpt-route-other",
                "routeCode": "別01",
                "routeLabel": "別０１ (A -> B)",
                "name": "別０１ (A -> B)",
                "depotId": "seta",
            },
        ]
    )

    filtered = _filter_by_route(
        frame,
        ["tokyu:meguro:さんまバス", "tokyu:meguro:黒01"],
        route_selectors=[
            "tokyu:meguro:さんまバス",
            "さんまバス",
            "さんま (目黒区総合庁舎 -> 目黒駅前)",
            "さんま",
            "tokyu:meguro:黒01",
            "黒01",
            "黒０１ (目黒駅前 -> 清水)",
        ],
        routes_df=routes_df,
        depot_ids=["meguro"],
    )

    assert filtered["trip_id"].tolist() == ["trip-1", "trip-2"]


def test_resolve_scope_prefers_dispatch_scope_over_stale_overlay_ids() -> None:
    scenario_like = {
        "scenario_overlay": {
            "depot_ids": ["legacy-depot"],
            "route_ids": ["legacy-route"],
        },
        "dispatch_scope": {
            "depotSelection": {
                "mode": "include",
                "depotIds": ["runtime-depot"],
                "primaryDepotId": "runtime-depot",
            },
            "routeSelection": {
                "mode": "include",
                "includeRouteIds": ["runtime-route"],
                "excludeRouteIds": [],
            },
            "serviceSelection": {"serviceIds": ["WEEKDAY"]},
        },
    }

    scope = resolve_scope(scenario_like, pd.DataFrame())

    assert scope.depot_ids == ["runtime-depot"]
    assert scope.route_ids == ["runtime-route"]
