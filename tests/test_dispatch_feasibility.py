"""
tests/test_dispatch_feasibility.py

Unit tests for FeasibilityEngine.can_connect().

Covers:
- Time-feasible connection (same stop, sufficient slack)
- Time-infeasible connection (same stop, arrives too late)
- Location mismatch without any deadhead rule (infeasible)
- Location mismatch WITH a deadhead rule (feasible when time allows)
- Vehicle type constraint blocks a connection
- Exact boundary: slack == 0 is feasible; slack == -1 is not
"""

import pytest

from src.dispatch.feasibility import FeasibilityEngine
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
        vehicle_profiles={"BEV": VehicleProfile(vehicle_type="BEV")},
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


class TestFeasibilityEngineSameStop:
    """Trip i and trip j share the same stop (no deadhead needed)."""

    def test_time_feasible_with_slack(self):
        """
        trip_i arrives 07:30 at stop A.
        Default turnaround = 10 min  → ready at 07:40.
        trip_j departs 08:00 → slack = 20 min → feasible.
        """
        engine = FeasibilityEngine()
        trip_i = make_trip("T1", "A", "A", "07:00", "07:30")
        trip_j = make_trip("T2", "A", "B", "08:00", "08:30")
        ctx = make_context(trips=[trip_i, trip_j], default_turnaround_min=10)

        result = engine.can_connect(trip_i, trip_j, ctx, "BEV")

        assert result.feasible is True
        assert result.slack_min == 20
        assert result.deadhead_time_min == 0

    def test_time_infeasible_too_tight(self):
        """
        trip_i arrives 07:30 at stop A.
        Default turnaround = 15 min → ready at 07:45.
        trip_j departs 07:25 → slack = -20 min → infeasible.
        """
        engine = FeasibilityEngine()
        trip_i = make_trip("T1", "A", "A", "07:00", "07:30")
        trip_j = make_trip("T2", "A", "B", "07:25", "08:00")
        ctx = make_context(trips=[trip_i, trip_j], default_turnaround_min=15)

        result = engine.can_connect(trip_i, trip_j, ctx, "BEV")

        assert result.feasible is False
        assert result.slack_min < 0
        assert "Insufficient time" in result.reason

    def test_exact_zero_slack_is_feasible(self):
        """
        trip_i arrives 07:30. Turnaround 10 min → ready at 07:40.
        trip_j departs exactly 07:40 → slack = 0 → still feasible.
        """
        engine = FeasibilityEngine()
        trip_i = make_trip("T1", "A", "A", "07:00", "07:30")
        trip_j = make_trip("T2", "A", "B", "07:40", "08:10")
        ctx = make_context(trips=[trip_i, trip_j], default_turnaround_min=10)

        result = engine.can_connect(trip_i, trip_j, ctx, "BEV")

        assert result.feasible is True
        assert result.slack_min == 0

    def test_slack_minus_one_is_infeasible(self):
        """
        trip_i arrives 07:30. Turnaround 10 min → ready at 07:40.
        trip_j departs 07:39 → slack = -1 → infeasible.
        """
        engine = FeasibilityEngine()
        trip_i = make_trip("T1", "A", "A", "07:00", "07:30")
        trip_j = make_trip("T2", "A", "B", "07:39", "08:09")
        ctx = make_context(trips=[trip_i, trip_j], default_turnaround_min=10)

        result = engine.can_connect(trip_i, trip_j, ctx, "BEV")

        assert result.feasible is False
        assert result.slack_min == -1


