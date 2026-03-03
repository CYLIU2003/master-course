"""
tests/test_dispatch_graph.py

Unit tests for ConnectionGraphBuilder.build().

Covers:
- All eligible trip nodes appear in graph keys
- Trips ineligible for vehicle type are excluded as nodes
- Feasible edges are present
- Infeasible edges (time, location, vehicle type) are excluded
- Self-loops never appear
- Empty trip list → empty graph
"""

import pytest

from src.dispatch.graph_builder import ConnectionGraphBuilder
from src.dispatch.models import (
    DeadheadRule,
    DispatchContext,
    Trip,
    TurnaroundRule,
    VehicleProfile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_context(
    trips=None,
    turnaround_rules=None,
    deadhead_rules=None,
    default_turnaround_min: int = 10,
) -> DispatchContext:
    return DispatchContext(
        service_date="2024-06-01",
        trips=trips or [],
        turnaround_rules=turnaround_rules or {},
        deadhead_rules=deadhead_rules or {},
        vehicle_profiles={
            "BEV": VehicleProfile(vehicle_type="BEV"),
            "ICE": VehicleProfile(vehicle_type="ICE"),
        },
        default_turnaround_min=default_turnaround_min,
    )


def make_trip(
    trip_id: str,
    origin: str,
    destination: str,
    departure_time: str,
    arrival_time: str,
    allowed: tuple = ("BEV",),
) -> Trip:
    return Trip(
        trip_id=trip_id,
        route_id="R1",
        origin=origin,
        destination=destination,
        departure_time=departure_time,
        arrival_time=arrival_time,
        distance_km=10.0,
        allowed_vehicle_types=allowed,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGraphBuilderNodes:
    """Graph node population."""

    def test_all_eligible_trips_are_nodes(self):
        """Every trip that allows BEV appears as a key in the graph."""
        trips = [
            make_trip("T1", "A", "A", "07:00", "07:30"),
            make_trip("T2", "A", "A", "08:00", "08:30"),
            make_trip("T3", "A", "A", "09:00", "09:30"),
        ]
        ctx = make_context(trips=trips)
        graph = ConnectionGraphBuilder().build(ctx, "BEV")

        assert set(graph.keys()) == {"T1", "T2", "T3"}

    def test_ineligible_trips_excluded_as_nodes(self):
        """Trips that do NOT allow BEV must not appear as graph nodes."""
        trips = [
            make_trip("T1", "A", "A", "07:00", "07:30", allowed=("BEV",)),
            make_trip("T2", "A", "A", "08:00", "08:30", allowed=("ICE",)),
        ]
        ctx = make_context(trips=trips)
        graph = ConnectionGraphBuilder().build(ctx, "BEV")

        assert "T1" in graph
        assert "T2" not in graph

    def test_empty_trips_gives_empty_graph(self):
        ctx = make_context(trips=[])
        graph = ConnectionGraphBuilder().build(ctx, "BEV")
        assert graph == {}

    def test_no_eligible_trips_gives_empty_graph(self):
        """All trips are ICE-only; BEV graph should be empty."""
        trips = [
            make_trip("T1", "A", "B", "07:00", "07:30", allowed=("ICE",)),
        ]
        ctx = make_context(trips=trips)
        graph = ConnectionGraphBuilder().build(ctx, "BEV")
        assert graph == {}


class TestGraphBuilderEdges:
    """Graph edge correctness."""

    def test_feasible_edge_is_present(self):
        """
        T1 arrives 07:30 at A, T2 departs 08:00 from A → slack=20, should connect.
        """
        trips = [
            make_trip("T1", "A", "A", "07:00", "07:30"),
            make_trip("T2", "A", "B", "08:00", "08:30"),
        ]
        ctx = make_context(trips=trips, default_turnaround_min=10)
        graph = ConnectionGraphBuilder().build(ctx, "BEV")

        assert "T2" in graph["T1"]

    def test_infeasible_time_edge_excluded(self):
        """
        T1 arrives 07:30, turnaround 10 → ready 07:40.
        T2 departs 07:25 → infeasible; no edge T1→T2.
        """
        trips = [
            make_trip("T1", "A", "A", "07:00", "07:30"),
            make_trip("T2", "A", "B", "07:25", "07:55"),
        ]
        ctx = make_context(trips=trips, default_turnaround_min=10)
        graph = ConnectionGraphBuilder().build(ctx, "BEV")

        assert "T2" not in graph["T1"]

    def test_infeasible_location_edge_excluded(self):
        """
        T1 ends at B, T2 starts at C, no deadhead rule → no edge T1→T2.
        """
        trips = [
            make_trip("T1", "A", "B", "07:00", "07:30"),
            make_trip("T2", "C", "D", "09:00", "09:30"),
        ]
        ctx = make_context(trips=trips)
        graph = ConnectionGraphBuilder().build(ctx, "BEV")

        assert "T2" not in graph["T1"]

    def test_deadhead_edge_included_when_rule_exists(self):
        """
        T1 ends at B, T2 starts at C.  DeadheadRule (B→C) = 20 min.
        T1 arrives 07:30 + turnaround 10 + deadhead 20 = 08:00.
        T2 departs 08:30 → slack 30 → feasible edge.
        """
        trips = [
            make_trip("T1", "A", "B", "07:00", "07:30"),
            make_trip("T2", "C", "D", "08:30", "09:00"),
        ]
        dh = DeadheadRule(from_stop="B", to_stop="C", travel_time_min=20)
        ctx = make_context(
            trips=trips,
            deadhead_rules={("B", "C"): dh},
            default_turnaround_min=10,
        )
        graph = ConnectionGraphBuilder().build(ctx, "BEV")

        assert "T2" in graph["T1"]

    def test_no_self_loops(self):
        """A trip must never have an edge to itself."""
        trips = [make_trip("T1", "A", "A", "07:00", "07:30")]
        ctx = make_context(trips=trips)
        graph = ConnectionGraphBuilder().build(ctx, "BEV")

        assert "T1" not in graph["T1"]

    def test_vehicle_type_constraint_blocks_edge(self):
        """
        T2 only allows ICE.  BEV graph must not contain an edge T1→T2.
        """
        trips = [
            make_trip("T1", "A", "A", "07:00", "07:30", allowed=("BEV",)),
            make_trip("T2", "A", "B", "08:00", "08:30", allowed=("ICE",)),
        ]
        ctx = make_context(trips=trips)
        graph = ConnectionGraphBuilder().build(ctx, "BEV")

        # T2 is not in graph at all (excluded as a node)
        assert "T2" not in graph

    def test_multiple_feasible_successors(self):
        """
        T1 can connect to both T2 and T3 (both depart late enough, same stop).
        """
        trips = [
            make_trip("T1", "A", "A", "07:00", "07:30"),
            make_trip("T2", "A", "B", "08:00", "08:30"),
            make_trip("T3", "A", "C", "09:00", "09:30"),
        ]
        ctx = make_context(trips=trips, default_turnaround_min=10)
        graph = ConnectionGraphBuilder().build(ctx, "BEV")

        assert "T2" in graph["T1"]
        assert "T3" in graph["T1"]

    def test_chain_three_trips(self):
        """
        Linear chain: T1 → T2 → T3 at stop A.
        T2 should also connect to T3.
        """
        trips = [
            make_trip("T1", "A", "A", "07:00", "07:30"),
            make_trip("T2", "A", "A", "08:00", "08:30"),
            make_trip("T3", "A", "A", "09:00", "09:30"),
        ]
        ctx = make_context(trips=trips, default_turnaround_min=10)
        graph = ConnectionGraphBuilder().build(ctx, "BEV")

        assert "T2" in graph["T1"]
        assert "T3" in graph["T1"]
        assert "T3" in graph["T2"]
        # Reverse or same-time connections should not appear
        assert "T1" not in graph["T2"]
        assert "T1" not in graph["T3"]
        assert "T2" not in graph["T3"]
