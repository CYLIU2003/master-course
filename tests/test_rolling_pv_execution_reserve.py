from dataclasses import replace

import pytest

from src.gurobi_runtime import ensure_gurobi, is_gurobi_available
from src.optimization.common.problem import (
    DepotEnergyAsset,
    OptimizationConfig,
    ProblemDepot,
)
from src.optimization.milp.pv_execution_reserve import (
    add_pv_execution_reserve_constraints,
    committed_pv_execution_slots,
)
from src.optimization.milp.solver_adapter import ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT
from src.optimization.rolling.pv_execution import IssuedEnergyCommand, execute_energy_slot
from test_daily_return_policy import daily_problem


pytestmark = pytest.mark.skipif(
    not is_gurobi_available(), reason="Gurobi is required for native reserve tests"
)


def _problem(
    *,
    depot_ids=("DEPOT",),
    physical_floors=None,
    period_floors=None,
    initial_soc=None,
    bess_enabled=True,
    import_limit_kw=100.0,
    information_mode="training_only_forecast_proxy",
    hard_import=False,
):
    base = daily_problem()
    physical_floors = physical_floors or {depot_id: 20.0 for depot_id in depot_ids}
    period_floors = period_floors or {depot_id: 80.0 for depot_id in depot_ids}
    initial_soc = initial_soc or {depot_id: physical_floors[depot_id] for depot_id in depot_ids}
    assets = {}
    for depot_id in depot_ids:
        assets[depot_id] = DepotEnergyAsset(
            depot_id=depot_id,
            bess_enabled=bess_enabled,
            bess_energy_kwh=100.0,
            bess_power_kw=100.0,
            bess_initial_soc_kwh=initial_soc[depot_id],
            bess_soc_min_kwh=physical_floors[depot_id],
            bess_soc_max_kwh=100.0,
            bess_charge_efficiency=0.9,
            bess_discharge_efficiency=0.8,
            allow_grid_to_bess=True,
            allow_pv_to_bess=True,
            allow_bess_to_bus=True,
            bess_terminal_soc_min_kwh=period_floors[depot_id],
            bess_terminal_soc_policy="minimum_only",
        )
    depots = tuple(
        ProblemDepot(depot_id=depot_id, name=depot_id, import_limit_kw=import_limit_kw)
        for depot_id in depot_ids
    )
    return replace(
        base,
        scenario=replace(base.scenario, timestep_min=60),
        depots=depots,
        depot_energy_assets=assets,
        metadata={
            **base.metadata,
            "date_series_contract": {"pv_information_mode": information_mode},
            "enable_contract_overage_penalty": bool(not hard_import),
        },
    )


def _config(*, execution_minutes=180):
    return OptimizationConfig(
        rolling_horizon_policy=ROLLING_REMAINING_DAY_FIXED_ASSIGNMENT,
        rolling_execution_minutes=execution_minutes,
    )


def _flow_model(problem, slots):
    gp, grb = ensure_gurobi()
    model = gp.Model("pv_execution_reserve_test")
    model.Params.OutputFlag = 0
    maps = {name: {} for name in ("grid_to_bus", "pv_to_bus", "grid_to_bess", "bess_to_bus")}
    for depot_id in problem.depot_energy_assets:
        for slot in slots:
            for name in maps:
                maps[name][(depot_id, slot)] = model.addVar(lb=0.0, name=f"{name}_{depot_id}_{slot}")
    model.update()
    model.setObjective(0.0, grb.MINIMIZE)
    return model, maps, grb


def _fix(model, variable_map, depot_id, values):
    for slot, value in values.items():
        model.addConstr(variable_map[(depot_id, slot)] == value)


def _solve(model, grb):
    model.optimize()
    return model.Status


def test_forecast_storage_cannot_fund_an_early_discharge_and_each_prefix_is_checked():
    problem = _problem(initial_soc={"DEPOT": 20.0}, physical_floors={"DEPOT": 20.0})
    slots = (5, 6, 7, 8)
    model, maps, grb = _flow_model(problem, slots)
    # The later grid charge would recover the ending inventory, but the first
    # committed slot already falls below the physical floor. The reserve API
    # intentionally has no PV-to-BESS input, so forecast PV cannot be credited.
    _fix(model, maps["grid_to_bess"], "DEPOT", {5: 0.0, 6: 2.0, 7: 0.0, 8: 0.0})
    _fix(model, maps["bess_to_bus"], "DEPOT", {5: 1.0, 6: 0.0, 7: 0.0, 8: 100.0})
    audit = add_pv_execution_reserve_constraints(
        model, problem, _config(), slots,
        is_remaining_day_reoptimization=True,
        grid_to_bus_var=maps["grid_to_bus"], pv_to_bus_var=maps["pv_to_bus"],
        grid_to_bess_var=maps["grid_to_bess"], bess_to_bus_var=maps["bess_to_bus"],
    )
    assert audit["committed_slot_indices"] == [5, 6, 7]
    assert audit["bess_floor_constraint_count"] == 3
    assert _solve(model, grb) == grb.INFEASIBLE


