"""Native Phase 3 regression tests for materialized ICE fuel inventories."""

from dataclasses import replace

import pytest

from src.gurobi_runtime import is_gurobi_available
from src.dispatch.models import DutyLeg, VehicleDuty
from src.optimization.common.problem import AssignmentPlan, OptimizationConfig, OptimizationMode
from src.optimization.common.result import ResultSerializer
from src.optimization.engine import OptimizationEngine
from src.optimization.milp.solver_adapter import (
    GurobiMILPAdapter,
    ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT,
    _stage2_slot_indices,
)
from src.optimization.validation.physical_event_schedule import validate_physical_event_schedule
from test_daily_return_policy import daily_problem


pytestmark = pytest.mark.skipif(
    not is_gurobi_available(), reason="Gurobi required for native Phase 3 regression"
)


def _ice_phase3_problem(
    *,
    vehicle_count: int = 1,
    initial_fuel_l: float = 20.0,
    reserve_fuel_l: float = 5.0,
    trip_fuel_l: float = 4.0,
    tank_capacity_l: float = 40.0,
):
    """Build a small daily-return case with explicit ICE inventory records."""
    base = daily_problem()
    trips = tuple(
        replace(
            trip,
            allowed_vehicle_types=("ICE",),
            fuel_l=trip_fuel_l,
            fuel_l_by_vehicle_type={"ICE": trip_fuel_l},
        )
        for trip in base.trips
    )
    dispatch_trips = tuple(
        replace(trip, allowed_vehicle_types=("ICE",))
        for trip in base.dispatch_context.trips
    )
    context = replace(
        base.dispatch_context,
        trips=dispatch_trips,
        vehicle_profiles={
            "ICE": replace(
                base.dispatch_context.vehicle_profiles["BEV"],
                vehicle_type="ICE",
                fuel_tank_capacity_l=tank_capacity_l,
                fuel_consumption_l_per_km=0.1,
                battery_capacity_kwh=None,
                energy_consumption_kwh_per_km=None,
            )
        },
    )
    template = replace(
        base.vehicles[0],
        vehicle_type="ICE",
        initial_soc=None,
        battery_capacity_kwh=None,
        reserve_soc=None,
        initial_fuel_l=initial_fuel_l,
        fuel_tank_capacity_l=tank_capacity_l,
        fuel_reserve_l=reserve_fuel_l,
        fuel_consumption_l_per_km=0.1,
        energy_consumption_kwh_per_km=None,
        charge_power_max_kw=None,
    )
    vehicles = tuple(
        replace(template, vehicle_id=f"ice-{index + 1}")
        for index in range(vehicle_count)
    )
    vehicle_type = replace(
        base.vehicle_types[0],
        vehicle_type_id="ICE",
        powertrain_type="ICE",
        battery_capacity_kwh=None,
        reserve_soc=None,
        fuel_tank_capacity_l=tank_capacity_l,
        fuel_consumption_l_per_km=0.1,
        energy_consumption_kwh_per_km=None,
    )
    flags = dict(base.metadata.get("cost_component_flags") or {})
    flags.update({"fuel_cost": False, "co2_cost": False})
    return replace(
        base,
        trips=trips,
        dispatch_context=context,
        vehicles=vehicles,
        vehicle_types=(vehicle_type,),
        metadata={
            **base.metadata,
            "cost_component_flags": flags,
            # Deliberately conflicting with the materialized 20 L record.
            "initial_ice_fuel_percent": 100.0,
            "min_ice_fuel_percent": 10.0,
            "max_ice_fuel_percent": 90.0,
            "stage1_exact_depot_connection_factors": False,
            "max_start_fragments_per_vehicle": 100,
            "max_end_fragments_per_vehicle": 100,
        },
    )


def _solve(problem):
    return OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase3_two_stage",
            time_limit_sec=20,
            stage1_time_limit_sec=12,
            stage2_time_limit_sec=8,
            mip_gap=0.0,
            gurobi_threads=1,
            random_seed=42,
            warm_start=False,
            allow_postsolve_repair=False,
        ),
    )


def _fixed_ice_plan(problem):
    duty_id = "ice-1:0"
    duty = VehicleDuty(
        duty_id,
        "ICE",
        tuple(
            DutyLeg(trip, deadhead_from_prev_min=30 if index == 0 else 90)
            for index, trip in enumerate(problem.dispatch_context.trips)
        ),
    )
    return AssignmentPlan(
        duties=(duty,),
        served_trip_ids=tuple(trip.trip_id for trip in problem.trips),
        metadata={"duty_vehicle_map": {duty_id: "ice-1"}},
    )


