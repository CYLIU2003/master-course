"""Diagnostic replay of old failure under the new clean solver source; never a weekly result."""
from pathlib import Path
import sys
import json
from dataclasses import replace

INPUT_ROOT = Path('C:/master-course-worktrees/shibu21-23-monthly-search-20260915')
FROZEN = Path('C:/master-course-worktrees/shibu21-23-monthly-search-20260915')
OUT = Path('C:/master-course/output/monthly_search_20260915/august_full_replay')
sys.path.insert(0, str(FROZEN))
from bff.store import scenario_store
from bff.services.run_preparation import materialize_scenario_from_prepared_input
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import OptimizationConfig, OptimizationMode
from src.optimization.common.result import ResultSerializer
from src.optimization.rolling.reoptimizer import RollingReoptimizer
from scripts.benchmarks.run_shibu21_24_seasonal_diagnostic import verify_evaluation_contract
import gurobipy as gp

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

OUT.mkdir(exist_ok=False)
case = INPUT_ROOT/'output/monthly_search_campaign_20260915/cases/2025-08-04'
original = case/'diagnostic/2025-08-04'
design = read(case/'design.json')
wrapper = read(case/'summary.json')
prepared = read(INPUT_ROOT/wrapper['prepare_result']['prepared_input_path'])
saved_store = scenario_store._STORE_DIR
scenario_store._STORE_DIR = INPUT_ROOT/'output/scenarios'
try:
    scenario = scenario_store._load(wrapper['prepare_result']['scenario_id'], skip_graph_arcs=True, repair_missing_master=False, repair_route_metadata=False)
finally:
    scenario_store._STORE_DIR = saved_store
scenario = materialize_scenario_from_prepared_input(scenario, prepared)
config = OptimizationConfig(mode=OptimizationMode.MILP, phase=design['phase'],
    time_limit_sec=design['day_ahead_wall_time_limit_sec'],
    stage1_time_limit_sec=design['stage1_time_limit_sec'], stage2_time_limit_sec=design['stage2_time_limit_sec'],
    mip_gap=design['mip_gap'], gurobi_threads=design['threads'], random_seed=design['seed'],
    research_run=False, allow_postsolve_repair=False, stage1_best_obj_stop_enabled=False)
print('Building original problem for one-hour diagnostic', flush=True)
problem = ProblemBuilder().build_from_scenario(scenario,depot_id='tsurumaki',service_id='WEEKDAY',config=config,planning_days=7)
problem = replace(problem, metadata={**problem.metadata,
    'phase3_diagnostics_dir':str(OUT/'failure_diagnostics'),
    'stage1_exact_depot_connection_factors':True, 'phase3_ice_refueling_policy':'no_refueling'})
verify_evaluation_contract(problem, design)
reference = ResultSerializer.deserialize_plan(problem,read(original/'canonical_solver_result.json'))
state = read(original/'rolling_hourly_chain/hour_048/initial_execution_state.json')
config = replace(config,time_limit_sec=design['rolling_hour_time_limit_sec'],stage2_time_limit_sec=design['rolling_hour_time_limit_sec'])

from src.optimization.common.vehicle_timeline import fixed_path_slot_loads
from src.optimization.common.soc_helpers import vehicle_initial_soc_kwh
class Captured(Exception):
    pass
class CaptureEngine:
    def solve(self, problem, config):
        self.problem, self.config = problem, config
        raise Captured()
rolling=RollingReoptimizer()
capture=CaptureEngine()
rolling._engine=capture
try:
    rolling.reoptimize_charging_hour(problem,reference,config,48*60,lookahead_hours=24,
        bess_terminal_policy=design['rolling_bess_terminal_policy'],
        actual_soc=state['actual_vehicle_soc_kwh'],actual_bess_soc_kwh=state['actual_bess_soc_kwh'],
        actual_vehicle_fuel_l=state['actual_vehicle_fuel_l'],actual_vehicle_positions=state['actual_vehicle_positions'],
        connected_charger_by_vehicle=state['connected_charger_by_vehicle'],
        active_charge_session_vehicle_ids=tuple(state['active_charge_session_vehicle_ids']),
        observed_on_peak_kw_by_depot=state['observed_on_peak_kw_by_depot'],
        observed_off_peak_kw_by_depot=state['observed_off_peak_kw_by_depot'])
except Captured:
    pass
rolling_problem=capture.problem


import pickle,hashlib,subprocess
from src.optimization.engine import OptimizationEngine
from scripts.benchmarks.run_shibu21_seasonal_diagnostic import validate_physical_event_schedule
with (OUT/'rolling_problem.pkl').open('wb') as stream:
    pickle.dump((rolling_problem,capture.config),stream)
original_optimize=gp.Model.optimize
records={}
model_hashes=[]
for method in (1,0):
    label=f'method_{method}'
    case_records=[]
    def record_optimize(model,*args,**kwargs):
        assert model.ModelName=='thesis_stage2_charging_dispatch',model.ModelName
        model.setParam('Method',method)
        model.setParam('LogFile',str(OUT/f'{label}.log'))
        model.update()
        assert model.NumConstrs==80780,model.NumConstrs
        path=OUT/f'{label}.mps';model.write(str(path))
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if model_hashes:assert digest==model_hashes[0]
        model_hashes.append(digest)
        original_optimize(model,*args,**kwargs)
        record={'status':model.Status,'solutions':model.SolCount,'runtime':model.Runtime,'mps_sha256':digest,
                'effective_time_limit':model.Params.TimeLimit,'method':model.Params.Method,'mip_focus':model.Params.MIPFocus}
        if model.SolCount:
            record.update(constraint_violation=model.ConstrVio,bound_violation=model.BoundVio,integrality_violation=model.IntVio)
        case_records.append(record)
    gp.Model.optimize=record_optimize
    try:
        diagnostic_problem=replace(rolling_problem,metadata={**rolling_problem.metadata,'phase3_diagnostics_dir':str(OUT/label/'failure_diagnostics')})
        result=OptimizationEngine().solve(diagnostic_problem,capture.config)
    finally:
        gp.Model.optimize=original_optimize
    serialized=ResultSerializer.serialize_result(result)
    (OUT/f'{label}_result.json').write_text(json.dumps(serialized,ensure_ascii=False),encoding='utf-8')
    physical=None
    if result.feasible:
        physical=validate_physical_event_schedule(problem=diagnostic_problem,serialized_result=serialized)
        (OUT/f'{label}_physical.json').write_text(json.dumps(physical,ensure_ascii=False),encoding='utf-8')
    records[label]={'feasible':result.feasible,'reasons':list(result.infeasibility_reasons),'native':case_records,
                    'physical_accepted':physical.get('accepted') if physical else None}
    (OUT/f'{label}_summary.json').write_text(json.dumps(records[label],indent=2),encoding='utf-8')
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=FROZEN,text=True).strip()=='10a40c9faa00d0a4725ae0062d6dbaa223f82bfd'
assert not subprocess.check_output(['git','status','--porcelain'],cwd=FROZEN)
(OUT/'summary.json').write_text(json.dumps({'status':'DIAGNOSIS_COMPLETED','weekly_result':False,'cases':records},indent=2),encoding='utf-8')
print(json.dumps(records),flush=True)
