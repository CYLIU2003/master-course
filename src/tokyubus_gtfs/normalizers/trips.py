"""
src.tokyubus_gtfs.normalizers.trips — BusTimetable → CanonicalTrip normalizer.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

from ..models import CanonicalDirection, CanonicalTrip, CanonicalTripStopTime
from .helpers import (
    data_hash,
    safe_time_hhmmss,
    service_id_from_odpt,
    short_id,
    stable_id,
    time_to_seconds,
)

_log = logging.getLogger(__name__)


def normalize_bus_timetables(
    raw_data: list,
    pattern_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
    stop_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[List[CanonicalTrip], List[CanonicalTripStopTime], Dict[str, int], List[str]]:
    """
    Normalize ``odpt:BusTimetable`` into canonical trips and stop times.

    Returns
    -------
    trips
        List of ``CanonicalTrip`` models.
    stop_times
        List of ``CanonicalTripStopTime`` models.
    trip_counts_by_route
        Mapping ``route_id → trip count`` for updating routes later.
    warnings
        List of warning messages.
    """
    patterns = pattern_lookup or {}
    stops = stop_lookup or {}

    trips: List[CanonicalTrip] = []
    stop_times: List[CanonicalTripStopTime] = []
    warnings: List[str] = []
    trip_counts_by_route: Dict[str, int] = {}

    # Group trips for index assignment
    grouped: Dict[Tuple[str, str, str], List[CanonicalTrip]] = {}

    def _stop_label(stop_id: Optional[str]) -> str:
        if not stop_id:
            return ""
        info = stops.get(stop_id, {})
        return str(info.get("name", "")) or short_id(stop_id, stop_id or "")

    for timetable in raw_data:
        if not isinstance(timetable, dict):
            continue

        pattern_id = str(timetable.get("odpt:busroutePattern") or "")
        calendar_raw = str(timetable.get("odpt:calendar") or "")
        tt_objects = timetable.get("odpt:busTimetableObject") or []

        if not pattern_id or not tt_objects:
            continue

        pattern = patterns.get(pattern_id, {})
        route_id = str(pattern.get("route_id") or stable_id("route", pattern_id))

        service_key = short_id(calendar_raw, "unknown")
        service_id = service_id_from_odpt(service_key)

        # Trip ID
        timetable_id = str(
            timetable.get("owl:sameAs")
            or timetable.get("@id")
            or f"odpt-trip-{hashlib.sha1(data_hash(timetable).encode()).hexdigest()[:12]}"
        )

        # Parse stop times
        trip_st: List[CanonicalTripStopTime] = []
        ordered = sorted(
            [obj for obj in tt_objects if isinstance(obj, dict)],
            key=lambda obj: int(obj.get("odpt:index") or 0),
        )

        for idx, st in enumerate(ordered):
            stop_id = str(st.get("odpt:busstopPole") or "")
            raw_dep = st.get("odpt:departureTime")
            raw_arr = st.get("odpt:arrivalTime")
            dep = safe_time_hhmmss(raw_dep)
            arr = safe_time_hhmmss(raw_arr)
            resolved_dep = dep or arr
            resolved_arr = arr or dep

            if not stop_id or (resolved_dep is None and resolved_arr is None):
                continue

            entry = CanonicalTripStopTime(
                trip_id=timetable_id,
                stop_id=stop_id,
                stop_sequence=idx,
                arrival_time=resolved_arr,
                departure_time=resolved_dep,
                arrival_seconds=time_to_seconds(resolved_arr),
                departure_seconds=time_to_seconds(resolved_dep),
                stop_name=_stop_label(stop_id),
                odpt_raw_arrival=str(raw_arr) if raw_arr else None,
                odpt_raw_departure=str(raw_dep) if raw_dep else None,
            )
            trip_st.append(entry)
            stop_times.append(entry)

        if len(trip_st) < 2:
            continue

        first = trip_st[0]
        last = trip_st[-1]
        dep_time = first.departure_time or first.arrival_time
        arr_time = last.arrival_time or last.departure_time
        if not dep_time or not arr_time:
            continue

        distance_km = float(pattern.get("total_distance_km") or 0.0)
        dep_sec = time_to_seconds(dep_time)
        arr_sec = time_to_seconds(arr_time)
        runtime_min = (
            (arr_sec - dep_sec) / 60.0
            if dep_sec is not None and arr_sec is not None and arr_sec > dep_sec
            else 0.0
        )

        trip = CanonicalTrip(
            trip_id=timetable_id,
            route_id=route_id,
            service_id=service_id,
            direction=CanonicalDirection.outbound,
            origin_stop_id=first.stop_id,
            destination_stop_id=last.stop_id,
            origin_name=first.stop_name,
            destination_name=last.stop_name,
            departure_time=dep_time or "",
            arrival_time=arr_time or "",
            departure_seconds=dep_sec,
            arrival_seconds=arr_sec,
            distance_km=distance_km,
            runtime_min=round(runtime_min, 1),
            odpt_timetable_id=timetable_id,
            odpt_pattern_id=pattern_id,
            odpt_calendar_raw=calendar_raw,
        )

        group_key = (route_id, service_id, "outbound")
        grouped.setdefault(group_key, []).append(trip)
        trip_counts_by_route[route_id] = trip_counts_by_route.get(route_id, 0) + 1

    # Assign trip indexes within each (route, service, direction) group
    for key in sorted(grouped):
        group = sorted(
            grouped[key],
            key=lambda t: (t.departure_time, t.arrival_time, t.trip_id),
        )
        for idx, trip in enumerate(group):
            trip.trip_index = idx
            trips.append(trip)

    _log.info(
        "Normalised %d BusTimetable records → %d trips, %d stop_times",
        len(raw_data),
        len(trips),
        len(stop_times),
    )
    return trips, stop_times, trip_counts_by_route, warnings
