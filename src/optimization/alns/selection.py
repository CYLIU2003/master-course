from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Dict, Iterable, List


@dataclass
class AdaptiveRouletteSelector:
    weights: Dict[str, float] = field(default_factory=dict)
    reaction: float = 0.2

    def choose(self, candidates: Iterable[str], rng: random.Random) -> str:
        items: List[str] = list(candidates)
        if not items:
            raise ValueError("No operator candidates available")
        scores = [max(self.weights.get(item, 1.0), 1e-6) for item in items]
        total = sum(scores)
        pick = rng.random() * total
        running = 0.0
        for item, score in zip(items, scores):
            running += score
            if running >= pick:
                return item
        return items[-1]

    def update(self, operator_name: str, reward: float) -> None:
        current = self.weights.get(operator_name, 1.0)
        self.weights[operator_name] = (1.0 - self.reaction) * current + self.reaction * reward
