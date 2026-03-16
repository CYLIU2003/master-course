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
    ConnectionArc,
    DeadheadRule,
    DutyLeg,
    Trip,
    TurnaroundRule,
    VehicleDuty,
    ValidationResult,
    hhmm_to_min,
)


_DEADHEAD_FALLBACK_SPEED_KMPH = 20.0


def _estimate_deadhead_distance_km(deadhead_time_min: int) -> float:
    if deadhead_time_min <= 0:
        return 0.0
    return round((deadhead_time_min / 60.0) * _DEADHEAD_FALLBACK_SPEED_KMPH, 4)


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
        "route_family_code": trip.route_family_code,
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
        route_family_code=str(
            d.get("route_family_code")
            or d.get("routeFamilyCode")
            or d.get("routeSeriesCode")
            or ""
        ),
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
        "distance_km": _estimate_deadhead_distance_km(rule.travel_time_min),
    }


# ── Duties ────────────────────────────────────────────────────


def duty_leg_to_dict(
    leg: DutyLeg, route_distances: Dict[str, float] | None = None
) -> Dict[str, Any]:
    trip_dict = trip_to_dict(leg.trip)
    deadhead_distance_km = _estimate_deadhead_distance_km(leg.deadhead_from_prev_min)
    return {
        "trip": trip_dict,
        "deadhead_time_min": leg.deadhead_from_prev_min,
        "deadhead_distance_km": deadhead_distance_km,
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
    arcs: List[ConnectionArc],
) -> Dict[str, Any]:
    feasible_count = sum(1 for arc in arcs if arc.feasible)
    serialized_arcs = []
    reason_counts: Dict[str, int] = {}

    for arc in arcs:
        reason_counts[arc.reason_code] = reason_counts.get(arc.reason_code, 0) + 1
        serialized_arcs.append(
            {
                "from_trip_id": arc.from_trip_id,
                "to_trip_id": arc.to_trip_id,
                "vehicle_type": arc.vehicle_type,
                "deadhead_time_min": arc.deadhead_time_min,
                "deadhead_distance_km": _estimate_deadhead_distance_km(arc.deadhead_time_min),
                "turnaround_time_min": arc.turnaround_time_min,
                "slack_min": arc.slack_min,
                "idle_time_min": max(0, arc.slack_min),
                "feasible": arc.feasible,
                "reason_code": arc.reason_code,
                "reason": arc.reason,
            }
        )

    return {
        "trips": [trip_to_dict(t) for t in trips],
        "arcs": serialized_arcs,
        "total_arcs": len(serialized_arcs),
        "feasible_arcs": feasible_count,
        "infeasible_arcs": len(serialized_arcs) - feasible_count,
        "reason_counts": reason_counts,
    }
