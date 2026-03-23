from __future__ import annotations

from unittest import mock

from bff.services import master_defaults
from src.research_dataset_loader import (
    build_dataset_bootstrap,
    _filter_depots_by_route_context,
    _filter_routes_by_route_ids,
    load_dataset_definition,
)


def test_filter_routes_and_depots_follow_available_trip_context() -> None:
    routes = [
        {"id": "route-a", "depotId": "dep-a"},
        {"id": "route-b", "depotId": ""},
        {"id": "route-c", "depotId": "dep-c"},
    ]
    assignments = [
        {"routeId": "route-a", "depotId": "dep-a"},
        {"routeId": "route-b", "depotId": "dep-b"},
    ]
    depots = [
        {"id": "dep-a"},
        {"id": "dep-b"},
        {"id": "dep-c"},
    ]

    filtered_routes = _filter_routes_by_route_ids(routes, {"route-a", "route-b"})
    filtered_depots = _filter_depots_by_route_context(depots, filtered_routes, assignments)

    assert [route["id"] for route in filtered_routes] == ["route-a", "route-b"]
    assert [depot["id"] for depot in filtered_depots] == ["dep-a", "dep-b"]


def test_build_dataset_bootstrap_keeps_dataset_depots_visible() -> None:
    definition = load_dataset_definition(master_defaults.DEFAULT_DATASET_ID)
    payload = build_dataset_bootstrap(
        master_defaults.DEFAULT_DATASET_ID,
        scenario_id="test-visible-depots",
        random_seed=42,
    )

    depot_ids = [
        str(item.get("id") or item.get("depotId") or "").strip()
        for item in payload.get("depots") or []
        if str(item.get("id") or item.get("depotId") or "").strip()
    ]
    selected_depot_ids = list(
        ((payload.get("dispatch_scope") or {}).get("depotSelection") or {}).get("depotIds")
        or []
    )

    assert depot_ids == list(definition.get("included_depots") or [])
    assert set(selected_depot_ids).issubset(set(depot_ids))
    assert payload["scenario_overlay"]["depot_ids"] == selected_depot_ids
    assert selected_depot_ids


def test_build_dataset_bootstrap_uses_catalog_fast_route_inventory() -> None:
    payload = build_dataset_bootstrap(
        master_defaults.DEFAULT_DATASET_ID,
        scenario_id="test-catalog-fast-routes",
        random_seed=42,
    )

    route_ids = [
        str(item.get("id") or "").strip()
        for item in payload.get("routes") or []
        if str(item.get("id") or "").strip()
    ]
    selected_route_ids = list(
        ((payload.get("dispatch_scope") or {}).get("routeSelection") or {}).get("includeRouteIds")
        or []
    )

    assert len(route_ids) > len(selected_route_ids)
    assert set(selected_route_ids).issubset(set(route_ids))
    assert payload["scenario_overlay"]["route_ids"] == selected_route_ids
    assert any(route_id not in set(selected_route_ids) for route_id in route_ids)


def test_build_dataset_bootstrap_routes_include_day_type_trip_counts() -> None:
    payload = build_dataset_bootstrap(
        master_defaults.DEFAULT_DATASET_ID,
        scenario_id="test-route-day-type-counts",
        random_seed=42,
    )

    route = next(
        item
        for item in payload.get("routes") or []
        if str(item.get("id") or "").strip() == "odpt-route-524c00d5ceff"
    )

    assert route["tripCountsByDayType"] == {"WEEKDAY": 191, "SAT": 152, "SUN_HOL": 152}
    assert int(route["tripCountTotal"]) == 495


def test_master_defaults_falls_back_to_runtime_default_when_preload_has_no_trips() -> None:
    preload_payload = {
        "depots": [{"id": "meguro"}],
        "routes": [{"id": "tokyu:meguro:黒01"}],
        "vehicle_templates": [{"id": "tmpl-preload"}],
        "route_depot_assignments": [],
        "depot_route_permissions": [],
        "dispatch_scope": {"datasetVersion": "preload-v1"},
        "feed_context": {},
        "trips": [],
    }
    runtime_payload = {
        "depots": [{"id": "ebara"}],
        "routes": [{"id": "odpt-route-1"}],
        "vehicle_templates": [{"id": "tmpl-runtime"}],
        "route_depot_assignments": [],
        "depot_route_permissions": [],
        "dispatch_scope": {"datasetVersion": "runtime-v1"},
        "feed_context": {},
        "trips": [{"trip_id": "trip-1"}],
    }

    with mock.patch.object(
        master_defaults,
        "build_dataset_bootstrap",
        side_effect=[preload_payload, runtime_payload],
    ):
        master_defaults._cached_preloaded_master_data.cache_clear()
        payload = master_defaults.get_preloaded_master_data("tokyu_dispatch_ready")
        master_defaults._cached_preloaded_master_data.cache_clear()

    assert payload["datasetId"] == master_defaults.DEFAULT_DATASET_ID
    assert payload["depots"] == runtime_payload["depots"]
    assert payload["routes"] == runtime_payload["routes"]


def test_master_defaults_uses_effective_dataset_id_from_bootstrap_feed_context() -> None:
    bootstrap_payload = {
        "depots": [{"id": "ebara"}],
        "routes": [{"id": "odpt-route-1"}],
        "vehicle_templates": [{"id": "tmpl-runtime"}],
        "route_depot_assignments": [],
        "depot_route_permissions": [],
        "dispatch_scope": {"datasetVersion": "runtime-v1"},
        "feed_context": {"datasetId": master_defaults.DEFAULT_DATASET_ID},
        "trips": [{"trip_id": "trip-1"}],
    }

    with mock.patch.object(
        master_defaults,
        "build_dataset_bootstrap",
        return_value=bootstrap_payload,
    ):
        master_defaults._cached_preloaded_master_data.cache_clear()
        payload = master_defaults.get_preloaded_master_data("tokyu_dispatch_ready")
        master_defaults._cached_preloaded_master_data.cache_clear()

    assert payload["datasetId"] == master_defaults.DEFAULT_DATASET_ID
