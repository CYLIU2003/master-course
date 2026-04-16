from __future__ import annotations

import pytest
from fastapi import HTTPException

from bff.routers import master_data
from bff.store import scenario_store


def _base_store_doc() -> dict[str, object]:
    return {
        "meta": {"id": "scenario-1", "updatedAt": "2026-04-16T00:00:00Z", "status": "draft"},
        "depots": [
            {"id": "dep-1"},
            {"id": "tsurumaki"},
            {"id": "seta"},
        ],
        "vehicles": [],
        "routes": [],
        "dispatch_scope": {},
        "depot_route_permissions": [],
        "vehicle_route_permissions": [],
    }


def test_create_vehicle_with_canonical_depot_id_is_visible_in_depot_filtered_list(monkeypatch) -> None:
    doc = _base_store_doc()

    monkeypatch.setattr(scenario_store, "_load_shallow", lambda scenario_id: doc)
    monkeypatch.setattr(scenario_store, "_save_master_subset", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        scenario_store,
        "_list_items",
        lambda scenario_id, field: list(doc[field]),
    )

    created = scenario_store.create_vehicle(
        "scenario-1",
        {
            "id": "veh-1",
            "depotId": "dep-1",
            "type": "BEV",
            "modelName": "UnitTest BEV",
            "energyConsumption": 1.2,
            "enabled": True,
        },
    )

    listed = scenario_store.list_vehicles("scenario-1", depot_id="dep-1")

    assert created["depotId"] == "dep-1"
    assert [item.get("id") for item in listed] == ["veh-1"]


def test_create_vehicle_normalizes_label_style_depot_id_to_canonical_id(monkeypatch) -> None:
    doc = _base_store_doc()

    monkeypatch.setattr(scenario_store, "_load_shallow", lambda scenario_id: doc)
    monkeypatch.setattr(scenario_store, "_save_master_subset", lambda *args, **kwargs: None)

    created = scenario_store.create_vehicle(
        "scenario-1",
        {
            "id": "veh-2",
            "depotId": "tsurumaki | 鶴巻営業所",
            "type": "BEV",
            "modelName": "UnitTest BEV 2",
            "energyConsumption": 1.2,
            "enabled": True,
        },
    )

    assert created["depotId"] == "tsurumaki"
    assert doc["vehicles"][0]["depotId"] == "tsurumaki"


def test_create_vehicle_batch_normalizes_label_style_depot_id(monkeypatch) -> None:
    doc = _base_store_doc()

    monkeypatch.setattr(scenario_store, "_load", lambda scenario_id, **kwargs: doc)
    monkeypatch.setattr(scenario_store, "_save", lambda payload: None)

    created = scenario_store.create_vehicle_batch(
        "scenario-1",
        {
            "depotId": "tsurumaki | 鶴巻営業所",
            "type": "BEV",
            "modelName": "TemplateVehicle",
            "energyConsumption": 1.2,
            "enabled": True,
        },
        quantity=2,
    )

    assert len(created) == 2
    assert all(item["depotId"] == "tsurumaki" for item in created)
    assert all(item["depotId"] == "tsurumaki" for item in doc["vehicles"])


def test_create_vehicle_endpoint_returns_422_for_unknown_depot_id(monkeypatch) -> None:
    monkeypatch.setattr(master_data, "_check_scenario", lambda scenario_id: None)

    def _raise_unknown_depot(scenario_id: str, payload: dict[str, object]) -> dict[str, object]:
        raise ValueError("Unknown depotId 'unknown-depot'")

    monkeypatch.setattr(master_data.store, "create_vehicle", _raise_unknown_depot)

    with pytest.raises(HTTPException) as exc_info:
        master_data.create_vehicle(
            "scenario-1",
            master_data.CreateVehicleBody(depotId="unknown-depot"),
        )

    assert exc_info.value.status_code == 422
    assert "Unknown depotId" in str(exc_info.value.detail)
