"""Regression for cyclic PV-only storage after an unexpectedly dark prefix."""
from dataclasses import replace

import pytest

from src.optimization.common.bess_reserve_policy import (
    EVALUATION_TARGET_ZERO_PV, POLICY_KEY, bess_reserve_policy, bess_reserve_targets,
)
from src.optimization.common.problem import OptimizationConfig
from src.optimization.milp.pv_execution_reserve import add_pv_execution_reserve_constraints
from src.optimization.rolling.reoptimizer import RollingReoptimizer
from test_rolling_bess_boundary_policy import _boundary_problem, _CaptureEngine
from test_rolling_pv_execution_reserve import _problem, _flow_model, _fix, _config


def protected(problem):
    return replace(problem, depot_energy_assets={
        d: replace(a, bess_balance_period="evaluation_period", allow_grid_to_bess=False,
                   bess_terminal_soc_policy="return_to_initial")
        for d, a in problem.depot_energy_assets.items()
    }, metadata={**problem.metadata, POLICY_KEY: EVALUATION_TARGET_ZERO_PV,
                 "enable_contract_overage_penalty": True,
                 "date_series_contract": {"pv_information_mode": "training_only_forecast_proxy",
                                          POLICY_KEY: EVALUATION_TARGET_ZERO_PV}})


@pytest.mark.parametrize("current_min,reference", [(0, 1200.0), (24 * 60, 4800.0)])
def test_original_target_survives_measured_soc_and_intermediate_or_final_window(current_min, reference):
    problem, plan, depot = _boundary_problem(bess_reference=reference, physical_floor=1200.0)
    problem = protected(problem)
    # No BESS day-ahead trace should be necessary under the protected policy.
    plan = replace(plan, bess_soc_kwh_by_depot_slot={})
    rolling = RollingReoptimizer()
    capture = _CaptureEngine()
    rolling._engine = capture
    from src.optimization.rolling.vehicle_execution import vehicle_positions_at
    rolling.reoptimize_charging_hour(problem, plan, OptimizationConfig(), current_min,
                                     lookahead_hours=24, actual_bess_soc_kwh={depot: 3200.0},
                                     actual_soc={"bev-1": 80.0}, actual_vehicle_fuel_l={},
                                     actual_vehicle_positions=vehicle_positions_at(problem, plan, current_min),
                                     observed_on_peak_kw_by_depot={depot: 0.0},
                                     observed_off_peak_kw_by_depot={depot: 0.0})
    asset = capture.problem.depot_energy_assets[depot]
    assert asset.bess_initial_soc_kwh == 3200.0
    assert asset.bess_terminal_soc_target_kwh == 3000.0
    assert asset.bess_terminal_soc_policy == "fixed_target"
    assert asset.bess_soc_min_kwh == 1200.0
    assert bess_reserve_targets(capture.problem) == {depot: 3000.0}
    if current_min == 0:
        assert capture.problem.metadata["bev_terminal_soc_target_kwh_by_vehicle"] == {"bev-1": 80.0}
        assert capture.problem.metadata["rolling_window_terminal_reference"]["bess_policy"] == EVALUATION_TARGET_ZERO_PV


def test_protection_rejects_a_policy_that_would_erase_the_terminal_target():
    problem, plan, _ = _boundary_problem()
    with pytest.raises(ValueError, match="retain the scenario"):
        RollingReoptimizer().reoptimize_charging_hour(
            protected(problem), plan, OptimizationConfig(), 0,
            lookahead_hours=24, bess_terminal_policy="minimum_only")


