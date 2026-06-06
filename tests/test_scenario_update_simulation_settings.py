from __future__ import annotations

from unittest import mock

from bff.routers import scenarios


def test_update_scenario_persists_simulation_settings() -> None:
    body = scenarios.UpdateScenarioBody(
        name="Scenario A",
        finalSocFloorPercent=0.2,
        finalSocTargetPercent=0.8,
        finalSocTargetTolerancePercent=0.15,
        initialSocPercent=0.88,
        initialSoc=0.85,
        socMin=0.2,
        socMax=0.9,
        pvProfileId="meguro_2026-04-13_60min",
        weatherMode="actual_date_profile",
        weatherFactorScalar=0.85,
        enableWeatherOperationPolicy=True,
        weatherProxyForecastPath="data/weather/proxy_forecasts/tokyo.json",
        weatherProxyDailyCsvPath="data/weather/processed/tokyo.csv",
        weatherProxyStationId="44132",
        weatherProxyStationName="東京",
        depotEnergyAssets=[
            {
                "depot_id": "tsurumaki",
                "pv_enabled": True,
                "pv_capacity_kw": 120.0,
                "bess_enabled": True,
                "bess_energy_kwh": 100.0,
                "bessInitialSocPercent": 50.0,
                "bessSocMinPercent": 10.0,
                "bessSocMaxPercent": 90.0,
                "bessTerminalSocMinPercent": 40.0,
            }
        ],
    )

    captured: dict[str, object] = {}

    def _capture_update(
        scenario_id: str,
        *,
        name=None,
        description=None,
        mode=None,
        operator_id=None,
        status=None,
        simulation_config=None,
    ) -> dict[str, object]:
        captured["scenario_id"] = scenario_id
        captured["name"] = name
        captured["description"] = description
        captured["mode"] = mode
        captured["operator_id"] = operator_id
        captured["status"] = status
        captured["simulation_config"] = simulation_config
        return {"id": scenario_id, "name": name}

    with (
        mock.patch.object(scenarios.store, "get_field", return_value={"existing_flag": True}),
        mock.patch.object(scenarios.store, "get_scenario_overlay", return_value={}),
        mock.patch.object(scenarios.store, "set_scenario_overlay"),
        mock.patch.object(scenarios.store, "update_scenario", side_effect=_capture_update),
    ):
        scenarios.update_scenario("scenario-1", body)

    simulation_config = captured["simulation_config"]
    assert isinstance(simulation_config, dict)
    assert simulation_config["existing_flag"] is True
    assert simulation_config["initial_soc_percent"] == 0.88
    assert simulation_config["final_soc_floor_percent"] == 0.2
    assert simulation_config["final_soc_target_percent"] == 0.8
    assert simulation_config["final_soc_target_tolerance_percent"] == 0.15
    assert simulation_config["initial_soc"] == 0.85
    assert simulation_config["soc_min"] == 0.2
    assert simulation_config["soc_max"] == 0.9
    assert simulation_config["pv_profile_id"] == "meguro_2026-04-13_60min"
    assert simulation_config["weather_mode"] == "actual_date_profile"
    assert simulation_config["weather_factor_scalar"] == 0.85
    assert simulation_config["enable_weather_operation_policy"] is True
    assert simulation_config["weather_proxy_forecast_path"] == "data/weather/proxy_forecasts/tokyo.json"
    assert simulation_config["weather_proxy_daily_csv_path"] == "data/weather/processed/tokyo.csv"
    assert simulation_config["weather_proxy_station_id"] == "44132"
    assert simulation_config["weather_proxy_station_name"] == "東京"
    asset = simulation_config["depot_energy_assets"][0]
    assert asset["depot_id"] == "tsurumaki"
    assert asset["pv_enabled"] is True
    assert asset["pv_capacity_kw"] == 120.0
    assert asset["bess_initial_soc_kwh"] == 50.0
    assert asset["bess_soc_min_kwh"] == 10.0
    assert asset["bess_soc_max_kwh"] == 90.0
    assert asset["bess_terminal_soc_min_kwh"] == 40.0
    assert asset["bess_initial_soc_ratio"] == 0.5
    assert asset["bess_soc_min_ratio"] == 0.1
    assert asset["bess_soc_max_ratio"] == 0.9
    assert asset["bess_terminal_soc_min_ratio"] == 0.4


def test_normalize_depot_energy_asset_accepts_dict_and_converts_percent() -> None:
    payload = {
        "tsurumaki": {
            "bessEnabled": True,
            "bessEnergyKwh": 200.0,
            "bessPowerKw": 50.0,
            "bessInitialSocPercent": 60.0,
            "bessSocMinPercent": 20.0,
            "bessSocMaxPercent": 90.0,
            "bessTerminalSocMinPercent": 55.0,
            "allowGridToBess": True,
        }
    }

    assets = scenarios._normalize_depot_energy_assets_payload(payload)

    assert assets[0]["depot_id"] == "tsurumaki"
    assert assets[0]["bess_initial_soc_kwh"] == 120.0
    assert assets[0]["bess_soc_min_kwh"] == 40.0
    assert assets[0]["bess_soc_max_kwh"] == 180.0
    assert assets[0]["bess_terminal_soc_min_kwh"] == 110.0
    assert assets[0]["bess_soc_min_ratio"] == 0.2
    assert assets[0]["bess_soc_max_ratio"] == 0.9
    assert assets[0]["allow_grid_to_bess"] is True


def test_normalize_depot_energy_asset_accepts_bess_buffer_ratios() -> None:
    assets = scenarios._normalize_depot_energy_assets_payload(
        [
            {
                "depot_id": "tsurumaki",
                "bess_enabled": True,
                "bess_energy_kwh": 500.0,
                "bess_initial_soc_ratio": 0.6,
                "bess_soc_min_ratio": 0.2,
                "bess_soc_max_ratio": 0.9,
                "bess_terminal_soc_min_ratio": 0.2,
            }
        ]
    )

    asset = assets[0]
    assert asset["bess_initial_soc_kwh"] == 300.0
    assert asset["bess_soc_min_kwh"] == 100.0
    assert asset["bess_soc_max_kwh"] == 450.0
    assert asset["bess_terminal_soc_min_kwh"] == 100.0
    assert asset["bess_soc_min_percent"] == 20.0
    assert asset["bess_soc_max_percent"] == 90.0
