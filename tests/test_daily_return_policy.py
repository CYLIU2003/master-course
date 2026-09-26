from dataclasses import replace

import pytest

from src.dispatch.daily_return import crosses_service_day
from src.dispatch.feasibility import FeasibilityEngine
from src.dispatch.models import DutyLeg, VehicleDuty
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import AssignmentPlan, ChargingSlot, OptimizationConfig
from src.optimization.common.result import ResultSerializer
from src.optimization.common.vehicle_timeline import build_vehicle_timeline, complete_home_slots, fixed_path_slot_loads
from src.optimization.rolling.reoptimizer import RollingReoptimizer
from src.optimization.validation.physical_event_schedule import validate_physical_event_schedule
from test_multiday_rolling_contract import _two_day_problem, _fixed_plan


def daily_problem():
    problem = _two_day_problem()
    trips = tuple(replace(trip, service_date=f"2025-02-0{3+i}", day_index=i, operator_id="tokyu")
                  for i, trip in enumerate(problem.trips))
    dispatch = [replace(trip, service_date=f"2025-02-0{3+i}", day_index=i, operator_id="tokyu")
                for i, trip in enumerate(problem.dispatch_context.trips)]
    return replace(problem, trips=trips, dispatch_context=replace(problem.dispatch_context, trips=dispatch,
                   daily_return_depot_id="DEPOT"), metadata={**problem.metadata, "daily_return_depot_id":"DEPOT"})


def test_weekly_controls_replace_inherited_tolerance_and_reject_contract_drift():
    from scripts.catalog.prepare_seven_day_candidates import _apply_daily_return_controls
    from scripts.benchmarks.run_shibu21_seasonal_diagnostic import verify_evaluation_contract
    document = {'simulation_config': {'bev_terminal_soc_policy':'fixed_target',
        'final_soc_target_percent':80, 'final_soc_target_tolerance_percent':20},
        'scenario_overlay': {'charging_constraints': {'bev_terminal_soc_policy':'fixed_target',
        'final_soc_target_percent':80, 'final_soc_target_tolerance_percent':20}},
        'vehicles': [{'id':'v', 'initialSoc':.72}]}
    _apply_daily_return_controls(document, 'DEPOT')
    assert document['simulation_config']['bev_terminal_soc_policy'] == 'return_to_initial'
    assert document['simulation_config']['final_soc_target_tolerance_percent'] == 0
    assert document['scenario_overlay']['charging_constraints']['final_soc_target_percent'] is None
    assert document['vehicles'] == [{'id':'v', 'initialSoc':.72}]
    problem = daily_problem()
    problem = replace(problem, metadata={**problem.metadata,
        'rolling_window_terminal_policy':'day_ahead_boundary_state',
        'bev_terminal_soc_policy':'return_to_initial', 'final_soc_target_tolerance_percent':0})
    design = {'bev_evaluation_terminal_policy':'return_to_initial', 'daily_return_depot_id':'DEPOT'}
    audit = verify_evaluation_contract(problem, design)
    assert audit['vehicle_targets']['bev-1'] == {'initial_kwh':80, 'terminal_target_kwh':80}
    for drift in ({'bev_terminal_soc_policy':'fixed_target'}, {'final_soc_target_tolerance_percent':20}):
        with pytest.raises(ValueError):
            verify_evaluation_contract(replace(problem,metadata={**problem.metadata,**drift}), design)


def test_intermediate_bess_reference_uses_physical_floor_and_restores_period_floor():
    problem = daily_problem()
    depot, asset = next(iter(problem.depot_energy_assets.items()))
    initial = asset.bess_initial_soc_kwh
    asset = replace(asset, bess_terminal_soc_min_kwh=initial)
    problem = replace(problem, depot_energy_assets={depot:asset}, metadata={**problem.metadata,
        'rolling_window_terminal_policy':'day_ahead_boundary_state'})
    plan = replace(_fixed_plan(problem), vehicle_soc_kwh_by_vehicle_slot={'bev-1':{25:80}},
        bess_soc_kwh_by_depot_slot={depot:{24:initial-5}})
    rolling = RollingReoptimizer()
    frozen = rolling._freeze_bess_terminal_soc_targets(problem)
    intermediate = rolling._apply_window_terminal_targets(frozen,plan,60,24)
    assert intermediate.depot_energy_assets[depot].bess_terminal_soc_target_kwh == initial-5
    assert intermediate.depot_energy_assets[depot].bess_terminal_soc_min_kwh == asset.bess_soc_min_kwh
    assert intermediate.metadata['bess_daily_balance_target_kwh_by_depot'][depot] == initial
    final = rolling._apply_window_terminal_targets(frozen,plan,24*60,24)
    assert final.depot_energy_assets[depot].bess_terminal_soc_min_kwh == initial


