from __future__ import annotations

from dataclasses import replace

import pytest

from src.dispatch.models import DispatchContext, Trip, VehicleProfile
from src.gurobi_runtime import is_gurobi_available
from src.optimization import (
    EnergyPriceSlot,
    OptimizationConfig,
    OptimizationEngine,
    OptimizationMode,
    ProblemBuilder,
)
from src.optimization.validation.small_exact_oracle import (
    solve_small_exact_assignment_oracle,
)


def _four_trip_two_vehicle_problem():
    context = DispatchContext(
        service_date="2025-08-05",
        trips=[
            Trip(
                trip_id="high-out",
                route_id="high",
                origin="DEPOT",
                destination="A",
                departure_time="08:00",
                arrival_time="08:20",
                distance_km=20.0,
                allowed_vehicle_types=("ICE",),
                origin_stop_id="DEPOT",
                destination_stop_id="A",
                operator_id="tokyu",
            ),
            Trip(
                trip_id="low-out",
                route_id="low",
                origin="DEPOT",
                destination="B",
                departure_time="08:10",
                arrival_time="08:30",
                distance_km=5.0,
                allowed_vehicle_types=("ICE",),
                origin_stop_id="DEPOT",
                destination_stop_id="B",
                operator_id="tokyu",
            ),
            Trip(
                trip_id="high-in",
                route_id="high",
                origin="A",
                destination="DEPOT",
                departure_time="08:30",
                arrival_time="08:50",
                distance_km=20.0,
                allowed_vehicle_types=("ICE",),
                origin_stop_id="A",
                destination_stop_id="DEPOT",
                operator_id="tokyu",
            ),
            Trip(
                trip_id="low-in",
                route_id="low",
                origin="B",
                destination="DEPOT",
                departure_time="08:40",
                arrival_time="09:00",
                distance_km=5.0,
                allowed_vehicle_types=("ICE",),
                origin_stop_id="B",
                destination_stop_id="DEPOT",
                operator_id="tokyu",
            ),
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "ICE": VehicleProfile(
                vehicle_type="ICE",
                fuel_tank_capacity_l=100.0,
                fuel_consumption_l_per_km=0.1,
            )
        },
        default_turnaround_min=10,
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="small-exact-oracle",
        config=OptimizationConfig(mode=OptimizationMode.MILP),
        vehicle_counts={"ICE": 2},
        price_slots=tuple(EnergyPriceSlot(slot_index=index) for index in range(4)),
        objective_mode="total_cost",
        objective_preset="research_lexicographic_v1",
        diesel_price_yen_per_l=150.0,
        initial_ice_fuel_percent=100.0,
        min_ice_fuel_percent=10.0,
        max_ice_fuel_percent=100.0,
        default_ice_tank_capacity_l=100.0,
        canonical_depot_id="DEPOT",
        timestep_min=60,
        horizon_start_min=7 * 60,
        operation_start_time="07:00",
        operation_end_time="11:00",
        enable_vehicle_cost=False,
        enable_driver_cost=False,
        enable_other_cost=False,
        cost_component_flags={
            "vehicle_fixed_cost": False,
            "vehicle_usage_cost": False,
            "driver_cost": False,
            "electricity_cost": False,
            "fuel_cost": True,
            "demand_charge_cost": False,
            "co2_cost": False,
            "switch_cost": False,
            "battery_degradation_cost": False,
        },
        milp_max_successors_per_trip=None,
        service_coverage_mode="strict",
    )
    vehicles = tuple(
        replace(
            vehicle,
            fuel_consumption_l_per_km=(
                0.1 if str(vehicle.vehicle_id).endswith("001") else 0.2
            ),
            initial_fuel_l=100.0,
            fuel_tank_capacity_l=100.0,
            fuel_reserve_l=10.0,
        )
        for vehicle in problem.vehicles
    )
    return replace(problem, vehicles=vehicles, baseline_plan=None)


def test_small_exact_oracle_matches_hand_calculated_optimum() -> None:
    problem = _four_trip_two_vehicle_problem()

    oracle = solve_small_exact_assignment_oracle(problem)

    assert oracle.enumerated_assignment_count == 16
    assert oracle.feasible_assignment_count == 2
    assert oracle.used_vehicle_day_count == 2
    assert oracle.fuel_l == pytest.approx(6.0)
    assert oracle.fuel_cost_jpy == pytest.approx(900.0)
    assert oracle.canonical_operating_cost_jpy == pytest.approx(900.0)
    efficient_vehicle = next(
        vehicle.vehicle_id
        for vehicle in problem.vehicles
        if vehicle.fuel_consumption_l_per_km == pytest.approx(0.1)
    )
    assert oracle.assignment_by_trip["high-out"] == efficient_vehicle
    assert oracle.assignment_by_trip["high-in"] == efficient_vehicle


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi is required")
def test_integrated_milp_matches_independent_small_exact_oracle() -> None:
    problem = _four_trip_two_vehicle_problem()
    oracle = solve_small_exact_assignment_oracle(problem)

    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            requested_phase="phase4_integrated",
            resolved_phase="phase4_integrated",
            executed_phase="phase4_integrated",
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            integrated_actual_cost_objective=True,
            phase4_phase3_seed_enabled=False,
            research_run=False,
            allow_postsolve_repair=False,
        ),
    )

    assert result.feasible is True
    assert len(result.plan.unserved_trip_ids) == 0
    assert len(result.plan.vehicle_paths()) == oracle.used_vehicle_day_count
    assert result.cost_breakdown["fuel_cost"] == pytest.approx(
        oracle.fuel_cost_jpy, abs=1.0e-6
    )
    assert result.cost_breakdown["total_cost"] == pytest.approx(
        oracle.canonical_operating_cost_jpy, abs=1.0e-6
    )
    assert result.cost_breakdown["ice_co2_kg"] == pytest.approx(
        oracle.fuel_l * problem.scenario.ice_co2_kg_per_l,
        abs=1.0e-6,
    )
    assert result.solver_metadata["integrated_primary_ice_fuel_l"] == (
        pytest.approx(oracle.fuel_l, abs=1.0e-6)
    )
    assert (
        result.solver_metadata["actual_cost_objective_numeric_reconciliation_passed"]
        is True
    )
    assert {
        trip_id: result.plan.vehicle_id_for_duty(duty.duty_id)
        for duty in result.plan.duties
        for trip_id in duty.trip_ids
    } == dict(oracle.assignment_by_trip)
