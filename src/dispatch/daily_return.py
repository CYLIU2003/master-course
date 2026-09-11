"""The explicit depot-return rule for connections between operating dates."""
from __future__ import annotations

from typing import Any


def crosses_service_day(previous: Any, following: Any) -> bool:
    """Use dated provenance, including trips after 24:00, when available."""
    previous_date = str(getattr(previous, "service_date", "") or "")
    following_date = str(getattr(following, "service_date", "") or "")
    if previous_date and following_date:
        return previous_date != following_date
    return int(previous.departure_min) // 1440 != int(following.departure_min) // 1440


def requires_daily_return(context: Any, previous: Any, following: Any) -> bool:
    return bool(getattr(context, "daily_return_depot_id", "")) and crosses_service_day(previous, following)


def checked_deadhead_minutes(context: Any, origin: str, destination: str) -> int:
    if context.locations_equivalent(origin, destination):
        return 0
    minutes = int(context.get_deadhead_min(origin, destination))
    if minutes <= 0:
        raise ValueError(f"Missing physical deadhead path: {origin}->{destination}")
    return minutes


def connection_deadhead_minutes(context: Any, previous: Any, following: Any) -> int:
    """Travel duration for the selected direct or mandatory via-depot route."""
    origin = str(getattr(previous, "destination_stop_id", "") or previous.destination)
    destination = str(getattr(following, "origin_stop_id", "") or following.origin)
    if requires_daily_return(context, previous, following):
        depot = str(context.daily_return_depot_id)
        return checked_deadhead_minutes(context, origin, depot) + checked_deadhead_minutes(context, depot, destination)
    return checked_deadhead_minutes(context, origin, destination)
