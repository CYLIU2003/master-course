from __future__ import annotations

from bff.services.run_preparation import _prepare_depot_energy_assets


def test_prepare_depot_energy_assets_derives_pv_capacity_from_depot_area() -> None:
    simulation_config = {
        "depot_energy_assets": [
            {
                "depot_id": "dep-1",
                "pv_capacity_factor_by_date": [
                    {
                        "date": "2025-08-01",
                        "slot_minutes": 60,
                        "capacity_factor_by_slot": [0.0, 0.5],
                    }
                ],
            }
        ]
    }
    rows = _prepare_depot_energy_assets(
        simulation_config,
        [{"id": "dep-1", "depotAreaM2": 1000.0}],
    )

    assert rows[0]["depot_area_m2"] == 1000.0
    assert rows[0]["estimated_installable_area_m2"] == 350.0
    assert rows[0]["pv_capacity_kw"] == 70.0
    assert rows[0]["derived_pv_capacity_kw"] == 70.0
    assert rows[0]["pv_enabled"] is True
    assert rows[0]["pv_generation_kwh_by_slot"] == [0.0, 35.0]


def test_prepare_depot_energy_assets_disables_pv_without_area() -> None:
    rows = _prepare_depot_energy_assets(
        {
            "depot_energy_assets": [
                {
                    "depot_id": "dep-1",
                    "pv_capacity_kw": 999.0,
                    "pv_generation_kwh_by_slot": [1.0],
                }
            ]
        },
        [{"id": "dep-1"}],
    )

    assert rows[0]["depot_area_m2"] is None
    assert rows[0]["pv_enabled"] is False
    assert rows[0]["pv_capacity_kw"] == 0.0
    assert rows[0]["pv_generation_kwh_by_slot"] == []


def test_prepare_depot_energy_assets_rescales_legacy_generation_shape() -> None:
    rows = _prepare_depot_energy_assets(
        {
            "depot_energy_assets": [
                {
                    "depot_id": "dep-1",
                    "depot_area_m2": 2000.0,
                    "pv_capacity_kw": 100.0,
                    "pv_generation_kwh_by_slot": [25.0, 50.0],
                }
            ]
        },
        [{"id": "dep-1"}],
    )

    assert rows[0]["pv_capacity_kw"] == 140.0
    assert rows[0]["legacy_pv_capacity_kw"] == 100.0
    assert rows[0]["capacity_factor_by_slot"] == [0.25, 0.5]
    assert rows[0]["pv_generation_kwh_by_slot"] == [35.0, 70.0]
