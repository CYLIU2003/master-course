from __future__ import annotations

import copy
from unittest import mock

from bff.routers.simulation import PrepareSimulationBody, PrepareSimulationSettingsBody
from bff.services import simulation_builder


def test_prepare_simulation_settings_defaults_enable_route_band_and_diagrams() -> None:
    settings = PrepareSimulationSettingsBody()

    assert settings.fixed_route_band_mode is True
    assert settings.enable_vehicle_diagram_output is True


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
            cost_component_flags={
                "vehicle_fixed_cost": False,
                "driver_cost": True,
                "electricity_cost": False,
                "fuel_cost": True,
            },
            deadhead_speed_kmh=18.0,
            objective_preset="cost",
            planning_days=2,
            service_dates=["2025-08-01", "2025-08-02"],
            fixed_route_band_mode=True,
            milp_max_successors_per_trip=24,
            enable_vehicle_diagram_output=False,
            pv_profile_id="meguro_solcast_avg_2025_08_60min",
            weather_mode="solcast_avg_2025_08_60min",
            weather_factor_scalar=1.0,
            depot_energy_assets=[
                {
                    "depot_id": "dep1",
                    "bess_enabled": True,
                    "bess_energy_kwh": 500.0,
                }
            ],
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
    assert updated["scenario_overlay"]["solver_config"]["milp_max_successors_per_trip"] == 24
    assert updated["dispatch_scope"]["fixedRouteBandMode"] is True
    assert updated["dispatch_scope"]["allowIntraDepotRouteSwap"] is False
    assert updated["simulation_config"]["disable_vehicle_acquisition_cost"] is True
    assert updated["simulation_config"]["cost_component_flags"]["vehicle_fixed_cost"] is False
    assert updated["simulation_config"]["cost_component_flags"]["driver_cost"] is True
    assert updated["simulation_config"]["cost_component_flags"]["electricity_cost"] is False
    assert updated["simulation_config"]["cost_component_flags"]["fuel_cost"] is True
    assert updated["simulation_config"]["deadhead_speed_kmh"] == 18.0
    assert updated["simulation_config"]["objective_preset"] == "cost"
    assert updated["simulation_config"]["fixed_route_band_mode"] is True
    assert updated["simulation_config"]["milp_max_successors_per_trip"] == 24
    assert updated["simulation_config"]["enable_vehicle_diagram_output"] is True
    assert updated["simulation_config"]["planning_days"] == 2
    assert updated["simulation_config"]["service_dates"] == ["2025-08-01", "2025-08-02"]
    assert updated["simulation_config"]["planning_horizon_hours"] == 48.0
    assert updated["simulation_config"]["weather_mode"] == "solcast_avg_2025_08_60min"
    assert updated["simulation_config"]["pv_profile_id"] == "meguro_solcast_avg_2025_08_60min"
    assert updated["simulation_config"]["depot_energy_assets"] == [
        {
            "depot_id": "dep1",
            "bess_enabled": True,
            "bess_energy_kwh": 500.0,
        }
    ]
