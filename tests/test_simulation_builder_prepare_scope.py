from __future__ import annotations

import copy
from unittest import mock

import pytest

from bff.routers.simulation import PrepareSimulationBody, PrepareSimulationSettingsBody
from bff.services import simulation_builder


def test_prepare_simulation_settings_defaults_enable_diagrams() -> None:
    settings = PrepareSimulationSettingsBody()

    # fixed_route_band_mode defaults to False (opt-in); matches SolverConfig default
    assert settings.fixed_route_band_mode is False
    assert settings.enable_vehicle_diagram_output is True
    assert settings.operation_time_window_enabled is False
    assert settings.start_time == "00:00"
    assert settings.end_time == "23:59"
    assert settings.planning_horizon_hours == 24.0


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
            enable_weather_operation_policy=True,
            weather_proxy_forecast_path="data/weather/proxy_forecasts/tokyo.json",
            weather_proxy_daily_csv_path="data/weather/processed/tokyo.csv",
            weather_proxy_station_id="44132",
            weather_proxy_station_name="東京",
            pv_marginal_charge_cost_yen_per_kwh=4.25,
            pv_curtail_penalty_yen_per_kwh=7.5,
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
    assert updated["simulation_config"]["enable_weather_operation_policy"] is True
    assert updated["simulation_config"]["weather_proxy_forecast_path"] == "data/weather/proxy_forecasts/tokyo.json"
    assert updated["simulation_config"]["weather_proxy_daily_csv_path"] == "data/weather/processed/tokyo.csv"
    assert updated["simulation_config"]["weather_proxy_station_id"] == "44132"
    assert updated["simulation_config"]["weather_proxy_station_name"] == "東京"
    assert updated["simulation_config"]["pv_marginal_charge_cost_yen_per_kwh"] == 4.25
    assert updated["scenario_overlay"]["cost_coefficients"]["pv_marginal_charge_cost_yen_per_kwh"] == 4.25
    assert updated["simulation_config"]["pv_curtail_penalty_yen_per_kwh"] == 7.5
    assert updated["scenario_overlay"]["cost_coefficients"]["pv_curtail_penalty_yen_per_kwh"] == 7.5
    assert updated["scenario_overlay"]["depot_energy_assets"] == {
        "dep1": {
            "depot_id": "dep1",
            "bess_enabled": True,
            "bess_energy_kwh": 500.0,
        }
    }
    assert updated["simulation_config"]["depot_energy_assets"] == [
        {
            "depot_id": "dep1",
            "bess_enabled": True,
            "bess_energy_kwh": 500.0,
        }
    ]


def test_apply_builder_configuration_migrates_legacy_fixed_weekday_marker() -> None:
    scenario_doc = {
        "meta": {},
        "depots": [{"id": "dep1", "name": "Depot 1"}],
        "routes": [{"id": "route-a", "depotId": "dep1", "routeCode": "A-1"}],
        "vehicles": [
            {"id": "veh-1", "depotId": "dep1", "type": "BEV", "enabled": True}
        ],
        "chargers": [{"id": "chg-1", "siteId": "dep1", "powerKw": 90}],
        "vehicle_templates": [],
        "scenario_overlay": {},
        "simulation_config": {
            "service_date": "2025-08-10",
            "service_dates": ["2025-08-10"],
            "weather_mode": "actual_date_profile",
            "allow_fixed_weekday_timetable_pv_counterfactual": True,
            "calendar_policy": "fixed_weekday_timetable_pv_counterfactual",
            "comparison_type": "fixed_weekday_timetable_pv_counterfactual",
            "comparison_role": "pv_curve_counterfactual",
            "counterfactual_pv_source_date": "2025-08-10",
        },
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
            service_date="2025-08-10",
            service_dates=["2025-08-10"],
            weather_mode="actual_date_profile",
            allow_fixed_weekday_timetable_pv_counterfactual=True,
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
            return_value=["route-a"],
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

    simulation_config = updated["simulation_config"]
    assert simulation_config["service_date"] == "2025-08-10"
    assert simulation_config["service_dates"] == ["2025-08-10"]
    assert simulation_config["allow_fixed_weekday_timetable_pv_counterfactual"] is True
    assert (
        simulation_config["calendar_policy"]
        == "fixed_weekday_timetable_pv_counterfactual"
    )
    assert simulation_config["comparison_type"] is None
    assert simulation_config["comparison_role"] is None
    assert simulation_config["counterfactual_pv_source_date"] is None
    assert simulation_config["weather_observation_date"] == "2025-08-10"

    explicit_invalid_body = body.model_copy(deep=True)
    explicit_invalid_body.simulation_settings.comparison_type = (
        "fixed_weekday_timetable_pv_counterfactual"
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
            return_value=["route-a"],
        ),
    ):
        with pytest.raises(
            ValueError,
            match="comparison_type must be",
        ):
            simulation_builder.apply_builder_configuration(
                "scenario-1",
                explicit_invalid_body,
            )


