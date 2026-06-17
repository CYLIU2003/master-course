from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from bff.routers.optimization import _research_vehicle_charging_source_timeseries_rows
from src.optimization.accounting.ledger_builder import build_accounting_artifacts
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    ChargingSlot,
    EnergyPriceSlot,
    OptimizationScenario,
    ProblemVehicle,
)


def test_accounting_data_flow_validation_reports_ok() -> None:
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
        energy_flow_rows=[
            {
                "date": "2026-01-01",
                "time": "00:00",
                "depot_id": "dep-1",
                "grid_to_bus_slot_kwh": 10.0,
                "grid_to_bess_slot_kwh": 5.0,
                "pv_generation_slot_kwh": 8.0,
                "pv_to_bus_slot_kwh": 3.0,
                "pv_to_bess_slot_kwh": 2.0,
                "pv_curtailed_slot_kwh": 3.0,
            }
        ],
        metadata={"slot_minutes": 30, "operator_id": "op-1"},
    )

    statuses = {row["check_name"]: row["status"] for row in artifacts.data_flow_validation}
    assert statuses["pv_generation_balance"] == "OK"
    assert statuses["grid_import_balance"] == "OK"
    assert statuses["operator_id_empty_count"] == "OK"


def test_energy_flow_time_idx_uses_planning_start_time() -> None:
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
        energy_flow_rows=[
            {
                "time_idx": 0,
                "depot_id": "dep-1",
                "grid_to_bus_kwh": 10.0,
                "grid_total_kwh": 10.0,
                "energy_price_yen_per_kwh": 18.0,
            },
            {
                "time_idx": 20,
                "depot_id": "dep-1",
                "grid_to_bus_kwh": 1.0,
                "grid_total_kwh": 1.0,
                "energy_price_yen_per_kwh": 18.0,
            },
        ],
        metadata={
            "slot_minutes": 60,
            "operator_id": "op-1",
            "planning_start_time": "05:00",
        },
    )

    row = artifacts.energy_flow_ledger[0]
    next_day_row = artifacts.energy_flow_ledger[1]
    assert row.slot_index == 0
    assert row.slot_start == "2026-01-01T05:00:00"
    assert row.slot_end == "2026-01-01T06:00:00"
    assert row.timestamp == row.slot_start
    assert row.grid_purchase_cost_jpy == pytest.approx(180.0)
    assert next_day_row.slot_index == 20
    assert next_day_row.slot_start == "2026-01-02T01:00:00"
    assert next_day_row.slot_end == "2026-01-02T02:00:00"


def test_vehicle_charging_source_allocation_uses_site_ratios_when_not_solver_native() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s", timestep_min=60, horizon_start="00:00"),
        dispatch_context=None,
        trips=(),
        vehicles=(
            ProblemVehicle(vehicle_id="v1", vehicle_type="BEV", home_depot_id="dep-1", battery_capacity_kwh=100.0),
            ProblemVehicle(vehicle_id="v2", vehicle_type="BEV", home_depot_id="dep-1", battery_capacity_kwh=100.0),
        ),
    )
    plan = AssignmentPlan(
        charging_slots=(
            ChargingSlot(vehicle_id="v1", slot_index=0, charger_id="charger-a", charge_kw=4.0, charging_depot_id="dep-1"),
            ChargingSlot(vehicle_id="v2", slot_index=0, charger_id="charger-b", charge_kw=6.0, charging_depot_id="dep-1"),
        ),
        grid_to_bus_kwh_by_depot_slot={"dep-1": {0: 6.0}},
        pv_to_bus_kwh_by_depot_slot={"dep-1": {0: 3.0}},
        bess_to_bus_kwh_by_depot_slot={"dep-1": {0: 1.0}},
        metadata={"source_provenance_exact": True, "vehicle_source_provenance_exact": False},
    )

    rows = _research_vehicle_charging_source_timeseries_rows(
        problem=problem,
        engine_result=SimpleNamespace(plan=plan),
        base_date=date(2026, 1, 1),
        operator_id="op-1",
    )
    active_rows = [row for row in rows if row["time"] == "00:00"]

    assert sum(row["grid_to_vehicle_kwh"] for row in active_rows) == pytest.approx(6.0)
    assert sum(row["pv_to_vehicle_kwh"] for row in active_rows) == pytest.approx(3.0)
    assert sum(row["bess_to_vehicle_kwh"] for row in active_rows) == pytest.approx(1.0)
    assert {row["vehicle_charging_source_allocation_method"] for row in active_rows} == {"proportional_by_timestep"}
    assert not any(row["vehicle_charging_source_is_solver_native"] for row in active_rows)


