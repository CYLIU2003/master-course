from __future__ import annotations

from unittest import mock

import pytest
from pydantic import ValidationError

from bff.routers import scenarios
from bff.routers.simulation import PrepareSimulationSettingsBody
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


def test_build_quick_setup_payload_includes_saved_controls_and_zeroes() -> None:
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
            "solver_config": {
                "objective_weights": {"battery_degradation_cost": 0.25},
                "mip_gap": 0.0,
            },
            "cost_coefficients": {
                "grid_flat_price_per_kwh": 0.0,
                "grid_sell_price_per_kwh": 0.0,
                "demand_charge_cost_per_kw": 0.0,
                "diesel_price_per_l": 0.0,
                "grid_co2_kg_per_kwh": 0.0,
                "co2_price_per_kg": 0.0,
                "ice_co2_kg_per_l": 0.0,
                "pv_marginal_charge_cost_yen_per_kwh": 3.5,
                "pv_curtail_penalty_yen_per_kwh": 6.5,
                "vehicle_usage_cost_jpy_per_used_bus": 30000.0,
                "vehicle_usage_cost_semantics": "fixed_vehicle_day_cost",
            },
            "charging_constraints": {"depot_power_limit_kw": 0.0},
        },
        "simulation_config": {
            "service_date": "2025-08-10",
            "random_seed": 0,
            "unserved_penalty": 0.0,
            "initial_ice_fuel_percent": 0.0,
            "min_ice_fuel_percent": 0.0,
            "max_ice_fuel_percent": 0.0,
            "default_ice_tank_capacity_l": 0.0,
            "deadhead_speed_kmh": 18.0,
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
            "operation_time_window_enabled": False,
            "enable_weather_operation_policy": True,
            "allow_fixed_weekday_timetable_pv_counterfactual": True,
            "comparison_type": "fixed_weekday_timetable_pv_counterfactual",
            "comparison_role": "pv_curve_counterfactual",
            "counterfactual_pv_source_date": "2025-08-10",
            "weather_proxy_forecast_path": "data/weather/proxy_forecasts/old.json",
            "weather_proxy_daily_csv_path": "data/weather/processed/tokyo.csv",
            "weather_proxy_station_id": "44132",
            "weather_proxy_station_name": "東京",
            "solcast_proxy_issue_date": "2025-08-09",
            "solcast_typical_curve_path": "data/weather/processed/typical.json",
            "solcast_typical_weather_class": "cloudy",
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
    assert payload["simulationSettings"]["operationTimeWindowEnabled"] is False
    assert payload["simulationSettings"]["enableWeatherOperationPolicy"] is True
    assert (
        payload["simulationSettings"]["allowFixedWeekdayTimetablePvCounterfactual"]
        is True
    )
    assert payload["simulationSettings"]["weatherProxyForecastPath"] == "data/weather/proxy_forecasts/old.json"
    assert payload["simulationSettings"]["weatherProxyDailyCsvPath"] == "data/weather/processed/tokyo.csv"
    assert payload["simulationSettings"]["weatherProxyStationId"] == "44132"
    assert payload["simulationSettings"]["weatherProxyStationName"] == "東京"
    assert payload["simulationSettings"]["solcastProxyIssueDate"] == "2025-08-09"
    assert payload["simulationSettings"]["solcastTypicalCurvePath"] == "data/weather/processed/typical.json"
    assert payload["simulationSettings"]["solcastTypicalWeatherClass"] == "cloudy"
    assert payload["simulationSettings"]["pvMarginalChargeCostYenPerKwh"] == 3.5
    assert payload["simulationSettings"]["pvCurtailPenaltyYenPerKwh"] == 6.5
    assert payload["simulationSettings"]["vehicleUsageCostJpyPerUsedBus"] == 30000.0
    assert payload["solverSettings"]["mipGap"] == 0.0
    assert payload["solverSettings"]["randomSeed"] == 0
    assert payload["simulationSettings"]["unservedPenalty"] == 0.0
    assert payload["simulationSettings"]["gridFlatPricePerKwh"] == 0.0
    assert payload["simulationSettings"]["gridSellPricePerKwh"] == 0.0
    assert payload["simulationSettings"]["demandChargeCostPerKw"] == 0.0
    assert payload["simulationSettings"]["dieselPricePerL"] == 0.0
    assert payload["simulationSettings"]["gridCo2KgPerKwh"] == 0.0
    assert payload["simulationSettings"]["co2PricePerKg"] == 0.0
    assert payload["simulationSettings"]["iceCo2KgPerL"] == 0.0
    assert payload["simulationSettings"]["depotPowerLimitKw"] == 0.0
    assert payload["simulationSettings"]["initialIceFuelPercent"] == 0.0
    assert payload["simulationSettings"]["minIceFuelPercent"] == 0.0
    assert payload["simulationSettings"]["maxIceFuelPercent"] == 0.0
    assert payload["simulationSettings"]["defaultIceTankCapacityL"] == 0.0
    assert payload["simulationSettings"]["deadheadSpeedKmh"] == 18.0
    assert payload["simulationSettings"]["vehicleUsageCostSemantics"] == (
        "fixed_vehicle_day_cost"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("planningDays", 0),
        ("timeStepMin", 0),
        ("timeLimitSeconds", 0),
        ("alnsIterations", 0),
        ("noImprovementLimit", 0),
        ("destroyFraction", 0.0),
        ("maxStartFragmentsPerVehicle", 0),
        ("maxEndFragmentsPerVehicle", 0),
        ("deadheadSpeedKmh", 0.0),
    ],
)
def test_quick_setup_rejects_zero_for_strictly_positive_controls(
    field: str,
    value: int | float,
) -> None:
    with pytest.raises(ValidationError):
        scenarios.UpdateQuickSetupBody(**{field: value})


