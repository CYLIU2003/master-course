from __future__ import annotations

import math

import pytest

from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    EnergyPriceSlot,
    OptimizationScenario,
    ProblemDepot,
)
from bff.mappers.scenario_to_problemdata import _build_sites
from src.scenario_overlay import ChargingConfig


TIMESTEP_MINUTES = 15


def _problem(*, depots: tuple[ProblemDepot, ...], metadata: dict | None = None) -> CanonicalOptimizationProblem:
    problem_metadata = (
        {"enable_contract_overage_penalty": True}
        if metadata is None
        else dict(metadata)
    )
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="contract-overage", timestep_min=TIMESTEP_MINUTES),
        dispatch_context=None,
        trips=(),
        vehicles=(),
        depots=depots,
        price_slots=(EnergyPriceSlot(slot_index=0, grid_buy_yen_per_kwh=30.0),),
        metadata=problem_metadata,
    )


def _depot(depot_id: str = "depot-a", import_limit_kw: float = 200.0) -> ProblemDepot:
    return ProblemDepot(depot_id=depot_id, name=depot_id, import_limit_kw=import_limit_kw)


def _plan(
    *,
    grid_to_bus: dict[str, dict[int, float]] | None = None,
    grid_to_bess: dict[str, dict[int, float]] | None = None,
    reported_overage: dict[str, dict[int, float]] | None = None,
) -> AssignmentPlan:
    return AssignmentPlan(
        grid_to_bus_kwh_by_depot_slot=grid_to_bus or {},
        grid_to_bess_kwh_by_depot_slot=grid_to_bess or {},
        contract_over_limit_kwh_by_depot_slot=reported_overage or {},
    )


def _report(problem: CanonicalOptimizationProblem, plan: AssignmentPlan):
    return FeasibilityChecker().evaluate(problem, plan)


def test_failed_autumn_slot_669_passes_explicit_soft_policy_with_exact_reported_overage() -> None:
    problem = _problem(depots=(_depot(),))
    physical = 67.32609273735918
    excess = physical - 200.0 * TIMESTEP_MINUTES / 60.0
    plan = _plan(
        grid_to_bus={"depot-a": {669: physical}},
        reported_overage={"depot-a": {669: excess}},
    )

    report = _report(problem, plan)

    assert report.feasible is True
    assert report.metrics["contract_power_violation_count"] == 0
    assert report.metrics["contract_overage_accounting_violation_count"] == 0
    assert report.metrics["contract_power_exceedance_count"] == 1
    assert report.metrics["contract_power_excess_kwh"] == pytest.approx(excess)
    assert report.metrics["contract_overage_reported_kwh"] == pytest.approx(excess)


@pytest.mark.parametrize("metadata", [{"enable_contract_overage_penalty": False}, {}])
def test_missing_or_disabled_soft_policy_keeps_contract_overage_as_hard_failure(metadata: dict) -> None:
    problem = _problem(depots=(_depot(),), metadata=metadata)
    plan = _plan(
        grid_to_bus={"depot-a": {0: 51.0}},
        reported_overage={"depot-a": {0: 1.0}},
    )

    report = _report(problem, plan)

    assert report.feasible is False
    assert report.metrics["contract_power_violation_count"] == 1
    assert report.metrics["contract_power_exceedance_count"] == 1


def test_soft_overage_sums_grid_to_bus_and_grid_to_bess_per_depot() -> None:
    problem = _problem(
        depots=(_depot("depot-a", 200.0), _depot("depot-b", 100.0)),
    )
    plan = _plan(
        grid_to_bus={"depot-a": {0: 45.0}, "depot-b": {0: 20.0}},
        grid_to_bess={"depot-a": {0: 10.0}, "depot-b": {0: 10.0}},
        reported_overage={"depot-a": {0: 5.0}, "depot-b": {0: 5.0}},
    )

    report = _report(problem, plan)

    assert report.feasible is True
    assert report.metrics["contract_power_violation_count"] == 0
    assert report.metrics["contract_overage_accounting_violation_count"] == 0
    assert report.metrics["contract_power_exceedance_count"] == 2
    assert report.metrics["contract_power_excess_kwh"] == pytest.approx(10.0)
    assert report.metrics["contract_overage_reported_kwh"] == pytest.approx(10.0)


