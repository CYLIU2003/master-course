"""Engine buses refuel at the home depot under ice_refueling_policy=depot_top_up."""

from dataclasses import replace

import pytest

from src.optimization.common.ice_refueling import (
    depot_top_up_refuel_slots,
    ice_refueling_policy,
    replay_fixed_ice_fuel,
)
from src.optimization.common.problem import RefuelSlot
from src.optimization.common.result import ResultSerializer
from src.optimization.common.vehicle_timeline import build_vehicle_timeline, complete_home_slots
from src.optimization.rolling.reoptimizer import assignment_plan_from_serialized_result
from src.optimization.validation.physical_event_schedule import validate_physical_event_schedule
from test_phase3_finite_ice_fuel import _fixed_ice_plan, _ice_phase3_problem, _solve

native = pytest.mark.usefixtures("admitted_gurobi_session")


def _depot(problem):
    return replace(problem, metadata={**problem.metadata, "ice_refueling_policy": "depot_top_up"})


def test_policy_defaults_to_no_refueling_and_rejects_unknown_values():
    problem = _ice_phase3_problem()
    assert ice_refueling_policy(problem) == "no_refueling"
    with pytest.raises(ValueError):
        ice_refueling_policy(replace(problem, metadata={**problem.metadata, "ice_refueling_policy": "anywhere"}))


def test_rule_fills_the_tank_at_home_only_when_the_next_leg_would_break_the_reserve():
    # 9 L start, 1 L reserve, 40 L tank, 6.7 L per service day (as in the no-refuel audit test).
    problem = _depot(_ice_phase3_problem(initial_fuel_l=9.0, reserve_fuel_l=1.0, trip_fuel_l=4.0))
    plan = _fixed_ice_plan(problem)

    slots = depot_top_up_refuel_slots(problem, plan)

    assert len(slots) == 1
    (slot,) = slots
    vehicle = problem.vehicles[0]
    events = build_vehicle_timeline(problem, plan)["ice-1"]
    assert slot.slot_index in complete_home_slots(problem, vehicle, events)
    assert slot.location_id == vehicle.home_depot_id
    assert slot.refuel_liters == pytest.approx(40.0 - (9.0 - 6.7))
    replay = replay_fixed_ice_fuel(problem, replace(plan, refuel_slots=slots), 0, 48)
    assert replay["violations"] == []
    assert replay["vehicles"]["ice-1"]["minimum_fuel_l"] >= 1.0 - 1e-9
    assert replay["vehicles"]["ice-1"]["refueled_l"] == pytest.approx(slot.refuel_liters)


def test_rule_does_not_refuel_when_the_initial_fuel_is_enough():
    problem = _depot(_ice_phase3_problem(initial_fuel_l=30.0, reserve_fuel_l=1.0, trip_fuel_l=4.0))
    assert depot_top_up_refuel_slots(problem, _fixed_ice_plan(problem)) == ()


def test_rule_raises_when_one_leg_needs_more_than_the_usable_tank():
    problem = _depot(_ice_phase3_problem(initial_fuel_l=5.0, reserve_fuel_l=1.0, trip_fuel_l=4.0,
                                         tank_capacity_l=6.0))
    with pytest.raises(ValueError, match="above the usable tank"):
        depot_top_up_refuel_slots(problem, _fixed_ice_plan(problem))


def test_replay_rejects_refuels_away_from_home_and_above_the_tank():
    problem = _depot(_ice_phase3_problem(initial_fuel_l=9.0, reserve_fuel_l=1.0, trip_fuel_l=4.0))
    plan = _fixed_ice_plan(problem)
    vehicle = problem.vehicles[0]
    home = complete_home_slots(problem, vehicle, build_vehicle_timeline(problem, plan)["ice-1"])
    away = next(slot for slot in range(48) if slot not in home)
    bad = replace(plan, refuel_slots=(RefuelSlot("ice-1", away, 1.0, vehicle.home_depot_id),
                                      RefuelSlot("ice-1", min(home), 100.0, vehicle.home_depot_id)))
    violations = replay_fixed_ice_fuel(problem, bad, 0, 48)["violations"]
    assert any("outside_a_complete_home_slot" in item for item in violations)
    assert any("fuel_range" in item for item in violations)


@native
def test_phase3_with_depot_refueling_serves_what_no_refueling_cannot():
    base = _ice_phase3_problem(vehicle_count=1, initial_fuel_l=9.0, reserve_fuel_l=1.0, trip_fuel_l=4.0)
    assert not _solve(base).feasible

    problem = _depot(base)
    result = _solve(problem)

    assert result.feasible, result.infeasibility_reasons
    assert set(result.plan.served_trip_ids) == {trip.trip_id for trip in problem.trips}
    stage1 = result.solver_metadata["stage1_ice_fuel_inventory_audit"]
    assert stage1["refueling_policy"] == "depot_top_up"
    assert stage1["usable_tank_per_service_day_l_by_vehicle"] == {"ice-1": pytest.approx(39.0)}
    assert stage1["constraint_count"] >= 1
    stage2 = result.solver_metadata["stage2_ice_fuel_inventory_audit"]
    assert stage2["refueling_policy"] == "depot_top_up" and stage2["accepted"] is True
    assert result.plan.refuel_slots == depot_top_up_refuel_slots(problem, result.plan)
    assert result.plan.refuel_slots
    physical = validate_physical_event_schedule(
        problem=problem, serialized_result=ResultSerializer.serialize_plan(result.plan))
    assert physical["accepted"], physical["violations"]


@native
def test_phase3_daily_tank_bound_still_rejects_a_day_beyond_one_tank():
    problem = _depot(_ice_phase3_problem(vehicle_count=1, initial_fuel_l=5.0, reserve_fuel_l=1.0,
                                         trip_fuel_l=4.0, tank_capacity_l=6.0))
    assert not _solve(problem).feasible


def test_rolling_restore_keeps_the_day_ahead_refueling_decisions():
    problem = _depot(_ice_phase3_problem(initial_fuel_l=9.0, reserve_fuel_l=1.0, trip_fuel_l=4.0))
    plan = _fixed_ice_plan(problem)
    plan = replace(plan, refuel_slots=depot_top_up_refuel_slots(problem, plan))

    restored = assignment_plan_from_serialized_result(problem, ResultSerializer.serialize_plan(plan))

    assert restored.refuel_slots == plan.refuel_slots
