from __future__ import annotations

import pytest

from src.optimization.common.bess_terminal_policy import (
    normalize_bess_terminal_policy,
    resolve_bess_terminal_soc_target_kwh,
)
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    DepotEnergyAsset,
    OptimizationScenario,
)


def test_missing_policy_preserves_positive_legacy_target() -> None:
    assert normalize_bess_terminal_policy("", has_explicit_target=True) == "fixed_target"
    assert (
        resolve_bess_terminal_soc_target_kwh(
            policy="",
            initial_soc_kwh=60.0,
            configured_target_kwh=50.0,
            terminal_soc_floor_kwh=20.0,
            maximum_soc_kwh=90.0,
        )
        == 50.0
    )


def test_minimum_only_disables_target_without_disabling_hard_floor() -> None:
    assert (
        resolve_bess_terminal_soc_target_kwh(
            policy="minimum_only",
            initial_soc_kwh=60.0,
            configured_target_kwh=50.0,
            terminal_soc_floor_kwh=20.0,
            maximum_soc_kwh=90.0,
        )
        is None
    )


def test_return_to_initial_resolves_initial_soc_within_bounds() -> None:
    assert (
        resolve_bess_terminal_soc_target_kwh(
            policy="return_to_initial",
            initial_soc_kwh=60.0,
            configured_target_kwh=0.0,
            terminal_soc_floor_kwh=20.0,
            maximum_soc_kwh=90.0,
        )
        == 60.0
    )


def test_return_to_zero_initial_soc_remains_an_explicit_zero_target() -> None:
    assert (
        resolve_bess_terminal_soc_target_kwh(
            policy="return_to_initial",
            initial_soc_kwh=0.0,
            configured_target_kwh=0.0,
            terminal_soc_floor_kwh=0.0,
            maximum_soc_kwh=90.0,
        )
        == 0.0
    )


def test_unknown_policy_is_rejected() -> None:
    with pytest.raises(ValueError, match="bess_terminal_soc_policy"):
        normalize_bess_terminal_policy("invented")


def test_explicit_fixed_zero_target_is_not_missing_legacy_target() -> None:
    controls = dict(
        initial_soc_kwh=50.0, configured_target_kwh=0.0,
        terminal_soc_floor_kwh=0.0, maximum_soc_kwh=90.0,
    )
    assert resolve_bess_terminal_soc_target_kwh(policy="fixed_target", **controls) == 0.0
    assert resolve_bess_terminal_soc_target_kwh(policy="", **controls) is None


def test_independent_validation_rejects_residual_energy_for_fixed_zero_target() -> None:
    from src.optimization.common.feasibility import FeasibilityChecker
    from src.optimization.common.problem import AssignmentPlan, EnergyPriceSlot

    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="explicit-zero"),
        dispatch_context=None, trips=(), vehicles=(),
        price_slots=(EnergyPriceSlot(slot_index=0),),
        depot_energy_assets={"dep-1": DepotEnergyAsset(
            depot_id="dep-1", bess_enabled=True, bess_energy_kwh=100.0,
            bess_power_kw=50.0, bess_initial_soc_kwh=50.0,
            bess_soc_max_kwh=90.0, bess_terminal_soc_policy="fixed_target",
            bess_terminal_soc_target_kwh=0.0,
        )},
    )
    metrics = FeasibilityChecker()._evaluate_bess_metrics(problem, AssignmentPlan())
    assert metrics["terminal_deviation_kwh"] == 50.0


def test_problem_rejects_fixed_target_outside_hard_soc_range() -> None:
    with pytest.raises(ValueError, match="fixed terminal BESS SOC target"):
        CanonicalOptimizationProblem(
            scenario=OptimizationScenario(scenario_id="invalid-target"),
            dispatch_context=None,
            trips=(),
            vehicles=(),
            depot_energy_assets={
                "dep-1": DepotEnergyAsset(
                    depot_id="dep-1",
                    bess_enabled=True,
                    bess_energy_kwh=100.0,
                    bess_initial_soc_kwh=50.0,
                    bess_soc_min_kwh=20.0,
                    bess_soc_max_kwh=90.0,
                    bess_terminal_soc_min_kwh=20.0,
                    bess_terminal_soc_policy="fixed_target",
                    bess_terminal_soc_target_kwh=95.0,
                )
            },
        )
