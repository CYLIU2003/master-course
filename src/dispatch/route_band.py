from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Tuple

from src.route_code_utils import extract_route_series_from_candidates


@dataclass(frozen=True)
class FragmentTransitionDiagnostic:
    feasible: bool
    reason_code: str
    direct_ok: bool
    depot_reset_ok: bool
    route_band_blocked: bool = False
    deadhead_missing: bool = False
    location_alias_missing: bool = False


def trip_route_band_key(trip_like: Any, fallback_route_id: str = "") -> str:
    family_code = str(getattr(trip_like, "route_family_code", "") or "").strip()
    route_id = str(
        getattr(trip_like, "route_id", "")
        or fallback_route_id
        or ""
    ).strip()
    series_code, _prefix, _number, _source = extract_route_series_from_candidates(
        family_code,
        route_id,
    )
    if series_code:
        return series_code
    if family_code:
        return family_code
    return route_id


def duty_route_band_ids(duty: Any) -> Tuple[str, ...]:
    bands = {
        trip_route_band_key(getattr(leg, "trip", None))
        for leg in tuple(getattr(duty, "legs", ()) or ())
    }
    bands.discard("")
    return tuple(sorted(bands))


def duties_route_band_ids(duties: Iterable[Any]) -> Tuple[str, ...]:
    bands = {
        band
        for duty in duties
        for band in duty_route_band_ids(duty)
        if str(band or "").strip()
    }
    return tuple(sorted(bands))


def fragment_transition_direct_deadhead_min(
    from_duty: Any,
    to_duty: Any,
    *,
    dispatch_context: Any | None,
) -> Tuple[bool, int]:
    if dispatch_context is None:
        return (True, 0)
    from_legs = tuple(getattr(from_duty, "legs", ()) or ())
    to_legs = tuple(getattr(to_duty, "legs", ()) or ())
    if not from_legs or not to_legs:
        return (True, 0)

    from_trip = getattr(from_legs[-1], "trip", None)
    to_trip = getattr(to_legs[0], "trip", None)
    if from_trip is None or to_trip is None:
        return (True, 0)

    from_location = str(
        getattr(from_trip, "destination_stop_id", "")
        or getattr(from_trip, "destination", "")
        or ""
    ).strip()
    to_location = str(
        getattr(to_trip, "origin_stop_id", "")
        or getattr(to_trip, "origin", "")
        or ""
    ).strip()
    if not from_location or not to_location:
        return (True, 0)

    return _required_deadhead_min(
        from_location,
        to_location,
        dispatch_context=dispatch_context,
    )


def fragment_transition_allows_direct_connection(
    from_duty: Any,
    to_duty: Any,
    *,
    dispatch_context: Any | None,
) -> bool:
    if dispatch_context is None:
        return True
    from_legs = tuple(getattr(from_duty, "legs", ()) or ())
    to_legs = tuple(getattr(to_duty, "legs", ()) or ())
    if not from_legs or not to_legs:
        return True

    from_trip = getattr(from_legs[-1], "trip", None)
    to_trip = getattr(to_legs[0], "trip", None)
    if from_trip is None or to_trip is None:
        return True

    direct_exists, direct_deadhead = fragment_transition_direct_deadhead_min(
        from_duty,
        to_duty,
        dispatch_context=dispatch_context,
    )
    if not direct_exists:
        return False
    get_turnaround_min = getattr(dispatch_context, "get_turnaround_min", None)
    turnaround_min = 0
    from_location = str(
        getattr(from_trip, "destination_stop_id", "")
        or getattr(from_trip, "destination", "")
        or ""
    ).strip()
    if callable(get_turnaround_min):
        try:
            turnaround_min = max(int(get_turnaround_min(from_location) or 0), 0)
        except Exception:
            turnaround_min = 0
    ready_min = int(getattr(from_trip, "arrival_min", 0) or 0) + turnaround_min + direct_deadhead
    next_departure_min = int(getattr(to_trip, "departure_min", 0) or 0)
    return ready_min <= next_departure_min


def fragment_transition_allows_depot_reset(
    from_duty: Any,
    to_duty: Any,
    *,
    home_depot_id: str,
    dispatch_context: Any | None,
    allow_same_day_depot_cycles: bool = True,
) -> bool:
    if not allow_same_day_depot_cycles:
        return False
    if dispatch_context is None:
        return True
    from_legs = tuple(getattr(from_duty, "legs", ()) or ())
    to_legs = tuple(getattr(to_duty, "legs", ()) or ())
    if not from_legs or not to_legs:
        return True
    home_depot = str(home_depot_id or "").strip()
    if not home_depot:
        return True
    get_deadhead_min = getattr(dispatch_context, "get_deadhead_min", None)
    get_turnaround_min = getattr(dispatch_context, "get_turnaround_min", None)
    if not callable(get_deadhead_min):
        return True

    from_trip = getattr(from_legs[-1], "trip", None)
    to_trip = getattr(to_legs[0], "trip", None)
    if from_trip is None or to_trip is None:
        return True

    from_location = str(
        getattr(from_trip, "destination_stop_id", "")
        or getattr(from_trip, "destination", "")
        or ""
    ).strip()
    to_location = str(
        getattr(to_trip, "origin_stop_id", "")
        or getattr(to_trip, "origin", "")
        or ""
    ).strip()
    if not from_location or not to_location:
        return True

    return_exists, return_deadhead = _required_deadhead_min(
        from_location,
        home_depot,
        dispatch_context=dispatch_context,
    )
    startup_exists, startup_deadhead = _required_deadhead_min(
        home_depot,
        to_location,
        dispatch_context=dispatch_context,
    )
    if not return_exists or not startup_exists:
        return False
    turnaround_min = 0
    if callable(get_turnaround_min):
        try:
            turnaround_min = max(int(get_turnaround_min(from_location) or 0), 0)
        except Exception:
            turnaround_min = 0
    ready_min = int(getattr(from_trip, "arrival_min", 0) or 0) + turnaround_min + return_deadhead + startup_deadhead
    next_departure_min = int(getattr(to_trip, "departure_min", 0) or 0)
    return ready_min <= next_departure_min