def test_intermediate_day_ahead_bev_target_survives_bess_minimum_only_policy():
    problem = daily_problem()
    depot, asset = next(iter(problem.depot_energy_assets.items()))
    problem = replace(
        problem,
        depot_energy_assets={depot: replace(
            asset,
            bess_terminal_soc_policy="fixed_target",
            bess_terminal_soc_target_kwh=50.0,
        )},
        metadata={**problem.metadata, "rolling_window_terminal_policy": "day_ahead_boundary_state"},
    )
    plan = replace(
        _fixed_plan(problem),
        vehicle_soc_kwh_by_vehicle_slot={"bev-1": {25: 65.0}},
        bess_soc_kwh_by_depot_slot={depot: {24: 45.0}},
    )
    rolling = RollingReoptimizer()
    frozen = rolling._freeze_bev_terminal_soc_targets(problem)
    frozen = rolling._freeze_bess_terminal_soc_targets(frozen)
    intermediate = rolling._apply_window_terminal_targets(frozen, plan, 60, 24)
    applied = rolling._apply_bess_terminal_policy(intermediate, "minimum_only")

    assert applied.metadata["rolling_window_terminal_reference"]["policy"] == "day_ahead_boundary_state"
    assert applied.metadata["bev_terminal_soc_target_kwh_by_vehicle"]["bev-1"] == pytest.approx(65.0)
    assert applied.depot_energy_assets[depot].bess_terminal_soc_policy == "minimum_only"
    assert applied.depot_energy_assets[depot].bess_terminal_soc_target_kwh == 0.0
    assert applied.metadata["rolling_bess_terminal_policy"] == "minimum_only"

    evaluation_end = rolling._apply_window_terminal_targets(frozen, plan, 24 * 60, 24)
    assert evaluation_end.metadata["bev_terminal_soc_target_kwh_by_vehicle"]["bev-1"] == pytest.approx(80.0)


def test_rolling_reference_stays_active_until_paid_next_morning_end():
    problem = daily_problem()
    depot, asset = next(iter(problem.depot_energy_assets.items()))
    problem = replace(
        problem,
        price_slots=problem.price_slots + (replace(problem.price_slots[-1], slot_index=48),),
        depot_energy_assets={depot: replace(
            asset, pv_generation_kwh_by_slot=asset.pv_generation_kwh_by_slot + (0.0,)
        )},
        metadata={**problem.metadata, "rolling_window_terminal_policy": "day_ahead_boundary_state"},
    )
    plan = replace(
        _fixed_plan(problem),
        vehicle_soc_kwh_by_vehicle_slot={"bev-1": {48: 70.0}},
        bess_soc_kwh_by_depot_slot={depot: {47: asset.bess_initial_soc_kwh}},
    )
    rolling = RollingReoptimizer()
    frozen = rolling._freeze_bev_terminal_soc_targets(problem)
    intermediate = rolling._apply_window_terminal_targets(frozen, plan, 24 * 60, 24)
    assert intermediate.metadata["bev_terminal_soc_target_kwh_by_vehicle"]["bev-1"] == 70.0
    final = rolling._apply_window_terminal_targets(frozen, plan, 25 * 60, 24)
    assert final.metadata["bev_terminal_soc_target_kwh_by_vehicle"]["bev-1"] == 80.0


