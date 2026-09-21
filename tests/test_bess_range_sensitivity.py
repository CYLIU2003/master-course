"""Explicit storage-range assumptions must reach Prepare and its verifier alike."""
from copy import deepcopy
from dataclasses import asdict, fields, replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.benchmarks.prepare_shibu21_24_seasonal_inputs import apply_seasonal_bess_policy
from scripts.benchmarks.run_daily_assignment_reference import build_example, assignment_plan
from scripts.benchmarks.run_stage1_root_search_diagnosis import BESS_RANGE_PROFILES, profile_design
from scripts.benchmarks.run_stage1_root_search_diagnosis import run
from scripts.benchmarks.run_shibu21_24_seasonal_diagnostic import verify_evaluation_contract
from scripts.benchmarks.seasonal_design_contract import seasonal_bess_controls, seasonal_bess_range
from src.optimization.common.problem import DepotEnergyAsset, OptimizationConfig, OptimizationMode
from src.optimization.common.result import ResultSerializer
from src.optimization.engine import OptimizationEngine
from src.optimization.validation.physical_event_schedule import validate_physical_event_schedule


ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT/'config/shibu21_23_bess_range_sensitivity_20260921.json'


def pair():
    base = json.loads(DESIGN.read_text(encoding='utf-8'))
    return tuple(profile_design(base,BESS_RANGE_PROFILES,p) for p in BESS_RANGE_PROFILES)


def test_pair_changes_only_range_and_keeps_full_network_and_common_budget():
    baseline, expanded = pair()
    assert {k for k in baseline if baseline[k] != expanded[k]} == {
        'bess_operating_range_profile','bess_terminal_soc_floor_percent'}
    for design in (baseline,expanded):
        assert design['threads']==4 and design['successor_pruning']==0
        assert design['postsolve_repair'] is False
        assert design['bess_terminal_soc_policy']=='minimum_only'
        assert design['bess_forecast_reserve_policy']=='physical_floor_only'
        assert design['stage1_time_limit_sec']==1800 and design['stage2_time_limit_sec']==120


def test_held_pair_stops_before_creating_output(tmp_path):
    path=tmp_path/'design.json'
    path.write_text(json.dumps({'execution_enabled':False,'diagnostic_profiles':BESS_RANGE_PROFILES}),encoding='utf-8')
    with pytest.raises(RuntimeError,match='EXECUTION_DISABLED'):
        run(path,tmp_path/'never-created')
    assert not (tmp_path/'never-created').exists()


@pytest.mark.parametrize('change',[
    {'bess_operating_range_basis':'verified_hardware'},
    {'bess_operating_range_basis':None},
    {'bess_operating_range_profile':'expanded_0_100'},
    {'bess_terminal_soc_floor_percent':20},
])
def test_mislabeled_or_inconsistent_expansion_is_rejected(change):
    _,expanded = pair()
    with pytest.raises(ValueError):
        seasonal_bess_controls({**expanded,**change})


def test_materialization_and_preflight_agree_and_do_not_change_parent_or_equipment():
    _,design = pair()
    parent = {'depot_id':'tsurumaki','bess_enabled':True,'bess_energy_kwh':6000,
        'bess_initial_soc_kwh':3000,'bess_power_kw':900,'bess_charge_efficiency':.95,
        'bess_discharge_efficiency':.95,'allow_grid_to_bess':False}
    original = deepcopy(parent)
    configured = apply_seasonal_bess_policy(parent,design=design)
    assert parent==original and all(configured[k]==v for k,v in original.items())
    assert configured['bess_soc_min_kwh']==configured['bess_terminal_soc_min_kwh']==600
    assert configured['bess_soc_max_kwh']==5400 and configured['bess_terminal_soc_target_kwh']==0
    assert configured['bess_soc_min_ratio']==.1 and configured['bess_soc_max_ratio']==.9
    metadata={**seasonal_bess_controls(design),'bev_terminal_soc_policy':'return_to_initial',
        'final_soc_target_tolerance_percent':0,'daily_return_depot_id':'tsurumaki',
        'rolling_window_terminal_policy':'day_ahead_boundary_state'}
    problem=SimpleNamespace(metadata=metadata,vehicles=(),
        depot_energy_assets={'tsurumaki':SimpleNamespace(**configured)})
    assert verify_evaluation_contract(problem,design)['bess_controls']['tsurumaki']['soc_min_kwh']==600
    problem.depot_energy_assets['tsurumaki'].bess_soc_max_kwh=4800
    with pytest.raises(ValueError,match='maximum SOC'):
        verify_evaluation_contract(problem,design)
    assert seasonal_bess_range({})==(20,80)


def test_native_expansion_can_use_more_inventory_without_weakening_energy_balance():
    pytest.importorskip('gurobipy')
    totals=[]
    for design in pair():
        problem=build_example()
        configured=apply_seasonal_bess_policy(asdict(problem.depot_energy_assets['DEPOT']),design=design)
        keys={f.name for f in fields(DepotEnergyAsset)}
        asset=DepotEnergyAsset(**{k:v for k,v in configured.items() if k in keys})
        problem=replace(problem,depot_energy_assets={'DEPOT':asset})
        plan=assignment_plan(problem,('bev-0','bev-0'))
        result=OptimizationEngine().solve(problem,OptimizationConfig(mode=OptimizationMode.MILP,
            phase='phase1_charging_only',fixed_assignment=plan,time_limit_sec=15,stage2_time_limit_sec=10,
            mip_gap=0,gurobi_threads=1,allow_postsolve_repair=False))
        assert result.feasible, result.infeasibility_reasons
        physical=validate_physical_event_schedule(problem=problem,
            serialized_result=ResultSerializer.serialize_plan(result.plan))
        assert physical['accepted'],physical['violations']
        assert result.plan.metadata['stage2_mip_gap_ratio']==0
        assert result.plan.bess_soc_kwh_by_depot_slot['DEPOT'][47]==pytest.approx(asset.bess_soc_min_kwh)
        totals.append(result.cost_breakdown['total_cost'])
    assert totals[0]-totals[1]==pytest.approx(95,abs=1e-6)
