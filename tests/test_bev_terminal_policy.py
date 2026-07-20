from __future__ import annotations

import pytest

from src.optimization.common.bev_terminal_policy import (
    BevTerminalSocPolicy,
    normalize_bev_terminal_soc_policy,
    resolve_bev_terminal_soc_target_kwh,
)
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemVehicle,
)
from src.optimization.common.soc_helpers import (
    effective_final_soc_target_kwh,
    final_soc_target_enabled,
)


def _problem(policy: str, *, configured_target: float | None = None) -> CanonicalOptimizationProblem:
    metadata = {"bev_terminal_soc_policy": policy}
    if configured_target is not None:
        metadata["final_soc_target_percent"] = configured_target
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="terminal", timestep_min=15),
        dispatch_context=object(),
        trips=(),
        vehicles=(),
        metadata=metadata,
    )


def _vehicle() -> ProblemVehicle:
    return ProblemVehicle(
        vehicle_id="bev-1",
        vehicle_type="BEV",
        home_depot_id="depot",
        initial_soc=0.8,
        reserve_soc=0.1,
        battery_capacity_kwh=300.0,
    )


def test_legacy_explicit_target_defaults_to_fixed_target() -> None:
    assert normalize_bev_terminal_soc_policy(
        None,
        has_explicit_target=True,
    ) is BevTerminalSocPolicy.FIXED_TARGET


def test_return_to_initial_uses_each_vehicle_initial_soc() -> None:
    problem = _problem("return_to_initial")

    assert final_soc_target_enabled(problem) is True
    assert effective_final_soc_target_kwh(
        problem,
        _vehicle(),
        cap_kwh=300.0,
    ) == pytest.approx(240.0)


def test_minimum_only_has_no_additional_target() -> None:
    problem = _problem("minimum_only")

    assert final_soc_target_enabled(problem) is False
    assert effective_final_soc_target_kwh(
        problem,
        _vehicle(),
        cap_kwh=300.0,
    ) is None


def test_fixed_target_requires_configured_target() -> None:
    with pytest.raises(ValueError, match="requires final_soc_target_percent"):
        resolve_bev_terminal_soc_target_kwh(
            policy="fixed_target",
            initial_soc_kwh=240.0,
            configured_target_kwh=None,
            terminal_soc_floor_kwh=30.0,
            maximum_soc_kwh=300.0,
        )
