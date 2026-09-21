"""The monthly restart must preserve new controls and reject stale BESS evidence."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.benchmarks.audit_auxiliary_bess import POLICY, audit_week, verify_flows
from scripts.benchmarks.audit_monthly_execution import verify_solver_controls
from scripts.benchmarks.monthly_week_contract import select_monthly_weeks
from scripts.build_monthly_interpretation import bess_condition_text
from scripts.watch_monthly_campaign import deployment_paths


def design():
    return json.loads((Path(__file__).resolve().parents[1] /
        'config/shibu21_23_monthly_auxiliary_20260921.json').read_text(encoding='utf-8'))


def config(d):
    return dict(phase=d['phase'], time_limit_sec=d['day_ahead_wall_time_limit_sec'],
        stage1_time_limit_sec=d['stage1_time_limit_sec'], stage2_time_limit_sec=d['stage2_time_limit_sec'],
        random_seed=d['seed'], gurobi_threads=d['threads'], mip_gap=d['mip_gap'],
        stage2_gurobi_presolve=d['stage2_search_policy']['Presolve'],
        stage1_gurobi_search_profile=d['stage1_gurobi_search_profile'], allow_postsolve_repair=False)


def test_all_months_enabled_with_fresh_prepare_and_full_rolling():
    d=design()
    assert d['execution_enabled'] is True and d['diagnostic_stop_after_day_ahead'] is False
    assert d['evaluation_weeks'] == select_monthly_weeks(2025, d['selection_holiday_dates'])
    assert len(d['evaluation_weeks']) == 12
    assert d['bess_priority_mode'] == 'pv_self_consumption'
    assert d['bess_terminal_soc_policy'] == 'minimum_only'
    assert d['bess_forecast_reserve_policy'] == 'physical_floor_only'
    assert d['bess_operating_range_profile'] == 'baseline_20_80'
    assert 'バス充電を優先' in bess_condition_text(d)
    assert deployment_paths({'deployment':'auxiliary'})[0] == Path('output/monthly_auxiliary_20260921')
    assert verify_solver_controls(config(d),d,d)['gurobi_threads'] == 4


def test_new_presolve_campaign_is_explicit_and_old_profile_is_rejected():
    d=json.loads((Path(__file__).resolve().parents[1]/
        'config/shibu21_23_monthly_auxiliary_presolve_20260921.json').read_text(encoding='utf-8'))
    assert d['evaluation_weeks']==design()['evaluation_weeks']
    assert d['stage2_search_policy']['Presolve']==2 and d['stage2_native_log_enabled'] is True
    assert verify_solver_controls(config(d),d,d)['stage2_gurobi_presolve']==2
    stale=config(d);stale['stage2_gurobi_presolve']=0
    with pytest.raises(ValueError,match='Input solver controls drift'):
        verify_solver_controls(stale,d,d)


def test_logging_recovery_changes_identity_only_and_keeps_delivery_separate():
    root=Path(__file__).resolve().parents[1]
    old=json.loads((root/'config/shibu21_23_monthly_auxiliary_presolve_20260921.json').read_text(encoding='utf-8'))
    new=json.loads((root/'config/shibu21_23_monthly_auxiliary_logfix_20260921.json').read_text(encoding='utf-8'))
    assert {key for key in new if old.get(key)!=new[key]} == {
        'input_manifests_directory','derived_from_design','revision_purpose'}
    assert verify_solver_controls(config(new),new,new)['stage2_gurobi_presolve']==2
    paths=deployment_paths({'deployment':'auxiliary_logfix'})
    for version in ('budget','search','phase_search','cyclic','reserve','auxiliary','auxiliary_presolve'):
        assert all(left != right for left,right in zip(paths,deployment_paths({'deployment':version})))


@pytest.mark.parametrize('field,value', [('stage1_time_limit_sec',120),('threads',12),
    ('mip_gap',.1),('bess_priority_mode','cost_driven'),('diagnostic_stop_after_day_ahead',True)])
def test_saved_controls_cannot_drift_from_new_frozen_design(field,value):
    d=design(); changed=deepcopy(d); changed[field]=value
    with pytest.raises(ValueError,match='drift'):
        verify_solver_controls(config(d),changed,d)


def test_independent_flow_audit_rejects_old_discharge_command_and_pv_diversion():
    asset=dict(bess_soc_min_kwh=20,bess_soc_max_kwh=80,bess_charge_efficiency=.9,
        bess_discharge_efficiency=.8,bess_power_kw=100,allow_bess_to_bus=True,allow_pv_to_bess=True)
    row=dict(grid_to_bus=9,pv_to_bus=3,bess_to_bus=0,pv_to_bess=0,grid_to_bess=0,pv_curtail=0,bess_soc=20)
    assert verify_flows(asset,start=20,pv=3,flows=row,duration=1)==20
    # Energy balance alone would pass these stale/incorrect source commands.
    stale={**row,'grid_to_bus':8,'bess_to_bus':1,'bess_soc':18.75}
    with pytest.raises(ValueError):
        verify_flows(asset,start=20,pv=3,flows=stale,duration=1)
    diverted={**row,'grid_to_bus':10,'pv_to_bus':2,'pv_to_bess':1,'bess_soc':20.9}
    with pytest.raises(ValueError):
        verify_flows(asset,start=20,pv=3,flows=diverted,duration=1)


def test_full_saved_week_audit_and_accounted_flow_tampering(tmp_path):
    d=design()
    asset=dict(bess_enabled=True,bess_priority_mode='pv_self_consumption',allow_grid_to_bess=False,
        bess_terminal_soc_target_kwh=0,bess_initial_soc_kwh=20,bess_soc_min_kwh=20,bess_soc_max_kwh=80,
        bess_charge_efficiency=.9,bess_discharge_efficiency=.8,bess_power_kw=100,
        allow_bess_to_bus=True,allow_pv_to_bess=True)
    values=dict(grid_to_bus=9,pv_to_bus=3,bess_to_bus=0,pv_to_bess=0,grid_to_bess=0,pv_curtail=0,bess_soc=20)
    def write(path, payload):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(payload),encoding='utf-8')
    def native(slots):
        return {'metadata':{'bess_soc_start_kwh_by_depot_slot':{'D':{str(s):20 for s in slots}}},
            **{f'{name}_kwh_by_depot_slot':{'D':{str(s):value for s in slots}}
               for name,value in values.items()}}
    write(tmp_path/'canonical_solver_result.json',native(range(672)))
    chain=tmp_path/'rolling_hourly_chain'
    plan=native(range(672));write(chain/'executed_plan.json',plan)
    for hour in range(168):
        folder=chain/f'hour_{hour:03d}'
        write(folder/'forecast_result.json',native(range(hour*4,min((hour+24)*4,672))))
        write(folder/'pv_execution_audit.json',{'policy_by_depot':{'D':POLICY},
            'future_observations_used':False,'bus_charging_commands_unchanged':True,
            'rows':[{'depot_id':'D','slot_index':slot,'actual_pv_kwh':3,'initial_bess_soc_kwh':20,
                     **{f'{name}_kwh':value for name,value in values.items()}}
                    for slot in range(hour*4,(hour+1)*4)]})
    terminal={'D':{'terminal_soc_kwh':20}}
    result=audit_week(tmp_path,d,terminal,{'D':asset})
    assert result['depots']['D']['executed_slots_verified']==672
    assert len(result['hashes'])==338
    plan['grid_to_bus_kwh_by_depot_slot']['D']['0']=8
    write(chain/'executed_plan.json',plan)
    with pytest.raises(ValueError,match='accounted executed plan'):
        audit_week(tmp_path,d,terminal,{'D':asset})
