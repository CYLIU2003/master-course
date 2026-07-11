from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from src.optimization.accounting import build_accounting_artifacts, validate_accounting_artifacts


def _problem() -> SimpleNamespace:
    vehicle = SimpleNamespace(
        vehicle_id="veh-1",
        vehicle_type="BEV",
        home_depot_id="dep-1",
        battery_capacity_kwh=100.0,
        initial_soc=60.0,
        energy_consumption_kwh_per_km=1.0,
        fuel_consumption_l_per_km=0.0,
    )
    vehicle_type = SimpleNamespace(
        vehicle_type_id="BEV",
        battery_capacity_kwh=100.0,
        energy_consumption_kwh_per_km=1.0,
        fuel_consumption_l_per_km=0.0,
        co2_emission_kg_per_l=0.0,
    )
    price_slot = SimpleNamespace(slot_index=0, grid_buy_yen_per_kwh=10.0)
    scenario = SimpleNamespace(timestep_min=30, diesel_price_yen_per_l=0.0, co2_price_per_kg=0.0)
    return SimpleNamespace(vehicles=[vehicle], vehicle_types=[vehicle_type], price_slots=[price_slot], scenario=scenario)


def test_build_accounting_artifacts_minimum_case() -> None:
    problem = _problem()
    artifacts = build_accounting_artifacts(
        problem=problem,
        scenario_id="scenario-1",
        run_id="run-1",
        service_date=date(2025, 8, 5),
        weather_date=date(2025, 8, 5),
        operator_id="tokyu",
        trip_assignment_rows=[
            {
                "trip_id": "trip-1",
                "route_id": "R1",
                "route_series_code": "R1",
                "served_flag": True,
                "assigned_vehicle_id": "veh-1",
                "assigned_vehicle_type": "BEV",
                "actual_departure": "2025-08-05T08:00:00",
                "actual_arrival": "2025-08-05T08:30:00",
                "distance_km": 10.0,
                "energy_used_kwh": 10.0,
                "deadhead_before_km": 0.0,
                "deadhead_after_km": 0.0,
            }
        ],
        vehicle_soc_timeseries_rows=[
            {"date": "2025-08-05", "time": "08:00", "vehicle_id": "veh-1", "soc_kwh": 50.0, "state": "service"},
            {"date": "2025-08-05", "time": "08:30", "vehicle_id": "veh-1", "soc_kwh": 69.0, "state": "charging"},
        ],
        vehicle_charging_source_rows=[
            {
                "date": "2025-08-05",
                "time": "08:30",
                "vehicle_id": "veh-1",
                "total_charge_kwh": 20.0,
                "grid_to_vehicle_kwh": 20.0,
                "pv_to_vehicle_kwh": 0.0,
                "bess_to_vehicle_kwh": 0.0,
            }
        ],
        energy_flow_rows=[
            {
                "date": "2025-08-05",
                "time": "08:30",
                "depot_id": "dep-1",
                "grid_to_bus_kwh": 20.0,
                "grid_to_bess_kwh": 0.0,
                "pv_to_bus_kwh": 0.0,
                "pv_to_bess_kwh": 0.0,
                "pv_curtailed_kwh": 0.0,
                "pv_generation_kwh": 0.0,
                "bess_to_bus_kwh": 0.0,
                "grid_total_kwh": 20.0,
                "grid_kw": 40.0,
                "energy_price_yen_per_kwh": 10.0,
                "demand_rate_jpy_per_kw": 0.0,
                "source_provenance_exact": True,
            }
        ],
        metadata={
            "objective_value": 200.0,
            "available_vehicle_count": 1,
            "operator_id": "tokyu",
            "scenario_id": "scenario-1",
            "run_id": "run-1",
            "service_date": "2025-08-05",
            "weather_date": "2025-08-05",
            "charging_source_provenance_exact": True,
            "fuel_price_jpy_per_liter": 0.0,
            "co2_price_jpy_per_kg": 0.0,
            "battery_degradation_price_jpy_per_kwh": 0.0,
            "slot_minutes": 30,
        },
    )

    assert artifacts.summary["total_charge_input_kwh"] == 20.0
    assert artifacts.summary["service_km"] == 10.0
    assert artifacts.summary["energy_cost_jpy"] == 200.0
    assert artifacts.summary["peak_grid_kw"] == 40.0
    issues = validate_accounting_artifacts(
        vehicle_rows=[row.to_dict() for row in artifacts.vehicle_slot_ledger],
        energy_rows=[row.to_dict() for row in artifacts.energy_flow_ledger],
        summary=artifacts.summary,
        strict=True,
    )
    assert issues == []

