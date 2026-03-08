"""
src/dispatch/graph_builder.py

ConnectionGraphBuilder: builds a directed graph of feasible trip connections
for a given vehicle type.  Each node is a trip_id; each directed edge (i → j)
means a vehicle of *vehicle_type* may operate trip j immediately after trip i.
"""

from __future__ import annotations

from typing import Dict, List

from .feasibility import FeasibilityEngine
from .models import ConnectionArc, DispatchContext


class ConnectionGraphBuilder:
    """Builds the directed feasibility graph from a DispatchContext."""

    def __init__(self) -> None:
        self._engine = FeasibilityEngine()

    def build(
        self,
        context: DispatchContext,
        vehicle_type: str,
    ) -> Dict[str, List[str]]:
        """
        Return an adjacency-list graph: {trip_id_i: [trip_id_j, ...]}
        containing only feasible edges for *vehicle_type*.

        All trips that are *allowed* for *vehicle_type* appear as nodes
        (even if they have no outgoing edges).
        """
        graph: Dict[str, List[str]] = {
            t.trip_id: []
            for t in context.trips
            if vehicle_type in t.allowed_vehicle_types
        }

        for arc in self.analyze(context, vehicle_type):
            if arc.feasible:
                graph[arc.from_trip_id].append(arc.to_trip_id)

        return graph

    def analyze(
        self,
        context: DispatchContext,
        vehicle_type: str,
    ) -> List[ConnectionArc]:
        """Return all analyzed candidate arcs for the given vehicle type."""
        trips = [
            trip for trip in context.trips if vehicle_type in trip.allowed_vehicle_types
        ]
        arcs: List[ConnectionArc] = []

        for trip_i in trips:
            for trip_j in trips:
                if trip_i.trip_id == trip_j.trip_id:
                    continue

                result = self._engine.can_connect(trip_i, trip_j, context, vehicle_type)
                arcs.append(
                    ConnectionArc(
                        from_trip_id=trip_i.trip_id,
                        to_trip_id=trip_j.trip_id,
                        vehicle_type=vehicle_type,
                        deadhead_time_min=result.deadhead_time_min,
                        turnaround_time_min=result.turnaround_time_min,
                        slack_min=result.slack_min,
                        feasible=result.feasible,
                        reason_code=result.reason_code,
                        reason=result.reason,
                    )
                )

        return arcs
