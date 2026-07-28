from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from bff.routers.optimization import (
    _apply_interactive_bev_utilization_policy,
    _apply_interactive_research_contract,
)
from bff.services.optimization_run.rolling_chain import (
    persist_frontend_day_ahead_rolling_contract,
)
from src.optimization import OptimizationConfig, ProblemBuilder
from src.optimization.common.fleet_contract import (
    resolve_scenario_fleet_contract,
)


def _scenario() -> dict:
    return {
        "meta": {"id": "frontend-formal-contract-parity"},
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
        "depots": [{"id": "depot-a", "name": "Depot A"}],
        "routes": [{"id": "route-a"}],
        "chargers": [
            {
                "id": "charger-a",
                "depotId": "depot-a",
                "powerKw": 90.0,
                "ports": 1,
            }
        ],
        "timetable_rows": [
            {
                "trip_id": "odpt.BusTimetable:Example.Weekday.0800",
                "route_id": "route-a",
                "origin": "stop-a",
                "destination": "stop-b",
                "departure": "08:00",
                "arrival": "08:30",
                "distance_km": 5.0,
                "service_id": "WEEKDAY",
                "allowed_vehicle_types": ["BEV", "ICE"],
                "operator_id": "operator-a",
            }
        ],
        "simulation_config": {"service_date": "2025-08-05"},
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


def test_problem_builder_preserves_exact_fleet_contract_for_rolling(
    tmp_path: Path,
) -> None:
    scenario = _scenario()
    expected = resolve_scenario_fleet_contract(
        deepcopy(scenario),
        selected_depot_ids=("depot-a",),
        research_run=True,
    )

    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id="depot-a",
        service_id="WEEKDAY",
        config=OptimizationConfig(research_run=True),
    )

    contract = problem.metadata["scenario_fleet_contract"]
    assert contract == expected.to_dict(include_source_records=True)
    assert contract["schema_version"] == "scenario_fleet_contract_v2"
    assert problem.metadata["scenario_fleet_contract_hash"] == (
        expected.fleet_contract_hash
    )
    assert problem.metadata["research_fleet_validation"]["status"] == "OK"
    assert problem.metadata["research_fleet_validation"]["fleet_contract_hash"] == (
        expected.fleet_contract_hash
    )

    prepared_path = tmp_path / "prepared.json"
    prepared_path.write_text('{"prepared_input_id":"prepared-1"}', encoding="utf-8")
    (tmp_path / "canonical_solver_result.json").write_text(
        '{"feasible":true}',
        encoding="utf-8",
    )
    (tmp_path / "summary.json").write_text(
        '{"scenario_id":"frontend-formal-contract-parity"}',
        encoding="utf-8",
    )
    audit = persist_frontend_day_ahead_rolling_contract(
        run_dir=tmp_path,
        scenario=scenario,
        problem=problem,
        prepared_input_path=prepared_path,
        scenario_id="frontend-formal-contract-parity",
        prepared_input_id="prepared-1",
        service_id="WEEKDAY",
        git_state={
            "git_sha": "abc123",
            "git_dirty": False,
            "git_state_available": True,
        },
    )

    persisted_contract = json.loads(
        (tmp_path / "scenario_fleet_contract.json").read_text(encoding="utf-8")
    )
    assert persisted_contract == expected.to_dict(include_source_records=True)
    assert audit["scenario_fleet_contract_hash"] == expected.fleet_contract_hash


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
