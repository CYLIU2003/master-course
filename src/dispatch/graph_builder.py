"""
src/dispatch/graph_builder.py

ConnectionGraphBuilder: builds a directed graph of feasible trip connections
for a given vehicle type.  Each node is a trip_id; each directed edge (i → j)
means a vehicle of *vehicle_type* may operate trip j immediately after trip i.
"""

from __future__ import annotations

from typing import Dict, List

from .feasibility import FeasibilityEngine
from .models import DispatchContext


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
        trips = context.trips
        # Seed graph: every eligible trip appears as a node.
        graph: Dict[str, List[str]] = {
            t.trip_id: [] for t in trips if vehicle_type in t.allowed_vehicle_types
        }

        trip_by_id = context.trips_by_id()

        for trip_i in trips:
            if vehicle_type not in trip_i.allowed_vehicle_types:
                continue
            for trip_j in trips:
                if trip_i.trip_id == trip_j.trip_id:
                    continue
                if vehicle_type not in trip_j.allowed_vehicle_types:
                    continue
                result = self._engine.can_connect(trip_i, trip_j, context, vehicle_type)
                if result.feasible:
                    graph[trip_i.trip_id].append(trip_j.trip_id)

        return graph
