"""
src/dispatch/feasibility.py

FeasibilityEngine: determines whether a vehicle may operate trip_j immediately
after trip_i, applying the hard constraint:

    arrival_time(i) + turnaround_time(i.destination) + deadhead(i.destination, j.origin)
        <= departure_time(j)
"""

from __future__ import annotations

from .models import ConnectionResult, DispatchContext, Trip


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

        # --- 2. Location continuity ---
        from_stop = trip_i.destination_stop_id or trip_i.destination
        to_stop = trip_j.origin_stop_id or trip_j.origin
        deadhead_min = context.get_deadhead_min(from_stop, to_stop)

        if from_stop != to_stop and deadhead_min == 0:
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
