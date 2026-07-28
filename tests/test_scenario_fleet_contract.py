from __future__ import annotations

import pytest

from src.optimization.common.fleet_contract import (
    FleetContractError,
    canonical_powertrain,
    parse_vehicle_available,
    resolve_scenario_fleet_contract,
)


def _bev(
    vehicle_id: str,
    *,
    depot_id: str = "A",
    vehicle_type: str = "BEV",
    enabled: object = True,
    initial_soc: float = 80.0,
) -> dict:
    return {
        "id": vehicle_id,
        "depotId": depot_id,
        "type": vehicle_type,
        "enabled": enabled,
        "initialSoc": initial_soc,
        "batteryKwh": 300.0,
        "energyConsumption": 1.2,
        "chargePowerKw": 90.0,
        "compatibleChargerIds": ["A-fast-1"],
    }


def _ice(
    vehicle_id: str,
    *,
    depot_id: str = "A",
    enabled: object = True,
) -> dict:
    return {
        "id": vehicle_id,
        "depotId": depot_id,
        "type": "ICE",
        "enabled": enabled,
        "initialFuelL": 180.0,
        "fuelTankL": 300.0,
        "fuelEfficiencyKmPerL": 5.0,
    }


@pytest.mark.parametrize(
    ("bev_count", "ice_count"),
    [(2, 1), (35, 25), (20, 0), (0, 12)],
)
def test_dynamic_inventory_is_derived_from_active_records(
    bev_count: int,
    ice_count: int,
) -> None:
    scenario = {
        "vehicles": [
            *[_bev(f"bev-{index}") for index in range(bev_count)],
            *[_ice(f"ice-{index}") for index in range(ice_count)],
        ]
    }

    contract = resolve_scenario_fleet_contract(
        scenario,
        selected_depot_ids=("A",),
        research_run=True,
    )

    expected = {}
    if bev_count:
        expected["BEV"] = bev_count
    if ice_count:
        expected["ICE"] = ice_count
    assert contract.inventory_by_powertrain == expected
    assert len(contract.active_vehicle_ids) == bev_count + ice_count
    assert contract.validation_status == "OK"


def test_zero_active_vehicle_set_fails_closed() -> None:
    with pytest.raises(FleetContractError, match="active_vehicle_set_is_empty"):
        resolve_scenario_fleet_contract(
            {"vehicles": [_bev("disabled", enabled=False)]},
            selected_depot_ids=("A",),
            research_run=True,
        )


def test_disabled_vehicle_is_excluded_with_reason_not_inventory_error() -> None:
    contract = resolve_scenario_fleet_contract(
        {"vehicles": [_bev("active"), _ice("maintenance", enabled="false")]},
        selected_depot_ids=("A",),
        research_run=True,
    )

    assert contract.active_vehicle_ids == ("active",)
    assert contract.excluded_vehicle_records == (
        {
            "vehicle_id": "maintenance",
            "reason": "enabled_false",
            "depot_id": "A",
        },
    )


def test_availability_field_is_honored_when_enabled_is_absent() -> None:
    vehicle = _bev("maintenance")
    vehicle.pop("enabled")
    vehicle["availability"] = "false"

    with pytest.raises(FleetContractError, match="active_vehicle_set_is_empty"):
        resolve_scenario_fleet_contract(
            {"vehicles": [vehicle]},
            selected_depot_ids=("A",),
            research_run=True,
        )


@pytest.mark.parametrize("value", [False, 0, "false", "0", "no", "off"])
def test_availability_false_tokens_are_false(value: object) -> None:
    assert parse_vehicle_available(value, research_run=True) is False


@pytest.mark.parametrize("value", [True, 1, "true", "1", "yes", "on"])
def test_availability_true_tokens_are_true(value: object) -> None:
    assert parse_vehicle_available(value, research_run=True) is True


def test_invalid_availability_token_fails_formal_contract() -> None:
    with pytest.raises(FleetContractError, match="explicit boolean token"):
        resolve_scenario_fleet_contract(
            {"vehicles": [_bev("bad", enabled="sometimes")]},
            selected_depot_ids=("A",),
            research_run=True,
        )


def test_conflicting_availability_fields_fail_formal_contract() -> None:
    vehicle = _bev("conflict", enabled=False)
    vehicle["available"] = True

    with pytest.raises(FleetContractError, match="conflicting"):
        resolve_scenario_fleet_contract(
            {"vehicles": [vehicle]},
            selected_depot_ids=("A",),
            research_run=True,
        )


@pytest.mark.parametrize(
    ("vehicles", "message"),
    [
        ([_bev("same"), _ice("SAME")], "duplicate_vehicle_id"),
        ([dict(_bev("x"), id="")], "missing_vehicle_id"),
        (
            [
                {
                    key: value
                    for key, value in _bev("x").items()
                    if key != "type"
                }
            ],
            "vehicle type is required",
        ),
    ],
)
def test_raw_identity_defects_fail_before_canonical_conversion(
    vehicles: list[dict],
    message: str,
) -> None:
    with pytest.raises(FleetContractError, match=message):
        resolve_scenario_fleet_contract(
            {"vehicles": vehicles},
            selected_depot_ids=("A",),
            research_run=True,
        )


