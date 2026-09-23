"""GA and ABC must pass the remaining exact-repair budget to their child MILP."""

from __future__ import annotations

import pytest

from src.optimization.abc import engine as abc_engine
from src.optimization.common.benchmarking import exact_repair_call_time_limit_sec
from src.optimization.common.problem import AssignmentPlan, OptimizationConfig, OptimizationMode
from src.optimization.common.search_profile import SearchProfile
from src.optimization.ga import engine as ga_engine


def test_exact_repair_budget_is_minimum_of_wall_cumulative_and_per_call() -> None:
    config = OptimizationConfig(time_limit_sec=1500, alns_iterations=500)
    assert exact_repair_call_time_limit_sec(
        config, exact_calls=0, exact_elapsed_sec=0, started_at=0, now=1490,
    ) == 10
    assert exact_repair_call_time_limit_sec(
        config, exact_calls=1, exact_elapsed_sec=118.7, started_at=0, now=100,
    ) == 1
    assert exact_repair_call_time_limit_sec(
        config, exact_calls=3, exact_elapsed_sec=0, started_at=0, now=100,
    ) == 0


@pytest.mark.parametrize(
    ("module", "optimizer_class", "mode"),
    [
        (ga_engine, ga_engine.GAOptimizer, OptimizationMode.GA),
        (abc_engine, abc_engine.ABCOptimizer, OptimizationMode.ABC),
    ],
)
def test_metaheuristic_passes_limit_and_parent_controls_to_partial_milp(
    monkeypatch, module, optimizer_class, mode,
) -> None:
    config = OptimizationConfig(
        mode=mode, time_limit_sec=1500, gurobi_threads=2,
        research_run=True, allow_postsolve_repair=False,
    )
    plan = AssignmentPlan(unserved_trip_ids=("t1",))
    profile = SearchProfile(started_at=0)
    captured = {}
    monkeypatch.setattr(module, "exact_repair_call_time_limit_sec", lambda *_a, **_k: 24)

    def fake_partial(problem, candidate, *, config, time_limit_sec):
        captured.update(config=config, time_limit_sec=time_limit_sec)
        return candidate

    monkeypatch.setattr(module, "partial_milp_repair", fake_partial)
    optimizer = optimizer_class()
    selected = optimizer._apply_selected_repair(
        None, plan, "partial_milp_repair",
        {"baseline_dispatch_repair": lambda _problem, candidate: candidate},
        config, profile, 0,
    )

    assert selected[2] == "partial_milp_repair"
    assert captured == {"config": config, "time_limit_sec": 24}


@pytest.mark.parametrize("module,optimizer_class", [(ga_engine, ga_engine.GAOptimizer), (abc_engine, abc_engine.ABCOptimizer)])
def test_metaheuristic_skips_exact_repair_when_budget_exhausted(monkeypatch, module, optimizer_class) -> None:
    config = OptimizationConfig()
    plan = AssignmentPlan(unserved_trip_ids=("t1",))
    profile = SearchProfile(started_at=0)
    monkeypatch.setattr(module, "exact_repair_call_time_limit_sec", lambda *_a, **_k: 0)
    monkeypatch.setattr(module, "partial_milp_repair", lambda *_a, **_k: pytest.fail("MILP called"))
    optimizer = optimizer_class()

    repaired, _elapsed, selected_name = optimizer._apply_selected_repair(
        None, plan, "partial_milp_repair",
        {"baseline_dispatch_repair": lambda _problem, candidate: candidate},
        config, profile, 0,
    )

    assert selected_name == "baseline_dispatch_repair"
    assert repaired is plan
    assert profile.fallback_count == 1
