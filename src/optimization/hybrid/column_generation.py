from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass(frozen=True)
class Column:
    column_id: str
    description: str
    reduced_cost_hint: float = 0.0


@dataclass
class ColumnPool:
    columns: List[Column] = field(default_factory=list)

    def add(self, column: Column) -> None:
        self.columns.append(column)


@dataclass
class PricingProblem:
    def generate_columns(self, master_duals: Dict[str, float]) -> List[Column]:
        if not master_duals:
            return []

        ranked = sorted(master_duals.items(), key=lambda item: item[1])
        candidates: List[Column] = []
        for idx, (dual_key, dual_value) in enumerate(ranked[:5]):
            reduced_cost_hint = float(dual_value)
            if reduced_cost_hint >= 0.0:
                continue
            candidates.append(
                Column(
                    column_id=f"cg-{idx + 1:03d}-{str(dual_key).replace(' ', '_')}",
                    description=f"Dual-guided candidate for {dual_key}",
                    reduced_cost_hint=reduced_cost_hint,
                )
            )
        return candidates
