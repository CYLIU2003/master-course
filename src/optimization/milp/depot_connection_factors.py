"""Exact extended formulation for complete via-depot successor groups.

Each complete bipartite connection group is represented by its origin and
destination incidence variables. Integral balanced incidence flows can always
be paired into the original connections. Vehicle labels are never aggregated.
Only groups whose energy coefficients and slot windows separate are eligible.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from bisect import bisect_left
from typing import Any, Iterable, Iterator, Sequence

from src.dispatch.daily_return import checked_deadhead_minutes, requires_daily_return
from src.optimization.common.soc_helpers import is_electric_vehicle, vehicle_energy_rate_kwh_per_km

ArcKey = tuple[str, str, str]
SlotRange = tuple[int, int]


@dataclass(frozen=True)
class SuccessorRow:
    vehicle_id: str
    origin: str
    targets: tuple[str, ...]


class ArcDomain:
    """Reiterable exact domain without allocating a tuple for every arc."""

    def __init__(self, rows: Sequence[SuccessorRow]):
        self.rows = tuple(rows)
        self.count = sum(len(row.targets) for row in self.rows)

    def __len__(self) -> int:
        return self.count

    def __iter__(self) -> Iterator[ArcKey]:
        for row in self.rows:
            for target in row.targets:
                yield row.vehicle_id, row.origin, target

    def is_acyclic(self, trips: dict[str, Any]) -> bool:
        checked: set[tuple[str, tuple[str, ...]]] = set()
        for row in self.rows:
            key = row.origin, row.targets
            if key in checked:
                continue
            checked.add(key)
            origin = trips.get(row.origin)
            if origin is None or any(
                target not in trips
                or trips[target].departure_min <= origin.departure_min
                for target in row.targets
            ):
                return False
        return True


@dataclass(frozen=True)
class ConnectionFactor:
    vehicle_id: str
    origins: tuple[str, ...]
    targets: tuple[str, ...]
    origin_envelope_counts: tuple[int, ...]
    target_envelope_counts: tuple[int, ...]
    origin_soc_ranges: tuple[SlotRange, ...]
    target_soc_ranges: tuple[SlotRange, ...]
    target_energy_kwh: tuple[float, ...]
    target_fuel_l: tuple[float, ...]
    target_departure_slots: tuple[int, ...]


def _interval_slots(adapter: Any, problem: Any, start: int, end: int) -> SlotRange:
    """Match the adapter's inclusive slot overlap rounding, without expansion."""
    first = adapter._slot_index(problem, start)
    adjusted_end = end + (1440 if end <= start else 0)
    last = adapter._slot_index(problem, max(adjusted_end - 1, start))
    return first, max(first, last) + 1


def connection_windows(
    adapter: Any, problem: Any, vehicle: Any, origin: Any, target: Any
) -> tuple[SlotRange, SlotRange] | None:
    """Return exact envelope and SOC windows as half-open slot intervals."""
    duration = adapter._connection_deadhead_min(problem, origin, target)
    interval = adapter._home_depot_residence_interval(
        problem, vehicle, origin, target, deadhead_min=duration
    )
    if interval is None:
        return None
    envelope = _interval_slots(adapter, problem, *interval)
    left, right = envelope
    if duration > 0:
        travel = adapter._connection_deadhead_interval(
            problem, vehicle, origin, target, deadhead_min=duration
        )
        travel_left, travel_right = _interval_slots(adapter, problem, *travel)
        if travel_left < right and travel_right > left:
            if travel_left <= left:
                left = min(right, travel_right)
            elif travel_right >= right:
                right = max(left, travel_left)
            else:
                # An interior hole cannot use the single-interval certificate.
                return None
    return envelope, (left, right)


