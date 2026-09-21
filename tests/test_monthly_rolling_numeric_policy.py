"""Phase-specific search controls must remain explicit in execution and audits."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import pytest
from scripts.benchmarks import audit_monthly_execution as auditor
from scripts.benchmarks.run_shibu21_seasonal_diagnostic import rolling_config_for_design
from src.optimization.common.problem import OptimizationConfig

def design():
    return json.loads((Path(__file__).resolve().parents[1]/'config/shibu21_23_monthly_auxiliary_rolling_20260921.json').read_text(encoding='utf-8'))

def test_hourly_policy_changes_only_the_declared_search_control_and_budget():
    d=design()
    config=OptimizationConfig(time_limit_sec=2400,stage1_time_limit_sec=1800,stage2_time_limit_sec=120,
                              stage2_gurobi_presolve=2,gurobi_threads=4,random_seed=42,mip_gap=.01)
    hourly=rolling_config_for_design(config,d)
    assert config.stage2_gurobi_presolve==2 and hourly.stage2_gurobi_presolve==0
    assert {k for k,v in asdict(config).items() if asdict(hourly)[k]!=v}=={
        'stage2_gurobi_presolve','stage2_time_limit_sec','time_limit_sec'}
    legacy=deepcopy(d);legacy['stage2_search_policy'].pop('rolling_Presolve')
    assert rolling_config_for_design(config,legacy).stage2_gurobi_presolve==2

@pytest.mark.parametrize('hourly_presolve,accepted',[(0,True),(2,False)])
def test_auditor_checks_every_original_hour_against_its_phase(hourly_presolve,accepted,monkeypatch,tmp_path):
    d=design()
    monkeypatch.setattr(auditor,'EXPECTED_SEARCH_CONTROLS_BY_KIND',{
        'day_ahead':{'stage2_gurobi_mip_focus':1,'stage2_gurobi_method':1},
        'hourly':{'stage2_gurobi_mip_focus':1,'stage2_gurobi_method':0}})
    base={'feasible':True,'trip_count_served':7,'trip_count_unserved':0,
          'effective_limits':{'stage2_time_limit_sec':120},'metadata':{},'solver_metadata':{
        'stage2_gurobi_aggregate':0,'stage2_gurobi_feasibility_tol':1e-9,'stage2_gurobi_integrality_tol':1e-9,
        'stage2_has_feasible_incumbent':True,'synthetic_pv_fallback_applied':False,
        'postsolve_repair_allowed':False,'postsolve_modified_solution':False,'derived_source_split':False,
        'successor_pruning_enabled':False,'arc_pruning_summary':{
            'candidate_arc_count_before_successor_pruning':10,'arc_count_after_successor_pruning':10,
            'pruned_arc_count':0,'pruned_origin_count':0,'max_candidate_successors_per_origin':5},
        'search_profile':{'fallback_count':0},'stage2_numeric_diagnostics':{
            'maximum_constraint_violation':0,'maximum_bound_violation':0,'maximum_integrality_violation':0}}}
    def read(path):
        document=deepcopy(base)
        hourly=path.name=='forecast_result.json'
        document['metadata']={'stage2_gurobi_mip_focus':1,'stage2_gurobi_method':0 if hourly else 1}
        document['solver_metadata']['stage2_gurobi_presolve']=hourly_presolve if hourly else 2
        document['solver_metadata']['stage2_time_limit_sec_effective']=15 if hourly else 120
        return document
    monkeypatch.setattr(auditor,'read_json',read)
    native,_,_=auditor.audit_native_entries(tmp_path,tmp_path/'chain',7,d)
    assert native['all_native_strict'] is accepted
    assert native['required_presolve'] is None
    assert native['required_presolve_by_kind']=={'day_ahead':2,'hourly':0}
    assert native['native_invalid_count']==(0 if accepted else 168)
