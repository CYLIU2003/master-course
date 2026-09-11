from dataclasses import replace

import pytest

from scripts.run_hourly_charging_reoptimization import _minute_label
from src.dispatch.models import DeadheadRule, DutyLeg, VehicleDuty
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import AssignmentPlan, DepotEnergyAsset, EnergyPriceSlot, OptimizationConfig
from src.optimization.milp.solver_adapter import ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT, _stage2_slot_indices
from src.optimization.rolling.reoptimizer import RollingReoptimizer
from src.optimization.engine import OptimizationEngine
from test_milp_soc_validator_roundtrip import _soc_roundtrip_problem


def _two_day_problem():
    problem = _soc_roundtrip_problem()
    first = problem.dispatch_context.trips[0]
    second = replace(first, trip_id='next-day-trip', departure_time='32:00', arrival_time='33:00')
    context = replace(problem.dispatch_context, trips=[first, second],
                      deadhead_rules={**problem.dispatch_context.deadhead_rules,('B','A'):DeadheadRule('B','A',30)})
    canonical_second = replace(problem.trips[0], trip_id=second.trip_id, departure_min=1920, arrival_min=1980)
    asset = DepotEnergyAsset(depot_id='DEPOT', pv_enabled=True, pv_generation_kwh_by_slot=(0.0,)*48,
                             bess_enabled=True, bess_energy_kwh=100, bess_power_kw=60,
                             bess_initial_soc_kwh=50, bess_soc_max_kwh=100,
                             bess_terminal_soc_policy='return_to_initial', bess_balance_period='daily')
    return replace(problem, dispatch_context=context, trips=problem.trips+(canonical_second,),
                   scenario=replace(problem.scenario, planning_days=2, horizon_end='48:00'),
                   price_slots=tuple(EnergyPriceSlot(i,grid_buy_yen_per_kwh=10) for i in range(48)),
                   depot_energy_assets={'DEPOT':asset})


def _fixed_plan(problem):
    duties=(VehicleDuty('bev-1:0', 'BEV', tuple(DutyLeg(trip,deadhead_from_prev_min=30)
                 for trip in problem.dispatch_context.trips)),)
    return AssignmentPlan(duties=duties, served_trip_ids=tuple(trip.trip_id for trip in problem.trips),
                          metadata={'duty_vehicle_map':{duty.duty_id:'bev-1' for duty in duties}})


@pytest.mark.parametrize('hours,stop',[(24,47),(48,48),(168,48)])
def test_lookahead_crosses_midnight_and_stops_at_available_input(hours,stop):
    problem=_two_day_problem()
    config=OptimizationConfig(rolling_current_min=23*60,rolling_horizon_policy=ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT,
                              rolling_lookahead_hours=hours)
    assert _stage2_slot_indices(problem,config,range(48))==tuple(range(23,stop))
    assert _minute_label(24*60)=='24:00'
    assert _minute_label(168*60)=='168:00'


def test_daily_balance_validator_rejects_borrowing_across_midnight():
    problem=_two_day_problem()
    plan=AssignmentPlan(bess_to_bus_kwh_by_depot_slot={'DEPOT':{23:9.5}},
                        grid_to_bess_kwh_by_depot_slot={'DEPOT':{24:10/.95}})
    metrics=FeasibilityChecker()._evaluate_bess_metrics(problem,plan)
    assert metrics['terminal_deviation_kwh']==pytest.approx(10)
    weekly=replace(problem,depot_energy_assets={'DEPOT':replace(problem.depot_energy_assets['DEPOT'],bess_balance_period='evaluation_period')})
    assert FeasibilityChecker()._evaluate_bess_metrics(weekly,plan)['terminal_deviation_kwh']==pytest.approx(0)


def test_formal_multiday_is_blocked_until_continuous_execution_is_accepted():
    with pytest.raises(ValueError,match='MULTIDAY_RESEARCH_BLOCKED'):
        OptimizationEngine().solve(_two_day_problem(),OptimizationConfig(research_run=True))


def test_actual_two_day_charging_model_respects_daily_boundary_and_24_hour_window():
    pytest.importorskip('gurobipy')
    problem=_two_day_problem()
    result=RollingReoptimizer().reoptimize_charging_hour(
        problem,_fixed_plan(problem),OptimizationConfig(time_limit_sec=10,mip_gap=0),0,lookahead_hours=24)
    assert result.feasible, result.infeasibility_reasons
    assert result.solver_metadata['rolling_stop_slot_index']==24
    assert result.plan.bess_soc_kwh_by_depot_slot['DEPOT'][23]==pytest.approx(50)
    assert max(result.plan.vehicle_soc_kwh_by_vehicle_slot['bev-1'])==24