def test_failed_hourly_solve_never_publishes_the_old_reference_energy_trace():
    from src.optimization.rolling.vehicle_execution import vehicle_positions_at
    pytest.importorskip("gurobipy")
    problem = daily_problem()
    rolling = RollingReoptimizer()
    config = OptimizationConfig(time_limit_sec=10, mip_gap=0, gurobi_threads=1,
                                allow_postsolve_repair=False)
    reference = rolling.reoptimize_charging_hour(problem, _fixed_plan(problem), config,
                                                 0, lookahead_hours=48)
    assert reference.feasible, reference.infeasibility_reasons
    assert reference.plan.charging_slots
    # There is no PV or permitted grid charging. A measured deficit cannot
    # meet the unchanged daily BESS equality; this is a real infeasibility.
    failed = rolling.reoptimize_charging_hour(problem, reference.plan, config, 17*60,
        lookahead_hours=24, actual_soc={"bev-1": reference.plan.vehicle_soc_kwh_by_vehicle_slot["bev-1"][17]},
        actual_bess_soc_kwh={"DEPOT": 49}, actual_vehicle_fuel_l={},
        actual_vehicle_positions=vehicle_positions_at(problem, reference.plan, 17*60),
        observed_on_peak_kw_by_depot={"DEPOT": 0}, observed_off_peak_kw_by_depot={"DEPOT": 0})
    assert not failed.feasible
    assert failed.solver_status == "infeasible"
    assert any("STAGE2_NO_INCUMBENT" in reason for reason in failed.infeasibility_reasons)
    assert not failed.plan.duties and not failed.plan.charging_slots
    assert not failed.plan.vehicle_soc_kwh_by_vehicle_slot
    assert not failed.plan.bess_soc_kwh_by_depot_slot
    assert not failed.plan.pv_to_bess_kwh_by_depot_slot
    assert not failed.solver_metadata["stage2_exact_optimality_certified"]


def test_rolling_reference_tolerance_cannot_accumulate_before_an_idle_final_day():
    from src.optimization.rolling.vehicle_execution import vehicle_positions_at
    pytest.importorskip("gurobipy")
    problem = daily_problem()
    problem = replace(
        problem,
        trips=problem.trips[:1],
        dispatch_context=replace(problem.dispatch_context, trips=problem.dispatch_context.trips[:1]),
        metadata={**problem.metadata, "bev_terminal_soc_policy": "return_to_initial",
                  "rolling_window_terminal_policy": "day_ahead_boundary_state"},
        # A negative tariff makes the solver use every permitted increment,
        # exposing an extra tolerance band without relying on tie-breaking.
        price_slots=tuple(replace(slot, grid_buy_yen_per_kwh=-1 if slot.slot_index == 23 else 10)
                          for slot in problem.price_slots),
    )
    reference = replace(
        _fixed_plan(problem),
        vehicle_soc_kwh_by_vehicle_slot={"bev-1": {i: 80.000001 for i in range(49)}},
        bess_soc_kwh_by_depot_slot={"DEPOT": {i: 50 for i in range(48)}},
    )
    rolling = RollingReoptimizer()
    config = OptimizationConfig(time_limit_sec=10, mip_gap=0, gurobi_threads=1,
                                allow_postsolve_repair=False)
    def solve(hour, soc):
        return rolling.reoptimize_charging_hour(
            problem, reference, config, hour*60, lookahead_hours=24,
            actual_soc={"bev-1": soc}, actual_bess_soc_kwh={"DEPOT": 50},
            actual_vehicle_positions=vehicle_positions_at(problem, reference, hour*60),
            actual_vehicle_fuel_l={}, observed_on_peak_kw_by_depot={"DEPOT": 0},
            observed_off_peak_kw_by_depot={"DEPOT": 0},
        )
    first = solve(23, 79)
    assert first.feasible, first.infeasibility_reasons
    observed_soc = first.plan.vehicle_soc_kwh_by_vehicle_slot["bev-1"][24]
    assert observed_soc <= 80.000001 + 1e-9
    final = solve(24, observed_soc)
    assert final.feasible, final.infeasibility_reasons
    assert final.plan.vehicle_soc_kwh_by_vehicle_slot["bev-1"][48] <= 80.000001 + 1e-9


def test_native_phase3_two_day_dispatch_uses_the_declared_fragment_allowance():
    from src.optimization.engine import OptimizationEngine
    from src.optimization.common.problem import OptimizationMode
    pytest.importorskip("gurobipy")
    problem = daily_problem()
    problem = replace(problem, metadata={**problem.metadata,
        "max_start_fragments_per_vehicle": 100, "max_end_fragments_per_vehicle": 100})
    result = OptimizationEngine().solve(problem, OptimizationConfig(mode=OptimizationMode.MILP,
        phase="phase3_two_stage", time_limit_sec=25, stage1_time_limit_sec=15,
        stage2_time_limit_sec=10, mip_gap=.1, gurobi_threads=1, allow_postsolve_repair=False))
    assert result.feasible, result.infeasibility_reasons
    assert set(result.plan.served_trip_ids) == {trip.trip_id for trip in problem.trips}
    physical = validate_physical_event_schedule(problem=problem, serialized_result=ResultSerializer.serialize_plan(result.plan))
    assert physical["accepted"], physical["violations"]


