"""
src/dispatch/odpt_adapter.py

Supplements an existing DispatchContext with data from a normalized ODPT
dataset (produced by the ODPT Explorer BFF and saved to
data/odpt/tokyu/normalized_dataset.json).

The timetable remains the single source of truth; this adapter merges
additional trips and stop-proximity deadhead rules on top of a CSV-loaded
context without modifying or replacing any existing entries.

Design rules (per AGENTS.md):
- This module only imports from .models — no app/, no src/constraints/.
- Existing trips and deadhead rules always take priority over ODPT data.
- No physical impossibility is introduced: trips with unparseable times are
  silently dropped.
"""

from __future__ import annotations

import json
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

from .models import DeadheadRule, DispatchContext, Trip


# ── Helpers ───────────────────────────────────────────────────────────────────


def _safe_hhmm(value: Any) -> str | None:
    """Return 'HH:MM' if *value* is a valid time string, else None."""
    if not isinstance(value, str):
        return None
    parts = value.strip().split(":")
    if len(parts) < 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    return f"{h:02d}:{m:02d}"


def _calendar_matches(calendar: str | None, calendar_filter: str | None) -> bool:
    """
    Return True when the trip's calendar field matches *calendar_filter*.

    The match is a case-insensitive substring check so both
    ``"Weekday"`` and ``"odpt.Calendar:TokyuBus.Weekday"`` work when the
    filter is ``"Weekday"``.  If *calendar_filter* is None all calendars
    are accepted.
    """
    if not calendar_filter:
        return True
    if not calendar:
        return True  # unknown calendar → include by default
    return calendar_filter.lower() in calendar.lower()


def _build_odpt_deadhead_rules(
    stops_data: dict[str, Any],
) -> dict[tuple[str, str], DeadheadRule]:
    """
    Build 1-minute deadhead rules between ODPT stops that share identical
    coordinates (rounded to 6 decimal places).  This mirrors the alias-rule
    logic already present in context_builder._build_deadhead_rules().
    """
    coord_to_stops: dict[tuple[float, float], list[str]] = defaultdict(list)

    for stop_id, stop in stops_data.items():
        lat = stop.get("lat")
        lon = stop.get("lon")
        if lat is None or lon is None:
            continue
        try:
            key = (round(float(lat), 6), round(float(lon), 6))
        except (TypeError, ValueError):
            continue
        coord_to_stops[key].append(stop_id)

    rules: dict[tuple[str, str], DeadheadRule] = {}
    for stop_ids in coord_to_stops.values():
        if len(stop_ids) < 2:
            continue
        for from_stop in stop_ids:
            for to_stop in stop_ids:
                if from_stop == to_stop:
                    continue
                rules[(from_stop, to_stop)] = DeadheadRule(
                    from_stop=from_stop,
                    to_stop=to_stop,
                    travel_time_min=1,
                )

    return rules


# ── Public API ────────────────────────────────────────────────────────────────


