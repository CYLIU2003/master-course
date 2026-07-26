from __future__ import annotations

from datetime import date

import pytest

from src.optimization.accounting.aggregators import build_accounting_summary
from src.optimization.accounting.ledger_builder import build_accounting_artifacts
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    EnergyPriceSlot,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
    ProblemVehicleType,
)


def _ice_problem() -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="s",
            timestep_min=60,
            diesel_price_yen_per_l=150.0,
        ),
        dispatch_context=None,
        trips=(
            ProblemTrip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_min=8 * 60,
                arrival_min=9 * 60,
                distance_km=10.0,
                allowed_vehicle_types=("ICE",),
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="ice-1",
                vehicle_type="ICE",
                home_depot_id="dep-1",
                fuel_consumption_l_per_km=1.0,
            ),
        ),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="ICE",
                powertrain_type="ICE",
                fuel_consumption_l_per_km=1.0,
                co2_emission_kg_per_l=2.58,
            ),
        ),
        price_slots=(EnergyPriceSlot(slot_index=8),),
    )


def _ice_artifacts(
    *,
    fuel_cost_enabled: bool,
    canonical_fuel_cost_jpy: float,
):
    return build_accounting_artifacts(
        problem=_ice_problem(),
        scenario_id="s",
        run_id="r",
        service_date=date(2025, 8, 5),
        weather_date=date(2025, 8, 5),
        operator_id="op",
        trip_assignment_rows=[
            {
                "trip_id": "t1",
                "route_id": "r1",
                "assigned_vehicle_id": "ice-1",
                "assigned_vehicle_type": "ICE",
                "scheduled_departure": "2025-08-05T08:00:00",
                "scheduled_arrival": "2025-08-05T09:00:00",
                "distance_km": 10.0,
                "served_flag": True,
            }
        ],
        vehicle_soc_timeseries_rows=[],
        vehicle_charging_source_rows=[],
        energy_flow_rows=[],
        metadata={
            "slot_minutes": 60,
            "fuel_price_jpy_per_liter": 150.0,
            "co2_price_jpy_per_kg": 1.0,
            "cost_component_flags": {"fuel_cost": fuel_cost_enabled},
            "canonical_fuel_cost_jpy": canonical_fuel_cost_jpy,
            "canonical_ice_co2_kg": 25.8,
        },
    )


def test_disabled_fuel_cost_preserves_physical_fuel_and_co2() -> None:
    artifacts = _ice_artifacts(
        fuel_cost_enabled=False,
        canonical_fuel_cost_jpy=0.0,
    )
    row = next(
        row
        for row in artifacts.vehicle_slot_ledger
        if row.vehicle_id == "ice-1" and row.activity_type == "service"
    )

    assert row.ice_fuel_liter == pytest.approx(10.0)
    assert row.fuel_start_l == pytest.approx(10.0)
    assert row.fuel_end_l == pytest.approx(0.0)
    assert row.refuel_l == pytest.approx(0.0)
    assert row.fuel_balance_error_l == pytest.approx(0.0)
    assert row.fuel_cost_jpy == pytest.approx(0.0)
    assert row.ice_co2_kg == pytest.approx(25.8)
    assert artifacts.summary["ice_fuel_consumed_l"] == pytest.approx(10.0)
    assert artifacts.summary["fuel_cost_jpy"] == pytest.approx(0.0)
    assert artifacts.summary["ice_co2_kg"] == pytest.approx(25.8)


def test_solver_fuel_cost_mismatch_is_ng_without_rewriting_physical_rows() -> None:
    artifacts = _ice_artifacts(
        fuel_cost_enabled=True,
        canonical_fuel_cost_jpy=1350.0,
    )
    row = next(
        row
        for row in artifacts.vehicle_slot_ledger
        if row.vehicle_id == "ice-1" and row.activity_type == "service"
    )
    statuses = {
        item["check_name"]: item["status"]
        for item in artifacts.data_flow_validation
    }

    assert row.ice_fuel_liter == pytest.approx(10.0)
    assert row.fuel_start_l == pytest.approx(10.0)
    assert row.fuel_end_l == pytest.approx(0.0)
    assert row.refuel_l == pytest.approx(0.0)
    assert row.fuel_cost_jpy == pytest.approx(1500.0)
    assert row.ice_co2_kg == pytest.approx(25.8)
    assert (
        statuses["solver_fuel_cost_matches_physical_fuel_ledger"]
        == "NG"
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
