from __future__ import annotations

import pytest

from src.optimization.accounting.aggregators import build_accounting_summary
from src.optimization.accounting.ledger_builder import (
    _align_vehicle_fuel_to_solver_cost_ledger,
)
from src.optimization.accounting.schema import VehicleSlotLedgerRow


def test_vehicle_fuel_reporting_rows_align_to_solver_canonical_totals() -> None:
    row = VehicleSlotLedgerRow(
        scenario_id="s",
        run_id="r",
        service_date="2025-08-05",
        weather_date="2025-08-05",
        operator_id="op",
        vehicle_id="ice-1",
        vehicle_type="ICE",
        slot_start="2025-08-05T08:00:00",
        slot_end="2025-08-05T09:00:00",
        slot_index=8,
        slot_minutes=60,
        trip_id="t1",
        activity_type="service",
        ice_fuel_liter=10.0,
        ice_co2_kg=25.8,
        fuel_start_l=10.0,
        fuel_end_l=0.0,
        fuel_cost_jpy=1500.0,
        co2_cost_jpy=25.8,
    )

    aligned = _align_vehicle_fuel_to_solver_cost_ledger(
        [row],
        metadata={
            "canonical_fuel_cost_jpy": 1350.0,
            "canonical_ice_co2_kg": 23.22,
        },
    )

    assert aligned[0].fuel_cost_jpy == pytest.approx(1350.0)
    assert aligned[0].ice_fuel_liter == pytest.approx(9.0)
    assert aligned[0].ice_co2_kg == pytest.approx(23.22)
    assert (
        aligned[0].created_by_stage
        == "solver_canonical_cost_allocation"
    )


def test_positive_solver_fuel_cost_cannot_be_allocated_to_empty_ledger() -> None:
    with pytest.raises(ValueError, match="empty fuel ledger"):
        _align_vehicle_fuel_to_solver_cost_ledger(
            [],
            metadata={"canonical_fuel_cost_jpy": 100.0},
        )


def test_accounting_summary_includes_peak_demand_and_grid_co2_cost() -> None:
    summary = build_accounting_summary(
        vehicle_rows=[
            {
                "vehicle_id": "ice-1",
                "vehicle_type": "ICE",
                "trip_id": "t1",
                "slot_start": "2025-08-05T08:00:00",
                "fuel_cost_jpy": 1500.0,
                "ice_co2_kg": 25.8,
            }
        ],
        vehicle_energy_rows=[
            {
                "vehicle_id": "ice-1",
                "ice_co2_kg": 25.8,
                "fuel_consumed_l": 10.0,
            }
        ],
        energy_rows=[
            {
                "grid_import_kwh": 20.0,
                "grid_kw": 40.0,
                "grid_emission_factor_kg_per_kwh": 0.5,
                "energy_cost_jpy": 400.0,
                "demand_rate_jpy_per_kw": 30.0,
            }
        ],
        metadata={
            "co2_price_jpy_per_kg": 1.0,
            "vehicle_usage_cost_jpy_per_used_bus": 0.0,
        },
    )

    assert summary["demand_charge_cost_jpy"] == pytest.approx(1200.0)
    assert summary["electricity_co2_kg"] == pytest.approx(10.0)
    assert summary["total_co2_kg"] == pytest.approx(35.8)
    assert summary["co2_cost_jpy"] == pytest.approx(35.8)