@pytest.mark.parametrize("vehicle_type", ["EV", "ELECTRIC"])
def test_electric_aliases_use_one_canonical_powertrain(vehicle_type: str) -> None:
    contract = resolve_scenario_fleet_contract(
        {"vehicles": [_bev("electric", vehicle_type=vehicle_type)]},
        selected_depot_ids=("A",),
        research_run=True,
    )

    assert contract.inventory_by_powertrain == {"BEV": 1}


def test_model_specific_type_uses_catalog_powertrain() -> None:
    scenario = {
        "vehicleTypeCatalog": [{"id": "BYD_K8", "powertrain": "BEV"}],
        "vehicles": [_bev("byd", vehicle_type="BYD_K8")],
    }

    assert (
        canonical_powertrain(
            scenario["vehicles"][0],
            scenario,
            research_run=True,
        )
        == "BEV"
    )
    contract = resolve_scenario_fleet_contract(
        scenario,
        selected_depot_ids=("A",),
        research_run=True,
    )
    assert contract.inventory_by_powertrain == {"BEV": 1}


def test_catalog_supplies_vehicle_type_physical_parameters_and_hash_input() -> None:
    scenario = {
        "vehicleTypeCatalog": [
            {
                "id": "BYD_K8",
                "powertrain": "BEV",
                "batteryKwh": 300.0,
                "energyConsumption": 1.2,
                "chargePowerKw": 90.0,
                "compatibleChargerIds": ["A-fast-1"],
            }
        ],
        "vehicles": [
            {
                "id": "byd",
                "type": "BYD_K8",
                "depotId": "A",
                "enabled": True,
                "initialSoc": 80.0,
            }
        ],
    }

    contract = resolve_scenario_fleet_contract(
        scenario,
        selected_depot_ids=("A",),
        research_run=True,
    )

    parameters = contract.active_vehicle_parameters[0]
    assert parameters["battery_capacity_kwh"] == 300.0
    assert parameters["initial_soc"] == 240.0
    assert parameters["compatible_charger_ids"] == ["A-fast-1"]
    assert contract.active_vehicle_records[0]["powertrain"] == "BEV"
    assert contract.active_vehicle_records[0]["batteryKwh"] == 300.0


@pytest.mark.parametrize(
    ("vehicle", "message"),
    [
        (
            {
                key: value
                for key, value in _bev("bev-no-soc").items()
                if key != "initialSoc"
            },
            "missing_initial_soc",
        ),
        (
            {
                key: value
                for key, value in _bev("bev-no-compat").items()
                if key != "compatibleChargerIds"
            },
            "missing_charger_compatibility_declaration",
        ),
        (
            {
                key: value
                for key, value in _ice("ice-no-fuel").items()
                if key != "initialFuelL"
            },
            "missing_initial_fuel_l",
        ),
    ],
)
def test_formal_vehicle_state_and_compatibility_are_explicit(
    vehicle: dict,
    message: str,
) -> None:
    with pytest.raises(FleetContractError, match=message):
        resolve_scenario_fleet_contract(
            {"vehicles": [vehicle]},
            selected_depot_ids=("A",),
            research_run=True,
        )


def test_same_counts_but_different_ids_produce_different_contract_hash() -> None:
    first = resolve_scenario_fleet_contract(
        {"vehicles": [_bev("bev-1"), _ice("ice-1")]},
        selected_depot_ids=("A",),
        research_run=True,
    )
    second = resolve_scenario_fleet_contract(
        {"vehicles": [_bev("bev-2"), _ice("ice-2")]},
        selected_depot_ids=("A",),
        research_run=True,
    )

    assert first.inventory_by_powertrain == second.inventory_by_powertrain
    assert first.active_vehicle_id_hash != second.active_vehicle_id_hash
    assert first.fleet_contract_hash != second.fleet_contract_hash


def test_same_ids_but_different_initial_soc_changes_parameter_and_state_hash() -> None:
    first = resolve_scenario_fleet_contract(
        {"vehicles": [_bev("bev-1", initial_soc=80.0)]},
        selected_depot_ids=("A",),
        research_run=True,
    )
    second = resolve_scenario_fleet_contract(
        {"vehicles": [_bev("bev-1", initial_soc=70.0)]},
        selected_depot_ids=("A",),
        research_run=True,
    )

    assert first.active_vehicle_id_hash == second.active_vehicle_id_hash
    assert first.initial_state_hash != second.initial_state_hash
    assert first.vehicle_parameter_hash != second.vehicle_parameter_hash


def test_multiple_depots_without_selected_scope_fails() -> None:
    with pytest.raises(FleetContractError, match="selected_depot_ids_required"):
        resolve_scenario_fleet_contract(
            {"vehicles": [_bev("a", depot_id="A"), _bev("b", depot_id="B")]},
            selected_depot_ids=(),
            research_run=True,
        )


def test_selected_depot_contains_only_its_exact_active_set() -> None:
    contract = resolve_scenario_fleet_contract(
        {"vehicles": [_bev("a", depot_id="A"), _bev("b", depot_id="B")]},
        selected_depot_ids=("A",),
        research_run=True,
    )

    assert contract.selected_depot_ids == ("A",)
    assert contract.active_vehicle_ids == ("a",)


def test_count_only_input_is_not_silently_expanded_during_formal_run() -> None:
    with pytest.raises(FleetContractError, match="active_vehicle_set_is_empty"):
        resolve_scenario_fleet_contract(
            {"vehicle_counts": {"BEV": 2, "ICE": 1}},
            selected_depot_ids=("A",),
            research_run=True,
        )
