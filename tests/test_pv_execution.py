from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.optimization.common.problem import (
    AssignmentPlan, ChargingSlot, DepotEnergyAsset, OptimizationEngineResult, OptimizationMode,
)
from src.optimization.rolling.pv_execution import (
    IssuedEnergyCommand, execute_energy_slot, execute_pv_prefix,
)
from test_multiday_rolling_contract import _two_day_problem, _fixed_plan
from src.optimization.rolling.day_ahead_hourly import build_next_execution_state
from src.optimization.common.evaluator import CostEvaluator
from scripts.run_hourly_charging_reoptimization import _build_executed_day_accounting
from bff.services.date_series_inputs import _date_forecast_rows, _persist_actual_profiles
from bff.services.optimization_run.rolling_chain import _prepare_actual_pv_execution_file


def _asset():
    return DepotEnergyAsset(depot_id='DEPOT', pv_enabled=True, bess_enabled=True,
                            bess_energy_kwh=100, bess_power_kw=80,
                            bess_initial_soc_kwh=50, bess_soc_min_kwh=10, bess_soc_max_kwh=90,
                            allow_grid_to_bess=True)


def test_forecast_profiles_cover_each_complete_jst_day(tmp_path):
    import hashlib

    directory = tmp_path / 'data/derived/seasonal_irradiance/tsurumaki/forecast_holdouts'
    directory.mkdir(parents=True)
    model = {'slot_minutes': 15, 'training_end_exclusive': '2025-01-01',
             'latitude': 35.635, 'longitude': 139.646,
             'cells': [{'season': 'summer', 'weather_class': 'sunny',
                        'source_day_count': 20, 'attenuation_by_slot': [.7] * 96}]}
    path = directory / 'training_model.json'
    path.write_text(json.dumps(model), encoding='utf-8')
    model_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    (directory / 'manifest.json').write_text(json.dumps({
        'artifacts': {'training_model.json': model_hash}}), encoding='utf-8')
    profiles, audit = _date_forecast_rows(tmp_path, ['2025-08-04', '2025-08-05'], 15, .85)
    assert [profile['date'] for profile in profiles] == ['2025-08-04', '2025-08-05']
    for profile in profiles:
        values = profile['capacity_factor_by_slot']
        assert len(values) == 96
        assert values[0] == values[-1] == 0
        assert values[48] > .3
    assert audit['issued_at'] == '2025-08-04T00:00:00+09:00'
    assert audit['model_sha256'] == model_hash
    assert audit['future_weather_class_known'] is False


def _execute(command, **kwargs):
    parameters = dict(actual_pv_kwh=0, initial_bess_soc_kwh=50, timestep_minutes=15,
                      import_limit_kw=80, allow_contract_overage=False, slot_index=0,
                      grid_price_yen_per_kwh=20)
    parameters.update(kwargs)
    return execute_energy_slot(_asset(), command, **parameters)


def test_pv_shortfall_preserves_charging_demand_and_updates_storage_from_actual_pv():
    flow = _execute(IssuedEnergyCommand(10, pv_to_bess_kwh=10), actual_pv_kwh=14)
    assert flow.pv_to_bus_kwh == 10
    assert flow.pv_to_bess_kwh == 4
    assert flow.bess_soc_kwh == pytest.approx(53.8)
    assert flow.grid_to_bus_kwh + flow.pv_to_bus_kwh + flow.bess_to_bus_kwh == 10
    assert flow.pv_to_bus_kwh + flow.pv_to_bess_kwh + flow.pv_curtail_kwh == 14


def test_pv_excess_cannot_increase_issued_bess_charge():
    flow = _execute(IssuedEnergyCommand(10, pv_to_bess_kwh=5), actual_pv_kwh=30)
    assert flow.pv_to_bess_kwh == 5
    assert flow.pv_curtail_kwh == 15


def test_hard_grid_limit_fails_and_soft_contract_records_the_overage():
    with pytest.raises(ValueError, match='hard grid import'):
        _execute(IssuedEnergyCommand(21))
    flow = _execute(IssuedEnergyCommand(21), allow_contract_overage=True)
    assert flow.grid_to_bus_kwh == 21
    assert flow.contract_over_limit_kwh == 1


@pytest.mark.parametrize('command,kwargs,message', [
    (IssuedEnergyCommand(10, bess_to_bus_kwh=10), {'initial_bess_soc_kwh':15}, 'SOC bounds'),
    (IssuedEnergyCommand(10, bess_to_bus_kwh=2, pv_to_bess_kwh=1), {}, 'simultaneously'),
    (IssuedEnergyCommand(1, bess_to_bus_kwh=2), {}, 'exceeds bus demand'),
    (IssuedEnergyCommand(25, bess_to_bus_kwh=25), {}, 'power limit'),
    (IssuedEnergyCommand(1), {'actual_pv_kwh':float('nan')}, 'finite'),
    (IssuedEnergyCommand(1), {'actual_pv_kwh':True}, 'finite'),
])
def test_invalid_execution_fails_without_changing_commands(command,kwargs,message):
    with pytest.raises(ValueError, match=message):
        _execute(command, **kwargs)


