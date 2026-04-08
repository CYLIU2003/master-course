from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest import mock

from bff.store import scenario_store


def test_default_dispatch_scope_enables_fixed_route_band_mode() -> None:
    scope = scenario_store._default_dispatch_scope()

    assert scope["fixedRouteBandMode"] is True


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


def test_set_public_data_state_preserves_existing_timetable_rows(tmp_path, monkeypatch) -> None:
    store_dir = tmp_path / "scenarios"
    monkeypatch.setattr(scenario_store, "_STORE_DIR", store_dir)

    scenario = scenario_store.create_scenario(
        name="Scenario 1",
        description="preserve artifacts",
        mode="thesis_mode",
    )
    scenario_id = str(scenario["id"])

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
            }
        ],
    )

    assert scenario_store.count_timetable_rows(scenario_id) == 1

    scenario_store.set_public_data_state(
        scenario_id,
        {"warnings": ["noop master-only update"]},
    )

    assert scenario_store.count_timetable_rows(scenario_id) == 1
    assert scenario_store.page_timetable_rows(scenario_id)[0]["trip_id"] == "trip-1"


def test_load_shallow_repairs_route_trip_counts_from_preload(tmp_path, monkeypatch) -> None:
    store_dir = tmp_path / "scenarios"
    monkeypatch.setattr(scenario_store, "_STORE_DIR", store_dir)

    scenario = scenario_store.create_scenario(
        name="Scenario 1",
        description="route metadata repair",
        mode="thesis_mode",
    )
    scenario_id = str(scenario["id"])

    scenario_store._save_master_subset(
        scenario_id,
        updates={
            "depots": [{"id": "dep-a", "name": "Depot A"}],
            "routes": [
                {
                    "id": "route-a",
                    "name": "黒０１",
                    "routeCode": "黒０１",
                    "tripCount": 587,
                }
            ],
            "vehicle_templates": [{"id": "tmpl-1"}],
            "route_depot_assignments": [{"routeId": "route-a", "depotId": "dep-a"}],
            "feed_context": {"datasetId": "tokyu_full"},
            "scenario_overlay": {"dataset_id": "tokyu_full"},
        },
        invalidate_dispatch=False,
    )

    monkeypatch.setattr(
        "bff.services.master_defaults.get_preloaded_master_data",
        lambda dataset_id: {
            "datasetId": dataset_id,
            "routes": [
                {
                    "id": "route-a",
                    "name": "黒０１",
                    "routeCode": "黒０１",
                    "tripCount": 495,
                    "tripCountTotal": 495,
                    "tripCountsByDayType": {
                        "WEEKDAY": 191,
                        "SAT": 152,
                        "SUN_HOL": 152,
                    },
                }
            ],
        },
    )

    route = scenario_store._load_shallow(scenario_id)["routes"][0]

    assert route["tripCount"] == 495
    assert route["tripCountTotal"] == 495
    assert route["tripCountsByDayType"] == {
        "WEEKDAY": 191,
        "SAT": 152,
        "SUN_HOL": 152,
    }


def test_timetable_rows_fall_back_to_tokyu_bus_data_when_artifacts_missing(
    tmp_path,
    monkeypatch,
) -> None:
    store_dir = tmp_path / "scenarios"
    monkeypatch.setattr(scenario_store, "_STORE_DIR", store_dir)

    scenario = scenario_store.create_scenario(
        name="Scenario 1",
        description="tokyu bus fallback",
        mode="thesis_mode",
    )
    scenario_id = str(scenario["id"])

    scenario_store._save_master_subset(
        scenario_id,
        updates={
            "depots": [{"id": "dep-a", "name": "Depot A"}],
            "routes": [{"id": "route-a", "name": "Route A", "routeCode": "A01"}],
            "vehicle_templates": [{"id": "tmpl-1"}],
            "route_depot_assignments": [{"routeId": "route-a", "depotId": "dep-a"}],
            "feed_context": {"datasetId": "tokyu_full"},
            "scenario_overlay": {"dataset_id": "tokyu_full"},
        },
        invalidate_dispatch=False,
    )

    monkeypatch.setattr(
        scenario_store,
        "_tokyu_bus_timetable_summary_for_doc",
        lambda doc, service_ids=None: {
            "totalRows": 5 if not service_ids else 3,
            "routeCount": 1,
            "byService": [{"serviceId": "WEEKDAY", "rowCount": 3, "routeCount": 1}],
            "imports": {},
        },
    )
    monkeypatch.setattr(
        scenario_store,
        "_tokyu_bus_timetable_rows_for_doc",
        lambda doc, service_ids=None: [
            {
                "trip_id": f"trip-{idx}",
                "route_id": "route-a",
                "service_id": "WEEKDAY",
                "departure": f"08:0{idx}",
                "arrival": f"08:3{idx}",
            }
            for idx in range(3)
        ],
    )
    monkeypatch.setattr(
        scenario_store,
        "_tokyu_bus_route_service_count_rows_for_doc",
        lambda doc: [
            {"route_id": "route-a", "service_id": "WEEKDAY", "trip_count": 3},
            {"route_id": "route-a", "service_id": "SAT", "trip_count": 2},
        ],
    )

    assert scenario_store.count_timetable_rows(scenario_id) == 5
    assert scenario_store.count_field_rows(scenario_id, "timetable_rows") == 5
    assert len(scenario_store.page_timetable_rows(scenario_id, limit=2)) == 2
    assert len(scenario_store.page_field_rows(scenario_id, "timetable_rows", limit=1)) == 1
    assert scenario_store.get_field_summary(scenario_id, "timetable_rows")["totalRows"] == 5
    assert scenario_store.summarize_route_service_trip_counts(scenario_id) == [
        {"route_id": "route-a", "service_id": "WEEKDAY", "trip_count": 3},
        {"route_id": "route-a", "service_id": "SAT", "trip_count": 2},
    ]


def test_scalar_artifact_falls_back_to_json_when_sqlite_is_locked(tmp_path, monkeypatch) -> None:
    store_dir = tmp_path / "scenarios"
    monkeypatch.setattr(scenario_store, "_STORE_DIR", store_dir)

    scenario = scenario_store.create_scenario(
        name="Scenario 1",
        description="scalar fallback",
        mode="thesis_mode",
    )
    scenario_id = str(scenario["id"])

    original_save_scalar = scenario_store.trip_store.save_scalar

    def _locked_save_scalar(db_path, name, value):
        if name == "optimization_result":
            raise sqlite3.OperationalError("database is locked")
        return original_save_scalar(db_path, name, value)

    monkeypatch.setattr(scenario_store.trip_store, "save_scalar", _locked_save_scalar)

    scenario_store.set_field(
        scenario_id,
        "optimization_result",
        {"solver_status": "OPTIMAL", "objective_value": 123.0},
    )

    refs = scenario_store.scenario_meta_store.default_refs(store_dir, scenario_id)
    optimization_json = scenario_store.trip_store.load_json(
        Path(refs["optimizationResult"]),
        None,
    )

    assert optimization_json == {"solver_status": "OPTIMAL", "objective_value": 123.0}
    assert scenario_store.get_field(scenario_id, "optimization_result") == {
        "solver_status": "OPTIMAL",
        "objective_value": 123.0,
    }
