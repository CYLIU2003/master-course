"""Exhaustive numerical reference for a declared synthetic two-day problem.

This is a formulation check, not a weekly solver or a research-release gate.
There is one trip per day, so assigning each trip to either vehicle enumerates
every dispatch in this example. Each assignment uses the existing physical
daily-return Stage 2. A single unresolved case blocks the reference certificate.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
from itertools import product
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.dispatch.models import DeadheadRule, DispatchContext, DutyLeg, Trip, VehicleDuty
from src.dispatch.feasibility import FeasibilityEngine, evaluate_startup_feasibility
from src.optimization.common.cost_components import COST_COMPONENT_DEFINITIONS
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import (
    AssignmentPlan, CanonicalOptimizationProblem, ChargerDefinition, DepotEnergyAsset,
    EnergyPriceSlot, OptimizationConfig, OptimizationMode, OptimizationScenario,
    ProblemDepot, ProblemTrip, ProblemVehicle, ProblemVehicleType,
)
from src.optimization.common.result import ResultSerializer
from src.optimization.engine import OptimizationEngine
from src.optimization.validation.physical_event_schedule import validate_physical_event_schedule


def build_example(*, extra_pv_kwh: float = 0) -> CanonicalOptimizationProblem:
    """Define synthetic inputs explicitly; never sample or rewrite a timetable."""
    if not math.isfinite(extra_pv_kwh) or extra_pv_kwh < 0:
        raise ValueError('extra PV must be finite and nonnegative')
    trips = tuple(Trip(f'trip-{day}', 'synthetic-route', 'A', 'B',
        f'{8+24*day}:00', f'{9+24*day}:00', 10, ('BEV',),
        operator_id='synthetic-operator', service_date=f'2025-02-0{3+day}',
        day_index=day) for day in range(2))
    vehicles = tuple(ProblemVehicle(f'bev-{i}', 'BEV', 'DEPOT', initial_soc=80,
        battery_capacity_kwh=100, reserve_soc=20, maximum_soc_kwh=100,
        energy_consumption_kwh_per_km=rate, charge_power_max_kw=60,
        soc_input_unit='kwh') for i, rate in enumerate((1.0, 1.4)))
    flags = {item.key: item.key in {'electricity_cost', 'vehicle_usage_cost'}
             for item in COST_COMPONENT_DEFINITIONS}
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario('synthetic-daily-assignment-reference',
            horizon_start='00:00', horizon_end='48:00', timestep_min=60,
            planning_days=2, allow_same_day_depot_cycles=False),
        dispatch_context=DispatchContext('2025-02-03', list(trips), {}, {
            ('DEPOT','A'): DeadheadRule('DEPOT','A',30),
            ('B','DEPOT'): DeadheadRule('B','DEPOT',60),
            ('B','A'): DeadheadRule('B','A',30)}, {}, daily_return_depot_id='DEPOT'),
        trips=tuple(ProblemTrip(t.trip_id, t.route_id, 'A', 'B', t.departure_min,
            t.arrival_min, 10, ('BEV',), energy_kwh=10, operator_id=t.operator_id,
            service_date=t.service_date, day_index=t.day_index) for t in trips),
        vehicles=vehicles,
        vehicle_types=(ProblemVehicleType('BEV','BEV', battery_capacity_kwh=100,
            charge_power_max_kw=60, reserve_soc=20, energy_consumption_kwh_per_km=1),),
        depots=(ProblemDepot('DEPOT','Synthetic depot',('charger',),import_limit_kw=100),),
        chargers=(ChargerDefinition('charger','DEPOT',60),),
        price_slots=tuple(EnergyPriceSlot(i, grid_buy_yen_per_kwh=10 if i%24<7 else 30)
                          for i in range(48)),
        depot_energy_assets={'DEPOT':DepotEnergyAsset('DEPOT', pv_enabled=True,
            pv_generation_kwh_by_slot=tuple(extra_pv_kwh if 10<=i%24<15 else 0 for i in range(48)),
            bess_enabled=True, bess_energy_kwh=100, bess_power_kw=60,
            bess_initial_soc_kwh=50, bess_soc_min_kwh=20, bess_soc_max_kwh=80,
            bess_terminal_soc_policy='minimum_only', bess_terminal_soc_min_kwh=20,
            bess_balance_period='evaluation_period')},
        metadata={'daily_return_depot_id':'DEPOT', 'bev_terminal_soc_policy':'return_to_initial',
            'final_soc_floor_percent':20, 'deadhead_speed_kmh':18,
            'bess_forecast_reserve_policy':'physical_floor_only',
            'milp_max_successors_per_trip':0, 'cost_component_flags':flags,
            'vehicle_usage_cost_jpy_per_used_bus':100,
            'pv_curtail_penalty_yen_per_kwh':0, 'pv_marginal_charge_cost_yen_per_kwh':0})


def assignment_plan(problem, assignment: tuple[str, ...]) -> AssignmentPlan:
    duties = []
    for vehicle in problem.vehicles:
        selected = [trip for trip,chosen in zip(problem.dispatch_context.trips,assignment)
                    if chosen == vehicle.vehicle_id]
        if not selected:
            continue
        startup = evaluate_startup_feasibility(selected[0], problem.dispatch_context,
                                               vehicle.home_depot_id)
        assert startup.feasible
        legs = [DutyLeg(selected[0], startup.deadhead_time_min)]
        for previous, trip in zip(selected,selected[1:]):
            connection = FeasibilityEngine().can_connect(previous, trip,
                problem.dispatch_context, vehicle.vehicle_type)
            assert connection.feasible
            legs.append(DutyLeg(trip, connection.deadhead_time_min))
        duties.append(VehicleDuty(vehicle.vehicle_id,vehicle.vehicle_type,tuple(legs)))
    return AssignmentPlan(duties=tuple(duties), served_trip_ids=tuple(t.trip_id for t in problem.trips),
        metadata={'duty_vehicle_map':{d.duty_id:d.duty_id for d in duties}})


def assignment_key(plan) -> tuple:
    return tuple(sorted((plan.vehicle_id_for_duty(d.duty_id), tuple(d.trip_ids)) for d in plan.duties))


def summarize(rows: list[dict], *, expected_assignments: list[tuple]) -> dict:
    """Never discard a failed/unfinished assignment to produce a false minimum."""
    expected_count = len(expected_assignments)
    complete = (len(rows) == expected_count and expected_count > 0
        and {tuple(row['assignment']) for row in rows} == set(expected_assignments)
        and all(row.get('accepted') is True
            and all(isinstance(row[k],(int,float)) and math.isfinite(row[k])
                    for k in ('total_upper_jpy','total_lower_jpy'))
            and row['total_lower_jpy'] <= row['total_upper_jpy']+1e-6 for row in rows))
    upper = min((r['total_upper_jpy'] for r in rows if r.get('accepted')), default=None)
    lower = min(r['total_lower_jpy'] for r in rows) if complete else None
    width = upper-lower if complete else None
    certified = complete and -1e-6 <= width <= 1e-6
    return {'status':'NUMERICAL_REFERENCE_COMPLETE' if certified else 'REFERENCE_BLOCKED',
        'enumeration_complete':complete, 'assignment_count':len(rows),
        'expected_assignment_count':expected_count, 'total_upper_jpy':upper,
        'total_lower_jpy':lower, 'absolute_gap_jpy':width,
        'scope':'synthetic_two_days_two_BEVs_one_trip_per_day_only',
        'full_week_global_optimality_proven':False, 'research_status':'DIAGNOSTIC',
        'numerical_tolerance_jpy':1e-6, 'rows':rows}


def _jsonable(value):
    if isinstance(value, dict):
        return {str(k):_jsonable(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _write(path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')


def run_reference(output: Path, *, extra_pv_kwh: float = 0) -> dict:
    problem = build_example(extra_pv_kwh=extra_pv_kwh)
    source_before = {key:subprocess.check_output(['git','-C',str(ROOT),*args],text=True).strip()
        for key,args in {'sha':['rev-parse','HEAD'],'dirty':['status','--porcelain']}.items()}
    output.mkdir(parents=True, exist_ok=False)
    snapshot = json.dumps(_jsonable(asdict(problem)), sort_keys=True, ensure_ascii=False)
    (output/'problem.json').write_text(snapshot+'\n',encoding='utf-8')
    rows = []
    assignments = list(product((v.vehicle_id for v in problem.vehicles), repeat=len(problem.trips)))
    # This API intentionally cannot accept a real timetable or an arbitrary fleet.
    assert len(assignments) == 4
    for index, assignment in enumerate(assignments):
        folder = output/f'assignment_{index:02d}'
        folder.mkdir()
        seed = assignment_plan(problem, assignment)
        config = OptimizationConfig(mode=OptimizationMode.MILP, phase='phase1_charging_only',
            fixed_assignment=seed, time_limit_sec=20, stage2_time_limit_sec=15,
            mip_gap=0, gurobi_threads=1, warm_start=False, allow_postsolve_repair=False)
        _write(folder/'config.json', _jsonable(asdict(config)))
        result = OptimizationEngine().solve(problem, config)
        raw = ResultSerializer.serialize_result(result)
        physical = validate_physical_event_schedule(problem=problem,
            serialized_result=ResultSerializer.serialize_plan(result.plan))
        _write(folder/'canonical_solver_result.json', raw)
        _write(folder/'physical_validation.json', physical)
        metadata = result.plan.metadata
        costs = CostEvaluator().evaluate(problem,result.plan).to_dict()
        objective, bound = metadata.get('stage2_objective'), metadata.get('stage2_best_bound')
        finite = all(isinstance(x,(int,float)) and math.isfinite(x)
                     for x in (objective,bound,costs['total_cost']))
        # In this explicitly constructed example only electricity varies within
        # an assignment; the two vehicle-days cost 200 JPY for every assignment.
        cost_match = finite and max(abs(costs['electricity_cost']-objective),
            abs(costs['vehicle_usage_cost']-200),
            abs(costs['total_cost']-200-objective)) <= 1e-6
        accepted = bool(result.feasible and physical['accepted'] and not physical['violations']
            and assignment_key(seed)==assignment_key(result.plan)
            and metadata.get('stage2_solver_status')=='optimal'
            and metadata.get('stage2_exact_optimality_certified') is True
            and finite and -1e-6 <= objective-bound <= 1e-6 and cost_match)
        rows.append({'assignment':assignment, 'accepted':accepted,
            'solver_status':metadata.get('stage2_solver_status'),
            'reasons':list(result.infeasibility_reasons), 'physical_accepted':physical['accepted'],
            'physical_violations':physical['violations'], 'cost_match':cost_match,
            'stage2_objective_jpy':objective, 'stage2_bound_jpy':bound,
            'total_upper_jpy':costs['total_cost'] if accepted else None,
            'total_lower_jpy':200+bound if accepted else None,
            'bess_initial_kwh':50, 'bess_final_kwh':result.plan.bess_soc_kwh_by_depot_slot.get('DEPOT',{}).get(47),
            'gurobi_feasibility_tol':metadata.get('stage2_gurobi_feasibility_tol'),
            'gurobi_integrality_tol':metadata.get('stage2_gurobi_integrality_tol'),
            'evidence_sha256':{name:hashlib.sha256((folder/name).read_bytes()).hexdigest()
                for name in ('canonical_solver_result.json','physical_validation.json','config.json')}})
        _write(output/'progress.json', {'finished':len(rows),'expected':4,'rows':rows})
    report = summarize(rows, expected_assignments=assignments)
    source_after = {key:subprocess.check_output(['git','-C',str(ROOT),*args],text=True).strip()
        for key,args in {'sha':['rev-parse','HEAD'],'dirty':['status','--porcelain']}.items()}
    if source_before != source_after:
        report['status'] = 'REFERENCE_BLOCKED_SOURCE_CHANGED'
    report.update(problem_sha256=hashlib.sha256((output/'problem.json').read_bytes()).hexdigest(),
        source_before=source_before, source_after=source_after,
        extra_pv_kwh_per_daytime_slot=extra_pv_kwh,
        source_file_sha256={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
            'scripts/benchmarks/run_daily_assignment_reference.py',
            'src/optimization/common/evaluator.py','src/optimization/milp/solver_adapter.py')})
    _write(output/'summary.json',report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--extra-pv-kwh',type=float,default=0)
    args = parser.parse_args()
    report = run_reference(args.output,extra_pv_kwh=args.extra_pv_kwh)
    print(json.dumps({key:value for key,value in report.items() if key != 'rows'},ensure_ascii=False))
    raise SystemExit(0 if report['status']=='NUMERICAL_REFERENCE_COMPLETE' else 1)
