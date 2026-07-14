from __future__ import annotations

from bff.routers.pv_management import _sync_scenario_overlay_depot_energy_assets


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
