"""
bff/mappers/dispatch_mappers.py

Converts between Python dispatch dataclasses (src/dispatch/models.py)
and the plain-dict JSON shapes expected by the frontend TypeScript types.

Field name mapping reference:
  Python Trip.departure_time   → JSON Trip.departure
  Python Trip.arrival_time     → JSON Trip.arrival
  Python Trip.departure_min    → JSON Trip.departure_min  (computed property)
  Python Trip.arrival_min      → JSON Trip.arrival_min    (computed property)
  Python TurnaroundRule.min_turnaround_min → JSON TurnaroundRule.turnaround_min
  Python DeadheadRule.from_stop            → JSON DeadheadRule.origin
  Python DeadheadRule.to_stop              → JSON DeadheadRule.destination
  Python DeadheadRule.travel_time_min      → JSON DeadheadRule.time_min
  Python DutyLeg.deadhead_from_prev_min    → JSON DutyLeg.deadhead_time_min
  Python VehicleDuty.legs (tuple)          → JSON VehicleDuty.legs (list)
"""

from __future__ import annotations

from typing import Any, Dict, List

from src.dispatch.models import (
    DeadheadRule,
    DutyLeg,
    Trip,
    TurnaroundRule,
    VehicleDuty,
    ValidationResult,
    hhmm_to_min,
)


def min_to_hhmm(minutes: int) -> str:
    """Convert integer minutes-from-midnight back to HH:MM string."""
    h = minutes // 60
    m = minutes % 60
    return f"{h:02d}:{m:02d}"


# ── Trip ──────────────────────────────────────────────────────


def trip_to_dict(trip: Trip, direction: str = "outbound") -> Dict[str, Any]:
    return {
        "trip_id": trip.trip_id,
        "route_id": trip.route_id,
        "direction": direction,
        "origin": trip.origin,
        "destination": trip.destination,
        "departure": trip.departure_time,
        "arrival": trip.arrival_time,
        "departure_min": trip.departure_min,
        "arrival_min": trip.arrival_min,
        "distance_km": trip.distance_km,
        "allowed_vehicle_types": list(trip.allowed_vehicle_types),
    }


def dict_to_trip(d: Dict[str, Any]) -> Trip:
    return Trip(
        trip_id=d["trip_id"],
        route_id=d["route_id"],
        origin=d["origin"],
        destination=d["destination"],
        departure_time=d["departure"],
        arrival_time=d["arrival"],
        distance_km=float(d["distance_km"]),
        allowed_vehicle_types=tuple(d["allowed_vehicle_types"]),
    )


# ── Rules ─────────────────────────────────────────────────────


def turnaround_rule_to_dict(rule: TurnaroundRule) -> Dict[str, Any]:
    return {
        "stop_id": rule.stop_id,
        "turnaround_min": rule.min_turnaround_min,
    }


def deadhead_rule_to_dict(rule: DeadheadRule) -> Dict[str, Any]:
    return {
        "origin": rule.from_stop,
        "destination": rule.to_stop,
        "time_min": rule.travel_time_min,
        "distance_km": 0.0,  # distance not tracked in current model
    }


# ── Duties ────────────────────────────────────────────────────


def duty_leg_to_dict(
    leg: DutyLeg, route_distances: Dict[str, float] | None = None
) -> Dict[str, Any]:
    trip_dict = trip_to_dict(leg.trip)
    return {
        "trip": trip_dict,
        "deadhead_time_min": leg.deadhead_from_prev_min,
        "deadhead_distance_km": 0.0,
    }


def vehicle_duty_to_dict(duty: VehicleDuty) -> Dict[str, Any]:
    legs = [duty_leg_to_dict(leg) for leg in duty.legs]
    trips = [leg["trip"] for leg in legs]

    total_distance = sum(t["distance_km"] for t in trips)
    total_service_time = sum(
        hhmm_to_min(t["arrival"]) - hhmm_to_min(t["departure"]) for t in trips
    )

    start_time = trips[0]["departure"] if trips else "00:00"
    end_time = trips[-1]["arrival"] if trips else "00:00"

    return {
        "duty_id": duty.duty_id,
        "vehicle_type": duty.vehicle_type,
        "legs": legs,
        "total_distance_km": total_distance,
        "total_deadhead_km": sum(leg["deadhead_distance_km"] for leg in legs),
        "total_service_time_min": total_service_time,
        "start_time": start_time,
        "end_time": end_time,
    }


def validation_result_to_dict(duty_id: str, result: ValidationResult) -> Dict[str, Any]:
    return {
        "duty_id": duty_id,
        "valid": result.valid,
        "errors": list(result.errors),
    }


# ── Graph ─────────────────────────────────────────────────────


def build_graph_response(
    trips: List[Trip],
    adjacency: Dict[str, List[str]],
) -> Dict[str, Any]:
    """
    Build the ConnectionGraph JSON response from the dispatch graph.

    The adjacency list from ConnectionGraphBuilder is:
        { trip_id_i: [trip_id_j, ...] }

    We expand this into full ConnectionArc objects.
    """
    arcs = []
    feasible_count = 0
    for from_id, to_ids in adjacency.items():
        for to_id in to_ids:
            arcs.append(
                {
                    "from_trip_id": from_id,
                    "to_trip_id": to_id,
                    "deadhead_time_min": 0,
                    "deadhead_distance_km": 0.0,
                    "idle_time_min": 0,
                    "feasible": True,
                    "reason": "feasible",
                }
            )
            feasible_count += 1

    return {
        "trips": [trip_to_dict(t) for t in trips],
        "arcs": arcs,
        "total_arcs": len(arcs),
        "feasible_arcs": feasible_count,
        "infeasible_arcs": 0,
    }
