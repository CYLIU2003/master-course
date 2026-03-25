from __future__ import annotations

from unittest import mock

from bff.services import master_defaults
from bff.store import scenario_store


def test_repair_missing_master_data_rebases_stale_runtime_master() -> None:
    doc = {
        "meta": {"id": "scenario-1"},
        "scenario_overlay": {
            "dataset_id": "tokyu_dispatch_ready",
            "dataset_version": "stale-v1",
            "random_seed": 42,
            "depot_ids": ["meguro"],
            "route_ids": ["tokyu:meguro:黒01"],
            "solver_config": {"mode": "mode_milp_only"},
        },
        "feed_context": {"datasetId": "tokyu_dispatch_ready", "snapshotId": "stale-v1"},
        "depots": [{"id": "meguro", "normalChargerCount": 9}],
        "routes": [{"id": "tokyu:meguro:黒01", "routeVariantTypeManual": "main"}],
        "vehicles": [{"id": "veh-1", "depotId": "meguro"}],
        "vehicle_templates": [{"id": "tmpl-old"}],
        "route_depot_assignments": [{"routeId": "tokyu:meguro:黒01", "depotId": "meguro"}],
        "depot_route_permissions": [{"depotId": "meguro", "routeId": "tokyu:meguro:黒01", "allowed": True}],
        "vehicle_route_permissions": [{"vehicleId": "veh-1", "routeId": "tokyu:meguro:黒01", "allowed": True}],
        "dispatch_scope": {
            "scopeId": "stale-scope",
            "operatorId": "tokyu",
            "datasetVersion": "stale-v1",
            "depotSelection": {
                "mode": "include",
                "depotIds": ["meguro"],
                "primaryDepotId": "meguro",
            },
            "routeSelection": {
                "mode": "include",
                "includeRouteIds": ["tokyu:meguro:黒01"],
                "excludeRouteIds": [],
            },
            "serviceSelection": {"serviceIds": ["WEEKDAY"]},
            "tripSelection": {"includeShortTurn": True},
            "serviceId": "WEEKDAY",
            "depotId": "meguro",
        },
        "calendar": [{"service_id": "WEEKDAY"}],
        "calendar_dates": [],
    }
    preload_payload = {
        "datasetId": "tokyu_full",
        "routes": [{"id": "odpt-route-1"}],
        "depots": [{"id": "ebara"}],
        "vehicleTemplates": [{"id": "tmpl-runtime"}],
        "routeDepotAssignments": [{"routeId": "odpt-route-1", "depotId": "ebara"}],
        "depotRoutePermissions": [{"depotId": "ebara", "routeId": "odpt-route-1", "allowed": True}],
        "dispatchScope": {
            "datasetVersion": "runtime-v1",
            "depotSelection": {"depotIds": ["ebara"], "primaryDepotId": "ebara"},
            "routeSelection": {"includeRouteIds": ["odpt-route-1"], "excludeRouteIds": []},
            "serviceSelection": {"serviceIds": ["WEEKDAY"]},
            "tripSelection": {"includeShortTurn": True},
        },
        "feedContext": {"datasetId": "tokyu_full"},
    }
    bootstrap_payload = {
        "depots": [{"id": "ebara"}, {"id": "meguro"}],
        "routes": [{"id": "odpt-route-1", "routeVariantTypeManual": None}],
        "vehicle_templates": [{"id": "tmpl-runtime"}],
        "route_depot_assignments": [{"routeId": "odpt-route-1", "depotId": "ebara"}],
        "depot_route_permissions": [{"depotId": "ebara", "routeId": "odpt-route-1", "allowed": True}],
        "dispatch_scope": {
            "scopeId": "runtime-scope",
            "operatorId": "tokyu",
            "datasetVersion": "runtime-v1",
            "depotSelection": {
                "mode": "include",
                "depotIds": ["ebara"],
                "primaryDepotId": "ebara",
            },
            "routeSelection": {
                "mode": "include",
                "includeRouteIds": ["odpt-route-1"],
                "excludeRouteIds": [],
            },
            "serviceSelection": {"serviceIds": ["WEEKDAY"]},
            "tripSelection": {"includeShortTurn": True},
            "serviceId": "WEEKDAY",
            "depotId": "ebara",
        },
        "feed_context": {"datasetId": "tokyu_full", "snapshotId": "runtime-v1"},
        "scenario_overlay": {
            "dataset_id": "tokyu_full",
            "dataset_version": "runtime-v1",
            "random_seed": 42,
            "depot_ids": ["ebara"],
            "route_ids": ["odpt-route-1"],
        },
        "stops": [{"id": "stop-1"}],
        "calendar": [{"service_id": "WEEKDAY"}],
        "calendar_dates": [],
    }

    with mock.patch.object(
        master_defaults,
        "get_preloaded_master_data",
        return_value=preload_payload,
    ), mock.patch.object(
        master_defaults,
        "build_dataset_bootstrap",
        return_value=bootstrap_payload,
    ):
        changed = master_defaults.repair_missing_master_data(
            doc,
            dataset_id="tokyu_dispatch_ready",
        )

    assert changed is True
    assert doc["feed_context"]["datasetId"] == "tokyu_full"
    assert [item["id"] for item in doc["routes"]] == ["odpt-route-1"]
    assert {item["id"] for item in doc["depots"]} == {"ebara", "meguro"}
    assert doc["dispatch_scope"]["routeSelection"]["includeRouteIds"] == []
    assert doc["dispatch_scope"]["depotSelection"]["depotIds"] == []
    assert doc["scenario_overlay"]["route_ids"] == []
    assert doc["scenario_overlay"]["depot_ids"] == []
    assert doc["scenario_overlay"]["solver_config"]["mode"] == "mode_milp_only"
    assert doc["vehicle_route_permissions"] == []


