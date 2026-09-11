"""The finite-fuel seed is a pre-solve candidate, with immutable inputs."""
from dataclasses import replace

import pytest

from src.dispatch.models import DutyLeg, VehicleDuty
from src.optimization.common.problem import AssignmentPlan, OptimizationConfig, OptimizationMode
from src.optimization.engine import OptimizationEngine
from src.optimization.milp.solver_adapter import GurobiMILPAdapter
from test_daily_return_policy import daily_problem


def _mixed_problem_with_overdrawn_ice_baseline():
    base = daily_problem()
    ice = replace(base.vehicles[0], vehicle_id="ice-1", vehicle_type="ICE",
                  initial_soc=None, battery_capacity_kwh=None, reserve_soc=None,
                  initial_fuel_l=9.0, fuel_tank_capacity_l=40.0, fuel_reserve_l=1.0,
                  fuel_consumption_l_per_km=0.1, energy_consumption_kwh_per_km=0.1)
    canonical = tuple(replace(trip, allowed_vehicle_types=("BEV", "ICE"),
                              fuel_l=4.0, fuel_l_by_vehicle_type={"ICE": 4.0}) for trip in base.trips)
    dispatch = [replace(trip, allowed_vehicle_types=("BEV", "ICE")) for trip in base.dispatch_context.trips]
    ice_profile = replace(base.dispatch_context.vehicle_profiles["BEV"], vehicle_type="ICE",
                          fuel_tank_capacity_l=40.0, fuel_consumption_l_per_km=0.1)
    duty = VehicleDuty("seed-path", "ICE", tuple(DutyLeg(trip) for trip in dispatch))
    baseline = AssignmentPlan(duties=(duty,), served_trip_ids=tuple(trip.trip_id for trip in canonical),
                              metadata={"duty_vehicle_map": {duty.duty_id: ice.vehicle_id}})
    return replace(base, trips=canonical, vehicles=base.vehicles + (ice,),
                   vehicle_types=base.vehicle_types + (replace(base.vehicle_types[0], vehicle_type_id="ICE",
                                                               powertrain_type="ICE", fuel_consumption_l_per_km=0.1),),
                   dispatch_context=replace(base.dispatch_context, trips=dispatch,
                                            vehicle_profiles={**base.dispatch_context.vehicle_profiles, "ICE": ice_profile}),
                   baseline_plan=baseline, metadata={**base.metadata, "max_start_fragments_per_vehicle": 100,
                                                       "max_end_fragments_per_vehicle": 100})


def test_pre_solve_seed_moves_whole_path_without_mutating_fleet_or_timetable():
    problem = _mixed_problem_with_overdrawn_ice_baseline()
    seeded = GurobiMILPAdapter()._problem_with_finite_fuel_warm_start(problem)

    assert problem.baseline_plan.vehicle_paths() == {"ice-1": tuple(trip.trip_id for trip in problem.trips)}
    assert seeded.baseline_plan.vehicle_paths() == {"bev-1": tuple(trip.trip_id for trip in problem.trips)}
    assert seeded.trips is problem.trips
    assert seeded.vehicles is problem.vehicles
    assert seeded.dispatch_context is problem.dispatch_context
    assert seeded.metadata["pre_solve_finite_fuel_seed"]["replacement_by_source_vehicle"] == {"ice-1": "bev-1"}
    assert not seeded.baseline_plan.charging_slots and not seeded.baseline_plan.refuel_slots


def test_native_model_validates_the_finite_fuel_seed_with_original_resources():
    pytest.importorskip("gurobipy")
    problem = _mixed_problem_with_overdrawn_ice_baseline()
    result = OptimizationEngine().solve(problem, OptimizationConfig(
        mode=OptimizationMode.MILP, phase="phase3_two_stage", time_limit_sec=25,
        stage1_time_limit_sec=15, stage2_time_limit_sec=10, mip_gap=0,
        gurobi_threads=1, warm_start=True, allow_postsolve_repair=False,
    ))
    assert result.feasible, result.infeasibility_reasons
    assert result.solver_metadata["pre_solve_finite_fuel_seed"]["applied"]
    assert result.solver_metadata["stage2_ice_fuel_inventory_audit"]["accepted"]
    assert set(result.plan.served_trip_ids) == {trip.trip_id for trip in problem.trips}
    assert not result.plan.refuel_slots


def test_unavailable_ice_does_not_add_a_fuel_budget_or_change_the_active_solve():
    pytest.importorskip("gurobipy")
    base = daily_problem()
    disabled = replace(base.vehicles[0], vehicle_id="disabled-ice", vehicle_type="ICE",
                       available=False, initial_fuel_l=0.0, fuel_tank_capacity_l=40.0,
                       fuel_reserve_l=5.0, fuel_consumption_l_per_km=0.1)
    problem = replace(base, vehicles=base.vehicles + (disabled,), metadata={
        **base.metadata, "max_start_fragments_per_vehicle": 100,
        "max_end_fragments_per_vehicle": 100,
    })
    result = OptimizationEngine().solve(problem, OptimizationConfig(
        mode=OptimizationMode.MILP, phase="phase3_two_stage", time_limit_sec=25,
        stage1_time_limit_sec=15, stage2_time_limit_sec=10, mip_gap=0,
        gurobi_threads=1, warm_start=False, allow_postsolve_repair=False,
    ))
    assert result.feasible, result.infeasibility_reasons
    assert "disabled-ice" not in result.plan.vehicle_paths()
    assert not result.solver_metadata["stage1_ice_fuel_inventory_audit"]["usable_initial_fuel_l_by_vehicle"]
    assert result.solver_metadata["stage1_ice_fuel_inventory_audit"]["excluded_unavailable_vehicles"] == [
        {"vehicle_id": "disabled-ice", "reason": "vehicle.available=false"},
    ]


def test_stale_baseline_with_unavailable_ice_is_rejected_before_fuel_validation():
    base = _mixed_problem_with_overdrawn_ice_baseline()
    problem = replace(base, vehicles=tuple(
        replace(vehicle, available=False, initial_fuel_l=-1.0)
        if vehicle.vehicle_id == "ice-1" else vehicle for vehicle in base.vehicles
    ))
    seeded = GurobiMILPAdapter()._problem_with_finite_fuel_warm_start(problem)
    assert seeded.baseline_plan is problem.baseline_plan
    assert seeded.metadata["pre_solve_finite_fuel_seed"] == {
        "applied": False, "reason": "baseline_uses_unavailable_vehicle", "vehicle_ids": ["ice-1"],
    }
