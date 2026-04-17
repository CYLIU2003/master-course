from __future__ import annotations

import pytest

from pydantic import ValidationError

from bff.routers import master_data


def _patch_runtime(monkeypatch) -> None:
    monkeypatch.setattr(master_data.store, "get_scenario", lambda scenario_id: {"id": scenario_id})
    monkeypatch.setattr(master_data.store, "ensure_runtime_master_data", lambda scenario_id: None)


def test_create_vehicle_accepts_initial_soc_and_clears_it_for_ice(monkeypatch) -> None:
    _patch_runtime(monkeypatch)
    captured: dict[str, object] = {}

    def _capture_create_vehicle(scenario_id: str, payload: dict[str, object]) -> dict[str, object]:
        captured["scenario_id"] = scenario_id
        captured["payload"] = dict(payload)
        return {"id": "veh-1", **payload}

    monkeypatch.setattr(master_data.store, "create_vehicle", _capture_create_vehicle)

    master_data.create_vehicle(
        "scenario-1",
        master_data.CreateVehicleBody(depotId="dep-1", type="BEV", initialSoc=0.75),
    )
    bev_payload = captured["payload"]
    assert isinstance(bev_payload, dict)
    assert bev_payload["initialSoc"] == 0.75
    assert bev_payload["type"] == "BEV"

    master_data.create_vehicle(
        "scenario-1",
        master_data.CreateVehicleBody(depotId="dep-1", type="ICE", initialSoc=0.75),
    )
    ice_payload = captured["payload"]
    assert isinstance(ice_payload, dict)
    assert ice_payload["initialSoc"] is None
    assert ice_payload["batteryKwh"] is None


def test_create_vehicle_batch_forwards_initial_soc(monkeypatch) -> None:
    _patch_runtime(monkeypatch)
    captured: dict[str, object] = {}

    def _capture_create_vehicle_batch(
        scenario_id: str,
        payload: dict[str, object],
        quantity: int,
    ) -> list[dict[str, object]]:
        captured["scenario_id"] = scenario_id
        captured["payload"] = dict(payload)
        captured["quantity"] = quantity
        return [{"id": "veh-1", **payload}]

    monkeypatch.setattr(master_data.store, "create_vehicle_batch", _capture_create_vehicle_batch)

    master_data.create_vehicle_batch(
        "scenario-1",
        master_data.CreateVehicleBatchBody(depotId="dep-1", type="BEV", initialSoc=0.6, quantity=2),
    )

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["initialSoc"] == 0.6
    assert captured["quantity"] == 2


def test_update_vehicle_preserves_explicit_null_initial_soc(monkeypatch) -> None:
    _patch_runtime(monkeypatch)
    monkeypatch.setattr(
        master_data.store,
        "get_vehicle",
        lambda scenario_id, vehicle_id: {"id": vehicle_id, "depotId": "dep-1", "type": "BEV", "initialSoc": 0.8},
    )
    captured: dict[str, object] = {}

    def _capture_update_vehicle(scenario_id: str, vehicle_id: str, patch: dict[str, object]) -> dict[str, object]:
        captured["scenario_id"] = scenario_id
        captured["vehicle_id"] = vehicle_id
        captured["patch"] = dict(patch)
        return {"id": vehicle_id, **patch}

    monkeypatch.setattr(master_data.store, "update_vehicle", _capture_update_vehicle)

    master_data.update_vehicle(
        "scenario-1",
        "veh-1",
        master_data.UpdateVehicleBody(modelName="Updated", initialSoc=None),
    )

    patch = captured["patch"]
    assert isinstance(patch, dict)
    assert patch["initialSoc"] is None
    assert patch["modelName"] == "Updated"


def test_update_vehicle_clears_initial_soc_for_ice(monkeypatch) -> None:
    _patch_runtime(monkeypatch)
    monkeypatch.setattr(
        master_data.store,
        "get_vehicle",
        lambda scenario_id, vehicle_id: {"id": vehicle_id, "depotId": "dep-1", "type": "BEV", "initialSoc": 0.8},
    )
    captured: dict[str, object] = {}

    def _capture_update_vehicle(scenario_id: str, vehicle_id: str, patch: dict[str, object]) -> dict[str, object]:
        captured["patch"] = dict(patch)
        return {"id": vehicle_id, **patch}

    monkeypatch.setattr(master_data.store, "update_vehicle", _capture_update_vehicle)

    master_data.update_vehicle(
        "scenario-1",
        "veh-1",
        master_data.UpdateVehicleBody(type="ICE", initialSoc=0.65),
    )

    patch = captured["patch"]
    assert isinstance(patch, dict)
    assert patch["initialSoc"] is None
    assert patch["batteryKwh"] is None


def test_vehicle_initial_soc_validation_rejects_out_of_range_values() -> None:
    with pytest.raises(ValidationError):
        master_data.CreateVehicleBody(depotId="dep-1", initialSoc=1.2)

    with pytest.raises(ValidationError):
        master_data.UpdateVehicleBody(initialSoc=-0.1)
