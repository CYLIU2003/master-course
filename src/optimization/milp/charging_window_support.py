"""Exact endpoint representation of slot-wise charging opportunity sums."""
from bisect import bisect_left
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


class VehicleAwayEvents:
    """Fraction of each slot that a vehicle certainly spends away from home.

    An away segment starts at the departure of a trip entered from home (a
    start arc, a daily-return connection, or a connection touching the home
    depot) and ends at the arrival of a trip left for home by the same arc
    kinds. In between, the vehicle drives or waits at a terminal. On one
    time-ordered binary path these segments are disjoint, so the sum below is
    the exact away fraction of each slot; the home-side deadhead legs count as
    home, which only relaxes. Each term adds ``sign * variable * H_m(slot)``,
    where ``H_m`` is the fraction of the slot at or after minute ``m``.
    """

    def __init__(self, slots: Sequence[int], *, horizon_start_min: int, step_min: int,
                 whole_slot: bool = False):
        self.slots = tuple(slots)
        if self.slots != tuple(sorted(set(self.slots))):
            raise ValueError("Away support requires sorted unique slots")
        self.horizon_start_min = int(horizon_start_min)
        self.step_min = max(int(step_min), 1)
        # whole_slot: a slot is away if the vehicle is away for any part of it, which is
        # exactly Stage 2's rule (charging only in slots spent wholly at home,
        # vehicle_timeline.complete_home_slots). A leave step (+1) covers the whole slot
        # holding the leave minute; a return step (-1) takes effect from the first slot
        # that starts at or after the return minute.
        self.whole_slot = bool(whole_slot)
        self.events: dict[int, list[Any]] = defaultdict(list)

    def _position(self, slot: int) -> int:
        return bisect_left(self.slots, slot)

    def add_home_visit(self, return_minute: float, leave_minute: float, variable: Any) -> None:
        """Back home at ``return_minute`` and out again at ``leave_minute`` on one arc.

        In whole-slot mode a visit that contains no complete slot leaves the vehicle away:
        adding the return step at the ceiling slot and the leave step at an earlier floor
        slot would make the away level 2 in between, which forces charge <= P (1 - 2) < 0
        and makes every path through such a short visit infeasible (rc27, 11/07).
        """
        if self.whole_slot:
            back = int(-((-(float(return_minute) - self.horizon_start_min)) // self.step_min))
            out = int((float(leave_minute) - self.horizon_start_min) // self.step_min)
            if out < back:
                return
        self.add_step(return_minute, variable, -1.0)
        self.add_step(leave_minute, variable, 1.0)

    def add_step(self, minute: float, variable: Any, sign: float, *, whole_slot: bool | None = None) -> None:
        offset = float(minute) - self.horizon_start_min
        if self.whole_slot if whole_slot is None else whole_slot:
            if sign > 0:
                slot = int(offset // self.step_min)
            else:
                slot = int(-((-offset) // self.step_min))
            position = self._position(slot)
            if position < len(self.slots):
                self.events[position].append(sign * variable)
            return
        slot = int(offset // self.step_min)
        head = ((slot + 1) * self.step_min - offset) / self.step_min
        for target, coefficient in ((slot, head), (slot + 1, 1.0 - head)):
            position = self._position(target)
            if coefficient > 1e-12 and position < len(self.slots):
                self.events[position].append(sign * coefficient * variable)

    def build(self, model: Any, gp: Any, grb: Any, *, vehicle_id: str) -> dict[int, Any]:
        if not self.events:
            return {}
        away = {}
        previous = 0.0
        for position, slot in enumerate(self.slots):
            current = model.addVar(lb=-grb.INFINITY, vtype=grb.CONTINUOUS,
                                   name=f"stage1_away_fraction__{vehicle_id}__{slot}")
            model.addConstr(current == previous + gp.quicksum(self.events.get(position, ())),
                            name=f"stage1_away_balance__{vehicle_id}__{slot}")
            away[slot] = current
            previous = current
        return away

    @property
    def endpoint_term_count(self) -> int:
        return sum(len(terms) for terms in self.events.values())
