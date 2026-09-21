"""Run the predeclared four-week diagnostic with all formal gates left intact.

Each attempt uses a new output directory and fingerprints its source files.
This entrypoint is intentionally diagnostic; it cannot grant research release.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bff.store import scenario_store
from scripts.benchmarks.seasonal_design_contract import require_execution_enabled
from bff.services.run_preparation import load_prepared_input, materialize_scenario_from_prepared_input
from bff.services.optimization_run.rolling_chain import _prepare_actual_pv_execution_file
from scripts.run_hourly_charging_reoptimization import _build_executed_day_accounting, _EXECUTED_SLOT_MAP_FIELDS
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import OptimizationConfig, OptimizationMode
from src.optimization.common.result import ResultSerializer
from src.optimization.engine import OptimizationEngine
from src.optimization.rolling.day_ahead_hourly import build_next_execution_state
from src.optimization.rolling.pv_execution import execute_pv_prefix
from src.optimization.rolling.reoptimizer import RollingReoptimizer
from src.optimization.validation.physical_event_schedule import validate_physical_event_schedule


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')


def source_snapshot() -> dict:
    files = [path for folder in ('src', 'bff', 'scripts') for path in (ROOT/folder).rglob('*.py')
             if '__pycache__' not in path.parts]
    files += [ROOT/'config/shibu21_2025_seasonal_test.json']
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(files)}


def verify_evaluation_contract(problem, design: dict) -> dict:
    """Fail before solving if inherited controls differ from the declared test."""
    from src.optimization.common.soc_helpers import (
        effective_final_soc_target_kwh, is_electric_vehicle, vehicle_initial_soc_kwh)
    metadata = problem.metadata
    if metadata.get('bev_terminal_soc_policy') != design['bev_evaluation_terminal_policy']:
        raise ValueError('Prepared BEV terminal policy differs from the declared evaluation')
    if float(metadata.get('final_soc_target_tolerance_percent') or 0) != 0:
        raise ValueError('The evaluation forbids an inherited percentage terminal tolerance')
    if metadata.get('daily_return_depot_id') != design['daily_return_depot_id']:
        raise ValueError('Prepared daily return depot differs from the declared evaluation')
    if metadata.get('rolling_window_terminal_policy') != 'day_ahead_boundary_state':
        raise ValueError('The declared rolling boundary policy was not preserved')
    targets = {}
    for vehicle in problem.vehicles:
        if is_electric_vehicle(problem, vehicle):
            initial = vehicle_initial_soc_kwh(problem, vehicle)
            target = effective_final_soc_target_kwh(problem, vehicle)
            if target is None or abs(target-initial) > 1e-6:
                raise ValueError(f'Terminal target does not return {vehicle.vehicle_id} to its own initial state')
            targets[vehicle.vehicle_id] = {'initial_kwh':initial, 'terminal_target_kwh':target}
    return {'status':'DECLARED_TERMINAL_CONTROLS_VERIFIED', 'vehicle_targets':targets}


def solve_week(
    week: str,
    output: Path,
    design: dict,
    contract_validator: Callable[[object, dict], dict] | None = None,
) -> dict:
    require_execution_enabled(design)
    manifest = json.loads((ROOT/design['input_manifests_directory']/week/'derived_scenarios.json').read_text(encoding='utf-8'))
    case = manifest['cases'][0]
    if case.get('prepared_input_namespace') == 'candidate_prepared_inputs':
        raise RuntimeError(
            'Solver blocked: candidate prepared input is outside the formal prepared_inputs namespace'
        )
    scenario = scenario_store._load(case['scenario_id'], skip_graph_arcs=True)
    prepared = load_prepared_input(
        scenario_id=case['scenario_id'],
        prepared_input_id=case['prepared_input_id'],
        scenarios_dir=ROOT / design.get('prepared_inputs_directory', 'output/prepared_inputs'),
    )
    prepared_scope_audit = dict(prepared.get('prepared_scope_audit') or {})
    if (
        prepared_scope_audit.get('status') == 'CANONICAL_INPUT_PREPARED_STRICT_TRANSITION_AUDIT_DEFERRED'
        or prepared_scope_audit.get('strict_transition_audit_executed') is False
    ):
        raise RuntimeError(
            'Solver blocked: prepared input is a lightweight candidate with deferred strict transition audit'
        )
    scenario = materialize_scenario_from_prepared_input(scenario, prepared)
    ice_refueling_policy = str(design.get('ice_refueling_policy', 'no_refueling'))
    if ice_refueling_policy != 'no_refueling':
        raise ValueError('This diagnostic requires an implemented explicit ICE refueling policy')
    config = OptimizationConfig(mode=OptimizationMode.MILP, phase=design['phase'],
        time_limit_sec=design['day_ahead_wall_time_limit_sec'],
        stage1_time_limit_sec=design['stage1_time_limit_sec'], stage2_time_limit_sec=design['stage2_time_limit_sec'],
        mip_gap=design['mip_gap'], gurobi_threads=design['threads'], random_seed=design['seed'],
        stage1_gurobi_search_profile=design.get('stage1_gurobi_search_profile', 'default'),
        rolling_execution_minutes=design['execution_minutes'],
        research_run=False, allow_postsolve_repair=False, stage1_best_obj_stop_enabled=False)
    problem = ProblemBuilder().build_from_scenario(scenario, depot_id='tsurumaki',service_id='WEEKDAY',config=config,planning_days=7)
    problem = replace(problem, metadata={**problem.metadata,
        'stage1_daily_path_cover_bound': bool(design.get('stage1_daily_path_cover_bound', False)),
        'stage1_native_log_enabled': bool(design.get('stage1_native_log_enabled', False)),
        'stage1_sparse_charge_window_support': bool(design.get('stage1_sparse_charge_window_support', False)),
        'phase3_diagnostics_dir':str(output/'day_ahead_failure_diagnostics'),
        'stage1_exact_depot_connection_factors': bool(
            design.get('stage1_exact_depot_connection_factors', False)
        ), 'phase3_ice_refueling_policy': ice_refueling_policy})
    validator = contract_validator or verify_evaluation_contract
    write_json(output/'evaluation_contract.json', validator(problem, design))
    if len(problem.trips) != case['timetable_row_count'] or len(problem.vehicles) != case['vehicle_count']:
        raise ValueError('Canonical trip/fleet inventory changed after prepared materialization')
    if problem.metadata.get('milp_max_successors_per_trip') not in (None,0):
        raise ValueError('Predeclared diagnostic requires the complete successor network')
    write_json(output/'input_audit.json', {'scenario_id':case['scenario_id'], 'prepared_input_id':case['prepared_input_id'],
        'trip_count':len(problem.trips), 'vehicle_ids':[v.vehicle_id for v in problem.vehicles],
        'days':case['days'], 'config':asdict(config), 'metadata':dict(problem.metadata),
        'canonical_vehicle_parameters':[asdict(v) for v in problem.vehicles]})
    actual_path = _prepare_actual_pv_execution_file(problem,output,repo_root=ROOT)
    if actual_path is None:
        raise ValueError('The seasonal test requires a separate verified actual-PV replay source')
    actuals = json.loads(Path(actual_path).read_text(encoding='utf-8'))['depot_profiles']
    summary = {'week':week,'status':'DIAGNOSTIC','research_status':'NOT_USED_FOR_RESEARCH_CONCLUSIONS',
               'trip_count':len(problem.trips),'distance_km':sum(t.distance_km for t in problem.trips),
               'fleet_count':len(problem.vehicles),'hourly_steps_accepted':0,'formal_solve':False}
    write_json(output/'progress.json', summary)
    print(f'{week}: native Phase 3 day-ahead solve begins',flush=True)
    started = time.perf_counter()
    result = OptimizationEngine().solve(problem,config)
    write_json(output/'canonical_solver_result.json',ResultSerializer.serialize_result(result))
    summary.update(day_ahead_feasible=result.feasible,day_ahead_status=result.solver_status,
                   day_ahead_seconds=time.perf_counter()-started,day_ahead_cost=dict(result.cost_breakdown),
                   day_ahead_reasons=list(result.infeasibility_reasons),
                   stage1_certified_gap=result.solver_metadata.get('stage1_certified_mip_gap_ratio'),
                   stage1_mip_gap=result.solver_metadata.get('stage1_mip_gap_ratio'))
    write_json(output/'progress.json', summary)
    if not result.feasible:
        summary['status']='DAY_AHEAD_FAILED'
        return summary
    physical = validate_physical_event_schedule(problem=problem,serialized_result=ResultSerializer.serialize_plan(result.plan))
    write_json(output/'day_ahead_physical_validation.json',physical)
    summary['day_ahead_physical_accepted'] = physical['accepted']
    if not physical['accepted']:
        summary.update(status='DAY_AHEAD_PHYSICAL_FAILED',physical_violations=physical['violations'])
        return summary
    from scripts.benchmarks.optimization_quality import day_ahead_quality
    quality = day_ahead_quality(result.plan.metadata, target_gap=float(design['mip_gap']))
    write_json(output/'day_ahead_optimization_quality.json', quality)
    summary['day_ahead_optimization_quality'] = quality
    if design.get('diagnostic_stop_after_day_ahead') is True:
        summary['status'] = 'DAY_AHEAD_ONLY_DIAGNOSIS_COMPLETE'
        write_json(output/'progress.json', summary)
        return summary
    reference = result.plan
    rolling = RollingReoptimizer()
    rolling_config = replace(config, time_limit_sec=design['rolling_hour_time_limit_sec'],stage2_time_limit_sec=design['rolling_hour_time_limit_sec'])
    state = None
    segments = []
    for hour in range(168):
        start, stop = hour*4,(hour+1)*4
        kwargs = {} if state is None else {
            'actual_soc':state.actual_vehicle_soc_kwh,'actual_bess_soc_kwh':state.actual_bess_soc_kwh,
            'actual_vehicle_fuel_l':state.actual_vehicle_fuel_l,'actual_vehicle_positions':state.actual_vehicle_positions,
            'connected_charger_by_vehicle':state.connected_charger_by_vehicle,
            'active_charge_session_vehicle_ids':state.active_charge_session_vehicle_ids,
            'observed_on_peak_kw_by_depot':state.observed_on_peak_kw_by_depot,
            'observed_off_peak_kw_by_depot':state.observed_off_peak_kw_by_depot}
        folder = output/'rolling_hourly_chain'/f'hour_{hour:03d}'
        hourly_problem = replace(problem, metadata={**problem.metadata,
            'phase3_diagnostics_dir':str(folder/'failure_diagnostics')})
        if state is not None:
            write_json(folder/'initial_execution_state.json',state.to_dict())
        result = rolling.reoptimize_charging_hour(
            hourly_problem,
            reference,
            rolling_config,
            hour * 60,
            lookahead_hours=24,
            bess_terminal_policy=design.get('rolling_bess_terminal_policy', 'scenario'),
            **kwargs,
        )
        write_json(folder/'forecast_result.json',ResultSerializer.serialize_result(result))
        if not result.feasible:
            summary.update(status='HOURLY_SOLVE_FAILED',failed_hour=hour,hourly_reasons=list(result.infeasibility_reasons),
                failed_solver_status=result.solver_status,
                failure_diagnostics=str(folder/'failure_diagnostics'),
                failed_initial_bess_soc_kwh=dict(state.actual_bess_soc_kwh) if state else {
                    depot:asset.bess_initial_soc_kwh for depot,asset in problem.depot_energy_assets.items()})
            return summary
        prefix = {depot:{slot:float(values[slot]) for slot in range(start,stop)} for depot,values in actuals.items()}
        initial_bess = state.actual_bess_soc_kwh if state else {depot:asset.bess_initial_soc_kwh for depot,asset in problem.depot_energy_assets.items()}
        step_problem,result,audit = execute_pv_prefix(problem,result,actual_pv_by_depot_slot=prefix,
            actual_bess_soc_kwh=initial_bess,start_slot=start,stop_slot=stop)
        state = build_next_execution_state(step_problem,result,current_min=hour*60,execution_minutes=60,
            prior_vehicle_fuel_l=state.actual_vehicle_fuel_l if state else None,
            prior_on_peak_kw_by_depot=state.observed_on_peak_kw_by_depot if state else None,
            prior_off_peak_kw_by_depot=state.observed_off_peak_kw_by_depot if state else None)
        write_json(folder/'execution_state.json',state.to_dict())
        write_json(folder/'pv_execution_audit.json',audit)
        segments.append((step_problem,result,start,stop))
        summary['hourly_steps_accepted']=hour+1
        write_json(output/'progress.json', summary)
        if hour%12==11:
            print(f'{week}: {hour+1}/168 hourly execution prefixes',flush=True)
    accounting = _build_executed_day_accounting(problem,reference,segments)
    write_json(output/'rolling_hourly_chain/executed_day_accounting.json',accounting)
    maps = {field:{} for field in _EXECUTED_SLOT_MAP_FIELDS}
    soc,charges,refuels = {},[],[]
    for _,executed,start,stop in segments:
        for field in maps:
            for owner,values in getattr(executed.plan,field).items():
                maps[field].setdefault(owner,{}).update({slot:value for slot,value in values.items() if start<=slot<stop})
        for owner,values in executed.plan.vehicle_soc_kwh_by_vehicle_slot.items():
            soc.setdefault(owner,{}).update({slot:value for slot,value in values.items() if start<=slot<=stop})
        charges.extend(slot for slot in executed.plan.charging_slots if start<=slot.slot_index<stop)
        refuels.extend(slot for slot in executed.plan.refuel_slots if start<=slot.slot_index<stop)
    plan = replace(reference,charging_slots=tuple(charges),refuel_slots=tuple(refuels),vehicle_soc_kwh_by_vehicle_slot=soc,**maps)
    actual_problem = replace(problem,depot_energy_assets={depot:replace(asset,pv_generation_kwh_by_slot=tuple(actuals[depot])) for depot,asset in problem.depot_energy_assets.items()})
    physical = validate_physical_event_schedule(problem=actual_problem,serialized_result=ResultSerializer.serialize_plan(plan))
    write_json(output/'rolling_hourly_chain/physical_validation.json',physical)
    evaluator = CostEvaluator()
    costs = evaluator.evaluate(actual_problem,plan)
    vehicle_ledger,daily_ledger = evaluator.build_plan_ledgers(actual_problem,plan,costs)
    plan = replace(plan,vehicle_cost_ledger=vehicle_ledger,daily_cost_ledger=daily_ledger)
    write_json(output/'rolling_hourly_chain/executed_plan.json',ResultSerializer.serialize_plan(plan))
    difference = abs(float(accounting['cost_breakdown']['total_cost'])-sum(row.total_cost_jpy for row in daily_ledger))
    summary.update(accounting_eligible=accounting['eligible'],physical_accepted=physical['accepted'],
                   accounting_reasons=accounting.get('rejection_reasons'),daily_cost_difference_jpy=difference,
                   executed_cost=accounting['cost_breakdown'],used_vehicles=len(plan.duties_by_vehicle()))
    summary['status'] = 'DIAGNOSTIC_EXECUTION_PASSED' if accounting['eligible'] and physical['accepted'] and difference<=1e-6 else 'EXECUTION_ACCEPTANCE_FAILED'
    return summary


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    design=json.loads((ROOT/'config/shibu21_2025_seasonal_test.json').read_text(encoding='utf-8'))
    source=source_snapshot()
    write_json(args.output/'source_manifest.json',{'source_sha256':source,'design':design,
        'base_git_sha':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'worktree_dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True)),
        'formal_research_run':False})
    summaries=[]
    for week in design['evaluation_weeks']:
        if source_snapshot()!=source:
            raise RuntimeError('Source changed during the diagnostic attempt; start a fresh output directory')
        output=args.output/week
        output.mkdir()
        try:
            summary=solve_week(week,output,design)
        except Exception as exc:
            import traceback
            (output/'error.txt').write_text(traceback.format_exc(),encoding='utf-8')
            summary=json.loads((output/'progress.json').read_text(encoding='utf-8')) if (output/'progress.json').exists() else {'week':week}
            summary.update(status='EXECUTION_ERROR', error=f'{type(exc).__name__}: {exc}',
                           research_status='NOT_USED_FOR_RESEARCH_CONCLUSIONS')
        write_json(output/'summary.json',summary)
        summaries.append(summary)
        write_json(args.output/'summary.json',summaries)
        print(json.dumps({'week':week,'status':summary['status'],'hours':summary.get('hourly_steps_accepted')},ensure_ascii=False),flush=True)
    if source_snapshot()!=source:
        raise RuntimeError('Source changed during the diagnostic attempt')


if __name__=='__main__':
    main()
