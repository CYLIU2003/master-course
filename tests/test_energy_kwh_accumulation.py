from __future__ import annotations

from datetime import date

from src.optimization.accounting.ledger_builder import build_accounting_artifacts


def _energy_row(*, grid_import_kw: float, slot_minutes: int) -> dict:
    return {
        "date": "2026-01-01",
        "time": "00:00",
        "depot_id": "dep-1",
        "grid_import_kw": grid_import_kw,
        "energy_price_yen_per_kwh": 20.0,
        "grid_to_bus_slot_kwh": grid_import_kw * slot_minutes / 60.0,
        "grid_to_bess_slot_kwh": 0.0,
        "pv_generation_slot_kwh": 0.0,
        "pv_to_bus_slot_kwh": 0.0,
        "pv_to_bess_slot_kwh": 0.0,
        "pv_curtailed_slot_kwh": 0.0,
    }


def test_grid_kw_to_kwh_accumulates_for_30_and_60_minutes() -> None:
    for slot_minutes, expected_kwh in ((30, 50.0), (60, 100.0)):
        artifacts = build_accounting_artifacts(
            problem=object(),
            scenario_id="s",
            run_id="r",
            service_date=date(2026, 1, 1),
            weather_date=date(2026, 1, 1),
            operator_id="op-1",
            trip_assignment_rows=[],
            vehicle_soc_timeseries_rows=[],
            vehicle_charging_source_rows=[],
            energy_flow_rows=[_energy_row(grid_import_kw=100.0, slot_minutes=slot_minutes)],
            metadata={"slot_minutes": slot_minutes, "operator_id": "op-1"},
        )

        row = artifacts.energy_flow_ledger[0]
        assert row.grid_import_kwh == expected_kwh
        assert row.grid_import_cumulative_kwh == expected_kwh
        assert row.grid_purchase_cost_jpy == expected_kwh * 20.0