def test_accounting_summary_separates_fallback_and_cost_definitions() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s", timestep_min=60),
        dispatch_context=None,
        trips=(),
        vehicles=(
            ProblemVehicle(
                vehicle_id="v1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                initial_soc=50.0,
                battery_capacity_kwh=100.0,
                reserve_soc=10.0,
            ),
        ),
        price_slots=(EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=20.0),),
    )
    artifacts = build_accounting_artifacts(
        problem=problem,
        scenario_id="s",
        run_id="r",
        service_date=date(2026, 1, 1),
        weather_date=date(2026, 1, 1),
        operator_id="op-1",
        trip_assignment_rows=[],
        vehicle_soc_timeseries_rows=[],
        vehicle_charging_source_rows=[
            {
                "date": "2026-01-01",
                "time": "00:00",
                "vehicle_id": "v1",
                "total_charge_kwh": 10.0,
                "grid_to_vehicle_kwh": 6.0,
                "pv_to_vehicle_kwh": 3.0,
                "bess_to_vehicle_kwh": 1.0,
            }
        ],
        energy_flow_rows=[
            {
                "date": "2026-01-01",
                "time": "00:00",
                "depot_id": "dep-1",
                "grid_to_bus_slot_kwh": 6.0,
                "pv_to_bus_slot_kwh": 3.0,
                "bess_to_bus_slot_kwh": 1.0,
                "pv_generation_slot_kwh": 3.0,
                "energy_price_yen_per_kwh": 20.0,
            }
        ],
        metadata={
            "slot_minutes": 60,
            "operator_id": "op-1",
            "solver_status": "BASELINE_FALLBACK",
            "fallback_applied": True,
            "objective_value": 999.0,
            "vehicle_charging_source_allocation_method": "proportional_by_timestep",
        },
    )

    statuses = {row["check_name"]: row["status"] for row in artifacts.data_flow_validation}
    assert statuses["vehicle_grid_to_vehicle_equals_grid_to_bus"] == "OK"
    assert statuses["vehicle_pv_to_vehicle_equals_pv_to_bus"] == "OK"
    assert statuses["vehicle_bess_to_vehicle_equals_bess_to_bus"] == "OK"
    assert statuses["soc_no_nan"] == "OK"
    assert statuses["soc_within_bounds"] == "OK"
    assert artifacts.summary["is_optimization_result"] is False
    assert artifacts.summary["result_interpretation"] == "baseline_fallback_result"
    assert artifacts.summary["objective_value"] == pytest.approx(999.0)
    assert artifacts.summary["gross_operating_cost_jpy"] != artifacts.summary["objective_value"]
    assert artifacts.summary["cost_definition"]["objective_is_actual_cost"] is False


