"""Exact endpoint representation of slot-wise charging opportunity sums."""
from collections import Counter, defaultdict
from typing import Any, Iterable, Sequence


class ChargingWindowSupportEvents:
    """Preserve sum-of-opportunities, including holes and multiplicities.

    For slot positions t, let d[t] be the change in the original coefficient
    vector. The recurrence s[t] = s[t-1] + d[t] x, s[-1] = 0 therefore equals
    the original sum for every fractional or integral x. No upper bound is
    added to s: the existing charge-availability variable still supplies its
    own [0, 1] bound. Original opportunities have nonnegative variables.
    """

    def __init__(self, slots: Sequence[int]):
        self.slots = tuple(slots)
        if self.slots != tuple(sorted(set(self.slots))):
            raise ValueError("Charging support requires sorted unique slots")
        self.positions = {slot: position for position, slot in enumerate(self.slots)}
        self.events: dict[int, list[Any]] = defaultdict(list)
        self.dense_term_occurrences = 0

    def add_slots(self, slots: Iterable[int], variable: Any) -> None:
        """Append exactly the original slot occurrences, without deduplication."""
        counts = Counter(self.positions[slot] for slot in slots)
        changes: dict[int, int] = defaultdict(int)
        for position, count in counts.items():
            changes[position] += count
            changes[position + 1] -= count
        for position, coefficient in changes.items():
            if coefficient and position < len(self.slots):
                self.events[position].append(coefficient * variable)
        self.dense_term_occurrences += sum(counts.values())

    def build(self, model: Any, gp: Any, grb: Any, *, vehicle_id: str) -> dict[int, Any]:
        if not self.dense_term_occurrences:
            return {}
        support = {}
        previous = 0.0
        for position, slot in enumerate(self.slots):
            current = model.addVar(lb=0.0, vtype=grb.CONTINUOUS,
                                   name=f"stage1_window_sum__{vehicle_id}__{slot}")
            model.addConstr(current == previous + gp.quicksum(self.events.get(position, ())),
                            name=f"stage1_window_balance__{vehicle_id}__{slot}")
            support[slot] = current
            previous = current
        return support

    @property
    def endpoint_term_count(self) -> int:
        return sum(len(terms) for terms in self.events.values())
