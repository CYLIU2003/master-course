from __future__ import annotations

from dataclasses import replace

import pytest

from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationScenario,
)
from src.optimization.milp.solver_adapter import (
    _FEEDBACK_GLOBAL_DEADLINE_KEY,
    _FEEDBACK_GLOBAL_STARTED_KEY,
    _remaining_stage_budget_sec,
    _resolve_stage2_feedback_global_budget,
    _stage1_solver_budget_with_stage2_reserve,
)


def _problem(*, metadata: dict | None = None) -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="feedback-deadline",
            timestep_min=15,
        ),
        dispatch_context=object(),
        trips=(),
        vehicles=(),
        metadata=metadata or {},
    )


def _config(*, time_limit_sec: int = 30) -> OptimizationConfig:
    return OptimizationConfig(
        time_limit_sec=time_limit_sec,
        stage1_time_limit_sec=20,
        stage2_time_limit_sec=20,
    )


def test_first_attempt_creates_one_global_deadline() -> None:
    started, deadline, limit = _resolve_stage2_feedback_global_budget(
        _problem(),
        _config(time_limit_sec=30),
        now_monotonic=100.0,
    )

    assert started == pytest.approx(100.0)
    assert deadline == pytest.approx(130.0)
    assert limit == pytest.approx(30.0)


def test_retry_reuses_original_deadline_instead_of_resetting_budget() -> None:
    original = _problem(
        metadata={
            _FEEDBACK_GLOBAL_STARTED_KEY: 100.0,
            _FEEDBACK_GLOBAL_DEADLINE_KEY: 130.0,
        }
    )

    started, deadline, limit = _resolve_stage2_feedback_global_budget(
        original,
        _config(time_limit_sec=30),
        now_monotonic=125.0,
    )

    assert started == pytest.approx(100.0)
    assert deadline == pytest.approx(130.0)
    assert limit == pytest.approx(30.0)
    assert _remaining_stage_budget_sec(
        deadline_monotonic=deadline,
        requested_sec=20.0,
        now_monotonic=125.0,
    ) == pytest.approx(5.0)


def test_expired_retry_budget_is_zero() -> None:
    assert _remaining_stage_budget_sec(
        deadline_monotonic=130.0,
        requested_sec=20.0,
        now_monotonic=131.0,
    ) == 0.0


def test_stage1_model_build_time_cannot_consume_stage2_reserve() -> None:
    assert _stage1_solver_budget_with_stage2_reserve(
        remaining_shared_budget_sec=40.0,
        requested_stage1_sec=80.0,
        requested_stage2_sec=20.0,
    ) == pytest.approx(32.0)
    assert _stage1_solver_budget_with_stage2_reserve(
        remaining_shared_budget_sec=15.0,
        requested_stage1_sec=80.0,
        requested_stage2_sec=20.0,
    ) == pytest.approx(12.0)
    assert _stage1_solver_budget_with_stage2_reserve(
        remaining_shared_budget_sec=30.0,
        requested_stage1_sec=30.0,
        requested_stage2_sec=30.0,
    ) == pytest.approx(15.0)
    assert _stage1_solver_budget_with_stage2_reserve(
        remaining_shared_budget_sec=40.0,
        requested_stage1_sec=80.0,
        requested_stage2_sec=0.0,
    ) == pytest.approx(40.0)


def test_invalid_internal_deadline_is_replaced_deterministically() -> None:
    problem = replace(
        _problem(),
        metadata={
            _FEEDBACK_GLOBAL_STARTED_KEY: "invalid",
            _FEEDBACK_GLOBAL_DEADLINE_KEY: 50.0,
        },
    )

    started, deadline, _ = _resolve_stage2_feedback_global_budget(
        problem,
        _config(time_limit_sec=30),
        now_monotonic=200.0,
    )

    assert started == pytest.approx(200.0)
    assert deadline == pytest.approx(230.0)