def fragment_transition_is_feasible(
    from_duty: Any,
    to_duty: Any,
    *,
    home_depot_id: str,
    dispatch_context: Any | None,
    fixed_route_band_mode: bool,
    allow_same_day_depot_cycles: bool = True,
) -> bool:
    return fragment_transition_diagnostic(
        from_duty,
        to_duty,
        home_depot_id=home_depot_id,
        dispatch_context=dispatch_context,
        fixed_route_band_mode=fixed_route_band_mode,
        allow_same_day_depot_cycles=allow_same_day_depot_cycles,
    ).feasible


def fragment_transition_diagnostic(
    from_duty: Any,
    to_duty: Any,
    *,
    home_depot_id: str,
    dispatch_context: Any | None,
    fixed_route_band_mode: bool,
    allow_same_day_depot_cycles: bool = True,
) -> FragmentTransitionDiagnostic:
    from_band = duty_route_band_ids(from_duty)
    to_band = duty_route_band_ids(to_duty)
    direct_exists, _direct_deadhead = fragment_transition_direct_deadhead_min(
        from_duty,
        to_duty,
        dispatch_context=dispatch_context,
    )
    direct_ok = fragment_transition_allows_direct_connection(
        from_duty,
        to_duty,
        dispatch_context=dispatch_context,
    )
    depot_reset_ok = fragment_transition_allows_depot_reset(
        from_duty,
        to_duty,
        home_depot_id=home_depot_id,
        dispatch_context=dispatch_context,
        allow_same_day_depot_cycles=allow_same_day_depot_cycles,
    )
    route_band_blocked = bool(
        fixed_route_band_mode and from_band and to_band and from_band != to_band
    )
    if fixed_route_band_mode and from_band and to_band and from_band != to_band:
        return FragmentTransitionDiagnostic(
            feasible=depot_reset_ok,
            reason_code="depot_reset_ok" if depot_reset_ok else "route_band_blocked",
            direct_ok=False,
            depot_reset_ok=depot_reset_ok,
            route_band_blocked=not depot_reset_ok,
            deadhead_missing=not direct_exists,
        )
    feasible = depot_reset_ok or direct_ok
    reason_code = "direct_ok" if direct_ok else ("depot_reset_ok" if depot_reset_ok else "deadhead_missing")
    return FragmentTransitionDiagnostic(
        feasible=feasible,
        reason_code=reason_code,
        direct_ok=direct_ok,
        depot_reset_ok=depot_reset_ok,
        deadhead_missing=not direct_exists and not depot_reset_ok,
        location_alias_missing=not direct_exists and dispatch_context is not None,
    )


def _required_deadhead_min(
    from_location: str,
    to_location: str,
    *,
    dispatch_context: Any | None,
) -> Tuple[bool, int]:
    if dispatch_context is None:
        return (True, 0)
    get_deadhead_min = getattr(dispatch_context, "get_deadhead_min", None)
    locations_equivalent = getattr(dispatch_context, "locations_equivalent", None)
    has_location_data = getattr(dispatch_context, "has_location_data", None)
    if callable(locations_equivalent) and locations_equivalent(from_location, to_location):
        return (True, 0)
    if not callable(get_deadhead_min):
        return (True, 0)
    try:
        deadhead_min = max(int(get_deadhead_min(from_location, to_location) or 0), 0)
    except Exception:
        return (True, 0)
    if deadhead_min > 0:
        return (True, deadhead_min)
    if callable(has_location_data) and (has_location_data(from_location) or has_location_data(to_location)):
        return (False, 0)
    return (True, 0)


def required_deadhead_diagnostic(
    from_location: str,
    to_location: str,
    *,
    dispatch_context: Any | None,
) -> tuple[bool, int, str]:
    exists, minutes = _required_deadhead_min(
        from_location,
        to_location,
        dispatch_context=dispatch_context,
    )
    if exists:
        return (True, minutes, "direct_ok")
    has_location_data = getattr(dispatch_context, "has_location_data", None)
    if callable(has_location_data):
        from_known = bool(has_location_data(from_location))
        to_known = bool(has_location_data(to_location))
        if from_known and to_known:
            return (False, minutes, "deadhead_missing")
    return (False, minutes, "location_alias_missing")