def test_energy_flow_kpi_co2_and_fuel_ledgers_are_canonical() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s", timestep_min=60),
        dispatch_context=None,
        trips=(),
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                initial_soc=80.0,
                battery_capacity_kwh=100.0,
                reserve_soc=10.0,
            ),
            ProblemVehicle(
                vehicle_id="ice-1",
                vehicle_type="ICE",
                home_depot_id="dep-1",
                fuel_consumption_l_per_km=0.2,
            ),
        ),
        price_slots=(EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=20.0, co2_factor=0.5),),
    )
    artifacts = build_accounting_artifacts(
        problem=problem,
        scenario_id="s",
        run_id="r",
        service_date=date(2026, 1, 1),
        weather_date=date(2026, 1, 1),
        operator_id="op-1",
        trip_assignment_rows=[
            {
                "trip_id": "trip-ice",
                "route_id": "r1",
                "assigned_vehicle_id": "ice-1",
                "assigned_vehicle_type": "ICE",
                "scheduled_departure": "2026-01-01T00:00:00",
                "scheduled_arrival": "2026-01-01T01:00:00",
                "distance_km": 10.0,
                "energy_used_kwh": 0.0,
                "served_flag": True,
            }
        ],
        vehicle_soc_timeseries_rows=[],
        vehicle_charging_source_rows=[
            {
                "date": "2026-01-01",
                "time": "00:00",
                "vehicle_id": "bev-1",
                "total_charge_kwh": 9.0,
                "grid_to_vehicle_kwh": 5.0,
                "pv_to_vehicle_kwh": 4.0,
                "bess_to_vehicle_kwh": 0.0,
            }
        ],
        energy_flow_rows=[
            {
                "date": "2026-01-01",
                "time": "00:00",
                "depot_id": "dep-1",
                "grid_to_bus_slot_kwh": 5.0,
                "pv_generation_slot_kwh": 10.0,
                "pv_to_bus_slot_kwh": 4.0,
                "pv_to_bess_slot_kwh": 3.0,
                "pv_curtailed_slot_kwh": 3.0,
                "energy_price_yen_per_kwh": 20.0,
                "grid_co2_factor_kg_per_kwh": 0.5,
            }
        ],
        metadata={
            "slot_minutes": 60,
            "operator_id": "op-1",
            "ice_co2_kg_per_l": 2.5,
            "fuel_price_jpy_per_liter": 150.0,
            "pv_generation_timeseries_total_kwh": 10.0,
            "depot_energy_flows_pv_generation_total_kwh": 10.0,
            "initial_soc_policy": "random_uniform",
            "initial_soc_min_ratio": 0.1,
            "initial_soc_max_ratio": 0.9,
            "initial_soc_random_seed": 12345,
        },
    )

    statuses = {row["check_name"]: row["status"] for row in artifacts.data_flow_validation}
    assert statuses["pv_generation_matches_pv_timeseries"] == "OK"
    assert statuses["pv_generation_matches_depot_energy_flows"] == "OK"
    assert statuses["pv_generation_balance"] == "OK"
    assert statuses["kpi_pv_generation_matches_energy_flow_ledger"] == "OK"
    assert statuses["co2_total_equals_grid_plus_ice"] == "OK"
    assert statuses["kpi_total_co2_matches_co2_ledger"] == "OK"
    assert statuses["fuel_timeseries_matches_vehicle_fuel_ledger"] == "OK"
    assert statuses["fuel_cost_matches_fuel_consumption"] == "OK"
    assert statuses["ice_co2_matches_fuel_consumption"] == "OK"
    assert statuses["initial_soc_within_configured_range"] == "OK"
    assert artifacts.energy_flow_ledger[0].pv_generation_kwh == pytest.approx(10.0)
    assert artifacts.summary["energy"]["pv_generation_kwh"] == pytest.approx(10.0)
    assert artifacts.summary["cost"]["grid_purchase_cost_jpy"] == pytest.approx(100.0)
    assert artifacts.summary["co2"]["grid_co2_kg"] == pytest.approx(2.5)
    assert artifacts.summary["co2"]["ice_co2_kg"] == pytest.approx(5.0)
    assert artifacts.summary["co2"]["total_co2_kg"] == pytest.approx(7.5)
    assert artifacts.summary["metadata"]["initial_soc_random_seed"] == 12345


def test_soc_violation_sets_physical_feasibility_false() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s", timestep_min=60),
        dispatch_context=None,
        trips=(),
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                initial_soc=5.0,
                battery_capacity_kwh=100.0,
                reserve_soc=20.0,
            ),
        ),
    )

    artifacts = build_accounting_artifacts(
        problem=problem,
        scenario_id="s",
        run_id="r",
        service_date=date(2026, 1, 1),
        weather_date=date(2026, 1, 1),
        operator_id="op-1",
        trip_assignment_rows=[],
        vehicle_soc_timeseries_rows=[],
        vehicle_charging_source_rows=[
            {
                "date": "2026-01-01",
                "time": "00:00",
                "vehicle_id": "bev-1",
                "total_charge_kwh": 0.0,
            }
        ],
        energy_flow_rows=[],
        metadata={"slot_minutes": 60, "operator_id": "op-1"},
    )

    assert artifacts.summary["physical_feasibility_status"] == "SOC_VIOLATION"
    assert artifacts.summary["is_physically_feasible"] is False
    assert artifacts.summary["has_soc_violation"] is True
    assert artifacts.summary["metadata"]["physical_feasibility_status"] == "SOC_VIOLATION"