def test_get_preloaded_master_data_reclassifies_all_generic_routes() -> None:
    bootstrap_payload = {
        "depots": [{"id": "seta"}],
        "routes": [
            {
                "id": "route-out",
                "name": "出入庫 (瀬田営業所 -> 二子玉川駅)",
                "routeCode": "出入庫",
                "routeLabel": "出入庫 (瀬田営業所 -> 二子玉川駅)",
                "startStop": "瀬田営業所",
                "endStop": "二子玉川駅",
                "tripCount": 6,
                "tripCountsByDayType": {"WEEKDAY": 6},
            },
            {
                "id": "route-in",
                "name": "出入庫 (二子玉川駅 -> 瀬田営業所)",
                "routeCode": "出入庫",
                "routeLabel": "出入庫 (二子玉川駅 -> 瀬田営業所)",
                "startStop": "二子玉川駅",
                "endStop": "瀬田営業所",
                "tripCount": 2,
                "tripCountsByDayType": {"WEEKDAY": 2},
            },
        ],
        "vehicle_templates": [],
        "route_depot_assignments": [],
        "depot_route_permissions": [],
        "dispatch_scope": {"datasetVersion": "v1"},
        "feed_context": {"datasetId": "tokyu_full"},
        "trips": [{"trip_id": "trip-1"}],
    }

    with mock.patch.object(
        master_defaults,
        "build_dataset_bootstrap",
        return_value=bootstrap_payload,
    ):
        master_defaults._cached_preloaded_master_data.cache_clear()
        payload = master_defaults.get_preloaded_master_data("tokyu_full")
        master_defaults._cached_preloaded_master_data.cache_clear()

    routes = {item["id"]: item for item in payload["routes"]}
    assert routes["route-out"]["routeFamilyCode"] == "出入庫:二子玉川駅⇔瀬田営業所"
    assert routes["route-out"]["routeVariantType"] == "depot_out"
    assert routes["route-in"]["routeFamilyCode"] == "出入庫:二子玉川駅⇔瀬田営業所"
    assert routes["route-in"]["routeVariantType"] == "depot_in"


def test_repair_route_metadata_from_preload_reclassifies_routes_and_preserves_user_override() -> None:
    doc = {
        "meta": {"id": "scenario-1"},
        "scenario_overlay": {"dataset_id": "tokyu_full"},
        "feed_context": {"datasetId": "tokyu_full"},
        "routes": [
            {
                "id": "route-out",
                "name": "出入庫 (瀬田営業所 -> 二子玉川駅)",
                "routeCode": "出入庫",
                "routeLabel": "出入庫 (瀬田営業所 -> 二子玉川駅)",
                "startStop": "瀬田営業所",
                "endStop": "二子玉川駅",
                "tripCount": 6,
                "routeVariantTypeManual": "branch",
                "canonicalDirectionManual": "outbound",
                "classificationSource": "user_manual_override",
                "manualClassificationLocked": True,
            }
        ],
    }
    preload_payload = {
        "datasetId": "tokyu_full",
        "routes": [
            {
                "id": "route-out",
                "name": "出入庫 (瀬田営業所 -> 二子玉川駅)",
                "routeCode": "出入庫",
                "routeLabel": "出入庫 (瀬田営業所 -> 二子玉川駅)",
                "startStop": "瀬田営業所",
                "endStop": "二子玉川駅",
                "tripCount": 6,
                "tripCountsByDayType": {"WEEKDAY": 6},
            }
        ],
    }

    with mock.patch.object(
        master_defaults,
        "get_preloaded_master_data",
        return_value=preload_payload,
    ):
        changed = scenario_store._repair_route_metadata_from_preload(doc)

    assert changed is True
    route = doc["routes"][0]
    assert route["routeFamilyCode"] == "出入庫:二子玉川駅⇔瀬田営業所"
    assert route["routeVariantTypeManual"] == "branch"
    assert route["canonicalDirectionManual"] == "outbound"
    assert route["classificationSource"] == "user_manual_override"
    assert route["manualClassificationLocked"] is True
    assert route["routeVariantType"] == "branch"
