from __future__ import annotations

from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationObjectiveWeights,
    OptimizationScenario,
    ProblemDepot,
    ProblemVehicle,
)


def _problem_with_assets(*, allow_grid_to_bess: bool, pv_enabled: bool, bess_enabled: bool) -> CanonicalOptimizationProblem:
    assets = {
        "dep-1": DepotEnergyAsset(
            depot_id="dep-1",
            pv_enabled=pv_enabled,
            pv_generation_kwh_by_slot=(6.0, 0.0),
            pv_capacity_kw=20.0 if pv_enabled else 0.0,
            bess_enabled=bess_enabled,
            bess_energy_kwh=20.0 if bess_enabled else 0.0,
            bess_power_kw=10.0 if bess_enabled else 0.0,
            bess_initial_soc_kwh=10.0 if bess_enabled else 0.0,
            bess_soc_min_kwh=0.0,
            bess_soc_max_kwh=20.0 if bess_enabled else 0.0,
            allow_grid_to_bess=allow_grid_to_bess,
            provisional_energy_cost_yen_per_kwh=15.0,
        )
    }
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="case",
            horizon_start="08:00",
            timestep_min=60,
            objective_mode="total_cost",
            demand_charge_on_peak_yen_per_kw=100.0,
            demand_charge_off_peak_yen_per_kw=0.0,
        ),
        dispatch_context=None,
        trips=(),
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                battery_capacity_kwh=300.0,
            ),
        ),
        depots=(
            ProblemDepot(
                depot_id="dep-1",
                name="Depot",
                import_limit_kw=9999.0,
            ),
        ),
        price_slots=(
            EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=10.0, demand_charge_weight=0.0),
            EnergyPriceSlot(slot_index=1, grid_buy_yen_per_kwh=40.0, demand_charge_weight=1.0),
        ),
        objective_weights=OptimizationObjectiveWeights(),
        depot_energy_assets=assets,
    )


def _plan_case0() -> AssignmentPlan:
    # PVなし/BESSなし: 高単価時間に全量 Grid->Bus
    return AssignmentPlan(
        grid_to_bus_kwh_by_depot_slot={"dep-1": {1: 10.0}},
    )


def _plan_case1() -> AssignmentPlan:
    # PVあり/BESSなし: 低単価時間にPV分が使え、ピーク時Gridが減る想定
    return AssignmentPlan(
        grid_to_bus_kwh_by_depot_slot={"dep-1": {1: 8.0}},
    )


def _plan_case2() -> AssignmentPlan:
    # PV+BESS, Grid->BESSなし: PVを貯めてピーク時にBESS放電
    return AssignmentPlan(
        grid_to_bus_kwh_by_depot_slot={"dep-1": {1: 5.0}},
        bess_to_bus_kwh_by_depot_slot={"dep-1": {1: 5.0}},
        pv_to_bess_kwh_by_depot_slot={"dep-1": {0: 5.0}},
        grid_to_bess_kwh_by_depot_slot={"dep-1": {0: 0.0}},
    )


def _plan_case3() -> AssignmentPlan:
    # PV+BESS, Grid->BESSあり: 夜間安価時間に蓄電しピーク時Gridをさらに削減
    return AssignmentPlan(
        grid_to_bus_kwh_by_depot_slot={"dep-1": {1: 3.0}},
        bess_to_bus_kwh_by_depot_slot={"dep-1": {1: 7.0}},
        pv_to_bess_kwh_by_depot_slot={"dep-1": {0: 4.0}},
        grid_to_bess_kwh_by_depot_slot={"dep-1": {0: 3.0}},
    )


def test_case_comparison_pv_bess_electricity_and_grid_usage_trends() -> None:
    evaluator = CostEvaluator()

    case0 = evaluator.evaluate(_problem_with_assets(allow_grid_to_bess=False, pv_enabled=False, bess_enabled=False), _plan_case0())
    case1 = evaluator.evaluate(_problem_with_assets(allow_grid_to_bess=False, pv_enabled=True, bess_enabled=False), _plan_case1())
    case2 = evaluator.evaluate(_problem_with_assets(allow_grid_to_bess=False, pv_enabled=True, bess_enabled=True), _plan_case2())
    case3 = evaluator.evaluate(_problem_with_assets(allow_grid_to_bess=True, pv_enabled=True, bess_enabled=True), _plan_case3())

    assert case1.grid_purchase_cost <= case0.grid_purchase_cost
    assert case2.peak_grid_kw <= case1.peak_grid_kw
    assert case3.grid_to_bess_kwh >= case2.grid_to_bess_kwh
    assert case3.grid_to_bus_kwh <= case2.grid_to_bus_kwh
