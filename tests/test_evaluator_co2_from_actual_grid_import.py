from __future__ import annotations

from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationScenario,
    ProblemDepot,
)


def test_evaluator_co2_uses_actual_grid_import_flows_when_available() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="s",
            horizon_start="08:00",
            timestep_min=60,
        ),
        dispatch_context=None,
        trips=(),
        vehicles=(),
        depots=(
            ProblemDepot(depot_id="dep-1", name="Depot", import_limit_kw=9999.0),
        ),
        price_slots=(
            EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=10.0, co2_factor=0.2),
            EnergyPriceSlot(slot_index=1, grid_buy_yen_per_kwh=20.0, co2_factor=0.5),
        ),
        depot_energy_assets={
            "dep-1": DepotEnergyAsset(depot_id="dep-1", allow_grid_to_bess=True),
        },
    )

    plan = AssignmentPlan(
        grid_to_bus_kwh_by_depot_slot={"dep-1": {0: 3.0, 1: 1.0}},
        grid_to_bess_kwh_by_depot_slot={"dep-1": {1: 2.0}},
    )

    breakdown = CostEvaluator().evaluate(problem, plan)

    expected = (3.0 * 0.2) + ((1.0 + 2.0) * 0.5)
    assert breakdown.total_co2_kg == expected
