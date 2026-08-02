from __future__ import annotations

from bff.routers.pv_management import (
    DepotEnergyAssetUpdate,
    _sync_scenario_overlay_depot_energy_assets,
    _update_depot_asset,
)


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