def test_physical_import_limit_is_independent_of_paid_contract_overage() -> None:
    problem = _problem(
        depots=(
            ProblemDepot(
                depot_id="depot-a",
                name="Depot A",
                import_limit_kw=200.0,
                physical_import_limit_kw=500.0,
            ),
        ),
    )
    within = _plan(
        grid_to_bus={"depot-a": {0: 100.0}},
        reported_overage={"depot-a": {0: 50.0}},
    )
    above = _plan(
        grid_to_bus={"depot-a": {0: 126.0}},
        reported_overage={"depot-a": {0: 76.0}},
    )

    within_report = _report(problem, within)
    above_report = _report(problem, above)

    assert within_report.feasible is True
    assert within_report.metrics["physical_grid_import_violation_count"] == 0
    assert above_report.feasible is False
    assert above_report.metrics["contract_power_violation_count"] == 0
    assert above_report.metrics["contract_overage_accounting_violation_count"] == 0
    assert above_report.metrics["physical_grid_import_violation_count"] == 1


def test_scenario_schema_and_legacy_site_keep_physical_and_contract_limits_separate() -> None:
    controls = ChargingConfig(
        depot_power_limit_kw=200.0, physical_grid_import_limit_kw=500.0
    )
    scenario = {
        "scenario_overlay": {"charging_constraints": controls.model_dump()},
        "depots": [{"id": "depot-a"}],
    }
    site = _build_sites(scenario, "depot-a")[0]
    assert site.grid_import_limit_kw == 500.0
    assert site.contract_demand_limit_kw == 200.0
    with pytest.raises(ValueError):
        ChargingConfig(physical_grid_import_limit_kw=0.0)


def test_at_or_below_import_limit_has_no_contract_overage() -> None:
    problem = _problem(depots=(_depot(),))
    plan = _plan(grid_to_bus={"depot-a": {0: 50.0 - 5.0e-7}})

    report = _report(problem, plan)

    assert report.feasible is True
    assert report.metrics["contract_power_violation_count"] == 0
    assert report.metrics["contract_power_exceedance_count"] == 0
    assert report.metrics["contract_power_excess_kwh"] == pytest.approx(0.0)
    assert report.metrics["contract_overage_reported_kwh"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    "reported_overage",
    [
        {},
        {"depot-a": {0: 0.5}},
        {"depot-a": {0: 2.0}},
        {"depot-a": {0: -1.0}},
        {"depot-a": {0: math.nan}},
        {"depot-a": {0: math.inf}},
    ],
)
def test_soft_overage_rejects_missing_inconsistent_or_nonfinite_accounting(
    reported_overage: dict[str, dict[int, float]],
) -> None:
    problem = _problem(depots=(_depot(),))
    plan = _plan(grid_to_bus={"depot-a": {0: 51.0}}, reported_overage=reported_overage)

    report = _report(problem, plan)

    assert report.feasible is False
    assert report.metrics["contract_overage_accounting_violation_count"] == 1


def test_soft_overage_accepts_reported_float_roundoff_within_one_micro_kwh() -> None:
    problem = _problem(depots=(_depot(),))
    plan = _plan(
        grid_to_bus={"depot-a": {0: 51.0}},
        reported_overage={"depot-a": {0: 1.0 + 5.0e-7}},
    )

    report = _report(problem, plan)

    assert report.feasible is True
    assert report.metrics["contract_overage_accounting_violation_count"] == 0
    assert report.metrics["contract_power_excess_kwh"] == pytest.approx(1.0)
    assert report.metrics["contract_overage_reported_kwh"] == pytest.approx(1.0000005)


def test_soft_overage_cost_is_five_hundred_yen_per_reported_kwh() -> None:
    grid_kwh = 67.32609273735918
    overage_kwh = 17.326092737359165
    problem = _problem(
        depots=(_depot(),),
        metadata={
            "enable_contract_overage_penalty": True,
            "contract_overage_penalty_yen_per_kwh": 500.0,
        },
    )
    plan = _plan(
        grid_to_bus={"depot-a": {0: grid_kwh}},
        reported_overage={"depot-a": {0: overage_kwh}},
    )

    breakdown = CostEvaluator().evaluate(problem, plan)

    assert _report(problem, plan).feasible is True
    assert breakdown.contract_overage_cost == pytest.approx(overage_kwh * 500.0)
    assert breakdown.total_cost == pytest.approx(grid_kwh * 30.0 + overage_kwh * 500.0)


@pytest.mark.parametrize("flow_name", ["grid_to_bus", "grid_to_bess", "reported_overage"])
def test_negative_sub_micro_kwh_is_not_accepted_as_accounting_roundoff(flow_name: str) -> None:
    problem = _problem(depots=(_depot(),))
    plan = _plan(**{flow_name: {"depot-a": {0: -5.0e-7}}})

    report = _report(problem, plan)

    assert report.feasible is False
    assert report.metrics["contract_overage_accounting_violation_count"] == 1
