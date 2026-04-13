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
        depotEnergyAssets=[
            {
                "depot_id": "tsurumaki",
                "pv_enabled": True,
                "pv_capacity_kw": 120.0,
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
    assert simulation_config["depot_energy_assets"] == [
        {
            "depot_id": "tsurumaki",
            "pv_enabled": True,
            "pv_capacity_kw": 120.0,
        }
    ]
