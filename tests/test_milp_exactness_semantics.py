from __future__ import annotations

from types import SimpleNamespace

import src.optimization.milp.solver_adapter as solver_adapter_module
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationScenario,
)
from src.optimization.milp.solver_adapter import (
    GurobiMILPAdapter,
    _supports_full_candidate_network_exact_milp,
)


def test_exactness_is_false_when_successor_pruning_removed_arcs() -> None:
    assert not _supports_full_candidate_network_exact_milp(
        {
            "successor_pruning_enabled": True,
            "candidate_arc_count_before_successor_pruning": 678_600,
            "arc_count_after_successor_pruning": 113_712,
            "pruned_arc_count": 564_888,
        }
    )


def test_exactness_is_true_when_no_candidate_arc_was_removed() -> None:
    assert _supports_full_candidate_network_exact_milp(
        {
            "successor_pruning_enabled": True,
            "candidate_arc_count_before_successor_pruning": 12,
            "arc_count_after_successor_pruning": 12,
            "pruned_arc_count": 0,
        }
    )


def test_exactness_is_conservative_for_invalid_pruning_metadata() -> None:
    assert not _supports_full_candidate_network_exact_milp({})
    assert not _supports_full_candidate_network_exact_milp(
        {"pruned_arc_count": "unknown"}
    )


def test_stage2_outcome_inherits_stage1_arc_pruning_semantics(monkeypatch) -> None:
    """The Stage 2 outcome must not lose the constructed-network scope."""

    monkeypatch.setattr(
        solver_adapter_module,
        "ensure_gurobi",
        lambda: (object(), object()),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="stage2-exactness"),
        dispatch_context=SimpleNamespace(),
        trips=(),
        vehicles=(),
    )
    stage1_plan = AssignmentPlan(
        metadata={
            "arc_pruning_summary": {
                "pruned_arc_count": 4,
            }
        }
    )

    outcome, _plan = GurobiMILPAdapter()._solve_thesis_stage2_charging_dispatch(
        problem,
        OptimizationConfig(),
        stage1_plan,
        stage1_status="optimal",
        stage1_gap=0.0,
        stage1_bound=0.0,
        stage1_objective_value=0.0,
        stage1_runtime_sec=0.0,
        slots_per_day=24,
    )

    assert outcome.supports_exact_milp is False
