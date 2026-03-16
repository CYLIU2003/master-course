"""
src/dispatch/dispatcher.py

DispatchGenerator: greedy trip-chaining algorithm that produces a list of
VehicleDuty objects from a DispatchContext.

Algorithm (greedy earliest-departure-first with return-leg preference):
1. Sort all eligible trips by departure time.
2. Maintain a pool of "open" duties (one per vehicle in progress).
3. For each trip (in departure order), find all open duties whose last trip
   can feasibly connect to this trip.  Score each candidate:

   Base score (always applied)
   - +0   : latest arrival wins (tightest-fit) — tie-breaker

   Return-leg bonus (swap=off or swap=intra-depot)
   - +200 : same route_id AND direction is reversed ("outbound" ↔ "inbound")
             → vehicle returns on the same line it arrived on
   - +100 : same origin stop as prev destination (no deadhead needed)
   - +50  : candidate is on the same route but same direction (e.g. shuttle loop)

   Intra-depot swap bonus (allow_intra_depot_swap=True)
   - +20  : different route but destination==origin (same stop, no deadhead)
   - +10  : different route but deadhead_time==0 (happens to be same stop)

   Inter-depot swap bonus (allow_inter_depot_swap=True)
   - +5   : any feasible connection even across depots

   Penalty
   - -1 per minute of deadhead (prefer shorter deadhead)

4. Pick the open duty with the highest score.  Ties broken by latest arrival.
5. If no open duty can accept the trip, open a new duty.

Feasibility definition is NOT changed — only the selection preference.
This greedy baseline is replaceable by a MILP solver; the interface stays stable.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .graph_builder import ConnectionGraphBuilder
from .models import DispatchContext, DispatchPlan, DutyLeg, Trip, VehicleBlock, VehicleDuty


def _opposite_direction(d: str) -> str:
    if d == "outbound":
        return "inbound"
    if d == "inbound":
        return "outbound"
    return ""


def _route_group_key(trip: Trip) -> str:
    family = str(getattr(trip, "route_family_code", "") or "").strip()
    return family or str(trip.route_id)


def _connection_score(
    last_trip: Trip,
    next_trip: Trip,
    context: DispatchContext,
) -> int:
    """Compute a preference score for chaining last_trip → next_trip.

    Higher is better.  Feasibility must already be confirmed by the caller.
    The score intentionally does NOT change feasibility; it only breaks ties
    among equally-feasible candidates.
    """
    score = 0

    deadhead_min = context.get_deadhead_min(last_trip.destination, next_trip.origin)

    # ── Soft penalty: prefer shorter deadhead ────────────────────────────────
    score -= deadhead_min  # -1 per minute of deadhead

    # ── Return-leg bonus: same route, reversed direction ──────────────────────
    # This implements the "vehicle runs back on the same line" preference.
    # Real buses in Japan typically do this unless the depot is in the way.
    same_route = _route_group_key(last_trip) == _route_group_key(next_trip)
    last_dir = last_trip.direction
    next_dir = next_trip.direction
    if (
        same_route
        and last_dir != "unknown"
        and next_dir != "unknown"
        and next_dir == _opposite_direction(last_dir)
    ):
        score += 200  # strongly prefer returning on same route

    # ── No-deadhead bonus: destination == origin ──────────────────────────────
    if last_trip.destination == next_trip.origin:
        score += 100

    # ── Same route, same direction (shuttle / loop) ───────────────────────────
    if same_route and last_dir == next_dir and last_dir != "unknown":
        score += 50

    # ── Intra-depot swap: different route, same stop ─────────────────────────
    if (
        context.allow_intra_depot_swap
        and not same_route
        and last_trip.destination == next_trip.origin
    ):
        score += 20
    elif context.allow_intra_depot_swap and not same_route and deadhead_min == 0:
        score += 10

    # ── Inter-depot swap: any feasible connection across depots ───────────────
    if context.allow_inter_depot_swap and not same_route:
        score += 5

    return score


class DispatchGenerator:
    """Greedy dispatcher: timetable → VehicleDuty list."""

    def __init__(self) -> None:
        self._graph_builder = ConnectionGraphBuilder()

    def generate_greedy_duties(
        self,
        context: DispatchContext,
        vehicle_type: str,
    ) -> List[VehicleDuty]:
        """
        Generate a list of VehicleDuty assignments for *vehicle_type* using
        a greedy earliest-departure heuristic with return-leg preference.

        Only trips that include *vehicle_type* in their allowed_vehicle_types
        are considered.
        """
        graph = self._graph_builder.build(context, vehicle_type)
        return self.generate_greedy_duties_from_graph(context, vehicle_type, graph)

    def generate_greedy_blocks(
        self,
        context: DispatchContext,
        vehicle_type: str,
    ) -> List[VehicleBlock]:
        graph = self._graph_builder.build(context, vehicle_type)
        return self.generate_greedy_blocks_from_graph(context, vehicle_type, graph)

    def generate_greedy_blocks_from_graph(
        self,
        context: DispatchContext,
        vehicle_type: str,
        graph: Dict[str, List[str]],
    ) -> List[VehicleBlock]:
        duties = self.generate_greedy_duties_from_graph(context, vehicle_type, graph)
        return [
            VehicleBlock(
                block_id=f"BLOCK-{vehicle_type}-{index:04d}",
                vehicle_type=vehicle_type,
                trip_ids=tuple(duty.trip_ids),
            )
            for index, duty in enumerate(duties, start=1)
        ]

    def generate_greedy_plan(
        self,
        context: DispatchContext,
        vehicle_type: str,
    ) -> DispatchPlan:
        graph = self._graph_builder.build(context, vehicle_type)
        duties = self.generate_greedy_duties_from_graph(context, vehicle_type, graph)
        blocks = self.generate_greedy_blocks_from_graph(context, vehicle_type, graph)
        return DispatchPlan(
            plan_id=f"PLAN-{vehicle_type}",
            vehicle_blocks=tuple(blocks),
            duties=tuple(duties),
            charging_plan=(),
        )

    def generate_greedy_duties_from_graph(
        self,
        context: DispatchContext,
        vehicle_type: str,
        graph: Dict[str, List[str]],
    ) -> List[VehicleDuty]:
        """Generate duties using a precomputed feasible-connection graph.

        Selection preference (highest score wins among feasible candidates):
        - Return-leg on same route gets a large bonus.
        - Shorter deadhead is preferred.
        - Swap bonuses apply when context flags allow it.
        """
        # Filter and sort eligible trips by departure time, then trip_id for
        # determinism when departure times are equal.
        eligible: List[Trip] = sorted(
            [t for t in context.trips if vehicle_type in t.allowed_vehicle_types],
            key=lambda t: (t.departure_min, t.trip_id),
        )

        if not eligible:
            return []

        # Build a quick lookup: trip_id → Trip
        trip_by_id: Dict[str, Trip] = {t.trip_id: t for t in eligible}

        # Each open duty is represented as (last_trip, accumulated_legs).
        open_duties: List[Tuple[Trip, List[DutyLeg]]] = []
        duty_counter = 0

        for trip in eligible:
            best_idx: Optional[int] = None
            best_score: int = -10_000  # lower than any real score

            for idx, (last_trip, _legs) in enumerate(open_duties):
                feasible_successors = graph.get(last_trip.trip_id, [])
                if trip.trip_id not in feasible_successors:
                    continue

                score = _connection_score(last_trip, trip, context)
                # Tie-break: later arrival = tighter fit = prefer
                score_with_tiebreak = score * 10_000 + last_trip.arrival_min

                if score_with_tiebreak > best_score:
                    best_score = score_with_tiebreak
                    best_idx = idx

            deadhead_min = 0
            if best_idx is not None:
                last_trip, legs = open_duties[best_idx]
                deadhead_min = context.get_deadhead_min(
                    last_trip.destination, trip.origin
                )
                legs.append(DutyLeg(trip=trip, deadhead_from_prev_min=deadhead_min))
                # Update last_trip in the open duty slot.
                open_duties[best_idx] = (trip, legs)
            else:
                # Start a new duty.
                open_duties.append(
                    (trip, [DutyLeg(trip=trip, deadhead_from_prev_min=0)])
                )

        duties: List[VehicleDuty] = []
        for last_trip, legs in open_duties:
            duty_counter += 1
            duties.append(
                VehicleDuty(
                    duty_id=f"DUTY-{vehicle_type}-{duty_counter:04d}",
                    vehicle_type=vehicle_type,
                    legs=tuple(legs),
                )
            )

        return duties
