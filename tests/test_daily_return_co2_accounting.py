"""Carbon accounting must use the same physical liters as weekly fuel costs."""
from dataclasses import replace

import pytest

from src.dispatch.models import DutyLeg, VehicleDuty
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import AssignmentPlan
from src.optimization.common.vehicle_timeline import build_vehicle_timeline
from test_phase3_finite_ice_fuel import _ice_phase3_problem, _fixed_ice_plan, _solve


def expected_emissions(problem, plan):
    vehicles = {vehicle.vehicle_id:vehicle for vehicle in problem.vehicles}
    types = {item.vehicle_type_id: item for item in problem.vehicle_types}
    return sum(sum(event.fuel_l for event in events)
               * (types[vehicles[vehicle].vehicle_type].co2_emission_kg_per_l
                  or problem.scenario.ice_co2_kg_per_l)
               for vehicle, events in build_vehicle_timeline(problem, plan).items())


@pytest.mark.parametrize('price', [0, 3])
def test_daily_carbon_uses_physical_movements_not_duty_deadhead_annotations(price):
    problem = _ice_phase3_problem()
    problem = replace(problem, scenario=replace(problem.scenario, co2_price_per_kg=price))
    original = _fixed_ice_plan(problem)
    # The daily timeline reconstructs mandatory start/return movements from
    # the declared paths. Legacy duty annotations are not that event ledger.
    annotated = replace(original, duties=tuple(replace(duty, legs=tuple(
        replace(leg, deadhead_from_prev_min=0) for leg in duty.legs)) for duty in original.duties))
    assert build_vehicle_timeline(problem, original) == build_vehicle_timeline(problem, annotated)
    expected = expected_emissions(problem, annotated)
    evaluator = CostEvaluator()
    physical_liters = sum(event[3] for event in evaluator._collect_fuel_drive_events(problem, annotated))
    assert expected == pytest.approx(physical_liters*problem.scenario.ice_co2_kg_per_l)
    assert evaluator._co2_breakdown_kg(problem, annotated, {})['ice_co2_kg'] == pytest.approx(expected)


def test_daily_carbon_uses_each_materialized_vehicle_emission_factor():
    problem = _ice_phase3_problem(vehicle_count=2)
    first, second = problem.vehicles
    second = replace(second, vehicle_type='ICE-special')
    types = (replace(problem.vehicle_types[0], co2_emission_kg_per_l=2.1),
             replace(problem.vehicle_types[0], vehicle_type_id='ICE-special', co2_emission_kg_per_l=3.2))
    problem = replace(problem, vehicles=(first, second), vehicle_types=types)
    duties = tuple(VehicleDuty(f'duty-{i}', vehicle.vehicle_type, (DutyLeg(trip),))
                   for i,(vehicle,trip) in enumerate(zip(problem.vehicles,problem.dispatch_context.trips)))
    plan = AssignmentPlan(duties=duties,served_trip_ids=tuple(t.trip_id for t in problem.trips),
        metadata={'duty_vehicle_map':{d.duty_id:v.vehicle_id for d,v in zip(duties,problem.vehicles)}})
    result = CostEvaluator()._co2_breakdown_kg(problem,plan,{})
    assert result['ice_co2_kg'] == pytest.approx(expected_emissions(problem,plan))


def test_native_two_day_fuel_and_co2_account_for_the_same_movements():
    pytest.importorskip('gurobipy')
    problem = _ice_phase3_problem()
    problem = replace(problem, metadata={**problem.metadata,'cost_component_flags':{
        **problem.metadata['cost_component_flags'],'fuel_cost':True,'co2_cost':True}})
    result = _solve(problem)
    assert result.feasible, result.infeasibility_reasons
    assert result.cost_breakdown['ice_co2_kg'] == pytest.approx(expected_emissions(problem,result.plan))
    assert result.cost_breakdown['ice_co2_kg'] == pytest.approx(
        result.cost_breakdown['ice_fuel_consumed_l']*problem.scenario.ice_co2_kg_per_l)
