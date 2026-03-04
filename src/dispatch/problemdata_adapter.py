"""
src/dispatch/problemdata_adapter.py

Adapter utilities that bridge legacy ProblemData tasks into the
timetable-first dispatch pipeline.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from src.data_schema import ProblemData, TravelConnection

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

    slot_minutes = max(1, int(round(data.delta_t_hour * 60.0)))
    trip_by_id = {trip.trip_id: trip for trip in context.trips}

    travel_connections: list[TravelConnection] = []
    for from_trip in context.trips:
        for to_trip in context.trips:
            if from_trip.trip_id == to_trip.trip_id:
                continue

            can_follow = (from_trip.trip_id, to_trip.trip_id) in feasible_edges
            if can_follow:
                deadhead_min = context.get_deadhead_min(
                    from_trip.destination,
                    to_trip.origin,
                )
                deadhead_slots = int(math.ceil(deadhead_min / slot_minutes))
            else:
                deadhead_slots = 0

            travel_connections.append(
                TravelConnection(
                    from_task_id=from_trip.trip_id,
                    to_task_id=to_trip.trip_id,
                    can_follow=can_follow,
                    deadhead_time_slot=deadhead_slots,
                    deadhead_distance_km=0.0,
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
