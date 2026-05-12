from __future__ import annotations

from types import SimpleNamespace

from bff.routers.optimization import _canonical_charging_output_payload
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationScenario,
    ProblemDepot,
)


def test_canonical_charging_output_reconciles_pv_curtail_from_generation() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s-pv", timestep_min=60),
        dispatch_context=None,
        trips=(),
        vehicles=(),
        depots=(ProblemDepot(depot_id="dep-1", name="Depot", import_limit_kw=9999.0),),
        price_slots=(EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=10.0),),
        depot_energy_assets={
            "dep-1": DepotEnergyAsset(
                depot_id="dep-1",
                pv_enabled=True,
                pv_generation_kwh_by_slot=(10.0,),
                capacity_factor_by_slot=(1.0,),
                bess_enabled=True,
                bess_energy_kwh=20.0,
                bess_initial_soc_kwh=10.0,
                bess_soc_max_kwh=20.0,
                bess_terminal_soc_min_kwh=8.0,
            )
        },
    )
    plan = AssignmentPlan(
        pv_to_bus_kwh_by_depot_slot={"dep-1": {0: 3.0}},
        pv_to_bess_kwh_by_depot_slot={"dep-1": {0: 4.0}},
        pv_curtail_kwh_by_depot_slot={"dep-1": {0: 99.0}},
    )
    engine_result = SimpleNamespace(
        plan=plan,
        cost_breakdown={},
        solver_metadata={},
        objective_value=0.0,
    )

    payload = _canonical_charging_output_payload(problem, engine_result)

    row = payload["rows"][0]
    totals = payload["summary"]["totals"]
    assert row["pv_curtail_kwh"] == 3.0
    assert row["pv_curtail_raw_kwh"] == 99.0
    assert row["pv_balance_residual_kwh"] == 0.0
    assert totals["pv_generation_kwh"] == 10.0
    assert totals["pv_curtail_kwh"] == 3.0
    assert totals["pv_utilization_rate"] == 0.7