def test_prefix_reads_no_future_actuals_and_preserves_vehicle_charge_and_soc():
    problem = _two_day_problem()
    original_soc = {'bev-1':{0:100,1:109}}
    plan = replace(_fixed_plan(problem),charging_slots=(ChargingSlot('bev-1',0,'charger',charge_kw=10,
                                                       charging_depot_id='DEPOT',energy_source='pv'),),
                          vehicle_soc_kwh_by_vehicle_slot=original_soc,
                          pv_to_bus_kwh_by_depot_slot={'DEPOT':{0:10}},
                          pv_to_bess_kwh_by_depot_slot={'DEPOT':{0:5}})
    result = OptimizationEngineResult(OptimizationMode.MILP,'optimal',0,plan,True)
    args = dict(actual_pv_by_depot_slot={'DEPOT':{0:4}},actual_bess_soc_kwh={'DEPOT':50},
                start_slot=0,stop_slot=1)
    actual_problem, executed, audit = execute_pv_prefix(problem,result,**args)
    assert executed.plan.grid_to_bus_kwh_by_depot_slot['DEPOT'][0] == 6
    assert executed.plan.bess_soc_kwh_by_depot_slot['DEPOT'][0] == 50
    assert executed.plan.vehicle_soc_kwh_by_vehicle_slot == original_soc
    assert executed.plan.charging_slots[0].charge_kw == 10
    assert executed.plan.charging_slots[0].energy_source is None
    assert actual_problem.depot_energy_assets['DEPOT'].pv_generation_kwh_by_slot[0] == 4
    assert audit['future_observations_used'] is False
    next_state = build_next_execution_state(actual_problem, executed, current_min=0, execution_minutes=60)
    assert next_state.actual_bess_soc_kwh['DEPOT'] == 50
    assert next_state.actual_vehicle_soc_kwh['bev-1'] == 109
    assert max(next_state.observed_on_peak_kw_by_depot['DEPOT'],
               next_state.observed_off_peak_kw_by_depot['DEPOT']) == 6
    assert result.plan.charging_slots[0].energy_source == 'pv'
    args['actual_pv_by_depot_slot'] = {'DEPOT':{0:4,1:999}}
    with pytest.raises(ValueError, match='without future observations'):
        execute_pv_prefix(problem,result,**args)


def test_period_asset_costs_include_all_days_even_without_charging():
    problem = _two_day_problem()
    asset = replace(problem.depot_energy_assets['DEPOT'], pv_capacity_kw=10,
                    pv_capex_jpy_per_kw=365, pv_life_years=1,
                    bess_capex_jpy_per_kwh=365, bess_life_years=1)
    problem = replace(problem, depot_energy_assets={'DEPOT': asset})
    cost = CostEvaluator().evaluate(problem, AssignmentPlan())
    assert cost.pv_asset_cost == 20
    assert cost.bess_asset_cost == 200
    assert cost.total_cost_with_assets - cost.total_cost == 220


def test_executed_period_rejects_daily_bess_borrowing_despite_balanced_final_inventory():
    problem = _two_day_problem()
    result = SimpleNamespace(plan=AssignmentPlan(bess_soc_kwh_by_depot_slot={'DEPOT':{23:40,47:50}}),
                             solver_metadata={'bev_terminal_soc_balance_satisfied':True})
    accounting = _build_executed_day_accounting(problem, AssignmentPlan(), [(problem,result,0,48)])
    assert accounting['bess_terminal_energy_balanced'] is True
    assert accounting['bess_daily_energy_balanced'] is False
    assert accounting['eligible'] is False
    assert 'bess_daily_energy_not_balanced' in accounting['rejection_reasons']


def test_actual_profile_is_hashed_and_scaled_using_the_prepared_equipment(tmp_path):
    problem = _two_day_problem()
    dates = ['2025-08-04','2025-08-05']
    profiles = [{'date': day, 'slot_minutes':60, 'capacity_factor_by_slot':[.5]*24} for day in dates]
    reference = _persist_actual_profiles(tmp_path, profiles, [{'sha256':'a'*64}], dates, 60)
    source = tmp_path / reference['path']
    document = json.loads(source.read_text(encoding='utf-8'))
    # This test's canonical depot uses DEPOT, whereas acquisition is Tsurumaki.
    asset = replace(problem.depot_energy_assets['DEPOT'], depot_id='tsurumaki',pv_capacity_kw=10,pv_supply_scale=.5)
    problem = replace(problem,depot_energy_assets={'tsurumaki':asset},metadata={
        **problem.metadata,'service_dates':dates,'date_series_contract':{
            'pv_information_mode':'training_only_forecast_proxy','pv_execution_input':reference}})
    path = _prepare_actual_pv_execution_file(problem,tmp_path/'run',repo_root=tmp_path)
    actual = json.loads(Path(path).read_text(encoding='utf-8'))
    assert actual['depot_profiles']['tsurumaki'] == [2.5]*48
    assert 'profiles' not in problem.metadata['date_series_contract']
    source.write_text(json.dumps({**document,'source_sha256':['b'*64]}),encoding='utf-8')
    with pytest.raises(ValueError, match='changed after Prepare'):
        _prepare_actual_pv_execution_file(problem,tmp_path/'run',repo_root=tmp_path)


def test_forecast_source_rows_are_combined_without_losing_physical_charge_energy():
    problem = _two_day_problem()
    charges = tuple(ChargingSlot('bev-1',0,'physical-charger',charge_kw=power,
                                 charging_depot_id='DEPOT',energy_source=source)
                    for source,power in [('grid',4),('pv',6)])
    plan = AssignmentPlan(charging_slots=charges,
                          grid_to_bus_kwh_by_depot_slot={'DEPOT':{0:4}},
                          pv_to_bus_kwh_by_depot_slot={'DEPOT':{0:6}})
    result = OptimizationEngineResult(OptimizationMode.MILP,'optimal',0,plan,True)
    _, executed, _ = execute_pv_prefix(problem,result,actual_pv_by_depot_slot={'DEPOT':{0:10}},
                                      actual_bess_soc_kwh={'DEPOT':50},start_slot=0,stop_slot=1)
    assert len(executed.plan.charging_slots) == 1
    assert executed.plan.charging_slots[0].charge_kw == 10
    assert CostEvaluator().evaluate(problem,executed.plan).grid_import_kwh == 0
