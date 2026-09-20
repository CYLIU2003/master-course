"""Behavioral regression: future plans must obey the next controller's rule."""
from dataclasses import replace

import pytest

from src.gurobi_runtime import ensure_gurobi
from src.optimization.common.bess_reserve_policy import (
    EVALUATION_TARGET_EVERY_PREFIX, EVALUATION_TARGET_ZERO_PV, POLICY_KEY,
    freeze_bess_terminal_soc_targets,
)
from src.optimization.milp.pv_execution_reserve import add_pv_execution_reserve_constraints
from test_bess_forecast_reserve import protected
from test_rolling_pv_execution_reserve import _problem, _config


def consistent_problem():
    p = protected(_problem(initial_soc={"DEPOT": 50.0}, period_floors={"DEPOT": 20.0}))
    return freeze_bess_terminal_soc_targets(replace(p, metadata={**p.metadata,
        POLICY_KEY: EVALUATION_TARGET_EVERY_PREFIX,
        "date_series_contract": {**p.metadata["date_series_contract"],
                                 POLICY_KEY: EVALUATION_TARGET_EVERY_PREFIX}}))


def replay(policy, pv, *, planning_only=False):
    gp, grb = ensure_gurobi()
    p = consistent_problem()
    p = replace(p, metadata={**p.metadata, POLICY_KEY: policy,
                            "date_series_contract": {**p.metadata["date_series_contract"], POLICY_KEY: policy}})
    soc, cost, starts, charged, audit = 50.0, 0.0, [], [], {}
    # A tiny positive PV cycling price removes the old plan's artificial tie:
    # borrow protected inventory tomorrow, recharge later, curtail PV today.
    for hour in range(1 if planning_only else 3):
        asset = replace(p.depot_energy_assets["DEPOT"], bess_initial_soc_kwh=soc,
                        bess_charge_efficiency=1.0, bess_discharge_efficiency=1.0)
        problem = replace(p, depot_energy_assets={"DEPOT": asset})
        model = gp.Model("planning_consistency_regression")
        model.Params.OutputFlag = 0
        slots = tuple(range(hour, 3))
        maps = {name: {("DEPOT", s): model.addVar(lb=0) for s in slots}
                for name in ("grid", "pv_bus", "grid_bess", "discharge", "charge", "soc")}
        try:
            for s in slots:
                key = ("DEPOT", s)
                demand = 10 if s == 1 else 0
                model.addConstr(maps["grid"][key] + maps["pv_bus"][key] + maps["discharge"][key] == demand)
                model.addConstr(maps["pv_bus"][key] + maps["charge"][key] <= pv[s])
                model.addConstr(maps["grid_bess"][key] == 0)
                model.addConstr(maps["soc"][key] >= 20)
                model.addConstr(maps["soc"][key] <= 60)
                end = maps["soc"][key] + maps["charge"][key] - maps["discharge"][key]
                model.addConstr(end >= 20)
                model.addConstr(end <= 60)
                model.addConstr(end == (50 if s == 2 else maps["soc"][("DEPOT", s+1)]))
            model.addConstr(maps["soc"][("DEPOT", hour)] == soc)
            audit = add_pv_execution_reserve_constraints(
                model, problem, _config(execution_minutes=60), slots,
                is_remaining_day_reoptimization=not planning_only,
                grid_to_bus_var=maps["grid"], pv_to_bus_var=maps["pv_bus"],
                grid_to_bess_var=maps["grid_bess"], bess_to_bus_var=maps["discharge"],
                bess_soc_start_var=maps["soc"])
            model.setObjective(gp.quicksum(10 * maps["grid"][k] + .01 * maps["charge"][k] for k in maps["grid"]), grb.MINIMIZE)
            model.optimize()
            assert model.Status == grb.OPTIMAL
            if planning_only:
                return model.ObjVal, audit
            key = ("DEPOT", hour)
            starts.append(soc)
            charged.append(maps["charge"][key].X)
            soc += maps["charge"][key].X - maps["discharge"][key].X
            cost += 10 * maps["grid"][key].X + .01 * maps["charge"][key].X
            assert soc >= 50 - 1e-7
        finally:
            model.dispose()
    assert soc == pytest.approx(50)
    return cost, starts, charged


