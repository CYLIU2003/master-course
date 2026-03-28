from __future__ import annotations

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
            }
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
