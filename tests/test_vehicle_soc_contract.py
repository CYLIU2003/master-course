from dataclasses import replace

import pytest

from src.dispatch.models import DispatchContext
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import CanonicalOptimizationProblem, ChargerDefinition, OptimizationScenario, ProblemVehicle
from src.optimization.common.soc_helpers import effective_final_soc_target_kwh, vehicle_initial_soc_kwh
from src.optimization.common.vehicle_soc_contract import resolve_vehicle_soc_contract
from src.optimization.rolling.reoptimizer import RollingReoptimizer
from src.optimization.milp.solver_adapter import _problem_vehicle_symmetry_signature
from src.optimization.validation.physical_event_schedule import validate_physical_event_schedule


def _problem(vehicle: ProblemVehicle, **metadata) -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id='bounds', timestep_min=15, horizon_start='00:00'),
        dispatch_context=DispatchContext(service_date='2025-08-05', trips=[], turnaround_rules={}, deadhead_rules={}, vehicle_profiles={}),
        trips=(), vehicles=(vehicle,), chargers=(ChargerDefinition('c1', 'depot', 90),), metadata=metadata,
    )


def _vehicle(**changes) -> ProblemVehicle:
    return replace(ProblemVehicle('v1','BEV','depot', initial_soc=72, battery_capacity_kwh=100,
                                  reserve_soc=10, maximum_soc_kwh=90, soc_input_unit='kwh', charge_power_max_kw=90), **changes)


@pytest.mark.parametrize('record', [
    {'initialSoc': .8, 'minSoc': .1, 'maxSoc': .9},
    {'initialSoc': 80, 'minSoc': 10, 'maxSoc': 90},
    {'initial_soc_kwh': 240, 'minimum_soc_kwh':30, 'maximum_soc_kwh':270},
])
def test_ratio_percentage_and_explicit_kwh_agree(record):
    contract = resolve_vehicle_soc_contract(record,300)
    assert (contract.initial_kwh, contract.minimum_kwh, contract.maximum_kwh) == (240,30,270)


@pytest.mark.parametrize('record', [
    {'initialSoc':.95,'maxSoc':.9}, {'initialSoc':-.1}, {'initialSoc':float('nan')},
    {'initialSoc':True}, {'initialSoc':.8,'maxSoc':101}, {'initialSoc':.8,'minSoc':.9},
    {'initialSoc':.8,'initial_soc_kwh':100}, {'initialSoc':.8,'maxSoc':float('inf')},
])
def test_invalid_initial_state_or_bound_is_never_clipped(record):
    with pytest.raises(ValueError):
        resolve_vehicle_soc_contract(record,300)


def test_builder_preserves_different_vehicle_bounds():
    vehicles = list(ProblemBuilder()._build_vehicles_from_records(
        [{'id':'v1','type':'BEV','batteryKwh':100,'initialSoc':.7,'minSoc':.1,'maxSoc':.9},
         {'id':'v2','type':'BEV','batteryKwh':200,'initialSoc':.6,'minSoc':.2,'maxSoc':.75}],
        {}, default_home_depot_id='depot', disable_vehicle_acquisition_cost=True,
    ))
    assert [(v.initial_soc,v.reserve_soc,v.maximum_soc_kwh,v.soc_input_unit) for v in vehicles] == [
        (70,10,90,'kwh'), (120,40,150,'kwh')]


def test_independent_replay_rejects_93_375_percent_on_90_percent_vehicle():
    problem = _problem(_vehicle())
    report = validate_physical_event_schedule(problem=problem, serialized_result={
        'vehicle_paths':{}, 'charging_schedule':[{'vehicle_id':'v1','charger_id':'c1',
            'charging_depot_id':'depot','slot_index':0,'charge_kw':90,'discharge_kw':0}],
    })
    assert report['status'] == 'INVALID'
    assert report['metrics']['ev_soc_upper_violation_count'] == 1
    assert report['vehicle_soc_events'][-1]['soc_after_kwh'] == pytest.approx(93.375)
    assert report['vehicle_soc_events'][-1]['maximum_soc_kwh'] == 90


def test_unused_vehicle_initial_upper_violation_is_checked():
    report = validate_physical_event_schedule(problem=_problem(_vehicle(initial_soc=95)), serialized_result={'vehicle_paths':{}, 'charging_schedule':[]})
    assert report['metrics']['ev_soc_upper_violation_count'] == 1
    assert report['accepted'] is False


def test_prepared_maximum_cannot_be_lost_in_canonical_model():
    problem = _problem(_vehicle(maximum_soc_kwh=100), scenario_fleet_contract={
        'active_vehicle_parameters':[{'vehicle_id':'v1','source_record':{'batteryKwh':100,'minSoc':.1,'maxSoc':.9}}]})
    report = validate_physical_event_schedule(problem=problem, serialized_result={'vehicle_paths':{},'charging_schedule':[]})
    assert report['metrics']['ev_soc_contract_violation_count'] == 1
    assert not report['accepted']


def test_independent_replay_checks_initial_state_against_source_or_measured_state():
    problem = _problem(_vehicle(initial_soc=75), scenario_fleet_contract={
        'active_vehicle_parameters':[{'vehicle_id':'v1','source_record':{'batteryKwh':100,'initialSoc':.72,'minSoc':.1,'maxSoc':.9}}]})
    report = validate_physical_event_schedule(problem=problem, serialized_result={'vehicle_paths':{},'charging_schedule':[]})
    assert report['metrics']['ev_soc_contract_violation_count'] == 1
    updated = RollingReoptimizer()._apply_actual_soc(problem, {'v1':70}, unit='kwh')
    report = validate_physical_event_schedule(problem=updated, serialized_result={'vehicle_paths':{},'charging_schedule':[]})
    assert report['metrics']['ev_soc_contract_violation_count'] == 0


def test_sub_kwh_state_survives_rolling_without_becoming_a_ratio():
    problem = _problem(_vehicle(initial_soc=.5,reserve_soc=0))
    assert vehicle_initial_soc_kwh(problem,problem.vehicles[0]) == .5
    updated = RollingReoptimizer()._apply_actual_soc(problem, {'v1':.4}, unit='kwh')
    assert vehicle_initial_soc_kwh(updated,updated.vehicles[0]) == .4
    assert updated.vehicles[0].maximum_soc_kwh == 90


def test_rolling_rejects_observed_overcharge_without_truncation():
    with pytest.raises(ValueError, match='outside'):
        RollingReoptimizer()._apply_actual_soc(_problem(_vehicle()), {'v1':93.375}, unit='kwh')


def test_terminal_target_above_vehicle_upper_bound_is_rejected():
    problem = _problem(_vehicle(),bev_terminal_soc_policy='fixed_target',final_soc_target_percent=95)
    with pytest.raises(ValueError, match='exceeds physical maximum'):
        effective_final_soc_target_kwh(problem, problem.vehicles[0])


def test_vehicles_with_different_upper_bounds_are_not_symmetry_clones():
    assert _problem_vehicle_symmetry_signature(_vehicle()) != _problem_vehicle_symmetry_signature(_vehicle(maximum_soc_kwh=85))
