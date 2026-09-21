"""The finite-fuel seed is a pre-solve candidate, with immutable inputs."""
from dataclasses import replace
from pathlib import Path

import pytest

from src.dispatch.models import DutyLeg, VehicleDuty
from src.optimization.common.problem import AssignmentPlan, OptimizationConfig, OptimizationMode
from src.optimization.engine import OptimizationEngine
from src.optimization.milp.solver_adapter import (
    GurobiMILPAdapter,
    _FEEDBACK_GLOBAL_DEADLINE_KEY,
)
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


def _mixed_problem_with_high_and_lower_initial_soc_bevs():
    problem = _mixed_problem_with_overdrawn_ice_baseline()
    high_initial = replace(
        problem.vehicles[0],
        initial_soc=100.0,
        charge_power_max_kw=0.0,
    )
    lower_initial = replace(
        problem.vehicles[0],
        vehicle_id="bev-low",
        initial_soc=50.0,
        charge_power_max_kw=60.0,
    )
    return replace(problem, vehicles=(high_initial, lower_initial, problem.vehicles[1]))


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


def test_energy_audit_rejects_high_initial_terminal_deficit_and_selects_lower_initial_bev():
    problem = _mixed_problem_with_high_and_lower_initial_soc_bevs()
    seeded = GurobiMILPAdapter()._problem_with_finite_fuel_warm_start(problem)

    assert seeded.baseline_plan.vehicle_paths() == {
        "bev-low": tuple(trip.trip_id for trip in problem.trips),
    }
    seed_metadata = seeded.metadata["pre_solve_finite_fuel_seed"]
    rejected = seed_metadata["rejected_energy_candidates"]
    assert rejected[0]["candidate_vehicle_id"] == "bev-1"
    assert rejected[0]["terminal_shortage_kwh"] == pytest.approx(74.0)
    assert seed_metadata["accepted_energy_candidates"]["bev-low"]["screen_verdict"] == (
        "OPTIMISTIC_BOUND_PASSED"
    )

    assert problem.baseline_plan.vehicle_paths() == {
        "ice-1": tuple(trip.trip_id for trip in problem.trips),
    }
    assert seeded.trips is problem.trips
    assert seeded.vehicles is problem.vehicles
    assert seeded.dispatch_context is problem.dispatch_context


def test_inconclusive_native_screen_retains_unverified_candidate_for_main_milp(monkeypatch):
    problem = _mixed_problem_with_overdrawn_ice_baseline()
    high_initial = replace(problem.vehicles[0], initial_soc=80.0, charge_power_max_kw=60.0)
    lower_initial = replace(high_initial, vehicle_id="bev-low", initial_soc=70.0)
    problem = replace(
        problem,
        vehicles=(high_initial, lower_initial, problem.vehicles[1]),
        metadata={**problem.metadata, _FEEDBACK_GLOBAL_DEADLINE_KEY: 0.0},
    )
    monkeypatch.setattr(
        "src.optimization.milp.solver_adapter.is_gurobi_available",
        lambda: True,
    )

    seeded = GurobiMILPAdapter()._problem_with_finite_fuel_warm_start(
        problem,
        config=OptimizationConfig(time_limit_sec=5, stage2_time_limit_sec=5),
    )

    assert seeded.baseline_plan.vehicle_paths() == {
        "bev-1": tuple(trip.trip_id for trip in problem.trips),
    }
    selected = seeded.metadata["pre_solve_finite_fuel_seed"]["accepted_energy_candidates"]["bev-1"]
    assert selected["selection"] == "unverified_seed_retained_for_main_milp"
    assert selected["screen_verdict"] == "INCONCLUSIVE"
    assert selected["native_screen_status"] == "global_deadline_exhausted"


@pytest.mark.parametrize('native_logging', [False, True])
def test_native_model_validates_the_finite_fuel_seed_with_original_resources(tmp_path, monkeypatch, native_logging):
    pytest.importorskip("gurobipy")
    problem = _mixed_problem_with_overdrawn_ice_baseline()
    problem = replace(problem, metadata={**problem.metadata,
        'stage2_native_log_enabled': native_logging, 'phase3_diagnostics_dir': str(tmp_path)})
    calls = []
    original = GurobiMILPAdapter._solve_thesis_stage2_charging_dispatch
    def capture(self, local_problem, config, assignment, **kwargs):
        calls.append((kwargs['stage1_status'], dict(local_problem.metadata)))
        return original(self, local_problem, config, assignment, **kwargs)
    monkeypatch.setattr(GurobiMILPAdapter, '_solve_thesis_stage2_charging_dispatch', capture)
    result = OptimizationEngine().solve(problem, OptimizationConfig(
        mode=OptimizationMode.MILP, phase="phase3_two_stage", time_limit_sec=25,
        stage1_time_limit_sec=15, stage2_time_limit_sec=10, mip_gap=0,
        gurobi_threads=1, warm_start=True, allow_postsolve_repair=False, stage2_gurobi_presolve=2,
    ))
    assert result.feasible, result.infeasibility_reasons
    assert result.solver_metadata["pre_solve_finite_fuel_seed"]["applied"]
    assert result.solver_metadata["stage2_ice_fuel_inventory_audit"]["accepted"]
    assert set(result.plan.served_trip_ids) == {trip.trip_id for trip in problem.trips}
    assert not result.plan.refuel_slots
    screens = [metadata for status, metadata in calls if status == 'pre_solve_vehicle_local_seed_screen']
    assert screens, 'The regression must reach the internal native seed screen'
    assert all(metadata['stage2_native_log_enabled'] is False for metadata in screens)
    assert all(metadata['phase3_diagnostics_dir'] == '' for metadata in screens)
    assert problem.metadata['stage2_native_log_enabled'] is native_logging
    assert problem.metadata['phase3_diagnostics_dir'] == str(tmp_path)
    if native_logging:
        assert Path(result.plan.metadata['stage2_native_log_path']).is_file()
    else:
        assert result.plan.metadata['stage2_native_log_path'] is None


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
