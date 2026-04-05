from __future__ import annotations

from unittest import mock

from src.optimization.abc.engine import ABCOptimizer
from src.optimization.alns.acceptance import BeeColonyAcceptance, GeneticLikeAcceptance
from src.optimization.alns.engine import ALNSOptimizer
from src.optimization.alns.selection import UniformRandomSelector
from src.optimization.common.problem import AssignmentPlan, OptimizationConfig, OptimizationEngineResult, OptimizationMode
from src.optimization.ga.engine import GAOptimizer


def _delegate_result() -> OptimizationEngineResult:
    return OptimizationEngineResult(
        mode=OptimizationMode.ALNS,
        solver_status="feasible",
        objective_value=1.0,
        plan=AssignmentPlan(),
        feasible=True,
    )


def test_alns_optimizer_honors_requested_acceptance_and_selection_variants() -> None:
    optimizer = ALNSOptimizer()

    ga_config = OptimizationConfig(acceptance="genetic_like", operator_selection="adaptive_roulette")
    abc_config = OptimizationConfig(acceptance="bee_colony_like", operator_selection="uniform_random")

    assert isinstance(optimizer._make_acceptance(ga_config), GeneticLikeAcceptance)
    assert not isinstance(optimizer._make_selector(ga_config), UniformRandomSelector)
    assert isinstance(optimizer._make_acceptance(abc_config), BeeColonyAcceptance)
    assert isinstance(optimizer._make_selector(abc_config), UniformRandomSelector)


def test_ga_optimizer_passes_distinct_search_config_to_delegate() -> None:
    optimizer = GAOptimizer()

    with mock.patch.object(optimizer._delegate, "solve", return_value=_delegate_result()) as solve:
        optimizer.solve(object(), OptimizationConfig())

    delegated_config = solve.call_args.args[1]
    assert delegated_config.mode == OptimizationMode.GA
    assert delegated_config.acceptance == "genetic_like"
    assert delegated_config.operator_selection == "adaptive_roulette"


def test_abc_optimizer_passes_distinct_search_config_to_delegate() -> None:
    optimizer = ABCOptimizer()

    with mock.patch.object(optimizer._delegate, "solve", return_value=_delegate_result()) as solve:
        optimizer.solve(object(), OptimizationConfig())

    delegated_config = solve.call_args.args[1]
    assert delegated_config.mode == OptimizationMode.ABC
    assert delegated_config.acceptance == "bee_colony_like"
    assert delegated_config.operator_selection == "adaptive_roulette"