def test_recursive_and_cumulative_soc_have_the_same_native_two_day_solution():
    from src.optimization.engine import OptimizationEngine
    from src.optimization.common.problem import OptimizationMode
    pytest.importorskip("gurobipy")
    results = []
    for representation in ("cumulative", "recursive"):
        problem = daily_problem()
        problem = replace(problem, metadata={**problem.metadata,
            "max_start_fragments_per_vehicle": 100, "max_end_fragments_per_vehicle": 100,
            "stage1_soc_state_representation": representation})
        result = OptimizationEngine().solve(problem, OptimizationConfig(mode=OptimizationMode.MILP,
            phase="phase3_two_stage", time_limit_sec=25, stage1_time_limit_sec=15,
            stage2_time_limit_sec=10, mip_gap=0, gurobi_threads=1, allow_postsolve_repair=False))
        assert result.feasible, result.infeasibility_reasons
        assert set(result.plan.served_trip_ids) == {trip.trip_id for trip in problem.trips}
        physical = validate_physical_event_schedule(problem=problem,
            serialized_result=ResultSerializer.serialize_plan(result.plan))
        assert physical["accepted"], physical["violations"]
        results.append(result)
    assert results[0].cost_breakdown["total_cost"] == pytest.approx(results[1].cost_breakdown["total_cost"], abs=1e-6)
    assert results[0].solver_status == results[1].solver_status


@pytest.mark.parametrize("change_band", [False, True])
def test_cross_day_connection_requires_both_return_and_next_startup(change_band):
    problem = daily_problem()
    if change_band:
        trips = [replace(trip, route_family_code=band)
                 for trip, band in zip(problem.dispatch_context.trips, ("渋21", "渋23"))]
        problem = replace(problem, dispatch_context=replace(
            problem.dispatch_context, trips=trips, fixed_route_band_mode=True))
    first, second = problem.dispatch_context.trips
    check = FeasibilityEngine().can_connect(first, second, problem.dispatch_context, "BEV")
    assert check.feasible
    assert check.deadhead_time_min == 90  # B->depot 60 + depot->A 30, rather than direct 30.
    tight = replace(second, departure_time="10:00", arrival_time="11:00")
    assert not FeasibilityEngine().can_connect(first, tight, problem.dispatch_context, "BEV").feasible
    context = replace(problem.dispatch_context, deadhead_rules={key:value for key,value in problem.dispatch_context.deadhead_rules.items()
                                                               if key != ("B", "DEPOT")})
    assert FeasibilityEngine().can_connect(first, second, context, "BEV").reason_code == "missing_daily_return_deadhead"


def test_operating_date_is_not_the_clock_midnight():
    first, second = daily_problem().trips
    after_midnight = replace(first, departure_min=1450, arrival_min=1500)
    assert not crosses_service_day(first, after_midnight)
    assert crosses_service_day(after_midnight, second)


def test_daily_return_energy_is_spent_before_night_charging_and_all_days_carry():
    problem = daily_problem()
    plan = _fixed_plan(problem)
    events = build_vehicle_timeline(problem, plan)["bev-1"]
    movements = [event for event in events if "deadhead" in event.event_type or event.event_type in ("daily_return","daily_startup","terminal_return")]
    assert [(event.event_type,event.start_min,event.end_min,event.energy_kwh) for event in movements] == [
        ("startup_deadhead",450,480,9), ("daily_return",550,610,18),
        ("daily_startup",1890,1920,9), ("terminal_return",1990,2050,18)]
    assert sum(event.energy_kwh for event in events) == pytest.approx(74)
    home = complete_home_slots(problem, problem.vehicles[0], events)
    assert 10 not in home and 11 in home and 23 in home and 24 in home and 31 not in home
    loads = fixed_path_slot_loads(problem,plan,list(range(48)))
    assert loads.energy_kwh[("bev-1",10)] == 18
    assert sum(loads.energy_kwh.values()) == 74
    charged = replace(plan, charging_slots=(ChargingSlot("bev-1",23,"chg-1",37/.95,charging_depot_id="DEPOT"),
                                            ChargingSlot("bev-1",47,"chg-1",37/.95,charging_depot_id="DEPOT")))
    assert not FeasibilityChecker()._evaluate_soc(problem,charged)
    physical = validate_physical_event_schedule(problem=problem,serialized_result=ResultSerializer.serialize_plan(charged))
    assert physical["accepted"], physical["violations"]
    assert sum(event["energy_kwh"] for event in physical["events"] if event["event_type"] != "charging") == 74
    premature = replace(charged, charging_slots=(replace(charged.charging_slots[0],slot_index=10),charged.charging_slots[1]))
    assert any("depot-residence" in error for error in FeasibilityChecker()._evaluate_soc(problem,premature))
    assert not validate_physical_event_schedule(problem=problem,serialized_result=ResultSerializer.serialize_plan(premature))["accepted"]


