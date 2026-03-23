from __future__ import annotations

import copy
from unittest import mock

from bff.routers.simulation import PrepareSimulationBody, PrepareSimulationSettingsBody
from bff.services import simulation_builder


def test_apply_builder_configuration_keeps_selected_routes_for_prepare_scope() -> None:
    scenario_doc = {
        "meta": {},
        "depots": [{"id": "dep1", "name": "Depot 1"}],
        "routes": [
            {"id": "route-a", "depotId": "dep1", "routeCode": "黒01"},
            {"id": "route-b", "depotId": "dep1", "routeCode": "黒02"},
        ],
        "vehicles": [
            {"id": "veh-1", "depotId": "dep1", "type": "BEV", "enabled": True}
        ],
        "chargers": [{"id": "chg-1", "siteId": "dep1", "powerKw": 90}],
        "vehicle_templates": [],
        "scenario_overlay": {},
        "simulation_config": {},
        "dispatch_scope": {},
        "calendar": [{"service_id": "WEEKDAY"}],
    }
    scenario_meta = {
        "datasetId": "tokyu_full",
        "datasetVersion": "v1",
        "operatorId": "tokyu",
        "randomSeed": 42,
    }
    body = PrepareSimulationBody(
        selected_depot_ids=["dep1"],
        selected_route_ids=["route-a"],
        day_type="WEEKDAY",
        simulation_settings=PrepareSimulationSettingsBody(
            use_selected_depot_vehicle_inventory=True,
            use_selected_depot_charger_inventory=True,
            disable_vehicle_acquisition_cost=True,
            deadhead_speed_kmh=18.0,
        ),
    )

    with (
        mock.patch.object(
            simulation_builder.store,
            "get_scenario_document_shallow",
            return_value=copy.deepcopy(scenario_doc),
        ),
        mock.patch.object(
            simulation_builder.store,
            "get_scenario",
            return_value=scenario_meta,
        ),
        mock.patch.object(
            simulation_builder.store,
            "route_ids_for_selected_depots",
            return_value=["route-a", "route-b"],
        ),
        mock.patch.object(simulation_builder.store, "_invalidate_dispatch_artifacts"),
        mock.patch.object(simulation_builder.store, "_save"),
        mock.patch.object(
            simulation_builder.store,
            "_now_iso",
            return_value="2026-03-22T00:00:00Z",
        ),
    ):
        updated = simulation_builder.apply_builder_configuration("scenario-1", body)

    assert updated["dispatch_scope"]["routeSelection"]["includeRouteIds"] == ["route-a"]
    assert updated["dispatch_scope"]["effectiveRouteIds"] == ["route-a"]
    assert updated["scenario_overlay"]["route_ids"] == ["route-a"]
    assert updated["simulation_config"]["disable_vehicle_acquisition_cost"] is True
    assert updated["simulation_config"]["deadhead_speed_kmh"] == 18.0
