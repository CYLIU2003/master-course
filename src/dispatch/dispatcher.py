"""
src/dispatch/dispatcher.py

DispatchGenerator: greedy trip-chaining algorithm that produces a list of
VehicleDuty objects from a DispatchContext.

Algorithm (greedy earliest-departure-first):
1. Sort all eligible trips by departure time.
2. Maintain a pool of "open" duties (one per vehicle in progress).
3. For each trip (in departure order), try to append it to an existing open
   duty whose last trip can feasibly connect to this trip.  Use the duty
   whose last trip finishes latest (tightest fit first) to minimise fleet size.
4. If no open duty can accept the trip, open a new duty.

This greedy baseline is replaceable by a MILP solver later; the interface
(DispatchContext, vehicle_type) → List[VehicleDuty] stays stable.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .graph_builder import ConnectionGraphBuilder
from .models import DispatchContext, DispatchPlan, DutyLeg, Trip, VehicleBlock, VehicleDuty


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
        a greedy earliest-departure heuristic.

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
        """Generate duties using a precomputed feasible-connection graph."""
        # Filter and sort eligible trips by departure time, then trip_id for
        # determinism when departure times are equal.
        eligible: List[Trip] = sorted(
            [t for t in context.trips if vehicle_type in t.allowed_vehicle_types],
            key=lambda t: (t.departure_min, t.trip_id),
        )

        if not eligible:
            return []

        # Each open duty is represented as (last_trip, accumulated_legs).
        open_duties: List[Tuple[Trip, List[DutyLeg]]] = []
        duty_counter = 0

        for trip in eligible:
            best_idx: Optional[int] = None
            best_arrival: int = -1  # latest arrival wins (tightest fit)

            for idx, (last_trip, _legs) in enumerate(open_duties):
                feasible_successors = graph.get(last_trip.trip_id, [])
                if (
                    trip.trip_id in feasible_successors
                    and last_trip.arrival_min > best_arrival
                ):
                    best_arrival = last_trip.arrival_min
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
