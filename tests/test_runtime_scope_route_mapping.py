from __future__ import annotations

import pandas as pd

from src.runtime_scope import RuntimeScope, _filter_by_route, load_scoped_timetables, load_scoped_trips, resolve_scope


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


def test_load_scoped_frames_drop_gtfs_reconciliation_duplicates(tmp_path, monkeypatch) -> None:
    built_dir = tmp_path / "tokyu_full"
    built_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {"id": "route-a", "routeCode": "黒01", "routeLabel": "黒01", "depotId": "dep1"},
        ]
    ).to_parquet(built_dir / "routes.parquet", index=False)
    pd.DataFrame(
        [
            {"trip_id": "trip-1", "route_id": "route-a", "service_id": "WEEKDAY"},
            {"trip_id": "trip-1__v1", "route_id": "route-a", "service_id": "WEEKDAY"},
        ]
    ).to_parquet(built_dir / "trips.parquet", index=False)
    pd.DataFrame(
        [
            {"trip_id": "trip-1", "route_id": "route-a", "service_id": "WEEKDAY", "stop_id": "stop-a"},
            {"trip_id": "trip-1__v1", "route_id": "route-a", "service_id": "WEEKDAY", "stop_id": "stop-a"},
        ]
    ).to_parquet(built_dir / "timetables.parquet", index=False)

    monkeypatch.setattr("src.runtime_scope.shard_runtime_ready", lambda dataset_id: False)
    monkeypatch.setattr("src.runtime_scope.tokyu_bus_data_ready", lambda dataset_id: False)

    scope = RuntimeScope(
        depot_ids=["dep1"],
        route_ids=["route-a"],
        service_ids=["WEEKDAY"],
    )

    trips = load_scoped_trips(built_dir, scope)
    timetables = load_scoped_timetables(built_dir, scope)

    assert trips["trip_id"].tolist() == ["trip-1"]
    assert timetables["trip_id"].tolist() == ["trip-1"]


def test_load_scoped_frames_prefer_tokyu_bus_data_over_built_parquet(tmp_path, monkeypatch) -> None:
    built_dir = tmp_path / "tokyu_full"
    built_dir.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(
        [
            {"id": "route-a", "routeCode": "黒01", "routeLabel": "黒01", "depotId": "meguro"},
        ]
    ).to_parquet(built_dir / "routes.parquet", index=False)
    pd.DataFrame(
        [
            {"trip_id": "stale-trip", "route_id": "route-a", "service_id": "WEEKDAY"},
        ]
    ).to_parquet(built_dir / "trips.parquet", index=False)
    pd.DataFrame(
        [
            {"trip_id": "stale-trip", "route_id": "route-a", "service_id": "WEEKDAY", "stop_id": "stop-a"},
        ]
    ).to_parquet(built_dir / "timetables.parquet", index=False)

    monkeypatch.setattr("src.runtime_scope.shard_runtime_ready", lambda dataset_id: False)
    monkeypatch.setattr("src.runtime_scope.tokyu_bus_data_ready", lambda dataset_id: True)
    monkeypatch.setattr(
        "src.runtime_scope.load_tokyu_bus_trip_rows_for_scope",
        lambda **kwargs: [
            {"trip_id": "bus-data-trip", "route_id": "route-a", "service_id": "WEEKDAY"}
        ],
    )
    monkeypatch.setattr(
        "src.runtime_scope.load_tokyu_bus_stop_time_rows_for_scope",
        lambda **kwargs: [
            {"trip_id": "bus-data-trip", "route_id": "route-a", "service_id": "WEEKDAY", "stop_id": "stop-a"}
        ],
    )

    scope = RuntimeScope(
        depot_ids=["meguro"],
        route_ids=["route-a"],
        service_ids=["WEEKDAY"],
    )

    trips = load_scoped_trips(built_dir, scope)
    timetables = load_scoped_timetables(built_dir, scope)

    assert trips["trip_id"].tolist() == ["bus-data-trip"]
    assert timetables["trip_id"].tolist() == ["bus-data-trip"]
