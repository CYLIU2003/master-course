from dataclasses import replace
from types import SimpleNamespace

import pytest

from scripts.run_hourly_charging_reoptimization import _build_executed_day_accounting
from src.optimization.common.executed_soc import audit_executed_bev_targets
from src.optimization.common.problem import (
    AssignmentPlan, CanonicalOptimizationProblem, EnergyPriceSlot,
    OptimizationScenario, ProblemVehicle,
)


def problem(policy="fixed_target"):
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="executed-target", timestep_min=15),
        dispatch_context=None, trips=(),
        vehicles=(ProblemVehicle(vehicle_id="bus", vehicle_type="BEV", home_depot_id="dep",
                                 battery_capacity_kwh=100, initial_soc=80,
                                 reserve_soc=20, maximum_soc_kwh=90),),
        price_slots=tuple(EnergyPriceSlot(slot_index=i) for i in range(2)),
        metadata={"bev_terminal_soc_policy": policy, "final_soc_target_percent": 80},
    )


@pytest.mark.parametrize("policy,terminal,expected", [
    ("fixed_target", 85., True), ("fixed_target", 79., False),
    ("fixed_target", 91., False), ("return_to_initial", 85., False),
    ("return_to_initial", 80., True), ("minimum_only", 30., True),
    ("minimum_only", 19., False), ("fixed_target", float("nan"), False),
    ("fixed_target", float("inf"), False), ("fixed_target", None, False),
])
def test_actual_terminal_policy_not_forecast_balance(policy, terminal, expected):
    trace = {0: 80., 1: 70.}
    if terminal is not None:
        trace[2] = terminal
    p = problem(policy)
    plan = AssignmentPlan(vehicle_soc_kwh_by_vehicle_slot={"bus": trace})
    assert audit_executed_bev_targets(p, plan)["satisfied"] is expected


@pytest.mark.parametrize("forecast_balanced,terminal,accepted", [(False, 85., True), (True, 79., False)])
def test_accounting_recomputes_terminal_from_executed_trace(forecast_balanced, terminal, accepted):
    p = problem()
    result = SimpleNamespace(
        plan=AssignmentPlan(vehicle_soc_kwh_by_vehicle_slot={"bus": {0: 80., 1: 80., 2: terminal}}),
        solver_metadata={"bev_terminal_soc_balance_satisfied": forecast_balanced},
    )
    accounting = _build_executed_day_accounting(p, AssignmentPlan(), [(p, result, 0, 2)])
    assert accounting["bev_terminal_energy_balanced"] is accepted
    assert accounting["lookahead_bev_inventory_balance_all_windows"] is forecast_balanced
    assert ("bev_terminal_energy_not_balanced" in accounting["rejection_reasons"]) is (not accepted)


def test_missing_used_vehicle_trace_is_rejected():
    from src.optimization.common.problem import ChargingSlot
    plan = AssignmentPlan(charging_slots=(ChargingSlot(vehicle_id="bus", charger_id="c", slot_index=0, charge_kw=1),))
    assert audit_executed_bev_targets(problem(), plan)["satisfied"] is False


@pytest.mark.parametrize("terminal,expected", [(65., True), (80., False), (64., False)])
def test_return_to_initial_uses_initial_not_configured_percentage(terminal, expected):
    p = problem("return_to_initial")
    p = replace(p, vehicles=(replace(p.vehicles[0], initial_soc=65),))
    plan = AssignmentPlan(vehicle_soc_kwh_by_vehicle_slot={"bus": {0: 65., 2: terminal}})
    audit = audit_executed_bev_targets(p, plan)
    assert audit["vehicles"]["bus"]["target_soc_kwh"] == 65.
    assert audit["satisfied"] is expected


@pytest.mark.parametrize("at_deadline,expected", [(90., True), (89., False), (None, False)])
def test_daily_deadline_is_not_replaced_by_later_full_charge(monkeypatch, at_deadline, expected):
    from src.optimization.common import executed_soc
    monkeypatch.setattr(executed_soc, "build_vehicle_timeline", lambda p, plan: {"bus": ()})
    monkeypatch.setattr(executed_soc, "fixed_path_soc_target_slots", lambda p, events: {0: 0})
    p = problem()
    p = replace(p, metadata={**p.metadata, "bev_soc_deadline_mode": "next_morning_operational_max"})
    trace = {0: 80., 2: 90.}
    if at_deadline is not None:
        trace[1] = at_deadline
    audit = audit_executed_bev_targets(p, AssignmentPlan(vehicle_soc_kwh_by_vehicle_slot={"bus": trace}))
    assert audit["satisfied"] is expected
    assert audit["vehicles"]["bus"]["daily_deadlines"]["0"]["boundary_slot"] == 1
