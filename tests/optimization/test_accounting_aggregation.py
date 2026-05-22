from __future__ import annotations

from src.optimization.accounting.aggregators import build_accounting_summary


def test_tou_energy_cost_uses_slot_price() -> None:
    summary = build_accounting_summary(
        vehicle_rows=[],
        energy_rows=[
            {"grid_total_kwh": 10.0, "grid_kw": 100.0, "energy_cost_jpy": 200.0, "demand_rate_jpy_per_kw": 0.0},
            {"grid_total_kwh": 20.0, "grid_kw": 250.0, "energy_cost_jpy": 600.0, "demand_rate_jpy_per_kw": 0.0},
            {"grid_total_kwh": 30.0, "grid_kw": 180.0, "energy_cost_jpy": 1200.0, "demand_rate_jpy_per_kw": 0.0},
        ],
        metadata={"available_vehicle_count": 0},
    )
    assert summary["energy_cost_jpy"] == 2000.0


def test_demand_cost_uses_peak_only() -> None:
    summary = build_accounting_summary(
        vehicle_rows=[],
        energy_rows=[
            {"grid_total_kwh": 10.0, "grid_kw": 100.0, "energy_cost_jpy": 0.0, "demand_rate_jpy_per_kw": 1000.0},
            {"grid_total_kwh": 20.0, "grid_kw": 250.0, "energy_cost_jpy": 0.0, "demand_rate_jpy_per_kw": 1000.0},
            {"grid_total_kwh": 30.0, "grid_kw": 180.0, "energy_cost_jpy": 0.0, "demand_rate_jpy_per_kw": 1000.0},
        ],
        metadata={"available_vehicle_count": 0},
    )
    assert summary["demand_cost_jpy"] == 250000.0