def test_grid_charge_can_fund_exact_efficiency_adjusted_discharge_and_replay_at_zero_pv():
    problem = _problem(initial_soc={"DEPOT": 50.0}, physical_floors={"DEPOT": 20.0})
    slots = (5, 6, 7)
    model, maps, grb = _flow_model(problem, slots)
    _fix(model, maps["grid_to_bess"], "DEPOT", {5: 10.0, 6: 0.0, 7: 0.0})
    _fix(model, maps["bess_to_bus"], "DEPOT", {5: 0.0, 6: 31.2, 7: 0.0})
    for name in ("grid_to_bus", "pv_to_bus"):
        _fix(model, maps[name], "DEPOT", {5: 0.0, 6: 0.0, 7: 0.0})
    audit = add_pv_execution_reserve_constraints(
        model, problem, _config(), slots,
        is_remaining_day_reoptimization=True,
        grid_to_bus_var=maps["grid_to_bus"], pv_to_bus_var=maps["pv_to_bus"],
        grid_to_bess_var=maps["grid_to_bess"], bess_to_bus_var=maps["bess_to_bus"],
    )
    assert audit["bess_floor_constraint_count"] == 3
    assert _solve(model, grb) == grb.OPTIMAL

    asset = problem.depot_energy_assets["DEPOT"]
    first = execute_energy_slot(
        asset, IssuedEnergyCommand(bus_demand_kwh=0.0, grid_to_bess_kwh=10.0),
        actual_pv_kwh=0.0, initial_bess_soc_kwh=50.0,
        timestep_minutes=60, import_limit_kw=100.0,
        allow_contract_overage=False, slot_index=5, grid_price_yen_per_kwh=0.0,
    )
    second = execute_energy_slot(
        asset, IssuedEnergyCommand(bus_demand_kwh=31.2, bess_to_bus_kwh=31.2),
        actual_pv_kwh=0.0, initial_bess_soc_kwh=first.bess_soc_kwh,
        timestep_minutes=60, import_limit_kw=100.0,
        allow_contract_overage=False, slot_index=6, grid_price_yen_per_kwh=0.0,
    )
    assert first.bess_soc_kwh == pytest.approx(59.0)
    assert second.bess_soc_kwh == pytest.approx(20.0)


def test_reserve_stops_after_execution_prefix_and_supports_nonzero_origin():
    problem = _problem(initial_soc={"DEPOT": 20.0}, physical_floors={"DEPOT": 20.0})
    slots = (5, 6, 7, 8)
    model, maps, grb = _flow_model(problem, slots)
    _fix(model, maps["bess_to_bus"], "DEPOT", {8: 100.0})
    audit = add_pv_execution_reserve_constraints(
        model, problem, _config(execution_minutes=180), slots,
        is_remaining_day_reoptimization=True,
        grid_to_bus_var=maps["grid_to_bus"], pv_to_bus_var=maps["pv_to_bus"],
        grid_to_bess_var=maps["grid_to_bess"], bess_to_bus_var=maps["bess_to_bus"],
    )
    assert audit["committed_slot_indices"] == [5, 6, 7]
    assert _solve(model, grb) == grb.OPTIMAL


def test_perfect_information_and_day_ahead_do_not_enable_reserve_or_validate_interval():
    problem = _problem(information_mode="historical_perfect_information")
    invalid_config = _config(execution_minutes=30)
    assert committed_pv_execution_slots(
        problem, invalid_config, (5, 6), is_remaining_day_reoptimization=False
    ) == ()
    model, maps, grb = _flow_model(problem, (5, 6))
    audit = add_pv_execution_reserve_constraints(
        model, problem, invalid_config, (5, 6),
        is_remaining_day_reoptimization=True,
        grid_to_bus_var=maps["grid_to_bus"], pv_to_bus_var=maps["pv_to_bus"],
        grid_to_bess_var=maps["grid_to_bess"], bess_to_bus_var=maps["bess_to_bus"],
    )
    assert audit["enabled"] is False
    assert audit["bess_floor_constraint_count"] == 0
    assert _solve(model, grb) == grb.OPTIMAL