def test_apply_builder_configuration_separates_service_and_pv_source_dates() -> None:
    scenario_doc = {
        "meta": {},
        "depots": [{"id": "dep1", "name": "Depot 1"}],
        "routes": [
            {"id": "route-a", "depotId": "dep1", "routeCode": "A-1"}
        ],
        "vehicles": [
            {
                "id": "veh-1",
                "depotId": "dep1",
                "type": "BEV",
                "enabled": True,
            }
        ],
        "chargers": [
            {"id": "chg-1", "siteId": "dep1", "powerKw": 90}
        ],
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
        service_date="2025-08-05",
        simulation_settings=PrepareSimulationSettingsBody(
            service_date="2025-08-05",
            service_dates=["2025-08-05"],
            pv_profile_id="dep1_2025-08-10_60min",
            comparison_type="same_service_date_pv_counterfactual",
            comparison_role="pv_curve_counterfactual",
            counterfactual_pv_source_date="2025-08-10",
            allow_fixed_weekday_timetable_pv_counterfactual=True,
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
            return_value=["route-a"],
        ),
        mock.patch.object(
            simulation_builder.store,
            "_invalidate_dispatch_artifacts",
        ),
        mock.patch.object(simulation_builder.store, "_save"),
        mock.patch.object(
            simulation_builder.store,
            "_now_iso",
            return_value="2026-07-29T00:00:00Z",
        ),
    ):
        updated = simulation_builder.apply_builder_configuration(
            "scenario-1",
            body,
        )

    simulation_config = updated["simulation_config"]
    assert simulation_config["service_date"] == "2025-08-05"
    assert simulation_config["comparison_type"] == (
        "same_service_date_pv_counterfactual"
    )
    assert simulation_config["comparison_role"] == "pv_curve_counterfactual"
    assert simulation_config["counterfactual_pv_source_date"] == "2025-08-10"
    assert simulation_config["weather_observation_date"] == "2025-08-10"
    assert simulation_config["weather_profile_source"] == (
        "dep1_2025-08-10_60min"
    )


def test_counterfactual_prepare_requires_explicit_fixed_timetable_permission() -> None:
    body = PrepareSimulationBody(
        selected_depot_ids=["dep1"],
        selected_route_ids=["route-a"],
        day_type="WEEKDAY",
        service_date="2025-08-05",
        simulation_settings=PrepareSimulationSettingsBody(
            service_date="2025-08-05",
            service_dates=["2025-08-05"],
            comparison_type="same_service_date_pv_counterfactual",
            comparison_role="pv_curve_counterfactual",
            counterfactual_pv_source_date="2025-08-10",
            allow_fixed_weekday_timetable_pv_counterfactual=False,
        ),
    )
    scenario_doc = {
        "meta": {},
        "depots": [{"id": "dep1", "name": "Depot 1"}],
        "routes": [
            {"id": "route-a", "depotId": "dep1", "routeCode": "A-1"}
        ],
        "vehicles": [
            {
                "id": "veh-1",
                "depotId": "dep1",
                "type": "BEV",
                "enabled": True,
            }
        ],
        "chargers": [
            {"id": "chg-1", "siteId": "dep1", "powerKw": 90}
        ],
        "vehicle_templates": [],
        "scenario_overlay": {},
        "simulation_config": {},
        "dispatch_scope": {},
        "calendar": [{"service_id": "WEEKDAY"}],
    }

    with (
        mock.patch.object(
            simulation_builder.store,
            "get_scenario_document_shallow",
            return_value=scenario_doc,
        ),
        mock.patch.object(
            simulation_builder.store,
            "get_scenario",
            return_value={
                "datasetId": "tokyu_full",
                "datasetVersion": "v1",
                "operatorId": "tokyu",
                "randomSeed": 42,
            },
        ),
        mock.patch.object(
            simulation_builder.store,
            "route_ids_for_selected_depots",
            return_value=["route-a"],
        ),
    ):
        with pytest.raises(
            ValueError,
            match="allow_fixed_weekday_timetable_pv_counterfactual=true",
        ):
            simulation_builder.apply_builder_configuration(
                "scenario-1",
                body,
            )


