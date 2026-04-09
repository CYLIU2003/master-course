from __future__ import annotations

from src.optimization.alns.acceptance import BeeColonyAcceptance, GeneticLikeAcceptance
from src.optimization.alns.engine import ALNSOptimizer
from src.optimization.alns.selection import UniformRandomSelector
from src.optimization.common.problem import OptimizationConfig


def test_alns_optimizer_honors_requested_acceptance_and_selection_variants() -> None:
    optimizer = ALNSOptimizer()

    ga_config = OptimizationConfig(acceptance="genetic_like", operator_selection="adaptive_roulette")
    abc_config = OptimizationConfig(acceptance="bee_colony_like", operator_selection="uniform_random")

    assert isinstance(optimizer._make_acceptance(ga_config), GeneticLikeAcceptance)
    assert not isinstance(optimizer._make_selector(ga_config), UniformRandomSelector)
    assert isinstance(optimizer._make_acceptance(abc_config), BeeColonyAcceptance)
    assert isinstance(optimizer._make_selector(abc_config), UniformRandomSelector)
