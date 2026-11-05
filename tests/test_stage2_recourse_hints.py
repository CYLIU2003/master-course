"""Day-ahead Stage 2 search hints from the Stage 1 energy recourse (stage1_recourse_hints)."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.optimization.common.problem import OptimizationConfig
from src.optimization.common.result import ResultSerializer
from src.optimization.milp.charging_mip_start import (
    CHARGING_START_POLICIES, RECOURSE_HINT_POLICY, apply_recourse_hints, validate_charging_start_policy,
)
from src.optimization.validation.physical_event_schedule import validate_physical_event_schedule
from test_daily_return_policy import daily_problem


def var():
    return SimpleNamespace(VarHintVal=None, LB=0.0, UB=1.0)


def test_hints_write_only_hint_values_inside_the_window():
    recourse = {"bess_soc_kwh_by_depot_slot": {"d": {"10": 50.0, "11": 40.0}},
                "grid_import_kwh_by_depot_slot": {"d": {"10": 2.5, "11": -0.0}},
                "charge_power_kw_by_vehicle_slot": {"v": {"10": 30.0, "11": 0.0}, "w": {"10": 9.0}}}
    soc = {("d", 10): var(), ("d", 11): var(), ("d", 12): var()}
    grid = {("d", 10): var(), ("d", 11): var()}
    on = {("v", 10): var(), ("v", 11): var(), ("w", 10): var()}
    audit = apply_recourse_hints(recourse=recourse, slot_indices=[10, 11], bess_soc_vars=soc,
                                 grid_import_vars=grid, charge_on_vars=on, vehicle_ids=["v"])
    assert audit["status"] == "APPLIED" and audit["scope"] == "variable_hints_only"
    assert (audit["bess_soc_hints"], audit["grid_import_hints"], audit["charge_on_hints"]) == (2, 2, 2)
    assert [soc[k].VarHintVal for k in sorted(soc)] == [50.0, 40.0, None]
    assert on[("v", 10)].VarHintVal == 1.0 and on[("v", 11)].VarHintVal == 0.0
    assert on[("w", 10)].VarHintVal is None  # not an assigned BEV of this solve
    assert all((v.LB, v.UB) == (0.0, 1.0) for v in on.values())  # bounds untouched


def test_policy_is_declared_and_defaults_stay_off():
    assert RECOURSE_HINT_POLICY in CHARGING_START_POLICIES
    assert validate_charging_start_policy(RECOURSE_HINT_POLICY) == RECOURSE_HINT_POLICY
    assert OptimizationConfig().stage2_charging_start_policy == "none"


def test_native_hints_leave_the_two_day_optimum_unchanged(admitted_gurobi_session):
    from src.optimization.engine import OptimizationEngine
    from src.optimization.common.problem import OptimizationMode
    pytest.importorskip("gurobipy")
    results = {}
    for policy in ("none", RECOURSE_HINT_POLICY):
        problem = daily_problem()
        problem = replace(problem, metadata={**problem.metadata,
            "max_start_fragments_per_vehicle": 100, "max_end_fragments_per_vehicle": 100})
        result = OptimizationEngine().solve(problem, OptimizationConfig(mode=OptimizationMode.MILP,
            phase="phase3_two_stage", time_limit_sec=25, stage1_time_limit_sec=15, stage2_time_limit_sec=10,
            mip_gap=0, gurobi_threads=1, allow_postsolve_repair=False, stage2_charging_start_policy=policy))
        assert result.feasible, result.infeasibility_reasons
        physical = validate_physical_event_schedule(problem=problem, serialized_result=ResultSerializer.serialize_plan(result.plan))
        assert physical["accepted"], physical["violations"]
        results[policy] = result
    hinted = results[RECOURSE_HINT_POLICY].solver_metadata["stage2_charging_start"]
    assert hinted["policy"] == RECOURSE_HINT_POLICY and hinted["hints"]["status"] == "APPLIED"
    assert results["none"].cost_breakdown["total_cost"] == pytest.approx(
        results[RECOURSE_HINT_POLICY].cost_breakdown["total_cost"], abs=1e-6)