def _certify_factor(
    adapter: Any, problem: Any, vehicle: Any,
    origins: tuple[str, ...], targets: tuple[str, ...], trips: dict[str, Any],
) -> ConnectionFactor | None:
    """Certify separate left/right windows and predecessor-independent costs."""
    if len(origins) * len(targets) <= len(origins) + len(targets):
        return None
    reference_target = trips[targets[0]]
    origin_windows = [
        connection_windows(adapter, problem, vehicle, trips[origin], reference_target)
        for origin in origins
    ]
    if any(window is None for window in origin_windows):
        return None
    # Both left boundaries are monotone in the depot-arrival event under the
    # grouping contract. Check that one origin realizes both maxima.
    anchor_idx = max(range(len(origins)), key=lambda idx: origin_windows[idx][0][0])
    anchor_envelope, anchor_soc = origin_windows[anchor_idx]
    if any(
        envelope[0] > anchor_envelope[0]
        or soc[0] > anchor_soc[0]
        or envelope[1] != anchor_envelope[1]
        or soc[1] != anchor_soc[1]
        for envelope, soc in origin_windows
    ):
        return None
    anchor = trips[origins[anchor_idx]]
    target_windows = [
        connection_windows(adapter, problem, vehicle, anchor, trips[target])
        for target in targets
    ]
    if any(window is None for window in target_windows):
        return None
    if any(
        envelope[0] != anchor_envelope[0] or soc[0] != anchor_soc[0]
        or envelope[1] < envelope[0] or soc[1] < soc[0]
        for envelope, soc in target_windows
    ):
        return None
    valid_slots = sorted({slot.slot_index for slot in problem.price_slots})

    def valid_count(interval: SlotRange) -> int:
        return bisect_left(valid_slots, interval[1]) - bisect_left(valid_slots, interval[0])

    return ConnectionFactor(
        vehicle_id=str(vehicle.vehicle_id), origins=origins, targets=targets,
        origin_envelope_counts=tuple(
            valid_count((envelope[0], anchor_envelope[0]))
            for envelope, _soc in origin_windows
        ),
        target_envelope_counts=tuple(valid_count(env) for env, _soc in target_windows),
        origin_soc_ranges=tuple((soc[0], anchor_soc[0]) for _env, soc in origin_windows),
        target_soc_ranges=tuple(soc for _env, soc in target_windows),
        target_energy_kwh=tuple(
            adapter._deadhead_energy_kwh(problem, vehicle, anchor.trip_id, target)
            for target in targets
        ),
        target_fuel_l=tuple(
            adapter._deadhead_fuel_l(problem, vehicle, anchor.trip_id, target)
            for target in targets
        ),
        target_departure_slots=tuple(
            adapter._slot_index(problem, trips[target].departure_min) for target in targets
        ),
    )


def factor_depot_connections(
    adapter: Any, problem: Any, rows: Sequence[SuccessorRow],
) -> tuple[ArcDomain, tuple[ConnectionFactor, ...]]:
    """Factor only certified complete groups; retain every other original arc."""
    trips = problem.trip_by_id()
    vehicles = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
    context = problem.dispatch_context
    policy_depot = str(getattr(context, "daily_return_depot_id", "") or "")
    if not policy_depot:
        return ArcDomain(rows), ()
    explicit: list[SuccessorRow] = []
    groups: dict[tuple[Any, ...], list[str]] = {}
    partitions: dict[tuple[str, tuple[str, ...], str], tuple[tuple[str, ...], ...]] = {}
    for row in rows:
        vehicle = vehicles[row.vehicle_id]
        home = str(getattr(vehicle, "home_depot_id", "") or "")
        if home != policy_depot:
            explicit.append(row)
            continue
        origin = trips[row.origin]
        partition_key = row.origin, row.targets, home
        partition = partitions.get(partition_key)
        if partition is None:
            ordinary, home_targets, away_targets = [], [], []
            for target_id in row.targets:
                target = trips[target_id]
                if not requires_daily_return(context, origin, target):
                    ordinary.append(target_id)
                elif adapter._locations_equivalent(problem, target.origin, home):
                    home_targets.append(target_id)
                else:
                    away_targets.append(target_id)
            partition = tuple(map(tuple, (ordinary, home_targets, away_targets)))
            partitions[partition_key] = partition
        if partition[0]:
            explicit.append(SuccessorRow(row.vehicle_id, row.origin, partition[0]))
        # Canonical travel uses stop IDs when supplied; residence uses the
        # canonical trip endpoints. Preserve both quantities in the group key.
        return_minutes = checked_deadhead_minutes(
            context, str(getattr(origin, "destination_stop_id", "") or origin.destination), home
        )
        residence_return_minutes = checked_deadhead_minutes(context, origin.destination, home)
        rate = vehicle_energy_rate_kwh_per_km(problem, vehicle, origin)
        for target_group in partition[1:]:
            if target_group:
                key = row.vehicle_id, return_minutes, residence_return_minutes, rate, target_group
                groups.setdefault(key, []).append(row.origin)
    factors = []
    certificates: dict[tuple[Any, ...], ConnectionFactor | None] = {}
    for (vehicle_id, _ret, _residence_ret, rate, targets), origins in groups.items():
        vehicle = vehicles[vehicle_id]
        certificate_key = (
            tuple(origins), targets, str(vehicle.home_depot_id), rate,
            max(float(vehicle.fuel_consumption_l_per_km or 0.0), 0.0),
            is_electric_vehicle(problem, vehicle),
        )
        if certificate_key not in certificates:
            certificates[certificate_key] = _certify_factor(
                adapter, problem, vehicle, tuple(origins), targets, trips
            )
        certificate = certificates[certificate_key]
        factor = replace(certificate, vehicle_id=vehicle_id) if certificate is not None else None
        if factor is None:
            explicit.extend(SuccessorRow(vehicle_id, origin, targets) for origin in origins)
        else:
            factors.append(factor)
    return ArcDomain(explicit), tuple(factors)


@dataclass
class FactorVariables:
    factor: ConnectionFactor
    origins: tuple[Any, ...]
    targets: tuple[Any, ...]