@pytest.mark.parametrize("discharge,expected_feasible", [(0.0, True), (0.8, False)])
def test_forecast_recharge_cannot_fund_spending_the_evaluation_reserve(discharge, expected_feasible):
    pytest.importorskip("gurobipy")
    p = protected(_problem(initial_soc={"DEPOT": 50.0}, period_floors={"DEPOT": 20.0}))
    p = RollingReoptimizer._freeze_bess_terminal_soc_targets(p)
    model, maps, grb = _flow_model(p, (0, 1))
    try:
        _fix(model, maps["grid_to_bess"], "DEPOT", {0: 0.0, 1: 0.0})
        _fix(model, maps["bess_to_bus"], "DEPOT", {0: discharge, 1: 0.0})
        audit = add_pv_execution_reserve_constraints(
            model, p, _config(execution_minutes=60), (0, 1),
            is_remaining_day_reoptimization=True, grid_to_bus_var=maps["grid_to_bus"],
            pv_to_bus_var=maps["pv_to_bus"], grid_to_bess_var=maps["grid_to_bess"],
            bess_to_bus_var=maps["bess_to_bus"])
        model.optimize()
        assert (model.Status == grb.OPTIMAL) == expected_feasible
        assert audit["protected_floor_kwh_by_depot"] == {"DEPOT": 50.0}
        assert audit["physical_floor_kwh_by_depot"] == {"DEPOT": 20.0}
    finally:
        model.dispose()


def test_observed_surplus_can_still_supply_buses_with_efficiency_loss():
    pytest.importorskip("gurobipy")
    p = protected(_problem(initial_soc={"DEPOT": 50.0}, period_floors={"DEPOT": 20.0}))
    p = RollingReoptimizer._freeze_bess_terminal_soc_targets(p)
    p = replace(p, depot_energy_assets={"DEPOT": replace(p.depot_energy_assets["DEPOT"], bess_initial_soc_kwh=60.0)})
    model, maps, grb = _flow_model(p, (0,))
    try:
        _fix(model, maps["grid_to_bess"], "DEPOT", {0: 0.0})
        _fix(model, maps["bess_to_bus"], "DEPOT", {0: 8.0})
        add_pv_execution_reserve_constraints(
            model, p, _config(execution_minutes=60), (0,),
            is_remaining_day_reoptimization=True, grid_to_bus_var=maps["grid_to_bus"],
            pv_to_bus_var=maps["pv_to_bus"], grid_to_bess_var=maps["grid_to_bess"],
            bess_to_bus_var=maps["bess_to_bus"])
        model.optimize()
        assert model.Status == grb.OPTIMAL
    finally:
        model.dispose()


@pytest.mark.parametrize("change,match", [
    ({"enable_contract_overage_penalty": False}, "paid grid"),
    ({"bess_terminal_soc_target_kwh_by_depot": {}}, "Missing frozen"),
    ({"bess_terminal_soc_target_kwh_by_depot": {"DEPOT": float("nan")}}, "Invalid frozen"),
    ({POLICY_KEY: "physical_floor_only"}, "differs from"),
])
def test_invalid_or_conflicting_reserve_contracts_fail_closed(change, match):
    p = protected(_problem(initial_soc={"DEPOT": 50.0}, period_floors={"DEPOT": 20.0}))
    p = RollingReoptimizer._freeze_bess_terminal_soc_targets(p)
    with pytest.raises(ValueError, match=match):
        bess_reserve_targets(replace(p, metadata={**p.metadata, **change}))


def test_legacy_policy_does_not_add_a_terminal_reserve():
    p = _problem()
    assert bess_reserve_policy(p) == "physical_floor_only"
    assert bess_reserve_targets(p) == {}