def test_next_morning_energy_horizon_checks_paid_final_charge_and_each_deadline():
    problem = daily_problem()
    problem = replace(problem, vehicles=tuple(replace(v, maximum_soc_kwh=80.0) for v in problem.vehicles))
    price = problem.price_slots[-1]
    asset = problem.depot_energy_assets["DEPOT"]
    problem = replace(
        problem,
        price_slots=problem.price_slots + (replace(price, slot_index=48),),
        depot_energy_assets={"DEPOT": replace(
            asset, pv_generation_kwh_by_slot=asset.pv_generation_kwh_by_slot + (0.0,)
        )},
        metadata={**problem.metadata, "bev_soc_deadline_mode": "next_morning_operational_max",
                  "final_overnight_mode": "include",
                  "bev_terminal_soc_policy": "fixed_target", "final_soc_target_percent": 80,
                  "post_return_target_slots": [23, 48]},
    )
    plan = _fixed_plan(problem)
    charged = replace(plan, charging_slots=(
        ChargingSlot("bev-1", 23, "chg-1", 37 / .95, charging_depot_id="DEPOT"),
        ChargingSlot("bev-1", 48, "chg-1", 37 / .95, charging_depot_id="DEPOT"),
    ))
    assert not FeasibilityChecker()._evaluate_soc(problem, charged)
    assert 48 in complete_home_slots(
        problem, problem.vehicles[0], build_vehicle_timeline(problem, charged)["bev-1"]
    )
    evaluator = CostEvaluator()
    cost = evaluator.evaluate(problem, charged)
    vehicle_rows, day_rows = evaluator.build_plan_ledgers(problem, charged, cost)
    assert len(day_rows) == 2
    assert day_rows[-1].total_cost_jpy > 0
    assert sum(row.total_cost_jpy for row in day_rows) == pytest.approx(cost.total_cost, abs=1e-6)
    assert vehicle_rows[-1].end_soc_kwh == pytest.approx(80)
    assert "paid_final_overnight" in day_rows[-1].cost_attribution_policy
    physical = validate_physical_event_schedule(
        problem=problem, serialized_result=ResultSerializer.serialize_plan(charged)
    )
    assert physical["accepted"], physical["violations"]
    without_final = replace(charged, charging_slots=charged.charging_slots[:1])
    errors = FeasibilityChecker()._evaluate_soc(problem, without_final)
    assert any("service_day=1" in error for error in errors), errors
    without_first = replace(charged, charging_slots=charged.charging_slots[1:])
    errors = FeasibilityChecker()._evaluate_soc(problem, without_first)
    assert any("service_day=0" in error for error in errors), errors


