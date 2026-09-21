"""More pointwise PV can be ignored: it cannot force a higher optimum.

This constructs a feasible equal-cost witness, not a global optimality claim
about the fixed-assignment solver used to obtain the starting plan.
"""
from dataclasses import replace

import pytest

from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import OptimizationConfig
from src.optimization.common.result import ResultSerializer
from src.optimization.rolling.reoptimizer import RollingReoptimizer
from src.optimization.validation.physical_event_schedule import validate_physical_event_schedule
from test_daily_return_policy import daily_problem
from test_multiday_rolling_contract import _fixed_plan


def test_additional_pointwise_pv_can_be_curtailed_without_more_cost_or_inventory():
    pytest.importorskip('gurobipy')
    low = daily_problem()
    asset = replace(low.depot_energy_assets['DEPOT'], bess_soc_min_kwh=20,
        bess_soc_max_kwh=80, bess_terminal_soc_policy='minimum_only',
        bess_terminal_soc_min_kwh=20, bess_terminal_soc_target_kwh=0,
        bess_balance_period='evaluation_period')
    low = replace(low, depot_energy_assets={'DEPOT':asset}, metadata={**low.metadata,
        'bess_forecast_reserve_policy':'physical_floor_only',
        'pv_curtail_penalty_yen_per_kwh':0,'pv_marginal_charge_cost_yen_per_kwh':0})
    result = RollingReoptimizer().reoptimize_charging_hour(low,_fixed_plan(low),
        OptimizationConfig(time_limit_sec=10,mip_gap=0,gurobi_threads=1,
                           allow_postsolve_repair=False),0,lookahead_hours=48)
    assert result.feasible, result.infeasibility_reasons
    increments = tuple(10.0 if 10 <= i%24 < 15 else 0.0 for i in range(48))
    high = replace(low, depot_energy_assets={'DEPOT':replace(asset,
        pv_generation_kwh_by_slot=tuple(a+b for a,b in zip(asset.pv_generation_kwh_by_slot,increments)))})
    curtail = {depot:dict(values) for depot,values in result.plan.pv_curtail_kwh_by_depot_slot.items()}
    curtail['DEPOT'] = {i:curtail.get('DEPOT',{}).get(i,0)+extra for i,extra in enumerate(increments)}
    witness = replace(result.plan,pv_curtail_kwh_by_depot_slot=curtail)
    physical = validate_physical_event_schedule(problem=high,serialized_result=ResultSerializer.serialize_plan(witness))
    assert physical['accepted'], physical['violations']
    feasibility = FeasibilityChecker().evaluate(high,witness)
    assert feasibility.feasible, feasibility.errors
    low_cost=CostEvaluator().evaluate(low,result.plan).to_dict()
    high_cost=CostEvaluator().evaluate(high,witness).to_dict()
    assert high_cost['total_cost']==pytest.approx(low_cost['total_cost'],abs=1e-6)
    assert high_cost['grid_import_kwh']==pytest.approx(low_cost['grid_import_kwh'])
    assert high_cost['pv_curtailed_kwh']-low_cost['pv_curtailed_kwh']==pytest.approx(sum(increments))
    assert witness.bess_soc_kwh_by_depot_slot==result.plan.bess_soc_kwh_by_depot_slot
    assert witness.charging_slots==result.plan.charging_slots
    assert witness.duties==result.plan.duties
