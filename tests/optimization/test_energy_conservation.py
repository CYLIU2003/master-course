from __future__ import annotations

from src.optimization.accounting.validators import validate_accounting_artifacts


def test_pv_conservation_validator() -> None:
    issues = validate_accounting_artifacts(
        vehicle_rows=[
            {
                "vehicle_id": "veh-1",
                "charge_input_kwh": 20.0,
                "soc_start_ratio": 0.5,
                "soc_end_ratio": 0.6,
                "soc_delta_charge_ratio": 0.2,
                "soc_delta_drive_ratio": 0.1,
                "soc_delta_loss_ratio": 0.0,
            }
        ],
        energy_rows=[
            {
                "pv_generation_kwh": 100.0,
                "pv_to_bus_kwh": 60.0,
                "pv_to_bess_kwh": 30.0,
                "pv_curtailed_kwh": 10.0,
                "grid_total_kwh": 0.0,
                "grid_to_bus_kwh": 0.0,
                "grid_to_bess_kwh": 0.0,
                "depot_aux_grid_kwh": 0.0,
                "grid_kw": 0.0,
            }
        ],
        summary={"peak_grid_kw": 0.0},
        strict=True,
    )
    assert issues == []

