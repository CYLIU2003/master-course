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
        },
    )

    assert normalized["effectiveRouteIds"] == ["route-b"]
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