@pytest.mark.parametrize("bright_hours", [0, 12])
def test_native_48_hour_chain_survives_forecast_overprediction_and_restores_inventory(bright_hours):
    pytest.importorskip("gurobipy")
    from src.optimization.rolling.pv_execution import execute_pv_prefix
    from src.optimization.rolling.day_ahead_hourly import build_next_execution_state
    from src.optimization.common.result import ResultSerializer
    from scripts.benchmarks.audit_bess_forecast_reserve import verify_prefix
    from test_daily_return_policy import daily_problem
    from test_multiday_rolling_contract import _fixed_plan

    p = protected(daily_problem())
    p = replace(p, depot_energy_assets={"DEPOT": replace(p.depot_energy_assets["DEPOT"],
        bess_soc_min_kwh=20.0, pv_generation_kwh_by_slot=(30.0,) * 48)},
        metadata={**p.metadata, "rolling_window_terminal_policy": "day_ahead_boundary_state"})
    config = OptimizationConfig(time_limit_sec=10, stage2_time_limit_sec=10, mip_gap=0,
                                gurobi_threads=1, allow_postsolve_repair=False)
    rolling = RollingReoptimizer()
    reference = rolling.reoptimize_charging_hour(p, _fixed_plan(p), config, 0).plan
    assert reference.vehicle_soc_kwh_by_vehicle_slot
    state = None
    for hour in range(48):
        kwargs = {} if state is None else {
            "actual_soc": state.actual_vehicle_soc_kwh,
            "actual_bess_soc_kwh": state.actual_bess_soc_kwh,
            "actual_vehicle_positions": state.actual_vehicle_positions,
            "actual_vehicle_fuel_l": state.actual_vehicle_fuel_l,
            "connected_charger_by_vehicle": state.connected_charger_by_vehicle,
            "active_charge_session_vehicle_ids": state.active_charge_session_vehicle_ids,
            "observed_on_peak_kw_by_depot": state.observed_on_peak_kw_by_depot,
            "observed_off_peak_kw_by_depot": state.observed_off_peak_kw_by_depot,
        }
        result = rolling.reoptimize_charging_hour(p, reference, config, hour * 60, lookahead_hours=24, **kwargs)
        assert result.feasible, (hour, result.infeasibility_reasons)
        initial = state.actual_bess_soc_kwh if state else {"DEPOT": 50.0}
        executed_problem, executed, audit = execute_pv_prefix(
            p, result, actual_pv_by_depot_slot={"DEPOT": {hour: 30.0 if hour < bright_hours else 0.0}},
            actual_bess_soc_kwh=initial, start_slot=hour, stop_slot=hour + 1)
        assert audit["future_observations_used"] is False
        assert audit["rows"][0]["grid_to_bess_kwh"] == pytest.approx(0, abs=1e-9)
        assert audit["rows"][0]["bess_soc_kwh"] >= 50.0 - 1e-6
        verify_prefix(audit["rows"], ResultSerializer.serialize_result(result), depot="DEPOT", target=50.0,
                      eta_charge=p.depot_energy_assets["DEPOT"].bess_charge_efficiency,
                      eta_discharge=p.depot_energy_assets["DEPOT"].bess_discharge_efficiency)
        state = build_next_execution_state(executed_problem, executed, current_min=hour * 60,
                                          execution_minutes=60)
    assert state.actual_bess_soc_kwh["DEPOT"] == pytest.approx(50.0, abs=1e-6)


def test_independent_audit_rejects_spending_reserve_even_if_actual_pv_hides_it():
    from scripts.benchmarks.audit_bess_forecast_reserve import verify_prefix
    rows = [{"depot_id": "DEPOT", "slot_index": 0, "initial_bess_soc_kwh": 50.0,
             "bess_soc_kwh": 50.0, "grid_to_bess_kwh": 0.0,
             "pv_to_bess_kwh": 10 / 0.95, "bess_to_bus_kwh": 9.5}]
    forecast = {"grid_to_bess_kwh_by_depot_slot": {},
                "bess_to_bus_kwh_by_depot_slot": {"DEPOT": {"0": 9.5}}}
    with pytest.raises(ValueError, match="spends terminal reserve"):
        verify_prefix(rows, forecast, depot="DEPOT", target=50.0, eta_charge=0.95, eta_discharge=0.95)


def test_new_monthly_design_declares_reserve_and_report_explains_operating_capacity():
    import json
    from pathlib import Path
    from scripts.benchmarks.seasonal_design_contract import seasonal_bess_controls
    from scripts.build_monthly_interpretation import bess_condition_text
    d = json.loads((Path(__file__).resolve().parents[1] / "config/shibu21_23_monthly_reserve_20260920.json").read_text(encoding="utf-8"))
    assert seasonal_bess_controls(d)[POLICY_KEY] == EVALUATION_TARGET_ZERO_PV
    text = bess_condition_text(d)
    assert "50%" in text and "PVのみ" in text and "各rolling窓末" in text
    for changed in ({POLICY_KEY: "unknown"}, {"rolling_bess_terminal_policy": "minimum_only"}):
        with pytest.raises(ValueError):
            seasonal_bess_controls({**d, **changed})
