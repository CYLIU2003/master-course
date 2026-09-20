"""A valid, inexpensive lower bound on strictly covered vehicle-days."""
from collections import defaultdict
from typing import Iterable, Mapping, Sequence

from .problem import ProblemTrip
from .strict_precheck import _interval_only_lower_bound, _hopcroft_karp_size


def vehicle_day_overlap_lower_bounds(
    trips: Sequence[ProblemTrip], day_by_trip: Mapping[str, int],
) -> dict[int, int]:
    """Sum peaks only over trips charged to the same departure-day bucket.

    One vehicle cannot serve overlapping trips. Ignoring deadhead, turnaround,
    compatibility and energy relaxes constraints, so each day's overlap peak
    is a lower bound, including overnight trips assigned to their start day.
    This does not multiply a whole-week fleet bound by the number of days.
    """
    grouped: dict[int, list[ProblemTrip]] = defaultdict(list)
    for trip in trips:
        if trip.arrival_min <= trip.departure_min:
            raise ValueError("Vehicle-day bound requires positive absolute trip intervals")
        grouped[day_by_trip[trip.trip_id]].append(trip)
    return {day: _interval_only_lower_bound(rows) for day, rows in sorted(grouped.items())}


def vehicle_day_path_cover_lower_bounds(
    trips: Sequence[ProblemTrip], day_by_trip: Mapping[str, int],
    successor_rows: Iterable[tuple[str, Sequence[str]]], *, full_network: bool,
) -> dict[int, int]:
    """Certify daily vehicle-days on the union of all vehicle successor arcs.

    Every original vehicle path restricted to its departure day is a path in
    this DAG. Discarding vehicle identity/SOC/fuel relaxes the problem. Minimum
    path cover equals vertex count minus maximum bipartite matching. Use the
    complete domain (including factored arcs), never a pruned successor graph.
    """
    if not full_network:
        raise ValueError("Daily path-cover bound requires the complete successor network")
    trip_by_id = {trip.trip_id: trip for trip in trips}
    if len(trip_by_id) != len(trips):
        raise ValueError("Daily path-cover bound requires unique trips")
    ordered = sorted(trips, key=lambda trip: (trip.departure_min, trip.trip_id))
    days = [day_by_trip[trip.trip_id] for trip in ordered]
    if days != sorted(days) or any(trip.arrival_min <= trip.departure_min for trip in trips):
        raise ValueError("Daily path-cover bound requires chronological departure-day buckets and positive durations")
    graphs: dict[int, dict[str, set[str]]] = defaultdict(dict)
    for trip in trips:
        graphs[day_by_trip[trip.trip_id]][trip.trip_id] = set()
    # Identical vehicles share row tuples. Cache row certificates once rather
    # than expanding the 78-million labelled-arc domain of a seven-day case.
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for origin, targets in successor_rows:
        key = origin, tuple(targets)
        if key in seen:
            continue
        seen.add(key)
        day = day_by_trip[origin]
        for target in targets:
            if trip_by_id[target].departure_min <= trip_by_id[origin].departure_min:
                raise ValueError("Daily path-cover bound requires an acyclic forward-time domain")
            if day_by_trip[target] == day:
                graphs[day][origin].add(target)
    return {day: len(graph) - _hopcroft_karp_size(
                {origin: tuple(sorted(targets)) for origin, targets in graph.items()})
            for day, graph in sorted(graphs.items())}