class FactoredConnectionVariables(dict):
    """Explicit arc variables plus separately represented complete groups.

    Iteration intentionally visits explicit variables only. Domain membership
    includes implicit arcs for path/MIP-start validation. Solver coefficients
    and solution extraction must explicitly use ``factors`` as well.
    """

    def __init__(self, explicit: dict, factors: Sequence[FactorVariables]):
        super().__init__(explicit)
        self.factors = tuple(factors)
        self.by_vehicle: dict[str, list[FactorVariables]] = {}
        self.by_origin: dict[tuple[str, str], list[FactorVariables]] = {}
        self.target_sets: dict[int, frozenset[str]] = {}
        for variables in self.factors:
            factor = variables.factor
            self.by_vehicle.setdefault(factor.vehicle_id, []).append(variables)
            self.target_sets[id(variables)] = frozenset(factor.targets)
            for origin in factor.origins:
                self.by_origin.setdefault((factor.vehicle_id, origin), []).append(variables)

    def find_factor(self, key: ArcKey) -> FactorVariables | None:
        for variables in self.by_origin.get((key[0], key[1]), ()):
            if key[2] in self.target_sets[id(variables)]:
                return variables
        return None

    def __contains__(self, key: object) -> bool:
        if super().__contains__(key):
            return True
        return isinstance(key, tuple) and len(key) == 3 and self.find_factor(key) is not None

    def expanded_selection(self, binary_value: Any, *, use_pool_solution: bool = False) -> set[ArcKey]:
        selected = set()
        for variables in self.factors:
            factor = variables.factor
            origins = [trip for trip, var in zip(factor.origins, variables.origins)
                       if binary_value(var, use_pool_solution=use_pool_solution)]
            targets = [trip for trip, var in zip(factor.targets, variables.targets)
                       if binary_value(var, use_pool_solution=use_pool_solution)]
            if len(origins) != len(targets):
                raise ValueError("Unbalanced integral depot-connection factor")
            selected.update((factor.vehicle_id, origin, target)
                            for origin, target in zip(origins, targets))
        return selected

    def set_factor_starts(self, selected: Iterable[ArcKey]) -> None:
        source_keys, target_keys = set(), set()
        for key in selected:
            variables = self.find_factor(key)
            if variables is not None:
                source = id(variables), key[1]
                target = id(variables), key[2]
                if source in source_keys or target in target_keys:
                    raise ValueError("MIP start repeats a factor incidence")
                source_keys.add(source)
                target_keys.add(target)
        for variables in self.factors:
            for trip, var in zip(variables.factor.origins, variables.origins):
                var.Start = float((id(variables), trip) in source_keys)
            for trip, var in zip(variables.factor.targets, variables.targets):
                var.Start = float((id(variables), trip) in target_keys)


def create_factor_variables(model: Any, gp: Any, grb: Any,
                            factors: Sequence[ConnectionFactor]) -> tuple[FactorVariables, ...]:
    result = []
    for index, factor in enumerate(factors):
        origins = tuple(model.addVar(vtype=grb.BINARY, name=f"df_o_{index}_{i}")
                        for i in range(len(factor.origins)))
        targets = tuple(model.addVar(vtype=grb.BINARY, name=f"df_t_{index}_{i}")
                        for i in range(len(factor.targets)))
        model.addConstr(gp.quicksum(origins) == gp.quicksum(targets), name=f"df_balance_{index}")
        result.append(FactorVariables(factor, origins, targets))
    return tuple(result)


def add_factor_soc_terms(
    model: Any, gp: Any, grb: Any, variables: FactoredConnectionVariables,
    vehicle_id: str, slots: Sequence[int],
) -> tuple[dict[int, Any], dict[int, list[Any]], list[Any], int]:
    """Add interval support by endpoint events, avoiding dense slot columns."""
    factors = variables.by_vehicle.get(vehicle_id, ())
    if not factors:
        return {}, {}, [], 0
    events: dict[int, list[Any]] = {}
    loads: dict[int, list[Any]] = {}
    terminal = []
    valid_slots = set(slots)
    for entry in factors:
        factor = entry.factor
        for energy, slot, var in zip(factor.target_energy_kwh, factor.target_departure_slots, entry.targets):
            if energy > 0:
                (loads.setdefault(slot, []) if slot in valid_slots else terminal).append(energy * var)
        for intervals, incidence_vars in (
            (factor.origin_soc_ranges, entry.origins),
            (factor.target_soc_ranges, entry.targets),
        ):
            for (left, right), var in zip(intervals, incidence_vars):
                first, after = bisect_left(slots, left), bisect_left(slots, right)
                if first < after:
                    events.setdefault(first, []).append(var)
                    events.setdefault(after, []).append(-var)
    support = {}
    previous = 0.0
    for position, slot in enumerate(slots):
        current = model.addVar(lb=0.0, vtype=grb.CONTINUOUS, name=f"df_support_{vehicle_id}_{slot}")
        model.addConstr(current == previous + gp.quicksum(events.get(position, ())),
                        name=f"df_support_balance_{vehicle_id}_{slot}")
        support[slot] = current
        previous = current
    return support, loads, terminal, len(slots)