@pytest.mark.parametrize("window_target", [None, 30.0, 80.0])
def test_next_morning_phase3_daily_return_native_stage2_preserves_deadlines(window_target):
    from src.gurobi_session import current_session
    if current_session() is None:
        pytest.skip("Native regression requires shared license admission")
    pytest.importorskip("gurobipy")
    from src.optimization.common.problem import OptimizationMode
    from src.optimization.engine import OptimizationEngine

    problem = daily_problem()
    problem = replace(problem, vehicles=tuple(replace(v, maximum_soc_kwh=80.0) for v in problem.vehicles))
    asset = problem.depot_energy_assets["DEPOT"]
    problem = replace(
        problem,
        price_slots=problem.price_slots + (replace(problem.price_slots[-1], slot_index=48),),
        depot_energy_assets={"DEPOT": replace(
            asset, pv_generation_kwh_by_slot=asset.pv_generation_kwh_by_slot + (0.0,)
        )},
        metadata={**problem.metadata,
                  "bev_soc_deadline_mode": "next_morning_operational_max",
                  "final_overnight_mode": "include",
                  "bev_terminal_soc_policy": "fixed_target",
                  "final_soc_target_percent": 80,
                  "post_return_target_slots": [23, 48],
                  "max_start_fragments_per_vehicle": 100,
                  "max_end_fragments_per_vehicle": 100},
    )
    # The rolling terminal reference must not replace a daily departure target.
    problem = replace(problem, metadata={**problem.metadata,
        "bev_terminal_soc_target_kwh_by_vehicle": {"bev-1": window_target} if window_target is not None else {},
        "bev_terminal_soc_policy": "minimum_only" if window_target is None else "fixed_target",
    })
    result = OptimizationEngine().solve(problem, OptimizationConfig(
        mode=OptimizationMode.MILP, phase="phase3_two_stage",
        time_limit_sec=20, stage1_time_limit_sec=10,
        stage2_time_limit_sec=10, mip_gap=.1, gurobi_threads=1,
        allow_postsolve_repair=False,
    ))
    assert result.feasible, result.infeasibility_reasons
    trace = result.plan.vehicle_soc_kwh_by_vehicle_slot["bev-1"]
    assert trace[24] >= 80 - 1e-6
    assert trace[49] >= 80 - 1e-6
    assert result.plan.metadata["stage2_feasible"] is True
    physical = validate_physical_event_schedule(
        problem=problem, serialized_result=ResultSerializer.serialize_plan(result.plan)
    )
    assert physical["accepted"], physical["violations"]


def test_native_duty_fragments_share_one_initial_state():
    problem = daily_problem()
    duties = tuple(VehicleDuty(f"bev-1:{i}","BEV",(DutyLeg(trip,30),)) for i,trip in enumerate(problem.dispatch_context.trips))
    plan = AssignmentPlan(duties=duties,metadata={"duty_vehicle_map":{duty.duty_id:"bev-1" for duty in duties}})
    errors = FeasibilityChecker()._evaluate_soc(problem,plan)
    assert any("SOC=6.0" in error for error in errors), errors
    assert sum(event.energy_kwh for event in build_vehicle_timeline(problem,plan)["bev-1"]) == 74


def test_ice_inventory_includes_daily_returns_and_both_startups():
    problem = daily_problem()
    vehicle = replace(problem.vehicles[0],vehicle_type="ICE",initial_fuel_l=30,fuel_tank_capacity_l=40,
                      fuel_reserve_l=5,fuel_consumption_l_per_km=.3)
    trips = tuple(replace(trip,allowed_vehicle_types=("ICE",),fuel_l=3) for trip in problem.trips)
    dispatch = [replace(trip,allowed_vehicle_types=("ICE",)) for trip in problem.dispatch_context.trips]
    problem = replace(problem,vehicles=(vehicle,),trips=trips,
                      vehicle_types=(replace(problem.vehicle_types[0],vehicle_type_id="ICE",powertrain_type="ICE"),),
                      dispatch_context=replace(problem.dispatch_context,trips=dispatch))
    duty = VehicleDuty("bev-1:0","ICE",tuple(DutyLeg(trip,30 if i==0 else 90) for i,trip in enumerate(dispatch)))
    plan = AssignmentPlan(duties=(duty,),metadata={"duty_vehicle_map":{duty.duty_id:"bev-1"}})
    events = build_vehicle_timeline(problem,plan)["bev-1"]
    assert sum(event.fuel_l for event in events) == pytest.approx(22.2)
    assert not FeasibilityChecker()._evaluate_soc(problem,plan)
    physical = validate_physical_event_schedule(problem=problem,serialized_result=ResultSerializer.serialize_plan(plan))
    assert physical["accepted"],physical["violations"]
    assert sum(event["fuel_l"] for event in physical["events"]) == pytest.approx(22.2)
    from src.optimization.common.evaluator import CostEvaluator
    evaluator = CostEvaluator()
    breakdown = evaluator.evaluate(problem, plan)
    vehicles, days = evaluator.build_plan_ledgers(problem, plan, breakdown)
    assert [row.start_fuel_l for row in vehicles] == pytest.approx([30, 18.9])
    assert [row.end_fuel_l for row in vehicles] == pytest.approx([18.9, 7.8])
    assert breakdown.ice_fuel_consumed_l == pytest.approx(22.2)
    assert sum(row.total_cost_jpy for row in days) == pytest.approx(breakdown.total_cost, abs=1e-6)
    assert days[0].ice_leftover_provisional_cost_jpy == 0
    assert days[1].ice_leftover_provisional_cost_jpy == pytest.approx(breakdown.leftover_ice_provisional_cost)
    assert [row.service_date for row in days] == ["2025-02-03", "2025-02-04"]
    depleted = replace(problem,vehicles=(replace(vehicle,initial_fuel_l=20),))
    assert any("[FUEL]" in error for error in FeasibilityChecker()._evaluate_soc(depleted,plan))
    assert validate_physical_event_schedule(problem=depleted,serialized_result=ResultSerializer.serialize_plan(plan))["metrics"]["fuel_lower_violation_count"] > 0


