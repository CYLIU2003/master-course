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
