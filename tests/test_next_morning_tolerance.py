from types import SimpleNamespace

import pytest

from src.optimization.common.bev_terminal_policy import validate_next_morning_tolerance
from src.optimization.common.executed_soc import audit_executed_bev_targets
from src.optimization.common.problem import (
    AssignmentPlan, CanonicalOptimizationProblem, EnergyPriceSlot, OptimizationScenario, ProblemVehicle,
)
from src.optimization.common.soc_helpers import BEV_TERMINAL_SOC_TARGET_KWH_BY_VEHICLE_KEY, next_morning_required_soc_kwh
from src.optimization.milp.solver_adapter import _stage2_result_accounting_reconciliation


def _problem(tolerance, **metadata):
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="morning", timestep_min=15),
        dispatch_context=None, trips=(),
        vehicles=(ProblemVehicle(vehicle_id="bus", vehicle_type="BEV", home_depot_id="dep",
                                 battery_capacity_kwh=100, initial_soc=80,
                                 reserve_soc=20, maximum_soc_kwh=90),),
        price_slots=tuple(EnergyPriceSlot(slot_index=i) for i in range(2)),
        metadata={"final_soc_target_percent": 90, "final_soc_target_tolerance_percent": tolerance,
                  "bev_terminal_soc_policy": "fixed_target", **metadata},
    )


@pytest.mark.parametrize("tolerance,expected", [(0, 90.0), (None, 90.0), (10, 80.0), (90, 30.0)])
def test_required_level_is_the_maximum_less_the_declared_tolerance(tolerance, expected):
    problem = _problem(tolerance, final_soc_floor_percent=30)
    assert next_morning_required_soc_kwh(problem, problem.vehicles[0]) == pytest.approx(expected)


def test_frozen_rolling_reference_does_not_lower_the_morning_requirement():
    problem = _problem(0, **{BEV_TERMINAL_SOC_TARGET_KWH_BY_VEHICLE_KEY: {"bus": 40.0}})
    assert next_morning_required_soc_kwh(problem, problem.vehicles[0]) == 90.0


@pytest.mark.parametrize("tolerance,soc,accepted,shortfall", [
    (10, 85.0, True, 5.0), (10, 79.0, False, 11.0), (0, 85.0, False, 5.0), (10, 90.0, True, 0.0),
])
def test_executed_morning_uses_the_floor_and_reports_the_shortfall(monkeypatch, tolerance, soc, accepted, shortfall):
    import src.optimization.common.executed_soc as module

    monkeypatch.setattr(module, "build_vehicle_timeline", lambda *_: {"bus": ()})
    monkeypatch.setattr(module, "fixed_path_soc_target_slots", lambda *_: {0: 0})
    problem = _problem(tolerance, bev_soc_deadline_mode="next_morning_operational_max")
    plan = AssignmentPlan(vehicle_soc_kwh_by_vehicle_slot={"bus": {0: 80.0, 1: soc, 2: 90.0}})
    audit = audit_executed_bev_targets(problem, plan)
    deadline = audit["vehicles"]["bus"]["daily_deadlines"]["0"]
    assert deadline["satisfied"] is accepted
    assert deadline["shortfall_to_target_kwh"] == pytest.approx(shortfall)


@pytest.mark.parametrize("tolerance,penalty,accepted", [(10, 50, True), (10, 0, False), (10, None, False), (0, None, True)])
def test_tolerance_requires_a_price_on_the_shortfall(tolerance, penalty, accepted):
    if accepted:
        validate_next_morning_tolerance(tolerance, penalty)
    else:
        with pytest.raises(ValueError, match="SHORTFALL_PENALTY"):
            validate_next_morning_tolerance(tolerance, penalty)


def test_reported_energy_objective_still_reconciles_with_the_ledger():
    breakdown = SimpleNamespace(total_co2_kg=0.0, co2_cost=0.0, grid_electricity_co2_kg=0.0, total_cost=110.0,
                                electricity_cost_provisional_leftover=0.0, fuel_cost=10.0, vehicle_cost=0.0,
                                vehicle_usage_cost=0.0, driver_cost=0.0, unserved_penalty=0.0, switch_cost=0.0,
                                degradation_cost=0.0, deviation_cost=0.0)
    model_objective, penalty = 150.0, 50.0
    _, delta, passed = _stage2_result_accounting_reconciliation(breakdown, stage2_objective_jpy=model_objective - penalty)
    assert passed and delta == pytest.approx(0.0)
    assert not _stage2_result_accounting_reconciliation(breakdown, stage2_objective_jpy=model_objective)[2]