def test_two_day_native_charging_solve_matches_the_physical_replay():
    pytest.importorskip("gurobipy")
    problem = daily_problem()
    plan = _fixed_plan(problem)
    result = RollingReoptimizer().reoptimize_charging_hour(problem,plan,
              OptimizationConfig(time_limit_sec=15,mip_gap=0,gurobi_threads=1),0,lookahead_hours=48)
    assert result.feasible,result.infeasibility_reasons
    assert sum(slot.charge_kw for slot in result.plan.charging_slots)*.95 == pytest.approx(74,abs=1e-5)
    physical = validate_physical_event_schedule(problem=problem,serialized_result=ResultSerializer.serialize_plan(result.plan))
    assert physical["accepted"],physical["violations"]
    from src.optimization.common.evaluator import CostEvaluator
    evaluator = CostEvaluator()
    breakdown = evaluator.evaluate(problem, result.plan)
    vehicles, days = evaluator.build_plan_ledgers(problem, result.plan, breakdown)
    assert vehicles[1].start_soc_kwh == pytest.approx(vehicles[0].end_soc_kwh)
    assert vehicles[1].end_soc_kwh == pytest.approx(80, abs=1e-5)
    assert sum(row.total_cost_jpy for row in days) == pytest.approx(breakdown.total_cost, abs=1e-6)
    assert all("not_solver_native_source_provenance" in row.cost_attribution_policy for row in days)


def test_execution_state_tracks_partial_trip_and_continuous_fuel():
    from src.optimization.rolling.vehicle_execution import advance_vehicle_prefix, vehicle_positions_at
    problem = daily_problem()
    vehicle = replace(problem.vehicles[0],vehicle_type="ICE",initial_fuel_l=30,fuel_tank_capacity_l=40,
                      fuel_reserve_l=5,fuel_consumption_l_per_km=.3)
    dispatch = [replace(trip,allowed_vehicle_types=("ICE",)) for trip in problem.dispatch_context.trips]
    problem = replace(problem,vehicles=(vehicle,),
                      trips=tuple(replace(trip,allowed_vehicle_types=("ICE",),fuel_l=3) for trip in problem.trips),
                      vehicle_types=(replace(problem.vehicle_types[0],vehicle_type_id="ICE",powertrain_type="ICE"),),
                      dispatch_context=replace(problem.dispatch_context,trips=dispatch))
    duty = VehicleDuty("bev-1:0","ICE",tuple(DutyLeg(trip,30 if i==0 else 90) for i,trip in enumerate(dispatch)))
    plan = AssignmentPlan(duties=(duty,),metadata={"duty_vehicle_map":{duty.duty_id:"bev-1"}})
    fuel,positions,ongoing,_ = advance_vehicle_prefix(problem,plan,start_min=0,stop_min=510)
    assert fuel["bev-1"] == pytest.approx(30-2.7-1.5)
    assert positions["bev-1"]["location_id"] is None
    assert ongoing["bev-1"]["trip_id"] == problem.trips[0].trip_id
    assert ongoing["bev-1"]["remaining_minutes"] == 30
    fuel,_,_,_ = advance_vehicle_prefix(problem,plan,start_min=510,stop_min=1440,prior_fuel_l=fuel)
    assert fuel["bev-1"] == pytest.approx(18.9)
    assert vehicle_positions_at(problem,plan,1440)["bev-1"]["location_id"] == "DEPOT"
    fuel,_,_,_ = advance_vehicle_prefix(problem,plan,start_min=1440,stop_min=2880,prior_fuel_l=fuel)
    assert fuel["bev-1"] == pytest.approx(7.8)
    with pytest.raises(ValueError,match="missing"):
        advance_vehicle_prefix(problem,plan,start_min=1440,stop_min=1500)


