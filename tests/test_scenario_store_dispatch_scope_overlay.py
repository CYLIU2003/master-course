from __future__ import annotations

from unittest import mock

from bff.store import scenario_store


def test_set_dispatch_scope_syncs_overlay_route_and_depot_ids(monkeypatch) -> None:
    doc = {
        "meta": {"id": "scenario-1", "updatedAt": "2026-03-21T00:00:00Z", "status": "draft"},
        "depots": [{"id": "dep-a"}, {"id": "dep-b"}],
        "routes": [
            {"id": "route-a", "depotId": "dep-a"},
            {"id": "route-b", "depotId": "dep-b"},
        ],
        "route_depot_assignments": [],
        "calendar": [{"service_id": "WEEKDAY"}],
        "dispatch_scope": {
            "scopeId": "scope-1",
            "operatorId": "tokyu",
            "datasetVersion": "v1",
            "depotSelection": {
                "mode": "include",
                "depotIds": ["dep-a"],
                "primaryDepotId": "dep-a",
            },
            "routeSelection": {
                "mode": "include",
                "includeRouteIds": ["route-a"],
                "excludeRouteIds": [],
            },
            "serviceSelection": {"serviceIds": ["WEEKDAY"]},
            "tripSelection": {"includeShortTurn": True},
            "serviceId": "WEEKDAY",
            "depotId": "dep-a",
        },
        "scenario_overlay": {
            "dataset_id": "tokyu_full",
            "dataset_version": "v1",
            "random_seed": 42,
            "depot_ids": ["dep-a"],
            "route_ids": ["route-a"],
        },
        "trips": None,
        "graph": None,
        "blocks": None,
        "duties": None,
        "dispatch_plan": None,
        "simulation_result": None,
        "optimization_result": None,
        "problemdata_build_audit": None,
        "optimization_audit": None,
        "simulation_audit": None,
    }

    monkeypatch.setattr(
        scenario_store,
        "_load",
        lambda scenario_id, **kwargs: doc,
    )
    monkeypatch.setattr(scenario_store, "_save", lambda payload: None)

    normalized = scenario_store.set_dispatch_scope(
        "scenario-1",
        {
            "depotSelection": {
                "mode": "include",
                "depotIds": ["dep-b"],
                "primaryDepotId": "dep-b",
            },
            "routeSelection": {
                "mode": "include",
                "includeRouteIds": ["route-b"],
                "excludeRouteIds": [],
            },
            "fixedRouteBandMode": True,
        },
    )

    assert normalized["effectiveRouteIds"] == ["route-b"]
    assert normalized["fixedRouteBandMode"] is True
    assert doc["scenario_overlay"]["depot_ids"] == ["dep-b"]
    assert doc["scenario_overlay"]["route_ids"] == ["route-b"]


def test_needs_runtime_master_alignment_when_runtime_has_more_catalog_fast_routes() -> None:
    doc = {
        "scenario_overlay": {"dataset_id": "tokyu_full"},
        "feed_context": {"datasetId": "tokyu_full"},
        "routes": [{"id": "route-a"}],
        "depots": [{"id": "dep-a"}],
    }
    payload = {
        "datasetId": "tokyu_full",
        "routes": [{"id": "route-a"}, {"id": "route-b"}],
        "depots": [{"id": "dep-a"}, {"id": "dep-b"}],
    }

    with mock.patch("bff.services.master_defaults.get_preloaded_master_data", return_value=payload):
        assert scenario_store._needs_runtime_master_alignment(doc) is True


def test_normalize_dispatch_scope_candidate_routes_ignore_full_matrix_permissions() -> None:
    doc = {
        "meta": {"operatorId": "tokyu"},
        "depots": [{"id": "dep-a"}, {"id": "dep-b"}],
        "routes": [
            {"id": "route-a", "depotId": "dep-a", "routeFamilyCode": "黒01"},
            {"id": "route-b", "depotId": "dep-b", "routeFamilyCode": "黒02"},
        ],
        "route_depot_assignments": [],
        "depot_route_permissions": [
            {"depotId": "dep-a", "routeId": "route-a", "allowed": True},
            {"depotId": "dep-a", "routeId": "route-b", "allowed": True},
            {"depotId": "dep-b", "routeId": "route-a", "allowed": True},
            {"depotId": "dep-b", "routeId": "route-b", "allowed": True},
        ],
        "calendar": [{"service_id": "WEEKDAY"}],
        "dispatch_scope": {
            "operatorId": "tokyu",
            "depotSelection": {
                "mode": "include",
                "depotIds": ["dep-a"],
                "primaryDepotId": "dep-a",
            },
            "routeSelection": {
                "mode": "all",
                "includeRouteIds": [],
                "excludeRouteIds": [],
            },
            "serviceSelection": {"serviceIds": ["WEEKDAY"]},
            "tripSelection": {
                "includeShortTurn": True,
                "includeDepotMoves": True,
                "includeDeadhead": True,
            },
            "serviceId": "WEEKDAY",
            "depotId": "dep-a",
        },
    }

    normalized = scenario_store._normalize_dispatch_scope(doc)

    assert normalized["candidateRouteIds"] == ["route-a"]
    assert normalized["effectiveRouteIds"] == ["route-a"]


def test_set_field_timetable_rows_updates_stats_and_invalidates_dispatch(tmp_path, monkeypatch) -> None:
    scenario_id = "scenario-1"
    store_dir = tmp_path / "scenarios"
    refs = scenario_store.scenario_meta_store.default_refs(store_dir, scenario_id)
    scenario_store.scenario_meta_store.save_meta(
        store_dir,
        scenario_id,
        {
            "scenarioId": scenario_id,
            "name": "Scenario 1",
            "meta": {
                "id": scenario_id,
                "name": "Scenario 1",
                "status": "optimized",
                "updatedAt": "2026-03-23T00:00:00Z",
                "operatorId": "tokyu",
            },
            "refs": refs,
            "stats": {
                "routeCount": 0,
                "stopCount": 0,
                "timetableRowCount": 0,
                "tripCount": 1,
                "dutyCount": 1,
            },
        },
    )
    monkeypatch.setattr(scenario_store, "_STORE_DIR", store_dir)

    scenario_store.set_field(scenario_id, "trips", [{"trip_id": "old-trip"}])
    scenario_store.set_field(
        scenario_id,
        "optimization_result",
        {"solver_status": "OPTIMAL"},
    )

    scenario_store.set_field(
        scenario_id,
        "timetable_rows",
        [
            {
                "trip_id": "trip-1",
                "route_id": "route-a",
                "service_id": "WEEKDAY",
                "departure": "08:00",
                "arrival": "08:30",
            },
            {
                "trip_id": "trip-1__v1",
                "route_id": "route-a",
                "service_id": "WEEKDAY",
                "departure": "08:00",
                "arrival": "08:30",
            },
        ],
        invalidate_dispatch=True,
    )

    updated_meta = scenario_store.scenario_meta_store.load_meta(store_dir, scenario_id)

    assert updated_meta["meta"]["status"] == "draft"
    assert updated_meta["stats"]["timetableRowCount"] == 1
    assert updated_meta["stats"]["tripCount"] == 0
    assert updated_meta["stats"]["dutyCount"] == 0
    assert scenario_store.get_field(scenario_id, "optimization_result") is None
    assert scenario_store.get_field(scenario_id, "trips") is None
