from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass(frozen=True)
class InfrastructureNeighborhood:
    depot_ids: List[str] = field(default_factory=list)
    charger_ids: List[str] = field(default_factory=list)
    trip_ids: List[str] = field(default_factory=list)
    vehicle_ids: List[str] = field(default_factory=list)
    slot_indices: List[int] = field(default_factory=list)