def test_prepare_settings_preserve_valid_zeroes_and_reject_invalid_zeroes() -> None:
    settings = PrepareSimulationSettingsBody(
        grid_flat_price_per_kwh=0.0,
        demand_charge_cost_per_kw=0.0,
        unserved_penalty=0.0,
        depot_power_limit_kw=0.0,
        mip_gap=0.0,
        random_seed=0,
        vehicle_usage_cost_semantics="fixed_vehicle_day_cost",
    )

    assert settings.grid_flat_price_per_kwh == 0.0
    assert settings.demand_charge_cost_per_kw == 0.0
    assert settings.unserved_penalty == 0.0
    assert settings.depot_power_limit_kw == 0.0
    assert settings.mip_gap == 0.0
    assert settings.random_seed == 0
    assert settings.vehicle_usage_cost_semantics == "fixed_vehicle_day_cost"

    with pytest.raises(ValidationError):
        PrepareSimulationSettingsBody(time_limit_seconds=0)
    with pytest.raises(ValidationError):
        PrepareSimulationSettingsBody(deadhead_speed_kmh=0.0)
    with pytest.raises(ValidationError):
        PrepareSimulationSettingsBody(vehicle_usage_cost_semantics="unknown")


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

    def _capture_set_overlay(_scenario_id: str, value) -> None:
        captured["scenario_overlay"] = value

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
        pvMarginalChargeCostYenPerKwh=4.25,
        pvCurtailPenaltyYenPerKwh=7.5,
        vehicleUsageCostJpyPerUsedBus=25000.0,
        vehicleUsageCostSemantics="driver_cost_proxy",
        gridFlatPricePerKwh=0.0,
        gridSellPricePerKwh=0.0,
        demandChargeCostPerKw=0.0,
        dieselPricePerL=0.0,
        gridCo2KgPerKwh=0.0,
        co2PricePerKg=0.0,
        iceCo2KgPerL=0.0,
        depotPowerLimitKw=0.0,
        unservedPenalty=0.0,
        randomSeed=0,
        initialIceFuelPercent=0.0,
        minIceFuelPercent=0.0,
        maxIceFuelPercent=0.0,
        defaultIceTankCapacityL=0.0,
        deadheadSpeedKmh=18.0,
        operationTimeWindowEnabled=False,
    )

    with (
        mock.patch.object(scenarios, "_ensure_runtime_master_data"),
        mock.patch.object(scenarios, "_quick_setup_route_selection_patch", return_value=current_scope["routeSelection"]),
        mock.patch.object(scenarios.store, "get_dispatch_scope", return_value=current_scope),
        mock.patch.object(scenarios.store, "get_scenario_document_shallow", return_value=doc),
        mock.patch.object(scenarios.store, "set_dispatch_scope", return_value=current_scope),
        mock.patch.object(scenarios.store, "get_scenario_overlay", return_value={}),
        mock.patch.object(scenarios.store, "get_field", return_value={}),
        mock.patch.object(scenarios.store, "set_scenario_overlay", side_effect=_capture_set_overlay),
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
    scenario_overlay = captured["scenario_overlay"]
    assert isinstance(scenario_overlay, dict)
    assert scenario_overlay["cost_coefficients"]["pv_marginal_charge_cost_yen_per_kwh"] == 4.25
    assert scenario_overlay["cost_coefficients"]["pv_curtail_penalty_yen_per_kwh"] == 7.5
    assert scenario_overlay["cost_coefficients"]["vehicle_usage_cost_jpy_per_used_bus"] == 25000.0
    assert scenario_overlay["cost_coefficients"]["vehicle_usage_cost_semantics"] == (
        "driver_cost_proxy"
    )
    assert scenario_overlay["cost_coefficients"]["grid_flat_price_per_kwh"] == 0.0
    assert scenario_overlay["cost_coefficients"]["grid_sell_price_per_kwh"] == 0.0
    assert scenario_overlay["cost_coefficients"]["demand_charge_cost_per_kw"] == 0.0
    assert scenario_overlay["cost_coefficients"]["diesel_price_per_l"] == 0.0
    assert scenario_overlay["cost_coefficients"]["grid_co2_kg_per_kwh"] == 0.0
    assert scenario_overlay["cost_coefficients"]["co2_price_per_kg"] == 0.0
    assert scenario_overlay["cost_coefficients"]["ice_co2_kg_per_l"] == 0.0
    assert scenario_overlay["charging_constraints"]["depot_power_limit_kw"] == 0.0
    assert simulation_config["pv_curtail_penalty_yen_per_kwh"] == 7.5
    assert simulation_config["vehicle_usage_cost_jpy_per_used_bus"] == 25000.0
    assert simulation_config["unserved_penalty"] == 0.0
    assert simulation_config["random_seed"] == 0
    assert simulation_config["initial_ice_fuel_percent"] == 0.0
    assert simulation_config["min_ice_fuel_percent"] == 0.0
    assert simulation_config["max_ice_fuel_percent"] == 0.0
    assert simulation_config["default_ice_tank_capacity_l"] == 0.0
    assert simulation_config["deadhead_speed_kmh"] == 18.0
    assert simulation_config["vehicle_usage_cost_semantics"] == (
        "driver_cost_proxy"
    )
    assert simulation_config["operation_time_window_enabled"] is False
    assert simulation_config["planning_horizon_hours"] == 24.0


def test_update_quick_setup_persists_weather_proxy_state_without_validation() -> None:
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
        serviceDate="2025-08-10",
        allowFixedWeekdayTimetablePvCounterfactual=True,
        enableWeatherOperationPolicy=True,
        weatherProxyForecastPath="data/weather/proxy_forecasts/2025-08-05.json",
        weatherProxyDailyCsvPath="data/weather/processed/tokyo.csv",
        weatherProxyStationId="44132",
        weatherProxyStationName="東京",
        solcastProxyIssueDate="2025-08-09",
        solcastTypicalCurvePath="data/weather/processed/typical.json",
        solcastTypicalWeatherClass="rainy",
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
    assert simulation_config["service_date"] == "2025-08-10"
    assert simulation_config["allow_fixed_weekday_timetable_pv_counterfactual"] is True
    assert simulation_config["calendar_policy"] == "fixed_weekday_timetable_pv_counterfactual"
    assert "comparison_type" not in simulation_config
    assert "comparison_role" not in simulation_config
    assert "counterfactual_pv_source_date" not in simulation_config
    assert simulation_config["enable_weather_operation_policy"] is True
    assert simulation_config["weather_proxy_forecast_path"] == "data/weather/proxy_forecasts/2025-08-05.json"
    assert simulation_config["weather_proxy_daily_csv_path"] == "data/weather/processed/tokyo.csv"
    assert simulation_config["weather_proxy_station_id"] == "44132"
    assert simulation_config["weather_proxy_station_name"] == "東京"
    assert simulation_config["solcast_proxy_issue_date"] == "2025-08-09"
    assert simulation_config["solcast_typical_curve_path"] == "data/weather/processed/typical.json"
    assert simulation_config["solcast_typical_weather_class"] == "rainy"


def test_update_quick_setup_forces_fixed_route_band_when_intra_swap_is_disabled() -> None:
    current_scope = {
        "serviceId": "WEEKDAY",
        "depotSelection": {"depotIds": ["dep1"], "primaryDepotId": "dep1"},
        "routeSelection": {"mode": "refine", "includeRouteIds": ["route-a"], "excludeRouteIds": []},
        "serviceSelection": {"serviceIds": ["WEEKDAY"]},
        "tripSelection": {"includeDeadhead": True},
        "allowIntraDepotRouteSwap": False,
        "fixedRouteBandMode": False,
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
        allowIntraDepotRouteSwap=False,
        fixedRouteBandMode=False,
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
    assert simulation_config["fixed_route_band_mode"] is True
