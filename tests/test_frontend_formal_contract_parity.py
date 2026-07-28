from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from bff.routers.optimization import (
    _apply_interactive_bev_utilization_policy,
    _apply_interactive_research_contract,
)
from src.optimization.common.fleet_contract import (
    resolve_scenario_fleet_contract,
)


def _scenario() -> dict:
    return {
        "vehicles": [
            {
                "id": "bev-a",
                "type": "EV",
                "depotId": "depot-a",
                "enabled": True,
                "initialSoc": 80.0,
                "batteryKwh": 300.0,
                "energyConsumption": 1.2,
                "chargePowerKw": 90.0,
                "compatibleChargerIds": ["charger-a"],
            },
            {
                "id": "ice-a",
                "type": "DIESEL",
                "depotId": "depot-a",
                "enabled": True,
                "initialFuelL": 100.0,
                "fuelTankL": 200.0,
                "fuelEfficiencyKmPerL": 5.0,
            },
            {
                "id": "ice-maintenance",
                "type": "ICE",
                "depotId": "depot-a",
                "enabled": "false",
                "initialFuelL": 100.0,
                "fuelTankL": 200.0,
                "fuelEfficiencyKmPerL": 5.0,
            },
        ],
        "simulation_config": {},
        "scenario_overlay": {"solver_config": {}},
    }


def test_frontend_contract_is_the_shared_scenario_fleet_contract() -> None:
    scenario = _scenario()
    expected = resolve_scenario_fleet_contract(
        deepcopy(scenario),
        selected_depot_ids=("depot-a",),
        research_run=True,
    )

    audit = _apply_interactive_research_contract(
        scenario,
        research_run=True,
        depot_id="depot-a",
    )

    simulation = scenario["simulation_config"]
    assert audit["expected_available_inventory"] == {"BEV": 1, "ICE": 1}
    assert audit["active_vehicle_ids"] == list(expected.active_vehicle_ids)
    assert audit["fleet_contract_hash"] == expected.fleet_contract_hash
    assert simulation["research_vehicle_id_hash"] == (
        expected.active_vehicle_id_hash
    )
    assert simulation["research_vehicle_parameter_hash"] == (
        expected.vehicle_parameter_hash
    )
    assert simulation["research_vehicle_initial_state_hash"] == (
        expected.initial_state_hash
    )
    assert simulation["scenario_fleet_contract"]["excluded_vehicle_records"] == [
        {
            "vehicle_id": "ice-maintenance",
            "reason": "enabled_false",
            "depot_id": "depot-a",
        }
    ]
    assert simulation["scenario_fleet_contract"][
        "active_vehicle_parameters"
    ][0]["source_record"]["id"] == "bev-a"


def test_all_available_bev_policy_uses_canonical_powertrain_not_type_label() -> None:
    problem = SimpleNamespace(
        vehicles=(
            SimpleNamespace(
                vehicle_id="bev-a",
                vehicle_type="BYD_K8",
                available=True,
            ),
            SimpleNamespace(
                vehicle_id="ice-a",
                vehicle_type="DIESEL_LARGE",
                available=True,
            ),
        ),
        vehicle_types=(
            SimpleNamespace(
                vehicle_type_id="BYD_K8",
                powertrain_type="BEV",
            ),
            SimpleNamespace(
                vehicle_type_id="DIESEL_LARGE",
                powertrain_type="ICE",
            ),
        ),
        metadata={},
    )

    policy = _apply_interactive_bev_utilization_policy(
        problem,
        require_all_available_bevs=True,
    )

    assert policy["available_bev_ids"] == ["bev-a"]
    assert policy["minimum_used_bev_count"] == 1
    assert problem.metadata["minimum_used_bev_vehicle_ids"] == ["bev-a"]