def test_48_hourly_prefixes_preserve_state_and_reject_changed_location():
    from src.optimization.rolling.day_ahead_hourly import build_next_execution_state
    pytest.importorskip("gurobipy")
    problem = daily_problem()
    plan = _fixed_plan(problem)
    rolling = RollingReoptimizer()
    config = OptimizationConfig(time_limit_sec=10,mip_gap=0,gurobi_threads=1)
    reference = rolling.reoptimize_charging_hour(problem,plan,config,0,lookahead_hours=48)
    assert reference.feasible,reference.infeasibility_reasons
    plan = reference.plan
    problem = replace(problem,metadata={**problem.metadata,"rolling_window_terminal_policy":"day_ahead_boundary_state"})
    state = None
    executed_charging = []
    for hour in range(48):
        kwargs = {} if state is None else {
            "actual_soc":state.actual_vehicle_soc_kwh,"actual_bess_soc_kwh":state.actual_bess_soc_kwh,
            "actual_vehicle_fuel_l":state.actual_vehicle_fuel_l,"actual_vehicle_positions":state.actual_vehicle_positions,
            "connected_charger_by_vehicle":state.connected_charger_by_vehicle,
            "active_charge_session_vehicle_ids":state.active_charge_session_vehicle_ids,
            "observed_on_peak_kw_by_depot":state.observed_on_peak_kw_by_depot,
            "observed_off_peak_kw_by_depot":state.observed_off_peak_kw_by_depot}
        result = rolling.reoptimize_charging_hour(problem,plan,config,hour*60,lookahead_hours=24,**kwargs)
        assert result.feasible,(hour,result.infeasibility_reasons)
        executed_charging.extend(slot for slot in result.plan.charging_slots if slot.slot_index==hour)
        state = build_next_execution_state(problem,result,current_min=hour*60,execution_minutes=60,
            prior_vehicle_fuel_l={} if state is None else state.actual_vehicle_fuel_l,
            prior_on_peak_kw_by_depot={} if state is None else state.observed_on_peak_kw_by_depot,
            prior_off_peak_kw_by_depot={} if state is None else state.observed_off_peak_kw_by_depot)
        if hour == 24:
            altered = {**kwargs,"actual_vehicle_positions":{"bev-1":{"location_id":"A","in_progress_event":None}}}
            with pytest.raises(ValueError,match="position"):
                rolling.reoptimize_charging_hour(problem,plan,config,hour*60,lookahead_hours=24,**altered)
    assert state.current_min == 2880
    assert state.actual_vehicle_soc_kwh["bev-1"] == pytest.approx(80,abs=1e-6)
    stitched = replace(plan,charging_slots=tuple(executed_charging))
    physical = validate_physical_event_schedule(problem=problem,serialized_result=ResultSerializer.serialize_plan(stitched))
    assert physical["accepted"],physical["violations"]


@pytest.mark.parametrize("window_target", [None, 30.0, 80.0])
def test_next_morning_validator_keeps_operating_max_with_lower_window_target(window_target):
    problem = daily_problem()
    problem = replace(problem, vehicles=tuple(replace(v, maximum_soc_kwh=80.0) for v in problem.vehicles))
    problem = replace(problem, metadata={**problem.metadata,
        "bev_soc_deadline_mode": "next_morning_operational_max",
        "post_return_target_slots": [23, 47],
        "bev_terminal_soc_target_kwh_by_vehicle": {"bev-1": window_target} if window_target is not None else {},
        "bev_terminal_soc_policy": "minimum_only" if window_target is None else "fixed_target",
    })
    # Start at 80, use 37 each day and restore only 27: daily state is 70/60.
    plan = replace(_fixed_plan(problem), charging_slots=tuple(
        ChargingSlot("bev-1", slot, "chg-1", 27 / .95, charging_depot_id="DEPOT")
        for slot in (23, 47)
    ))
    errors = FeasibilityChecker()._evaluate_soc(problem, plan)
    for day in (0, 1):
        assert any(f"service_day={day}" in error and "target=80" in error for error in errors), errors
