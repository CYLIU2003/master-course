"""Bus service continues when optional storage reaches either boundary."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.optimization.common.bess_dispatch_policy import PV_BUS_FIRST_POLICY
from src.optimization.common.problem import DepotEnergyAsset, OptimizationConfig, OptimizationMode
from src.optimization.rolling.pv_execution import IssuedEnergyCommand, execute_energy_slot, execute_pv_prefix
from src.optimization.milp.auxiliary_bess import add_auxiliary_bess_constraints
from src.optimization.milp.pv_execution_reserve import add_pv_execution_reserve_constraints
from scripts.benchmarks.prepare_shibu21_24_seasonal_inputs import apply_seasonal_bess_policy
from scripts.benchmarks.seasonal_design_contract import seasonal_bess_controls
from scripts.benchmarks.seasonal_design_contract import require_execution_enabled
from scripts.benchmarks.run_shibu21_24_seasonal_diagnostic import verify_evaluation_contract


def asset(**overrides):
    values = dict(depot_id='DEPOT', pv_enabled=True, bess_enabled=True,
        bess_energy_kwh=100, bess_power_kw=100, bess_initial_soc_kwh=50,
        bess_soc_min_kwh=20, bess_soc_max_kwh=80, bess_charge_efficiency=.9,
        bess_discharge_efficiency=.8, bess_terminal_soc_policy='minimum_only',
        bess_terminal_soc_min_kwh=20, bess_priority_mode='pv_self_consumption')
    values.update(overrides)
    return DepotEnergyAsset(**values)


def execute(storage, demand, pv, soc, **kwargs):
    return execute_energy_slot(storage, IssuedEnergyCommand(demand, bess_to_bus_kwh=999, pv_to_bess_kwh=999),
        actual_pv_kwh=pv, initial_bess_soc_kwh=soc, timestep_minutes=60,
        import_limit_kw=kwargs.get('limit', 1000), allow_contract_overage=kwargs.get('soft', False),
        slot_index=0, grid_price_yen_per_kwh=20)


def test_auxiliary_execution_respects_separate_physical_import_limit():
    storage = asset(bess_enabled=False)
    with pytest.raises(ValueError, match="physical equipment limit"):
        execute_energy_slot(
            storage, IssuedEnergyCommand(12), actual_pv_kwh=0,
            initial_bess_soc_kwh=0, timestep_minutes=60, import_limit_kw=5,
            allow_contract_overage=True, slot_index=0,
            grid_price_yen_per_kwh=20, physical_import_limit_kw=10,
        )


@pytest.mark.parametrize('lower,upper', [(20,80),(10,90)])
def test_lower_boundary_idles_then_surplus_recharges_and_discharge_resumes(lower, upper):
    storage = asset(bess_soc_min_kwh=lower, bess_soc_max_kwh=upper, bess_terminal_soc_min_kwh=lower)
    empty = execute(storage, 12, 3, lower)
    assert (empty.pv_to_bus_kwh, empty.grid_to_bus_kwh, empty.bess_to_bus_kwh)==(3,9,0)
    assert empty.bess_soc_kwh == lower
    restored = execute(storage, 10, 30, empty.bess_soc_kwh)
    assert restored.pv_to_bus_kwh == 10 and restored.pv_to_bess_kwh == 20
    assert restored.bess_soc_kwh == pytest.approx(lower+18)
    used = execute(storage, 30, 0, restored.bess_soc_kwh)
    assert used.bess_to_bus_kwh == pytest.approx(14.4)
    assert used.grid_to_bus_kwh == pytest.approx(15.6)
    assert used.bess_soc_kwh == pytest.approx(lower)


def test_pv_is_used_before_bess_and_full_storage_curtails_only_surplus():
    full = execute(asset(), 10, 50, 80)
    assert full.pv_to_bus_kwh == 10 and full.bess_to_bus_kwh == 0
    assert full.pv_to_bess_kwh == 0 and full.pv_curtail_kwh == 40
    partial = execute(asset(), 10, 50, 71)
    assert partial.pv_to_bess_kwh == pytest.approx(10)
    assert partial.pv_curtail_kwh == pytest.approx(30)
    assert partial.bess_soc_kwh == pytest.approx(80)


def test_optional_storage_disabled_or_power_limited_preserves_bus_demand():
    disabled = execute(asset(bess_enabled=False), 12, 3, 0)
    assert disabled.grid_to_bus_kwh == 9 and disabled.bess_to_bus_kwh == 0
    limited = execute(asset(bess_power_kw=5), 12, 3, 50)
    assert limited.bess_to_bus_kwh == 5 and limited.grid_to_bus_kwh == 4
    with pytest.raises(ValueError, match='hard grid import'):
        execute(asset(), 12, 0, 20, limit=10)
    assert execute(asset(), 12, 0, 20, limit=10, soft=True).contract_over_limit_kwh == 2


def test_policy_does_not_silently_reintroduce_grid_charge_or_restoration():
    for storage in (asset(allow_grid_to_bess=True), asset(bess_terminal_soc_target_kwh=50),
                    asset(bess_terminal_soc_min_kwh=50)):
        with pytest.raises(ValueError, match='no added reserve/restoration'):
            execute(storage, 10, 0, 50)
    # Invalid observed input is reported, never converted into invented energy.
    with pytest.raises(ValueError, match='outside configured bounds'):
        execute(asset(), 10, 0, 1)


def test_prepare_preserves_parent_and_carries_explicit_policy():
    parent=asdict(asset(bess_priority_mode='cost_driven')); before=deepcopy(parent)
    design={'bess_priority_mode':'pv_self_consumption'}
    configured=apply_seasonal_bess_policy(parent,design=design)
    assert parent==before
    assert configured['bess_priority_mode']=='pv_self_consumption'
    assert configured['bess_terminal_soc_target_kwh']==0 and configured['allow_grid_to_bess'] is False
    assert apply_seasonal_bess_policy(parent)['bess_priority_mode']=='cost_driven'
    with pytest.raises(ValueError,match='minimum_only/physical_floor_only'):
        seasonal_bess_controls({**design,'bess_terminal_soc_policy':'return_to_initial','rolling_bess_terminal_policy':'scenario'})


def test_new_design_is_held_and_preflight_detects_dropped_policy():
    path=Path(__file__).resolve().parents[1]/'config/shibu21_23_auxiliary_bess_20260921.json'
    design=json.loads(path.read_text(encoding='utf-8'))
    assert design['evaluation_weeks']==['2025-05-12']
    with pytest.raises(RuntimeError,match='EXECUTION_DISABLED'):
        require_execution_enabled(design)
    configured=apply_seasonal_bess_policy(asdict(asset()),design=design)
    metadata={**seasonal_bess_controls(design),'bev_terminal_soc_policy':'return_to_initial',
              'daily_return_depot_id':'tsurumaki','rolling_window_terminal_policy':'day_ahead_boundary_state'}
    problem=SimpleNamespace(metadata=metadata,vehicles=(),
        depot_energy_assets={'DEPOT':SimpleNamespace(**configured)})
    assert verify_evaluation_contract(problem,design)['bess_controls']['DEPOT']['priority_mode']=='pv_self_consumption'
    problem.depot_energy_assets['DEPOT'].bess_priority_mode='cost_driven'
    with pytest.raises(ValueError,match='priority mode'):
        verify_evaluation_contract(problem,design)


@pytest.mark.parametrize('permission', ['allow_bess_to_bus','allow_pv_to_bess'])
def test_disabled_storage_direction_is_not_used(permission):
    storage=asset(**{permission:False})
    if permission=='allow_bess_to_bus':
        assert execute(storage,10,0,50).bess_to_bus_kwh==0
    else:
        assert execute(storage,10,30,50).pv_to_bess_kwh==0


def test_native_forecast_min_constraints_match_causal_execution_at_bounds():
    gp=pytest.importorskip('gurobipy')
    storage=asset(pv_generation_kwh_by_slot=(3.,30.,0.,100.))
    demands=(12.,10.,30.,10.)
    with gp.Model('auxiliary_bess_rule') as model:
        model.Params.OutputFlag=0
        maps={name:{('DEPOT',s):model.addVar(lb=0) for s in range(4)}
              for name in ('grid_bus','pv_bus','bess_bus','pv_charge','grid_charge','curtail')}
        soc={('DEPOT',s):model.addVar(lb=20,ub=80) for s in range(4)}
        model.addConstr(soc['DEPOT',0]==20)
        for s,d in enumerate(demands):
            key=('DEPOT',s)
            model.addConstr(maps['grid_bus'][key]+maps['pv_bus'][key]+maps['bess_bus'][key]==d)
            model.addConstr(maps['pv_bus'][key]+maps['pv_charge'][key]+maps['curtail'][key]==storage.pv_generation_kwh_by_slot[s])
            if s<3:
                model.addConstr(soc['DEPOT',s+1]==soc[key]+.9*maps['pv_charge'][key]-maps['bess_bus'][key]/.8)
        add_auxiliary_bess_constraints(model,storage,range(4),duration_hours=1,soc_start=soc,
                                      **{k:v for k,v in maps.items() if k!='curtail'})
        model.setObjective(0)
        model.optimize()
        assert model.Status==gp.GRB.OPTIMAL
        current=20
        for s,d in enumerate(demands):
            result=execute(storage,d,storage.pv_generation_kwh_by_slot[s],current)
            for name,field in [('grid_bus','grid_to_bus_kwh'),('pv_bus','pv_to_bus_kwh'),
                               ('bess_bus','bess_to_bus_kwh'),('pv_charge','pv_to_bess_kwh'),('curtail','pv_curtail_kwh')]:
                assert maps[name]['DEPOT',s].X==pytest.approx(getattr(result,field),abs=1e-6)
            current=result.bess_soc_kwh


def test_adaptive_rolling_reserve_does_not_require_fixed_bess_discharge():
    from test_rolling_pv_execution_reserve import _problem,_config,_flow_model
    problem=_problem(hard_import=True,import_limit_kw=10,period_floors={'DEPOT':20})
    problem=replace(problem,depot_energy_assets={'DEPOT':asset(bess_initial_soc_kwh=20)})
    model,maps,grb=_flow_model(problem,(0,))
    try:
        audit=add_pv_execution_reserve_constraints(model,problem,_config(execution_minutes=60),(0,),
            is_remaining_day_reoptimization=True,grid_to_bus_var=maps['grid_to_bus'],
            pv_to_bus_var=maps['pv_to_bus'],grid_to_bess_var=maps['grid_to_bess'],bess_to_bus_var=maps['bess_to_bus'])
        assert audit['bess_floor_constraint_count']==0 and audit['adaptive_bess_depot_ids']==['DEPOT']
        # No-PV/no-storage backup still has to respect the existing hard grid cap.
        model.addConstr(maps['grid_to_bus']['DEPOT',0]+maps['pv_to_bus']['DEPOT',0]+maps['bess_to_bus']['DEPOT',0]==11)
        model.optimize()
        assert model.Status==grb.INFEASIBLE
    finally:
        model.dispose()


@pytest.mark.parametrize('presolve', [0, 2])
def test_fixed_stage2_and_execution_agree_for_two_day_charging(tmp_path, presolve):
    pytest.importorskip('gurobipy')
    from scripts.benchmarks.run_daily_assignment_reference import build_example,assignment_plan
    from src.optimization.engine import OptimizationEngine
    from src.optimization.common.result import ResultSerializer
    from src.optimization.validation.physical_event_schedule import validate_physical_event_schedule
    problem=build_example(extra_pv_kwh=20)
    storage=replace(problem.depot_energy_assets['DEPOT'],bess_priority_mode='pv_self_consumption')
    problem=replace(problem,depot_energy_assets={'DEPOT':storage},
        metadata={**problem.metadata,'stage2_native_log_enabled':True,'phase3_diagnostics_dir':str(tmp_path)})
    result=OptimizationEngine().solve(problem,OptimizationConfig(mode=OptimizationMode.MILP,
        phase='phase1_charging_only',fixed_assignment=assignment_plan(problem,('bev-0','bev-0')),
        time_limit_sec=20,stage2_time_limit_sec=15,mip_gap=0,gurobi_threads=1,allow_postsolve_repair=False,
        stage2_gurobi_presolve=presolve))
    assert result.feasible,result.infeasibility_reasons
    native_log=Path(result.plan.metadata['stage2_native_log_path'])
    assert native_log.is_file() and 'Solution count' in native_log.read_text(encoding='utf-8')
    physical=validate_physical_event_schedule(problem=problem,serialized_result=ResultSerializer.serialize_plan(result.plan))
    assert physical['accepted'],physical['violations']
    _,executed,audit=execute_pv_prefix(problem,result,
        actual_pv_by_depot_slot={'DEPOT':dict(enumerate(storage.pv_generation_kwh_by_slot))},
        actual_bess_soc_kwh={'DEPOT':50},start_slot=0,stop_slot=48)
    assert audit['policy']==PV_BUS_FIRST_POLICY
    for field in ('grid_to_bus','pv_to_bus','bess_to_bus','pv_to_bess','pv_curtail','bess_soc'):
        predicted=getattr(result.plan,field+'_kwh_by_depot_slot').get('DEPOT',{})
        actual=getattr(executed.plan,field+'_kwh_by_depot_slot').get('DEPOT',{})
        for s in range(48):
            assert predicted.get(s,0)==pytest.approx(actual.get(s,0),abs=1e-5),(field,s)
