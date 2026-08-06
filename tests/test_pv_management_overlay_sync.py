from __future__ import annotations

from bff.routers.pv_management import (
    DepotEnergyAssetsUpdateRequest,
    DepotEnergyAssetUpdate,
    _find_solcast_csv,
    _sync_scenario_overlay_depot_energy_assets,
    _update_depot_asset,
    _update_scenario_pv_profile,
    update_depot_energy_assets,
)


def test_tsurumaki_pv_api_uses_current_solcast_artifact() -> None:
    path = _find_solcast_csv("tsurumaki")

    assert path.as_posix().endswith(
        "data/external/solcast_raw/tsurumaki_2025_08_60min.csv"
    )
    assert path.is_file()


def test_pv_asset_sync_updates_legacy_frontend_summary_flag() -> None:
    scenario = {
        "simulation_config": {
            "depot_energy_assets": [
                {"depot_id": "dep-1", "pv_enabled": True},
                {"depot_id": "dep-2", "pv_enabled": False},
            ]
        },
        "scenario_overlay": {"cost_coefficients": {"pv_enabled": False}},
    }

    _sync_scenario_overlay_depot_energy_assets(scenario)

    assert scenario["scenario_overlay"]["cost_coefficients"]["pv_enabled"] is True


def test_pv_asset_sync_clears_summary_flag_when_all_assets_are_disabled() -> None:
    scenario = {
        "simulation_config": {
            "depot_energy_assets": [{"depot_id": "dep-1", "pv_enabled": False}]
        },
        "scenario_overlay": {"cost_coefficients": {"pv_enabled": True}},
    }

    _sync_scenario_overlay_depot_energy_assets(scenario)

    assert scenario["scenario_overlay"]["cost_coefficients"]["pv_enabled"] is False


def test_update_depot_asset_uses_rated_output_and_preserves_measured_area() -> None:
    scenario = {
        "simulation_config": {"depot_energy_assets": []},
        "scenario_overlay": {},
    }

    _update_depot_asset(
        scenario,
        DepotEnergyAssetUpdate(
            depot_id="dep-1",
            depot_area_m2=1000.0,
            pv_capacity_kw=120.0,
        ),
    )

    row = scenario["simulation_config"]["depot_energy_assets"][0]
    assert row["depot_area_m2"] == 1000.0
    assert row["pv_capacity_kw"] == 120.0
    assert row["derived_pv_capacity_kw"] == 120.0
    assert row["estimated_installable_area_m2"] == 600.0
    assert row["estimated_depot_area_from_pv_capacity_m2"] == 1714.285714
    assert row["pv_capacity_kw_manual_override"] is True
    assert row["pv_capacity_input_mode"] == "rated_output_manual"


def test_generated_profile_updates_direct_and_date_indexed_series_together() -> None:
    scenario = {
        "simulation_config": {
            "depot_energy_assets": [
                {
                    "depot_id": "dep-1",
                    "bess_enabled": True,
                    "bess_energy_kwh": 6000.0,
                    "pv_generation_kwh_by_date": [{"date": "stale"}],
                }
            ]
        },
        "scenario_overlay": {"cost_coefficients": {"pv_enabled": False}},
    }
    factors = [0.0, 0.5]
    generation = [0.0, 500.0]

    _update_scenario_pv_profile(
        scenario,
        "dep-1",
        "2025-08-05",
        1450.0,
        5000.0,
        14285.714286,
        1000.0,
        True,
        0.85,
        60,
        factors,
        generation,
    )

    sim_cfg = scenario["simulation_config"]
    row = sim_cfg["depot_energy_assets"][0]
    assert row["pv_capacity_kw"] == 1000.0
    assert row["estimated_installable_area_m2"] == 5000.0
    assert row["estimated_depot_area_from_pv_capacity_m2"] == 14285.714286
    assert row["pv_case_id"] == "dep-1_2025-08-05_60min"
    assert row["pv_capacity_factor_by_date"] == [
        {
            "date": "2025-08-05",
            "slot_minutes": 60,
            "capacity_factor_by_slot": factors,
        }
    ]
    assert row["pv_generation_kwh_by_date"] == [
        {
            "date": "2025-08-05",
            "slot_minutes": 60,
            "pv_generation_kwh_by_slot": generation,
        }
    ]
    assert row["bess_energy_kwh"] == 6000.0
    assert sim_cfg["pv_profile_id"] == "dep-1_2025-08-05_60min"
    assert scenario["scenario_overlay"]["cost_coefficients"]["pv_enabled"] is True
    assert scenario["scenario_overlay"]["depot_energy_assets"]["dep-1"] == row


def test_depot_asset_api_uses_shallow_load_and_atomic_experiment_save(
    monkeypatch,
) -> None:
    scenario = {
        "simulation_config": {"depot_energy_assets": []},
        "scenario_overlay": {"cost_coefficients": {"pv_enabled": False}},
    }
    saved: dict = {}

    monkeypatch.setattr(
        "bff.routers.pv_management.store.get_scenario_document_shallow",
        lambda scenario_id: scenario,
    )

    def _capture_replace(
        scenario_id: str,
        *,
        simulation_config: dict,
        scenario_overlay: dict | None,
    ) -> None:
        saved.update(
            scenario_id=scenario_id,
            simulation_config=simulation_config,
            scenario_overlay=scenario_overlay,
        )

    monkeypatch.setattr(
        "bff.routers.pv_management.store.replace_scenario_experiment_configuration",
        _capture_replace,
    )

    response = update_depot_energy_assets(
        "scenario-1",
        DepotEnergyAssetsUpdateRequest(
            depot_assets=[
                DepotEnergyAssetUpdate(
                    depot_id="dep-1",
                    depot_area_m2=1450.0,
                    pv_capacity_kw=1000.0,
                    pv_enabled=True,
                )
            ]
        ),
    )

    assert response["updated_count"] == 1
    assert saved["scenario_id"] == "scenario-1"
    row = saved["simulation_config"]["depot_energy_assets"][0]
    assert row["pv_capacity_kw"] == 1000.0
    assert saved["scenario_overlay"]["depot_energy_assets"]["dep-1"] == row
    assert saved["scenario_overlay"]["cost_coefficients"]["pv_enabled"] is True
