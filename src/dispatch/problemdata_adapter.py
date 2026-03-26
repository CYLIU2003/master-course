"""
src/dispatch/problemdata_adapter.py

Adapter utilities that bridge legacy ProblemData tasks into the
timetable-first dispatch pipeline.
"""

from __future__ import annotations

import math
import unicodedata
from dataclasses import dataclass

from src.data_schema import ProblemData, TravelConnection
from src.route_family_runtime import DeadheadMetric

from .models import DeadheadRule, DispatchContext, Trip, TurnaroundRule, VehicleProfile
from .pipeline import TimetableDispatchPipeline


@dataclass(frozen=True)
class DispatchTravelBuildReport:
    service_date: str
    vehicle_types: tuple[str, ...]
    trip_count: int
    edge_count: int
    generated_connections: int
    warnings: tuple[str, ...]


def _minutes_to_hhmm(total_minutes: int) -> str:
    hours = total_minutes // 60
    mins = total_minutes % 60
    return f"{hours:02d}:{mins:02d}"


def _normalize_vehicle_type(raw: str) -> str:
    text = str(raw).strip().upper()
    if text in ("BEV", "EV", "EV_BUS"):
        return "BEV"
    if text in ("ICE", "ENGINE", "ENGINE_BUS", "DIESEL"):
        return "ICE"
    if "BEV" in text or text.startswith("EV"):
        return "BEV"
    if "ICE" in text or "ENGINE" in text or "DIESEL" in text:
        return "ICE"
    return "BEV"


def _normalize_terminal_label(raw: str) -> str:
    return unicodedata.normalize("NFKC", str(raw or "")).strip().lower()


def _hhmm_to_minutes(raw: str) -> int:
    text = str(raw or "00:00").strip()
    parts = text.split(":", 1)
    try:
        hh = int(parts[0])
        mm = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError):
        return 0
    if hh < 0:
        hh = 0
    if mm < 0:
        mm = 0
    return hh * 60 + mm


def _allowed_vehicle_types(required_vehicle_type: str | None) -> tuple[str, ...]:
    if required_vehicle_type is None or str(required_vehicle_type).strip() == "":
        return ("BEV", "ICE")
    vtype = _normalize_vehicle_type(str(required_vehicle_type))
    return (vtype,)


def _build_vehicle_profiles(data: ProblemData) -> dict[str, VehicleProfile]:
    profiles: dict[str, VehicleProfile] = {}

    for vehicle in data.vehicles:
        vehicle_type = _normalize_vehicle_type(vehicle.vehicle_type)
        if vehicle_type == "BEV":
            if vehicle_type in profiles:
                continue
            profiles[vehicle_type] = VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=vehicle.battery_capacity or 300.0,
                energy_consumption_kwh_per_km=1.0,
            )
            continue

        if vehicle_type in profiles:
            continue
        profiles[vehicle_type] = VehicleProfile(
            vehicle_type="ICE",
            fuel_tank_capacity_l=vehicle.fuel_tank_capacity or 150.0,
            fuel_consumption_l_per_km=0.2,
        )

    if not profiles:
        profiles["BEV"] = VehicleProfile(
            vehicle_type="BEV",
            battery_capacity_kwh=300.0,
            energy_consumption_kwh_per_km=1.0,
        )
    return profiles


def _build_dispatch_context_from_problem_data(
    data: ProblemData,
    service_date: str,
    default_turnaround_min: int,
    turnaround_rules: dict[str, int] | None,
    deadhead_rules: dict[tuple[str, str], int] | None,
) -> DispatchContext:
    slot_minutes = max(1, int(round(data.delta_t_hour * 60.0)))

    trips: list[Trip] = []
    for task in data.tasks:
        dep_min = int(task.start_time_idx) * slot_minutes
        arr_min = int(task.end_time_idx) * slot_minutes
        if arr_min < dep_min:
            arr_min = dep_min

        trips.append(
            Trip(
                trip_id=task.task_id,
                route_id="task",
                origin=task.origin,
                destination=task.destination,
                departure_time=_minutes_to_hhmm(dep_min),
                arrival_time=_minutes_to_hhmm(arr_min),
                distance_km=task.distance_km,
                allowed_vehicle_types=_allowed_vehicle_types(
                    task.required_vehicle_type
                ),
                origin_stop_id=str(getattr(task, "origin_stop_id", None) or ""),
                destination_stop_id=str(getattr(task, "destination_stop_id", None) or ""),
                route_family_code=str(getattr(task, "route_family_code", None) or ""),
                direction=str(getattr(task, "direction", None) or ""),
                route_variant_type=str(getattr(task, "route_variant_type", None) or ""),
            )
        )

    turn_rules = {
        stop_id: TurnaroundRule(stop_id=stop_id, min_turnaround_min=max(0, int(mins)))
        for stop_id, mins in (turnaround_rules or {}).items()
    }
    dh_rules = {
        (from_stop, to_stop): DeadheadRule(
            from_stop=from_stop,
            to_stop=to_stop,
            travel_time_min=max(1, int(mins)),
        )
        for (from_stop, to_stop), mins in (deadhead_rules or {}).items()
        if from_stop != to_stop
    }

    profiles = _build_vehicle_profiles(data)
    return DispatchContext(
        service_date=service_date,
        trips=trips,
        turnaround_rules=turn_rules,
        deadhead_rules=dh_rules,
        vehicle_profiles=profiles,
        default_turnaround_min=max(0, int(default_turnaround_min)),
    )