class TestFeasibilityEngineDeadhead:
    """Trip i ends at a different stop from trip j's start."""

    def test_no_deadhead_rule_infeasible(self):
        """
        trip_i ends at stop B, trip_j starts at stop C.
        No DeadheadRule for (B, C) exists → infeasible (can't teleport).
        """
        engine = FeasibilityEngine()
        trip_i = make_trip("T1", "A", "B", "07:00", "07:30")
        trip_j = make_trip("T2", "C", "D", "09:00", "09:30")
        ctx = make_context(trips=[trip_i, trip_j])  # no deadhead rules

        result = engine.can_connect(trip_i, trip_j, ctx, "BEV")

        assert result.feasible is False
        assert "No deadhead path" in result.reason

    def test_deadhead_rule_exists_time_ok(self):
        """
        trip_i ends at B, trip_j starts at C.
        DeadheadRule (B→C) = 20 min.
        trip_i arrives 07:30 + turnaround 10 + deadhead 20 = 08:00.
        trip_j departs 08:30 → slack = 30 → feasible.
        """
        engine = FeasibilityEngine()
        trip_i = make_trip("T1", "A", "B", "07:00", "07:30")
        trip_j = make_trip("T2", "C", "D", "08:30", "09:00")
        dh_rule = DeadheadRule(from_stop="B", to_stop="C", travel_time_min=20)
        ctx = make_context(
            trips=[trip_i, trip_j],
            deadhead_rules={("B", "C"): dh_rule},
            default_turnaround_min=10,
        )

        result = engine.can_connect(trip_i, trip_j, ctx, "BEV")

        assert result.feasible is True
        assert result.deadhead_time_min == 20
        assert result.slack_min == 30

    def test_deadhead_rule_exists_time_insufficient(self):
        """
        DeadheadRule (B→C) = 20 min.
        trip_i arrives 07:30 + turnaround 10 + deadhead 20 = 08:00.
        trip_j departs 07:55 → slack = -5 → infeasible.
        """
        engine = FeasibilityEngine()
        trip_i = make_trip("T1", "A", "B", "07:00", "07:30")
        trip_j = make_trip("T2", "C", "D", "07:55", "08:25")
        dh_rule = DeadheadRule(from_stop="B", to_stop="C", travel_time_min=20)
        ctx = make_context(
            trips=[trip_i, trip_j],
            deadhead_rules={("B", "C"): dh_rule},
            default_turnaround_min=10,
        )

        result = engine.can_connect(trip_i, trip_j, ctx, "BEV")

        assert result.feasible is False
        assert "Insufficient time" in result.reason


class TestFeasibilityEngineVehicleType:
    """Vehicle type constraint checks."""

    def test_vehicle_type_not_allowed_for_trip_j(self):
        """
        trip_j only allows ICE.  Connecting a BEV vehicle must fail.
        """
        engine = FeasibilityEngine()
        trip_i = make_trip("T1", "A", "A", "07:00", "07:30", allowed=("BEV", "ICE"))
        trip_j = make_trip("T2", "A", "B", "08:00", "08:30", allowed=("ICE",))
        ctx = make_context(trips=[trip_i, trip_j])

        result = engine.can_connect(trip_i, trip_j, ctx, "BEV")

        assert result.feasible is False
        assert "not allowed" in result.reason

    def test_vehicle_type_allowed_passes(self):
        """
        trip_j allows BEV and ICE — connecting a BEV should pass the type check.
        """
        engine = FeasibilityEngine()
        trip_i = make_trip("T1", "A", "A", "07:00", "07:30", allowed=("BEV",))
        trip_j = make_trip("T2", "A", "B", "08:00", "08:30", allowed=("BEV", "ICE"))
        ctx = make_context(trips=[trip_i, trip_j])

        result = engine.can_connect(trip_i, trip_j, ctx, "BEV")

        assert result.feasible is True

    def test_vehicle_type_checked_before_location(self):
        """
        Vehicle type violation is checked first; even if location is also wrong
        the returned reason should reference the type, not location.
        """
        engine = FeasibilityEngine()
        trip_i = make_trip("T1", "A", "B", "07:00", "07:30", allowed=("BEV",))
        # trip_j starts at C (different from B) and only allows ICE
        trip_j = make_trip("T2", "C", "D", "09:00", "09:30", allowed=("ICE",))
        ctx = make_context(trips=[trip_i, trip_j])

        result = engine.can_connect(trip_i, trip_j, ctx, "BEV")

        assert result.feasible is False
        assert "not allowed" in result.reason


class TestFeasibilityEngineTurnaroundRule:
    """Stop-specific turnaround rules override the default."""

    def test_stop_specific_turnaround_applied(self):
        """
        Stop A has a specific turnaround of 5 min (not the default 10).
        trip_i arrives 07:30 + turnaround 5 = 07:35.
        trip_j departs 07:40 → slack = 5 → feasible.
        With default 10 it would be slack=-5, infeasible.
        """
        engine = FeasibilityEngine()
        trip_i = make_trip("T1", "X", "A", "07:00", "07:30")
        trip_j = make_trip("T2", "A", "Y", "07:40", "08:10")
        ta_rule = TurnaroundRule(stop_id="A", min_turnaround_min=5)
        ctx = make_context(
            trips=[trip_i, trip_j],
            turnaround_rules={"A": ta_rule},
            default_turnaround_min=10,
        )

        result = engine.can_connect(trip_i, trip_j, ctx, "BEV")

        assert result.feasible is True
        assert result.slack_min == 5