def supplement_context_from_odpt(
    context: DispatchContext,
    dataset_path: str | Path,
    calendar_filter: str | None = None,
    default_vehicle_types: tuple[str, ...] = ("BEV",),
    default_trip_distance_km: float = 10.0,
) -> DispatchContext:
    """
    Load a normalized ODPT dataset and merge additional trips and deadhead
    rules into *context*, returning a **new** DispatchContext.

    The original *context* is never mutated.

    Parameters
    ----------
    context:
        An existing DispatchContext (typically loaded from CSV via
        ``load_dispatch_context_from_csv``).
    dataset_path:
        Path to ``data/odpt/tokyu/normalized_dataset.json``.
    calendar_filter:
        Optional substring to filter trips by their ``calendar`` field
        (e.g. ``"Weekday"``, ``"Saturday"``).  If ``None``, all trips are
        included regardless of calendar.
    default_vehicle_types:
        Vehicle types assigned to ODPT trips.  The ODPT schema carries no
        vehicle-type field, so these are applied uniformly.
    default_trip_distance_km:
        Fallback distance when no distance can be derived from the ODPT data.

    Returns
    -------
    DispatchContext
        A new context with merged trips and deadhead rules.
        Existing trips (matched by ``trip_id``) and deadhead rules (matched
        by ``(from_stop, to_stop)``) are **never overwritten**.
    """
    path = Path(dataset_path)
    if not path.exists():
        warnings.warn(
            f"ODPT dataset not found at '{path}'. "
            "Returning original context unchanged.",
            stacklevel=2,
        )
        return context

    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)

    stops_data: dict[str, Any] = raw.get("stops", {})
    patterns_data: dict[str, Any] = raw.get("routePatterns", {})
    trips_data: dict[str, Any] = raw.get("trips", {})

    # Pattern → route_id lookup (prefer odpt:busroute; fall back to pattern_id)
    pattern_to_route: dict[str, str] = {}
    for pid, pattern in patterns_data.items():
        route = pattern.get("busroute") or pid
        pattern_to_route[pid] = route

    # Existing trip IDs → skip duplicates from ODPT
    existing_ids: set[str] = {t.trip_id for t in context.trips}

    new_trips: list[Trip] = []
    skipped_dup = 0
    skipped_cal = 0
    skipped_bad = 0

    for trip_id, trip in trips_data.items():
        if trip_id in existing_ids:
            skipped_dup += 1
            continue

        calendar = trip.get("calendar")
        if not _calendar_matches(calendar, calendar_filter):
            skipped_cal += 1
            continue

        stop_times: list[dict[str, Any]] = trip.get("stop_times", [])
        if len(stop_times) < 2:
            skipped_bad += 1
            continue  # need at least origin + destination

        origin = stop_times[0].get("stop_id", "")
        destination = stop_times[-1].get("stop_id", "")
        if not origin or not destination:
            skipped_bad += 1
            continue

        # Prefer departure at first stop; fall back to arrival
        dep_raw = stop_times[0].get("departure") or stop_times[0].get("arrival")
        # Prefer arrival at last stop; fall back to departure
        arr_raw = stop_times[-1].get("arrival") or stop_times[-1].get("departure")

        dep = _safe_hhmm(dep_raw)
        arr = _safe_hhmm(arr_raw)
        if dep is None or arr is None:
            skipped_bad += 1
            continue

        pattern_id = trip.get("pattern_id", "")
        route_id = pattern_to_route.get(pattern_id, pattern_id or "odpt_unknown")

        new_trips.append(
            Trip(
                trip_id=trip_id,
                route_id=route_id,
                origin=origin,
                destination=destination,
                departure_time=dep,
                arrival_time=arr,
                distance_km=default_trip_distance_km,
                allowed_vehicle_types=default_vehicle_types,
            )
        )

    # Build supplemental deadhead rules from ODPT stop proximity
    odpt_deadhead = _build_odpt_deadhead_rules(stops_data)

    # Merge: existing rules always win (do not overwrite)
    merged_deadhead: dict[tuple[str, str], DeadheadRule] = {
        **odpt_deadhead,
        **context.deadhead_rules,
    }

    if skipped_dup:
        warnings.warn(
            f"supplement_context_from_odpt: skipped {skipped_dup} ODPT trip(s) "
            "already present in the CSV context.",
            stacklevel=2,
        )
    if skipped_bad:
        warnings.warn(
            f"supplement_context_from_odpt: dropped {skipped_bad} ODPT trip(s) "
            "due to missing or unparseable stop_times / time fields.",
            stacklevel=2,
        )

    return DispatchContext(
        service_date=context.service_date,
        trips=list(context.trips) + new_trips,
        turnaround_rules=dict(context.turnaround_rules),
        deadhead_rules=merged_deadhead,
        vehicle_profiles=dict(context.vehicle_profiles),
        default_turnaround_min=context.default_turnaround_min,
    )