def test_consistent_planning_stores_early_pv_and_avoids_later_grid_cost():
    old = replay(EVALUATION_TARGET_ZERO_PV, [10, 0, 10])
    new = replay(EVALUATION_TARGET_EVERY_PREFIX, [10, 0, 10])
    assert old[0] == pytest.approx(100)
    assert old[2][0] == pytest.approx(0)
    assert new[0] == pytest.approx(.1)
    assert new[2][0] == pytest.approx(10)
    assert new[1][1] == pytest.approx(60)


@pytest.mark.parametrize("pv", [[0, 0, 10], [10, 0, 10], [20, 0, 10]])
def test_more_early_pv_does_not_increase_cost_in_controlled_perfect_forecast_case(pv):
    cost, _, _ = replay(EVALUATION_TARGET_EVERY_PREFIX, pv)
    assert cost == pytest.approx(100 if pv[0] == 0 else .1)


def test_day_ahead_applies_same_future_reserve_as_controller():
    objective, audit = replay(EVALUATION_TARGET_EVERY_PREFIX, [0, 0, 10], planning_only=True)
    assert objective == pytest.approx(100)
    assert audit["planning_reserve"]["protected_slot_indices"] == [0, 1, 2]


def test_stage1_recourse_cannot_borrow_reserve_before_late_pv():
    from test_weather_coupled_assignment import _problem as recourse_problem
    from src.optimization.common.problem import DepotEnergyAsset
    from src.optimization.milp.solver_adapter import GurobiMILPAdapter
    gp, grb = ensure_gurobi()
    asset = DepotEnergyAsset(depot_id="tsurumaki", pv_enabled=True,
        pv_generation_kwh_by_slot=(0.0, 10.0), bess_enabled=True,
        bess_energy_kwh=100, bess_power_kw=100, bess_initial_soc_kwh=50,
        bess_soc_min_kwh=20, bess_soc_max_kwh=80, bess_charge_efficiency=1,
        bess_discharge_efficiency=1, bess_balance_period="evaluation_period",
        bess_terminal_soc_policy="return_to_initial", allow_grid_to_bess=False,
        allow_pv_to_bess=True, allow_bess_to_bus=True)
    p = recourse_problem(pv_kwh_by_slot=(0., 10.), grid_prices=(10., 10.), asset=asset,
                         enable_contract_overage_penalty=True)
    p = freeze_bess_terminal_soc_targets(protected(p, EVALUATION_TARGET_EVERY_PREFIX))
    model = gp.Model("stage1_reserve_regression")
    model.Params.OutputFlag = 0
    try:
        charges = {("bev", s): model.addVar(lb=v, ub=v) for s, v in enumerate((10., 0.))}
        recourse = GurobiMILPAdapter()._add_stage1_time_indexed_energy_recourse_relaxation(
            model, gp=gp, grb=grb, problem=p, component_flags={}, config=_config(execution_minutes=60),
            recourse_state={"slot_indices": (0, 1), "timestep_h": 1.,
                            "charge_power_by_vehicle_slot": charges,
                            "electric_vehicle_by_id": {"bev": p.vehicles[0]}})
        model.setObjective(recourse.objective_expression, grb.MINIMIZE)
        model.optimize()
        assert model.Status == grb.OPTIMAL
        assert recourse.grid_to_bus_by_depot_slot[("tsurumaki", 0)].X == pytest.approx(10)
        assert recourse.configuration["bess_planning_reserve"]["bess_floor_constraint_count"] == 2
    finally:
        model.dispose()


def test_independent_audit_rejects_a_future_reserve_violation():
    from scripts.benchmarks.audit_bess_forecast_reserve import verify_planning_reserve
    native = {"metadata": {"bess_soc_start_kwh_by_depot_slot": {"DEPOT": {"0": 50., "1": 50.}}},
              "grid_to_bess_kwh_by_depot_slot": {},
              "bess_to_bus_kwh_by_depot_slot": {"DEPOT": {"1": 1.}}}
    with pytest.raises(ValueError, match="future forecast block spends"):
        verify_planning_reserve(native, depot="DEPOT", target=50., eta_charge=1.,
                                eta_discharge=1., slots=[0, 1], block_size=1)