def _factor_native_ice_tight_problem():
    """Convert the six-trip factor fixture to two identical ICE vehicles."""
    from test_milp_depot_factor_native import factor_native_problem

    base = factor_native_problem()
    trips = tuple(
        replace(
            trip,
            allowed_vehicle_types=("ICE",),
            fuel_l=20.0,
            fuel_l_by_vehicle_type={"ICE": 20.0},
        )
        for trip in base.trips
    )
    dispatch_trips = tuple(
        replace(trip, allowed_vehicle_types=("ICE",))
        for trip in base.dispatch_context.trips
    )
    template = replace(
        base.vehicles[0],
        vehicle_type="ICE",
        initial_fuel_l=100.0,
        fuel_tank_capacity_l=120.0,
        fuel_reserve_l=10.0,
        fuel_consumption_l_per_km=0.3,
    )
    vehicle_type = replace(
        base.vehicle_types[0],
        vehicle_type_id="ICE",
        powertrain_type="ICE",
        fuel_tank_capacity_l=120.0,
        fuel_consumption_l_per_km=0.3,
    )
    context = replace(
        base.dispatch_context,
        trips=dispatch_trips,
        vehicle_profiles={
            "ICE": replace(
                base.dispatch_context.vehicle_profiles["BEV"],
                vehicle_type="ICE",
                fuel_tank_capacity_l=120.0,
                fuel_consumption_l_per_km=0.3,
            )
        },
    )
    return replace(
        base,
        trips=trips,
        dispatch_context=context,
        vehicles=(replace(template, vehicle_id="ice-1"), replace(template, vehicle_id="ice-2")),
        vehicle_types=(vehicle_type,),
        metadata={
            **base.metadata,
            "max_start_fragments_per_vehicle": 100,
            "max_end_fragments_per_vehicle": 100,
            "stage1_exact_depot_connection_factors": False,
        },
    )


def test_phase3_rejects_insufficient_materialized_fuel_even_when_costs_are_disabled():
    problem = _ice_phase3_problem(
        vehicle_count=1,
        initial_fuel_l=9.0,
        reserve_fuel_l=1.0,
        trip_fuel_l=4.0,
    )

    result = _solve(problem)

    assert not result.feasible
    audit = result.solver_metadata["stage1_ice_fuel_inventory_audit"]
    assert audit["refueling_policy"] == "no_refueling"
    assert audit["usable_initial_fuel_l_by_vehicle"] == {"ice-1": pytest.approx(8.0)}
    assert audit["constraint_count"] == 1


def test_phase3_keeps_prepared_144_liters_and_16_liter_reserve():
    problem = _ice_phase3_problem(
        vehicle_count=1,
        initial_fuel_l=144.0,
        reserve_fuel_l=16.0,
        trip_fuel_l=4.0,
        tank_capacity_l=160.0,
    )

    result = _solve(problem)

    assert result.feasible, result.infeasibility_reasons
    audit = result.solver_metadata["stage1_ice_fuel_inventory_audit"]
    assert audit["usable_initial_fuel_l_by_vehicle"] == {
        "ice-1": pytest.approx(128.0),
    }


def test_phase3_splits_work_across_ice_vehicles_without_exceeding_each_budget():
    problem = _ice_phase3_problem(
        vehicle_count=2,
        initial_fuel_l=9.0,
        reserve_fuel_l=1.0,
        trip_fuel_l=4.0,
    )

    result = _solve(problem)

    assert result.feasible, result.infeasibility_reasons
    assert set(result.plan.served_trip_ids) == {trip.trip_id for trip in problem.trips}
    assigned_counts = {
        vehicle_id: sum(
            1
            for duty in result.plan.duties
            if result.plan.vehicle_id_for_duty(duty.duty_id) == vehicle_id
            for _leg in duty.legs
        )
        for vehicle_id in ("ice-1", "ice-2")
    }
    assert assigned_counts == {"ice-1": 1, "ice-2": 1}
    audit = result.solver_metadata["stage1_ice_fuel_inventory_audit"]
    assert audit["usable_initial_fuel_l_by_vehicle"] == {
        "ice-1": pytest.approx(8.0),
        "ice-2": pytest.approx(8.0),
    }


