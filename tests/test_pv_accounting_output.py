from __future__ import annotations

from types import SimpleNamespace

import pytest

from bff.routers.optimization import _canonical_charging_output_payload
from bff.services.optimization_run.cost_breakdown import cost_breakdown
from src.optimization.common.energy_flow_accounting import (
    compute_pv_curtail_kwh,
    compute_pv_utilization_rate,
    normalize_pv_energy_breakdown,
)
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationScenario,
    ProblemDepot,
)


def test_compute_pv_curtail_treats_pv_to_bess_as_pv_used() -> None:
    assert compute_pv_curtail_kwh(614.709375, 53.8356, 560.873775) == pytest.approx(0.0)
    assert compute_pv_curtail_kwh(614.709375, 127.95, 0.0) == pytest.approx(486.759375)
    assert compute_pv_curtail_kwh(100.0, 20.0, 80.0) == pytest.approx(0.0)
    assert compute_pv_curtail_kwh(100.0, 20.0, 50.0) == pytest.approx(30.0)


def test_normalize_pv_breakdown_ignores_stale_raw_curtail_when_balance_inputs_exist() -> None:
    normalized = normalize_pv_energy_breakdown(
        {
            "pv_generated_kwh": 614.709375,
            "pv_to_bus_kwh": 53.8356,
            "pv_to_bess_kwh": 560.873775,
            "pv_curtailed_kwh": 560.873775,
        }
    )

    assert normalized["pv_curtailed_kwh"] == pytest.approx(0.0)
    assert normalized["pv_curtail_kwh"] == pytest.approx(0.0)
    assert normalized["pv_curtail_reported_raw_kwh"] == pytest.approx(560.873775)
    assert normalized["pv_used_total_kwh"] == pytest.approx(614.709375)
    assert compute_pv_utilization_rate(614.709375, 53.8356, 560.873775) == pytest.approx(1.0)


def test_normalize_pv_breakdown_uses_legacy_pv_used_direct_as_bus_use() -> None:
    normalized = normalize_pv_energy_breakdown(
        {
            "pv_generated_kwh": 100.0,
            "pv_used_direct_kwh": 25.0,
        }
    )

    assert normalized["pv_to_bus_kwh"] == pytest.approx(25.0)
    assert normalized["pv_curtailed_kwh"] == pytest.approx(75.0)


def test_cost_evaluator_does_not_count_pv_to_bess_as_curtail() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s-pv-eval", timestep_min=60),
        dispatch_context=None,
        trips=(),
        vehicles=(),
        depots=(ProblemDepot(depot_id="dep-1", name="Depot", import_limit_kw=9999.0),),
        price_slots=(EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=10.0),),
        depot_energy_assets={
            "dep-1": DepotEnergyAsset(
                depot_id="dep-1",
                pv_enabled=True,
                pv_generation_kwh_by_slot=(100.0,),
                capacity_factor_by_slot=(1.0,),
                bess_enabled=True,
                bess_energy_kwh=100.0,
                bess_initial_soc_kwh=50.0,
                bess_soc_max_kwh=100.0,
            )
        },
    )
    plan = AssignmentPlan(
        pv_to_bus_kwh_by_depot_slot={"dep-1": {0: 20.0}},
        pv_to_bess_kwh_by_depot_slot={"dep-1": {0: 80.0}},
        pv_curtail_kwh_by_depot_slot={"dep-1": {0: 80.0}},
    )

    breakdown = CostEvaluator().evaluate(problem, plan).to_dict()

    assert breakdown["pv_generated_kwh"] == 100.0
    assert breakdown["pv_to_bus_kwh"] == 20.0
    assert breakdown["pv_to_bess_kwh"] == 80.0
    assert breakdown["pv_used_total_kwh"] == 100.0
    assert breakdown["pv_curtailed_kwh"] == 0.0
    assert breakdown["pv_curtail_kwh"] == 0.0


def test_cost_breakdown_detail_recomputes_stale_pv_curtail_from_balance() -> None:
    rows = cost_breakdown(
        {
            "objective_value": 0.0,
            "obj_breakdown": {
                "pv_generated_kwh": 614.709375,
                "pv_to_bus_kwh": 53.8356,
                "pv_to_bess_kwh": 560.873775,
                "pv_curtailed_kwh": 560.873775,
            },
        },
        None,
    )

    assert rows["pv_curtail_kwh"] == pytest.approx(0.0)
    assert rows["pv_to_bess_kwh"] == pytest.approx(560.873775)


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
