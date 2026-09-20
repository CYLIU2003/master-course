"""A valid, inexpensive lower bound on strictly covered vehicle-days."""
from collections import defaultdict
from typing import Mapping, Sequence

from .problem import ProblemTrip
from .strict_precheck import _interval_only_lower_bound


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