@pytest.mark.parametrize("factored", [False, True])
def test_phase3_factor_toggle_preserves_materialized_ice_inventory(factored):
    problem = _ice_phase3_problem(
        vehicle_count=2,
        initial_fuel_l=30.0,
        reserve_fuel_l=5.0,
        trip_fuel_l=4.0,
    )
    problem = replace(
        problem,
        metadata={
            **problem.metadata,
            "stage1_exact_depot_connection_factors": factored,
        },
    )

    result = _solve(problem)

    assert result.feasible, result.infeasibility_reasons
    audit = result.solver_metadata["stage1_ice_fuel_inventory_audit"]
    assert audit["usable_initial_fuel_l_by_vehicle"] == {
        "ice-1": pytest.approx(25.0),
        "ice-2": pytest.approx(25.0),
    }
    assert audit["refueling_policy"] == "no_refueling"


def test_phase3_factor_on_and_off_have_the_same_fuel_budget_and_coverage():
    results = []
    for factored in (False, True):
        problem = _ice_phase3_problem(
            vehicle_count=2,
            initial_fuel_l=30.0,
            reserve_fuel_l=5.0,
            trip_fuel_l=4.0,
        )
        problem = replace(
            problem,
            metadata={
                **problem.metadata,
                "stage1_exact_depot_connection_factors": factored,
            },
        )
        results.append(_solve(problem))

    assert all(result.feasible for result in results), [
        result.infeasibility_reasons for result in results
    ]
    assert [set(result.plan.served_trip_ids) for result in results] == [
        set(results[0].plan.served_trip_ids)
    ] * 2
    assert [
        result.solver_metadata["stage1_ice_fuel_inventory_audit"][
            "usable_initial_fuel_l_by_vehicle"
        ]
        for result in results
    ] == [
        {"ice-1": pytest.approx(25.0), "ice-2": pytest.approx(25.0)},
    ] * 2


def test_phase3_factor_fuel_terms_match_explicit_six_trip_ice_network():
    results = []
    for factored in (False, True):
        problem = _factor_native_ice_tight_problem()
        problem = replace(
            problem,
            metadata={
                **problem.metadata,
                "stage1_exact_depot_connection_factors": factored,
            },
        )
        result = _solve(problem)
        assert result.feasible, result.infeasibility_reasons
        assert set(result.plan.served_trip_ids) == {trip.trip_id for trip in problem.trips}
        physical = validate_physical_event_schedule(
            problem=problem,
            serialized_result=ResultSerializer.serialize_plan(result.plan),
        )
        assert physical["accepted"], physical["violations"]
        results.append(result)

        factor_audit = result.solver_metadata["depot_connection_factor_audit"]
        if factored:
            assert factor_audit["applied"] is True
            assert factor_audit["factor_count"] > 0

    assert results[0].cost_breakdown["total_cost"] == pytest.approx(
        results[1].cost_breakdown["total_cost"], abs=1e-6
    )
    assert set(results[0].plan.served_trip_ids) == set(results[1].plan.served_trip_ids)


def test_stage2_rejects_overloaded_fixed_ice_plan_without_a_feasible_incumbent():
    problem = _ice_phase3_problem(
        vehicle_count=1,
        initial_fuel_l=9.0,
        reserve_fuel_l=1.0,
        trip_fuel_l=4.0,
    )
    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase1_charging_only",
            fixed_assignment=_fixed_ice_plan(problem),
            time_limit_sec=20,
            stage2_time_limit_sec=8,
            mip_gap=0.0,
            gurobi_threads=1,
            allow_postsolve_repair=False,
        ),
    )

    assert not result.feasible
    assert result.solver_metadata["stage2_has_feasible_incumbent"] is False
    assert result.solver_metadata["stage2_solver_status"] == "fixed_ice_fuel_inventory_infeasible"
    audit = result.solver_metadata["stage2_ice_fuel_inventory_audit"]
    assert audit["accepted"] is False
    assert audit["vehicles"]["ice-1"]["consumed_fuel_l"] == pytest.approx(13.4)


def test_rolling_fixed_ice_audit_excludes_fuel_consumed_outside_the_window():
    problem = _ice_phase3_problem(
        vehicle_count=1,
        initial_fuel_l=30.0,
        reserve_fuel_l=1.0,
        trip_fuel_l=4.0,
    )
    plan = _fixed_ice_plan(problem)
    config = OptimizationConfig(
        rolling_horizon_policy=ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT,
        rolling_current_min=24 * 60,
        rolling_lookahead_hours=24,
    )
    slots = _stage2_slot_indices(problem, config, list(range(48)))
    assert slots == tuple(range(24, 48))

    audit = GurobiMILPAdapter()._fixed_ice_fuel_inventory_audit(
        problem, plan, slots
    )

    assert audit["accepted"] is True
    assert audit["vehicles"]["ice-1"]["consumed_fuel_l"] == pytest.approx(6.7)
    assert audit["vehicles"]["ice-1"]["terminal_fuel_l"] == pytest.approx(23.3)