def build_travel_connections_via_dispatch(
    data: ProblemData,
    service_date: str,
    default_turnaround_min: int = 10,
    turnaround_rules: dict[str, int] | None = None,
    deadhead_rules: dict[tuple[str, str], int] | None = None,
    deadhead_metrics: dict[tuple[str, str], DeadheadMetric] | None = None,
) -> tuple[list[TravelConnection], DispatchTravelBuildReport]:
    """
    Build full TravelConnection matrix from dispatch feasibility graph.

    The returned list includes every ordered task pair (r1, r2), r1 != r2.
    """
    context = _build_dispatch_context_from_problem_data(
        data=data,
        service_date=service_date,
        default_turnaround_min=default_turnaround_min,
        turnaround_rules=turnaround_rules,
        deadhead_rules=deadhead_rules,
    )

    pipeline = TimetableDispatchPipeline()
    vehicle_types = sorted(context.vehicle_profiles.keys())
    feasible_edges: set[tuple[str, str]] = set()
    warnings: list[str] = []

    for vehicle_type in vehicle_types:
        result = pipeline.run(context, vehicle_type=vehicle_type)
        for from_trip, successors in result.graph.items():
            for to_trip in successors:
                feasible_edges.add((from_trip, to_trip))
        warnings.extend([f"[{vehicle_type}] {w}" for w in result.warnings])

    # Fallback: if dispatch graph is empty, allow only same-terminal handoffs
    # (normalized terminal label match) with no deadhead assumption.
    # This keeps the fallback conservative and avoids introducing arbitrary moves.
    if not feasible_edges and context.trips:
        fallback_edges: set[tuple[str, str]] = set()
        for vehicle_type in vehicle_types:
            for from_trip in context.trips:
                if vehicle_type not in from_trip.allowed_vehicle_types:
                    continue
                from_terminal = _normalize_terminal_label(
                    from_trip.destination_stop_id or from_trip.destination
                )
                if not from_terminal:
                    continue
                from_ready_min = (
                    _hhmm_to_minutes(from_trip.arrival_time)
                    + context.get_turnaround_min(from_trip.destination_stop_id or from_trip.destination)
                )
                for to_trip in context.trips:
                    if from_trip.trip_id == to_trip.trip_id:
                        continue
                    if vehicle_type not in to_trip.allowed_vehicle_types:
                        continue
                    to_terminal = _normalize_terminal_label(
                        to_trip.origin_stop_id or to_trip.origin
                    )
                    if from_terminal != to_terminal:
                        continue
                    if from_ready_min <= _hhmm_to_minutes(to_trip.departure_time):
                        fallback_edges.add((from_trip.trip_id, to_trip.trip_id))
        if fallback_edges:
            feasible_edges = fallback_edges
            warnings.append(
                "[fallback] dispatch graph was empty; generated same-terminal continuity edges only."
            )

    slot_minutes = max(1, int(round(data.delta_t_hour * 60.0)))
    trip_by_id = {trip.trip_id: trip for trip in context.trips}

    travel_connections: list[TravelConnection] = []
    for from_trip in context.trips:
        for to_trip in context.trips:
            if from_trip.trip_id == to_trip.trip_id:
                continue

            can_follow = (from_trip.trip_id, to_trip.trip_id) in feasible_edges
            if not can_follow:
                continue

            from_stop = from_trip.destination_stop_id or from_trip.destination
            to_stop = to_trip.origin_stop_id or to_trip.origin
            deadhead_min = context.get_deadhead_min(from_stop, to_stop)
            deadhead_slots = int(math.ceil(deadhead_min / slot_minutes))
            deadhead_distance_km = float(
                (
                    deadhead_metrics or {}
                ).get((from_stop, to_stop), DeadheadMetric(from_stop, to_stop, deadhead_min)).distance_km
            )

            # Store only feasible edges. Infeasible pairs are treated as missing
            # downstream, which avoids O(n^2) connection payloads for large scopes.
            travel_connections.append(
                TravelConnection(
                    from_task_id=from_trip.trip_id,
                    to_task_id=to_trip.trip_id,
                    can_follow=True,
                    deadhead_time_slot=deadhead_slots,
                    deadhead_distance_km=deadhead_distance_km,
                    deadhead_energy_kwh=0.0,
                )
            )

    report = DispatchTravelBuildReport(
        service_date=service_date,
        vehicle_types=tuple(vehicle_types),
        trip_count=len(trip_by_id),
        edge_count=len(feasible_edges),
        generated_connections=len(travel_connections),
        warnings=tuple(warnings),
    )
    return travel_connections, report
