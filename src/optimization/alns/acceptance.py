from __future__ import annotations

import math
import random

from src.optimization.common.problem import SolutionState


class AcceptanceCriterion:
    def accept(
        self,
        candidate: SolutionState,
        incumbent: SolutionState,
        best: SolutionState,
        rng: random.Random,
    ) -> bool:
        raise NotImplementedError


class HillClimbingAcceptance(AcceptanceCriterion):
    def accept(
        self,
        candidate: SolutionState,
        incumbent: SolutionState,
        best: SolutionState,
        rng: random.Random,
    ) -> bool:
        return candidate.objective() <= incumbent.objective()


class SimulatedAnnealingAcceptance(AcceptanceCriterion):
    def __init__(self, initial_temperature: float = 25.0, cooling_rate: float = 0.995):
        self._temperature = initial_temperature
        self._cooling_rate = cooling_rate

    def accept(
        self,
        candidate: SolutionState,
        incumbent: SolutionState,
        best: SolutionState,
        rng: random.Random,
    ) -> bool:
        if candidate.objective() <= incumbent.objective():
            self._temperature *= self._cooling_rate
            return True
        delta = candidate.objective() - incumbent.objective()
        threshold = math.exp(-delta / max(self._temperature, 1e-9))
        self._temperature *= self._cooling_rate
        return rng.random() < threshold


class GeneticLikeAcceptance(AcceptanceCriterion):
    def __init__(self, mutation_survival_prob: float = 0.03):
        self._mutation_survival_prob = min(max(float(mutation_survival_prob or 0.0), 0.0), 1.0)

    def accept(
        self,
        candidate: SolutionState,
        incumbent: SolutionState,
        best: SolutionState,
        rng: random.Random,
    ) -> bool:
        if candidate.objective() <= incumbent.objective():
            return True
        return rng.random() < self._mutation_survival_prob


class BeeColonyAcceptance(AcceptanceCriterion):
    def __init__(self, scout_prob: float = 0.08, elite_tolerance_ratio: float = 0.01):
        self._scout_prob = min(max(float(scout_prob or 0.0), 0.0), 1.0)
        self._elite_tolerance_ratio = max(float(elite_tolerance_ratio or 0.0), 0.0)

    def accept(
        self,
        candidate: SolutionState,
        incumbent: SolutionState,
        best: SolutionState,
        rng: random.Random,
    ) -> bool:
        if candidate.objective() <= incumbent.objective():
            return True
        best_objective = max(best.objective(), 1.0e-9)
        relative_gap = (candidate.objective() - best.objective()) / best_objective
        if relative_gap <= self._elite_tolerance_ratio:
            return True
        return rng.random() < self._scout_prob
