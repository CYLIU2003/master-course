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
        return [
            Column(
                column_id="cg-seed-001",
                description="Placeholder column generated from master dual summary",
                reduced_cost_hint=float(next(iter(master_duals.values()))),
            )
        ]