def test_active_reserve_rejects_unaligned_execution_interval():
    problem = _problem()
    with pytest.raises(ValueError, match="aligned positive execution interval"):
        committed_pv_execution_slots(
            problem, _config(execution_minutes=30), (5, 6),
            is_remaining_day_reoptimization=True,
        )


def test_hard_import_uses_worst_case_zero_pv_but_soft_overage_remains_unchanged():
    slots = (5,)
    hard_problem = _problem(bess_enabled=False, import_limit_kw=10.0, hard_import=True)
    hard_model, hard_maps, hard_grb = _flow_model(hard_problem, slots)
    for name, value in (("grid_to_bus", 7.0), ("pv_to_bus", 4.0), ("grid_to_bess", 0.5)):
        _fix(hard_model, hard_maps[name], "DEPOT", {5: value})
    audit = add_pv_execution_reserve_constraints(
        hard_model, hard_problem, _config(execution_minutes=60), slots,
        is_remaining_day_reoptimization=True,
        grid_to_bus_var=hard_maps["grid_to_bus"], pv_to_bus_var=hard_maps["pv_to_bus"],
        grid_to_bess_var=hard_maps["grid_to_bess"], bess_to_bus_var=hard_maps["bess_to_bus"],
    )
    assert audit["hard_import_constraint_count"] == 1
    assert _solve(hard_model, hard_grb) == hard_grb.INFEASIBLE

    soft_problem = _problem(bess_enabled=False, import_limit_kw=10.0, hard_import=False)
    soft_model, soft_maps, soft_grb = _flow_model(soft_problem, slots)
    for name, value in (("grid_to_bus", 7.0), ("pv_to_bus", 4.0), ("grid_to_bess", 0.5)):
        _fix(soft_model, soft_maps[name], "DEPOT", {5: value})
    soft_audit = add_pv_execution_reserve_constraints(
        soft_model, soft_problem, _config(execution_minutes=60), slots,
        is_remaining_day_reoptimization=True,
        grid_to_bus_var=soft_maps["grid_to_bus"], pv_to_bus_var=soft_maps["pv_to_bus"],
        grid_to_bess_var=soft_maps["grid_to_bess"], bess_to_bus_var=soft_maps["bess_to_bus"],
    )
    assert soft_audit["hard_import_constraint_count"] == 0
    assert _solve(soft_model, soft_grb) == soft_grb.OPTIMAL


def test_depots_are_independent_and_period_floor_is_not_used_in_committed_prefix():
    problem = _problem(
        depot_ids=("DEPOT", "DEPOT2"),
        physical_floors={"DEPOT": 20.0, "DEPOT2": 5.0},
        period_floors={"DEPOT": 80.0, "DEPOT2": 90.0},
        initial_soc={"DEPOT": 20.0, "DEPOT2": 5.0},
    )
    slots = (5,)
    model, maps, grb = _flow_model(problem, slots)
    audit = add_pv_execution_reserve_constraints(
        model, problem, _config(execution_minutes=60), slots,
        is_remaining_day_reoptimization=True,
        grid_to_bus_var=maps["grid_to_bus"], pv_to_bus_var=maps["pv_to_bus"],
        grid_to_bess_var=maps["grid_to_bess"], bess_to_bus_var=maps["bess_to_bus"],
    )
    assert audit["physical_floor_kwh_by_depot"] == {"DEPOT": 20.0, "DEPOT2": 5.0}
    assert _solve(model, grb) == grb.OPTIMAL

    isolated_model, isolated_maps, isolated_grb = _flow_model(problem, slots)
    _fix(isolated_model, isolated_maps["grid_to_bess"], "DEPOT", {5: 2.0})
    _fix(isolated_model, isolated_maps["grid_to_bess"], "DEPOT2", {5: 0.0})
    _fix(isolated_model, isolated_maps["bess_to_bus"], "DEPOT2", {5: 1.0})
    add_pv_execution_reserve_constraints(
        isolated_model, problem, _config(execution_minutes=60), slots,
        is_remaining_day_reoptimization=True,
        grid_to_bus_var=isolated_maps["grid_to_bus"], pv_to_bus_var=isolated_maps["pv_to_bus"],
        grid_to_bess_var=isolated_maps["grid_to_bess"], bess_to_bus_var=isolated_maps["bess_to_bus"],
    )
    # Depot 1's charge must not subsidize depot 2's discharge.
    assert _solve(isolated_model, isolated_grb) == isolated_grb.INFEASIBLE
