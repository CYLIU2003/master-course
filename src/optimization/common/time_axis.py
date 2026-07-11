from __future__ import annotations

from typing import Any, Tuple


ALLOWED_TIMESTEP_MIN = {30, 60}


def normalize_timestep_min(raw: Any, *, default: int = 30) -> int:
    if raw is None or raw == "":
        value = default
    elif isinstance(raw, str):
        text = raw.strip().lower()
        aliases = {
            "30": 30,
            "30m": 30,
            "30min": 30,
            "pt30m": 30,
            "60": 60,
            "60m": 60,
            "60min": 60,
            "1h": 60,
            "pt1h": 60,
        }
        if text in aliases:
            value = aliases[text]
        else:
            try:
                value = int(float(text))
            except ValueError as exc:
                raise ValueError(f"timestep_min must be 30 or 60 minutes, got {raw!r}") from exc
    else:
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"timestep_min must be 30 or 60 minutes, got {raw!r}") from exc

    if value not in ALLOWED_TIMESTEP_MIN:
        raise ValueError(f"timestep_min must be 30 or 60 minutes, got {value!r}")
    return value


def slot_hours(timestep_min: Any, *, default: int = 30) -> float:
    return normalize_timestep_min(timestep_min, default=default) / 60.0


def normalize_horizon_start_min(raw: Any, *, default: int = 0) -> int:
    """Parse a service-day horizon start expressed as minutes or HH:MM."""

    if raw is None or raw == "":
        return int(default)
    if isinstance(raw, str) and ":" in raw:
        try:
            hh_text, mm_text = raw.split(":", 1)
            return max(int(hh_text) * 60 + int(mm_text), 0) % (24 * 60)
        except ValueError:
            return int(default)
    try:
        return max(int(raw), 0) % (24 * 60)
    except (TypeError, ValueError):
        return int(default)


def service_minute(minute: Any, *, horizon_start_min: Any = 0) -> int:
    """Map wall-clock minutes to monotonically increasing service-day time."""

    value = int(minute or 0)
    if value < 0:
        value %= 24 * 60
    horizon_start = normalize_horizon_start_min(horizon_start_min)
    if horizon_start > 0 and value < horizon_start:
        value += 24 * 60
    return value


def chronological_trip_key(
    trip: Any,
    *,
    horizon_start_min: Any = 0,
) -> Tuple[int, int, str]:
    """Return a stable chronological key without changing timetable values.

    Dispatch and reporting layers receive both ``ProblemTrip`` and dispatch
    ``Trip`` instances.  The shared key keeps their ordering identical while
    preserving the original trip objects.  An arrival before departure is
    treated as a crossing-midnight trip for ordering only; it is not silently
    rewritten in the timetable contract.
    """

    departure_min = service_minute(
        getattr(trip, "departure_min", 0), horizon_start_min=horizon_start_min
    )
    arrival_min = service_minute(
        getattr(trip, "arrival_min", departure_min),
        horizon_start_min=horizon_start_min,
    )
    if arrival_min < departure_min:
        arrival_min += 24 * 60
    return departure_min, arrival_min, str(getattr(trip, "trip_id", "") or "")


def chronological_duty_key(
    duty: Any,
    *,
    horizon_start_min: Any = 0,
) -> Tuple[int, int, str]:
    """Return the stable chronological key for a vehicle duty/fragment."""

    legs = tuple(getattr(duty, "legs", ()) or ())
    if not legs:
        return 10**9, 10**9, str(getattr(duty, "duty_id", "") or "")
    first_trip = getattr(legs[0], "trip", legs[0])
    last_trip = getattr(legs[-1], "trip", legs[-1])
    departure_min, _arrival_min, _trip_id = chronological_trip_key(
        first_trip, horizon_start_min=horizon_start_min
    )
    _last_departure, arrival_min, _last_trip_id = chronological_trip_key(
        last_trip, horizon_start_min=horizon_start_min
    )
    return departure_min, arrival_min, str(getattr(duty, "duty_id", "") or "")
