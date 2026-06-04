from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.optimization.accounting.ledger_builder import build_accounting_artifacts


def test_vehicle_energy_ledger_balances_ev_sources_and_soc() -> None:
    problem = SimpleNamespace(
        scenario=SimpleNamespace(timestep_min=30),
        vehicles=(SimpleNamespace(vehicle_id="bev-1", vehicle_type="BEV", battery_capacity_kwh=100.0, charge_efficiency=0.9),),
        vehicle_types=(),
        price_slots=(SimpleNamespace(slot_index=0, grid_buy_yen_per_kwh=20.0),),
    )
    artifacts = build_accounting_artifacts(
        problem=problem,
        scenario_id="s",
        run_id="r",
        service_date=date(2026, 1, 1),
        weather_date=date(2026, 1, 1),
        operator_id="op-1",
        trip_assignment_rows=[],
        vehicle_soc_timeseries_rows=[{"vehicle_id": "bev-1", "date": "2026-01-01", "time": "00:00", "soc_kwh": 59.0}],
        vehicle_charging_source_rows=[{"vehicle_id": "bev-1", "date": "2026-01-01", "time": "00:00", "grid_to_vehicle_kwh": 10.0, "pv_to_vehicle_kwh": 5.0, "bess_to_vehicle_kwh": 0.0, "total_charge_kwh": 15.0}],
        energy_flow_rows=[{"date": "2026-01-01", "time": "00:00", "depot_id": "dep-1", "grid_to_bus_slot_kwh": 10.0, "pv_to_bus_slot_kwh": 5.0, "bess_to_bus_slot_kwh": 0.0, "grid_to_bess_slot_kwh": 0.0}],
        metadata={"slot_minutes": 30, "operator_id": "op-1"},
    )

    row = max(artifacts.vehicle_energy_ledger, key=lambda item: item.fuel_consumed_l)
    assert row.charge_input_kwh == 15.0
    assert row.charge_to_battery_kwh == 13.5
    assert abs(row.soc_balance_error_kwh) <= 1.0e-6
    assert abs(row.charge_source_balance_error_kwh) <= 1.0e-6


def test_vehicle_energy_ledger_balances_ice_fuel() -> None:
    problem = SimpleNamespace(
        scenario=SimpleNamespace(timestep_min=30),
        vehicles=(SimpleNamespace(vehicle_id="ice-1", vehicle_type="ICE", fuel_consumption_l_per_km=0.5),),
        vehicle_types=(),
        price_slots=(),
    )
    artifacts = build_accounting_artifacts(
        problem=problem,
        scenario_id="s",
        run_id="r",
        service_date=date(2026, 1, 1),
        weather_date=date(2026, 1, 1),
        operator_id="op-1",
        trip_assignment_rows=[{"trip_id": "t1", "assigned_vehicle_id": "ice-1", "assigned_vehicle_type": "ICE", "scheduled_departure": "2026-01-01T00:00:00", "scheduled_arrival": "2026-01-01T00:30:00", "distance_km": 10.0, "served_flag": True}],
        vehicle_soc_timeseries_rows=[],
        vehicle_charging_source_rows=[],
        energy_flow_rows=[],
        metadata={"slot_minutes": 30, "operator_id": "op-1", "fuel_price_jpy_per_liter": 100.0},
    )

    row = max(artifacts.vehicle_energy_ledger, key=lambda item: item.fuel_consumed_l)
    assert row.fuel_consumed_l == 5.0
    assert row.fuel_cost_jpy == 500.0
    assert abs(row.fuel_balance_error_l) <= 1.0e-6
