from __future__ import annotations

import copy

import pytest

from bff.store import scenario_store


def _base_doc() -> dict[str, object]:
    return {
        "meta": {"id": "scenario-1", "updatedAt": "2026-04-16T00:00:00Z", "status": "draft"},
        "depots": [{"id": "dep-1"}],
        "vehicles": [
            {
                "id": "veh-1",
                "depotId": "dep-1",
                "type": "BEV",
                "modelName": "Vehicle-1",
                "energyConsumption": 1.2,
                "enabled": True,
            }
        ],
        "vehicle_templates": [{"id": "tpl-1", "name": "Template-1", "type": "BEV"}],
        "routes": [{"id": "route-1", "depotId": "dep-1"}],
        "stops": [],
        "route_depot_assignments": [],
        "depot_route_permissions": [],
        "vehicle_route_permissions": [{"vehicleId": "veh-1", "routeId": "route-1", "allowed": True}],
        "dispatch_scope": scenario_store._default_dispatch_scope(),
        "scenario_overlay": {},
        "calendar": [{"service_id": "WEEKDAY"}],
        "calendar_dates": [],
        "timetable_rows": [],
        "stop_timetables": [],
        "trips": None,
        "graph": None,
        "blocks": None,
        "duties": None,
        "dispatch_plan": None,
        "simulation_result": None,
        "optimization_result": None,
    }


def test_item_mutations_load_shallow_doc_under_scenario_lock(monkeypatch) -> None:
    scenario_id = "scenario-1"
    lock = scenario_store._scenario_lock(scenario_id)
    doc = _base_doc()
    observed_lock_state: list[bool] = []

    def _load_shallow_locked(sid: str, *, repair_route_metadata: bool = True) -> dict[str, object]:
        assert sid == scenario_id
        observed_lock_state.append(lock._is_owned())
        return doc

    monkeypatch.setattr(scenario_store, "_load_shallow", _load_shallow_locked)
    monkeypatch.setattr(scenario_store, "_save_master_subset", lambda *args, **kwargs: None)

    scenario_store._create_item(
        scenario_id,
        "vehicles",
        {
            "depotId": "dep-1",
            "type": "BEV",
            "modelName": "Vehicle-2",
            "energyConsumption": 1.1,
            "enabled": True,
        },
    )
    scenario_store._update_item(
        scenario_id,
        "vehicles",
        "id",
        "veh-1",
        {"modelName": "Vehicle-1-updated"},
    )
    scenario_store._delete_item(scenario_id, "vehicles", "id", "veh-1")

    assert observed_lock_state == [True, True, True]


@pytest.mark.parametrize(
    "operation",
    [
        "create_vehicle_batch",
        "duplicate_vehicle_batch",
        "delete_vehicle",
        "create_vehicle_template",
        "update_vehicle_template",
        "delete_vehicle_template",
    ],
)
def test_vehicle_mutation_paths_load_full_doc_under_lock(monkeypatch, operation: str) -> None:
    scenario_id = "scenario-1"
    lock = scenario_store._scenario_lock(scenario_id)
    doc = copy.deepcopy(_base_doc())
    observed_lock_state: list[bool] = []

    def _load_locked(sid: str, **kwargs) -> dict[str, object]:
        assert sid == scenario_id
        observed_lock_state.append(lock._is_owned())
        return doc

    monkeypatch.setattr(scenario_store, "_load", _load_locked)
    monkeypatch.setattr(scenario_store, "_save", lambda payload: None)

    if operation == "create_vehicle_batch":
        scenario_store.create_vehicle_batch(
            scenario_id,
            {
                "depotId": "dep-1",
                "type": "BEV",
                "modelName": "BatchVehicle",
                "energyConsumption": 1.0,
                "enabled": True,
            },
            quantity=2,
        )
    elif operation == "duplicate_vehicle_batch":
        scenario_store.duplicate_vehicle_batch(scenario_id, "veh-1", quantity=2)
    elif operation == "delete_vehicle":
        scenario_store.delete_vehicle(scenario_id, "veh-1")
    elif operation == "create_vehicle_template":
        scenario_store.create_vehicle_template(scenario_id, {"name": "New Template", "type": "BEV"})
    elif operation == "update_vehicle_template":
        scenario_store.update_vehicle_template(scenario_id, "tpl-1", {"name": "Updated Template"})
    elif operation == "delete_vehicle_template":
        scenario_store.delete_vehicle_template(scenario_id, "tpl-1")
    else:  # pragma: no cover
        raise AssertionError(f"Unexpected operation: {operation}")

    assert observed_lock_state == [True]


def test_set_dispatch_scope_loads_full_doc_under_lock(monkeypatch) -> None:
    scenario_id = "scenario-1"
    lock = scenario_store._scenario_lock(scenario_id)
    doc = copy.deepcopy(_base_doc())
    observed_lock_state: list[bool] = []

    def _load_locked(sid: str, **kwargs) -> dict[str, object]:
        assert sid == scenario_id
        observed_lock_state.append(lock._is_owned())
        return doc

    monkeypatch.setattr(scenario_store, "_load", _load_locked)
    monkeypatch.setattr(scenario_store, "_save", lambda payload: None)

    scenario_store.set_dispatch_scope(
        scenario_id,
        {
            "depotSelection": {
                "mode": "include",
                "depotIds": ["dep-1"],
                "primaryDepotId": "dep-1",
            },
            "routeSelection": {
                "mode": "include",
                "includeRouteIds": ["route-1"],
                "excludeRouteIds": [],
            },
            "fixedRouteBandMode": True,
        },
    )

    assert observed_lock_state == [True]


def test_set_field_simulation_config_loads_full_doc_under_lock(tmp_path, monkeypatch) -> None:
    store_dir = tmp_path / "scenarios"
    monkeypatch.setattr(scenario_store, "_STORE_DIR", store_dir)

    scenario = scenario_store.create_scenario(
        name="Atomic Set Field",
        description="lock test",
        mode="thesis_mode",
    )
    scenario_id = str(scenario["id"])
    lock = scenario_store._scenario_lock(scenario_id)
    observed_lock_state: list[bool] = []
    original_load = scenario_store._load

    def _load_locked(sid: str, **kwargs):
        if sid == scenario_id:
            observed_lock_state.append(lock._is_owned())
        return original_load(sid, **kwargs)

    monkeypatch.setattr(scenario_store, "_load", _load_locked)

    scenario_store.set_field(
        scenario_id,
        "simulation_config",
        {"objectiveMode": "total_cost"},
    )

    assert observed_lock_state and all(observed_lock_state)
    shallow = scenario_store.get_scenario_document_shallow(scenario_id)
    assert shallow.get("simulation_config") == {"objectiveMode": "total_cost"}
