"""
src/dispatch/feasibility.py

FeasibilityEngine: determines whether a vehicle may operate trip_j immediately
after trip_i, applying the hard constraint:

    arrival_time(i) + turnaround_time(i.destination) + deadhead(i.destination, j.origin)
        <= departure_time(j)
"""

from __future__ import annotations

from typing import Any

from .models import ConnectionResult, DispatchContext, Trip
from .route_band import trip_route_band_key


class FeasibilityEngine:
    """Stateless engine that checks pairwise trip connection feasibility."""

    def can_connect(
        self,
        trip_i: Trip,
        trip_j: Trip,
        context: DispatchContext,
        vehicle_type: str,
    ) -> ConnectionResult:
        """
        Check whether trip_j can follow trip_i for a vehicle of *vehicle_type*.

        Hard constraints (all must pass):
        1. Vehicle type is permitted for trip_j.
        2. Sufficient time: arrival(i) + turnaround(i.dest) + deadhead(i.dest, j.origin)
           <= departure(j).
        3. Location continuity: if no deadhead rule exists between i.destination
           and j.origin the stops must be identical.
        """
        # --- 1. Vehicle type constraint ---
        if vehicle_type not in trip_j.allowed_vehicle_types:
            return ConnectionResult(
                feasible=False,
                reason_code="vehicle_type_mismatch",
                reason=(
                    f"Vehicle type '{vehicle_type}' not allowed for trip "
                    f"'{trip_j.trip_id}' (allowed: {trip_j.allowed_vehicle_types})"
                ),
            )

        if bool(getattr(context, "fixed_route_band_mode", False)):
            from_band = trip_route_band_key(trip_i)
            to_band = trip_route_band_key(trip_j)
            if from_band and to_band and from_band != to_band:
                return ConnectionResult(
                    feasible=False,
                    reason_code="route_band_mismatch",
                    reason=(
                        f"Fixed route-band mode forbids connecting trip '{trip_i.trip_id}' "
                        f"({from_band}) to trip '{trip_j.trip_id}' ({to_band})"
                    ),
                )

        # --- 2. Location continuity ---
        from_stop = trip_i.destination_stop_id or trip_i.destination
        to_stop = trip_j.origin_stop_id or trip_j.origin
        deadhead_min = context.get_deadhead_min(from_stop, to_stop)

        if not context.locations_equivalent(from_stop, to_stop) and deadhead_min == 0:
            # No deadhead path exists between these stops.
            return ConnectionResult(
                feasible=False,
                reason_code="missing_deadhead",
                reason=(
                    f"No deadhead path from '{from_stop}' to '{to_stop}': "
                    f"location continuity broken between trip '{trip_i.trip_id}' "
                    f"and trip '{trip_j.trip_id}'"
                ),
            )

        # --- 3. Time continuity ---
        turnaround_min = context.get_turnaround_min(from_stop)
        earliest_departure_j = trip_i.arrival_min + turnaround_min + deadhead_min
        slack = trip_j.departure_min - earliest_departure_j

        if slack < 0:
            return ConnectionResult(
                feasible=False,
                reason_code="insufficient_time",
                reason=(
                    f"Insufficient time: trip '{trip_i.trip_id}' arrives at "
                    f"{trip_i.arrival_time}, turnaround {turnaround_min} min, "
                    f"deadhead {deadhead_min} min → earliest ready "
                    f"{earliest_departure_j} min, but trip '{trip_j.trip_id}' "
                    f"departs at {trip_j.departure_min} min (slack={slack})"
                ),
                deadhead_time_min=deadhead_min,
                turnaround_time_min=turnaround_min,
                slack_min=slack,
            )

        return ConnectionResult(
            feasible=True,
            reason_code="feasible",
            reason=(
                f"OK: slack={slack} min, deadhead={deadhead_min} min, "
                f"turnaround={turnaround_min} min"
            ),
            deadhead_time_min=deadhead_min,
            turnaround_time_min=turnaround_min,
            slack_min=slack,
        )


def evaluate_startup_feasibility(
    trip_like: Any,
    context: DispatchContext,
    home_depot_id: str,
) -> ConnectionResult:
    home_depot = str(home_depot_id or "").strip()
    origin_stop = str(
        getattr(trip_like, "origin_stop_id", "")
        or getattr(trip_like, "origin", "")
        or ""
    ).strip()
    if not home_depot or not origin_stop:
        return ConnectionResult(
            feasible=True,
            reason_code="startup_location_unknown",
            reason="Startup location check skipped because depot or origin is missing.",
        )

    if context.locations_equivalent(home_depot, origin_stop):
        return ConnectionResult(
            feasible=True,
            reason_code="feasible",
            reason=(
                f"Depot '{home_depot}' is equivalent to startup origin '{origin_stop}'."
            ),
            deadhead_time_min=0,
        )

    deadhead_min = max(int(context.get_deadhead_min(home_depot, origin_stop) or 0), 0)
    if deadhead_min > 0:
        return ConnectionResult(
            feasible=True,
            reason_code="feasible",
            reason=(
                f"Startup deadhead from depot '{home_depot}' to '{origin_stop}' exists "
                f"({deadhead_min} min)."
            ),
            deadhead_time_min=deadhead_min,
        )

    has_location_data = getattr(context, "has_location_data", None)
    home_has_data = bool(callable(has_location_data) and has_location_data(home_depot))
    origin_has_data = bool(callable(has_location_data) and has_location_data(origin_stop))
    if home_has_data and origin_has_data:
        return ConnectionResult(
            feasible=False,
            reason_code="startup_deadhead_missing",
            reason=(
                f"No startup deadhead rule from depot '{home_depot}' to first origin "
                f"'{origin_stop}'."
            ),
        )
    if home_has_data or origin_has_data:
        return ConnectionResult(
            feasible=False,
            reason_code="startup_alias_missing",
            reason=(
                f"Depot '{home_depot}' and startup origin '{origin_stop}' do not resolve "
                f"to an equivalent alias set."
            ),
        )
    return ConnectionResult(
        feasible=True,
        reason_code="startup_location_unknown",
        reason=(
            f"Startup path from depot '{home_depot}' to '{origin_stop}' could not be "
            "validated because location metadata is incomplete."
        ),
    )
