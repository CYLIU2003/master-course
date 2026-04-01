from __future__ import annotations

from unittest import mock

from bff.routers import scenarios
from tools.scenario_backup_tk import (
    _compose_saved_objective_weights,
    _split_saved_objective_weights,
)


def test_objective_weight_helpers_roundtrip_frontend_fields() -> None:
    saved = _compose_saved_objective_weights(
        {"switch_cost": 2.5, "utilization": 0.1},
        slack_penalty=123456.0,
        degradation_weight=0.25,
    )

    visible, slack_penalty, degradation_weight = _split_saved_objective_weights(saved)

    assert visible == {"switch_cost": 2.5, "utilization": 0.1}
    assert slack_penalty == 123456.0
    assert degradation_weight == 0.25


def test_build_quick_setup_payload_includes_saved_objective_weights() -> None:
    doc = {
        "depots": [{"id": "dep1", "name": "Depot 1"}],
        "routes": [
            {
                "id": "route-a",
                "depotId": "dep1",
                "routeCode": "黒01",
                "routeFamilyCode": "黒01",
                "name": "黒01",
                "tripCount": 3,
                "routeVariantType": "main_outbound",
            }
        ],
        "route_depot_assignments": [],
        "vehicles": [],
        "chargers": [],
        "vehicle_templates": [],
        "scenario_overlay": {
            "solver_config": {"objective_weights": {"battery_degradation_cost": 0.25}},
        },
        "simulation_config": {
            "objective_weights": {
                "switch_cost": 2.5,
                "slack_penalty": 123456.0,
                "degradation": 0.25,
            },
            "cost_component_flags": {
                "vehicle_fixed_cost": False,
                "driver_cost": True,
                "electricity_cost": False,
                "fuel_cost": True,
            },
        },
    }
    scenario = {
        "id": "scenario-1",
        "name": "Scenario 1",
        "operatorId": "tokyu",
        "datasetVersion": "v1",
        "datasetId": "tokyu_full",
        "status": "draft",
        "feedContext": {},
        "stats": {},
    }
    dispatch_scope = {
        "serviceId": "WEEKDAY",
        "effectiveRouteIds": ["route-a"],
        "depotSelection": {"depotIds": ["dep1"], "primaryDepotId": "dep1"},
        "routeSelection": {"mode": "refine", "includeRouteIds": [], "excludeRouteIds": []},
        "serviceSelection": {"serviceIds": ["WEEKDAY"]},
        "tripSelection": {"includeDeadhead": True},
    }

    payload = scenarios._build_quick_setup_payload(
        scenario,
        doc,
        dispatch_scope,
        selected_depot_ids=["dep1"],
        route_limit=20,
    )

    assert payload["simulationSettings"]["objectiveWeights"] == {
        "switch_cost": 2.5,
        "slack_penalty": 123456.0,
        "degradation": 0.25,
    }
    assert payload["simulationSettings"]["degradationWeight"] == 0.25
    assert payload["simulationSettings"]["costComponentFlags"]["vehicle_fixed_cost"] is False
    assert payload["simulationSettings"]["costComponentFlags"]["driver_cost"] is True
    assert payload["simulationSettings"]["costComponentFlags"]["electricity_cost"] is False
    assert payload["simulationSettings"]["costComponentFlags"]["fuel_cost"] is True


def test_update_quick_setup_persists_cost_component_toggles() -> None:
    current_scope = {
        "serviceId": "WEEKDAY",
        "depotSelection": {"depotIds": ["dep1"], "primaryDepotId": "dep1"},
        "routeSelection": {"mode": "refine", "includeRouteIds": ["route-a"], "excludeRouteIds": []},
        "serviceSelection": {"serviceIds": ["WEEKDAY"]},
        "tripSelection": {"includeDeadhead": True},
    }
    doc = {
        "depots": [{"id": "dep1", "name": "Depot 1"}],
        "routes": [{"id": "route-a", "depotId": "dep1", "routeCode": "黒01"}],
        "route_depot_assignments": [],
        "vehicles": [],
        "chargers": [],
        "vehicle_templates": [],
    }
    scenario = {
        "id": "scenario-1",
        "name": "Scenario 1",
        "operatorId": "tokyu",
        "datasetVersion": "v1",
        "datasetId": "tokyu_full",
        "status": "draft",
        "feedContext": {},
        "stats": {},
    }
    captured: dict[str, object] = {}

    def _capture_set_field(_scenario_id: str, field: str, value) -> None:
        captured[field] = value

    body = scenarios.UpdateQuickSetupBody(
        selectedDepotIds=["dep1"],
        selectedRouteIds=["route-a"],
        dayType="WEEKDAY",
        costComponentFlags={
            "vehicle_fixed_cost": False,
            "driver_cost": False,
            "electricity_cost": True,
            "fuel_cost": False,
        },
    )

    with (
        mock.patch.object(scenarios, "_ensure_runtime_master_data"),
        mock.patch.object(scenarios, "_quick_setup_route_selection_patch", return_value=current_scope["routeSelection"]),
        mock.patch.object(scenarios.store, "get_dispatch_scope", return_value=current_scope),
        mock.patch.object(scenarios.store, "get_scenario_document_shallow", return_value=doc),
        mock.patch.object(scenarios.store, "set_dispatch_scope", return_value=current_scope),
        mock.patch.object(scenarios.store, "get_scenario_overlay", return_value={}),
        mock.patch.object(scenarios.store, "get_field", return_value={}),
        mock.patch.object(scenarios.store, "set_scenario_overlay"),
        mock.patch.object(scenarios.store, "set_field", side_effect=_capture_set_field),
        mock.patch.object(scenarios.store, "get_scenario", return_value=scenario),
        mock.patch.object(scenarios, "_build_quick_setup_payload", return_value={"ok": True}),
    ):
        scenarios.update_quick_setup("scenario-1", body)

    simulation_config = captured["simulation_config"]
    assert isinstance(simulation_config, dict)
    assert simulation_config["cost_component_flags"]["vehicle_fixed_cost"] is False
    assert simulation_config["cost_component_flags"]["driver_cost"] is False
    assert simulation_config["cost_component_flags"]["electricity_cost"] is True
    assert simulation_config["cost_component_flags"]["fuel_cost"] is False