def test_counterfactual_prepare_rejects_truncated_source_datetime() -> None:
    body = PrepareSimulationBody(
        selected_depot_ids=["dep1"],
        selected_route_ids=["route-a"],
        day_type="WEEKDAY",
        service_date="2025-08-05",
        simulation_settings=PrepareSimulationSettingsBody(
            service_date="2025-08-05",
            service_dates=["2025-08-05"],
            comparison_type="same_service_date_pv_counterfactual",
            comparison_role="pv_curve_counterfactual",
            counterfactual_pv_source_date="2025-08-10T12:00:00",
            allow_fixed_weekday_timetable_pv_counterfactual=True,
        ),
    )
    scenario_doc = {
        "meta": {},
        "depots": [{"id": "dep1", "name": "Depot 1"}],
        "routes": [
            {"id": "route-a", "depotId": "dep1", "routeCode": "A-1"}
        ],
        "vehicles": [
            {
                "id": "veh-1",
                "depotId": "dep1",
                "type": "BEV",
                "enabled": True,
            }
        ],
        "chargers": [
            {"id": "chg-1", "siteId": "dep1", "powerKw": 90}
        ],
        "vehicle_templates": [],
        "scenario_overlay": {},
        "simulation_config": {},
        "dispatch_scope": {},
        "calendar": [{"service_id": "WEEKDAY"}],
    }

    with (
        mock.patch.object(
            simulation_builder.store,
            "get_scenario_document_shallow",
            return_value=scenario_doc,
        ),
        mock.patch.object(
            simulation_builder.store,
            "get_scenario",
            return_value={
                "datasetId": "tokyu_full",
                "datasetVersion": "v1",
                "operatorId": "tokyu",
                "randomSeed": 42,
            },
        ),
        mock.patch.object(
            simulation_builder.store,
            "route_ids_for_selected_depots",
            return_value=["route-a"],
        ),
    ):
        with pytest.raises(
            ValueError,
            match="counterfactual_pv_source_date must be YYYY-MM-DD",
        ):
            simulation_builder.apply_builder_configuration(
                "scenario-1",
                body,
            )


def test_apply_builder_configuration_preserves_explicit_vehicle_initial_soc() -> None:
    scenario_doc = {
        "meta": {},
        "depots": [{"id": "dep1", "name": "Depot 1"}],
        "routes": [{"id": "route-a", "depotId": "dep1", "routeCode": "黒01"}],
        "vehicles": [
            {
                "id": "veh-1",
                "depotId": "dep1",
                "type": "BEV",
                "enabled": True,
                "initialSoc": 0.55,
            }
        ],
        "chargers": [{"id": "chg-1", "siteId": "dep1", "powerKw": 90}],
        "vehicle_templates": [],
        "scenario_overlay": {},
        "simulation_config": {"initial_soc": 0.8},
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
            return_value=["route-a"],
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

    assert updated["vehicles"][0]["initialSoc"] == 0.55
    assert updated["simulation_config"]["initial_soc"] == 0.8


def test_apply_builder_configuration_forces_fixed_route_band_when_intra_swap_is_disabled() -> None:
    scenario_doc = {
        "meta": {},
        "depots": [{"id": "dep1", "name": "Depot 1"}],
        "routes": [{"id": "route-a", "depotId": "dep1", "routeCode": "黒01"}],
        "vehicles": [{"id": "veh-1", "depotId": "dep1", "type": "BEV", "enabled": True}],
        "chargers": [{"id": "chg-1", "siteId": "dep1", "powerKw": 90}],
        "vehicle_templates": [],
        "scenario_overlay": {},
        "simulation_config": {},
        "dispatch_scope": {
            "allowIntraDepotRouteSwap": False,
            "fixedRouteBandMode": False,
        },
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
        allow_intra_depot_route_swap=False,
        simulation_settings=PrepareSimulationSettingsBody(
            use_selected_depot_vehicle_inventory=True,
            use_selected_depot_charger_inventory=True,
            fixed_route_band_mode=False,
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
            return_value=["route-a"],
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

    assert updated["dispatch_scope"]["allowIntraDepotRouteSwap"] is False
    assert updated["dispatch_scope"]["fixedRouteBandMode"] is True
    assert updated["simulation_config"]["fixed_route_band_mode"] is True
    assert updated["scenario_overlay"]["solver_config"]["fixed_route_band_mode"] is True
