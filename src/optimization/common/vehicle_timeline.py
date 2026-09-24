"""Continuous physical timeline for fixed dispatch decisions with daily returns.

The selected duties and timetable remain unchanged. Every depot visit is backed
by a travel event, and only complete stationary slots permit charging/refueling.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.dispatch.daily_return import checked_deadhead_minutes, requires_daily_return
from src.dispatch.feasibility import FeasibilityEngine

from .soc_helpers import (
    deadhead_distance_km, deadhead_energy_from_minutes_kwh,
    horizon_start_min, is_electric_vehicle, trip_energy_kwh,
)


@dataclass(frozen=True)
class VehicleEvent:
    vehicle_id: str
    event_type: str
    start_min: int
    end_min: int
    start_location: str
    end_location: str
    energy_kwh: float = 0.0
    fuel_l: float = 0.0
    trip_id: str = ""
    distance_km: float = 0.0


def _trip_fuel(vehicle: Any, trip: Any) -> float:
    quantities = dict(getattr(trip, "fuel_l_by_vehicle_type", {}) or {})
    for key in (str(vehicle.vehicle_type), str(vehicle.vehicle_type).upper(), "ICE"):
        if key in quantities:
            return float(quantities[key])
    rate = float(getattr(vehicle, "fuel_consumption_l_per_km", 0.0) or 0.0)
    return float(trip.distance_km) * rate if rate > 0 else float(trip.fuel_l)


def connection_energy_events(problem: Any, vehicle: Any, previous: Any, following: Any) -> tuple[tuple[int, float], ...]:
    """Movement-end minutes and energy under the daily-return timeline policy.

    Keep return and outbound consumption separate: posting both at the next
    departure can falsely exceed the SOC ceiling during overnight charging.
    Zero-duration legs retain zero energy to preserve the two-leg structure.
    """
    context = problem.dispatch_context
    home = str(vehicle.home_depot_id)
    ready = int(previous.arrival_min) + context.get_turnaround_min(previous.destination)
    if requires_daily_return(context, previous, following):
        returning = checked_deadhead_minutes(context, previous.destination, home)
        outbound = checked_deadhead_minutes(context, home, following.origin)
        return (
            (ready + returning, deadhead_energy_from_minutes_kwh(problem, vehicle, previous, returning)),
            (int(following.departure_min), deadhead_energy_from_minutes_kwh(problem, vehicle, following, outbound)),
        )
    duration = checked_deadhead_minutes(context, previous.destination, following.origin)
    end = int(following.departure_min) if context.locations_equivalent(previous.destination, home) else ready + duration
    return ((end, deadhead_energy_from_minutes_kwh(problem, vehicle, previous, duration)),)


def build_vehicle_timeline(problem: Any, plan: Any) -> dict[str, tuple[VehicleEvent, ...]]:
    """Materialize native duty boundaries and mandatory daily depot visits."""
    context = problem.dispatch_context
    depot = str(getattr(context, "daily_return_depot_id", "") or "")
    if not depot:
        raise ValueError("A continuous daily-return timeline requires an explicit depot")
    vehicles = {vehicle.vehicle_id: vehicle for vehicle in problem.vehicles}
    trips = problem.trip_by_id()
    dispatch_trips = context.trips_by_id()
    start = horizon_start_min(problem)
    stop = start + int(problem.scenario.planning_days) * 1440
    if (problem.metadata or {}).get("bev_soc_deadline_mode") == "next_morning_operational_max":
        stop = start + len(problem.price_slots) * int(problem.scenario.timestep_min)
    result = {}
    checker = FeasibilityEngine()
    for vehicle_id, duties in plan.duties_by_vehicle().items():
        vehicle = vehicles[vehicle_id]
        home = str(vehicle.home_depot_id)
        if not context.locations_equivalent(home, depot):
            raise ValueError(f"Daily-return depot disagrees with vehicle home: {vehicle_id}")
        electric = is_electric_vehicle(problem, vehicle)
        events: list[VehicleEvent] = []

        def stationary(kind: str, begin: int, end: int, location: str) -> None:
            if end < begin:
                raise ValueError(f"Negative {kind} interval for {vehicle_id}: {begin}..{end}")
            if end > begin:
                events.append(VehicleEvent(vehicle_id, kind, begin, end, location, location))

        def movement(kind: str, begin: int, origin: str, destination: str, reference: Any) -> int:
            minutes = checked_deadhead_minutes(context, origin, destination)
            distance = deadhead_distance_km(problem, minutes)
            energy = deadhead_energy_from_minutes_kwh(problem, vehicle, reference, minutes)
            rate = float(getattr(vehicle, "fuel_consumption_l_per_km", 0.0) or 0.0)
            if not electric and distance > 0 and rate <= 0:
                raise ValueError(f"ICE movement has no positive fuel rate: {vehicle_id}")
            if minutes:
                events.append(VehicleEvent(vehicle_id, kind, begin, begin + minutes,
                                           origin, destination, energy, 0.0 if electric else distance * rate,
                                           distance_km=distance))
            return begin + minutes

        path = [(duty.duty_id, trips[leg.trip.trip_id]) for duty in duties for leg in duty.legs]
        path.sort(key=lambda item: (int(item[1].departure_min), str(item[1].trip_id)))
        previous = None
        previous_duty = None
        for duty_id, trip in path:
            dep, arr = int(trip.departure_min), int(trip.arrival_min)
            origin, destination = str(trip.origin), str(trip.destination)
            if arr <= dep:
                raise ValueError(f"Invalid absolute trip interval: {trip.trip_id}")
            if previous is None:
                leave = dep - checked_deadhead_minutes(context, home, origin)
                stationary("waiting", start, leave, home)
                movement("startup_deadhead", leave, home, origin, trip)
            else:
                ready = int(previous.arrival_min) + context.get_turnaround_min(previous.destination)
                stationary("turnaround", int(previous.arrival_min), ready, previous.destination)
                via_home = duty_id != previous_duty or requires_daily_return(context, previous, trip)
                if via_home:
                    home_arrival = movement("daily_return", ready, previous.destination, home, previous)
                    leave = dep - checked_deadhead_minutes(context, home, origin)
                    stationary("waiting", home_arrival, leave, home)
                    movement("daily_startup", leave, home, origin, trip)
                else:
                    check = checker.can_connect(dispatch_trips[previous.trip_id], dispatch_trips[trip.trip_id],
                                                context, str(vehicle.vehicle_type))
                    if not check.feasible:
                        raise ValueError(f"Infeasible native connection: {previous.trip_id}->{trip.trip_id}: {check.reason_code}")
                    duration = checked_deadhead_minutes(context, previous.destination, origin)
                    begin = dep - duration if context.locations_equivalent(previous.destination, home) else ready
                    stationary("waiting", ready, begin, previous.destination)
                    arrived = movement("connection_deadhead", begin, previous.destination, origin, previous)
                    stationary("waiting", arrived, dep, origin)
            events.append(VehicleEvent(vehicle_id, "service_trip", dep, arr, origin, destination,
                                       trip_energy_kwh(problem, vehicle, trip) if electric else 0.0,
                                       0.0 if electric else _trip_fuel(vehicle, trip), str(trip.trip_id),
                                       float(trip.distance_km)))
            previous, previous_duty = trip, duty_id
        if previous is not None:
            ready = int(previous.arrival_min) + context.get_turnaround_min(previous.destination)
            stationary("turnaround", int(previous.arrival_min), ready, previous.destination)
            arrived = movement("terminal_return", ready, previous.destination, home, previous)
            stationary("waiting", arrived, stop, home)
        result[vehicle_id] = tuple(events)
    return result


def complete_home_slots(problem: Any, vehicle: Any, events: tuple[VehicleEvent, ...]) -> frozenset[int]:
    """A slot is eligible only if the bus is home for its entire duration."""
    start = horizon_start_min(problem)
    step = int(problem.scenario.timestep_min)
    slots = set()
    for event in events:
        if event.event_type != "waiting" or not problem.dispatch_context.locations_equivalent(event.start_location, vehicle.home_depot_id):
            continue
        first = max(0, (event.start_min - start + step - 1) // step)
        end = (event.end_min - start) // step
        slots.update(range(first, end))
    return frozenset(slots)


def fixed_path_soc_target_slots(problem: Any, events: tuple[VehicleEvent, ...]) -> dict[int, int]:
    """End-of-slot SOC deadlines before the next morning's outbound movement.

    A depot departure can precede the first service trip. Requiring the operating
    maximum after consuming outbound energy makes a physically valid full bus
    infeasible. Use the last complete charging slot before departure, never
    extend the declared deadline. The final paid horizon remains unchanged.
    """
    deadlines = (problem.metadata or {}).get("post_return_target_slots")
    if not isinstance(deadlines, (list, tuple)):
        return {}
    start = horizon_start_min(problem)
    step = int(problem.scenario.timestep_min)
    served = {(event.start_min-start)//1440 for event in events if event.event_type == "service_trip"}
    result = {}
    for day in served:
        if not 0 <= day < len(deadlines):
            raise ValueError("NEXT_MORNING_TARGET_SLOT_MISSING")
        slot = int(deadlines[day])
        next_services = [event for event in events if event.event_type == "service_trip"
                         and (event.start_min-start)//1440 == day+1]
        if next_services:
            first = min(next_services, key=lambda event: event.start_min)
            leave = first.start_min
            for event in events:
                if event.event_type in {"daily_startup", "startup_deadhead"} and event.end_min == first.start_min:
                    leave = min(leave, event.start_min)
            slot = min(slot, (leave-start)//step-1)
        if slot < 0:
            raise ValueError("NEXT_MORNING_NO_PREDEPARTURE_SLOT")
        result[day] = slot
    return result


@dataclass(frozen=True)
class FixedPathSlotLoads:
    energy_kwh: dict[tuple[str, int], float]
    service_active: dict[str, set[int]]
    movement_active: dict[str, set[int]]
    home_slots: dict[str, set[int]]
    energy_before_departure: dict[tuple[str, str], float]


def fixed_path_slot_loads(problem: Any, plan: Any, slot_indices: list[int]) -> FixedPathSlotLoads:
    """Post return consumption before any later home charging can supply it."""
    timelines = build_vehicle_timeline(problem, plan)
    start = horizon_start_min(problem)
    step = int(problem.scenario.timestep_min)
    energy, service, movement, home, departure = {}, {}, {}, {}, {}
    for vehicle in problem.vehicles:
        vehicle_id = str(vehicle.vehicle_id)
        if not is_electric_vehicle(problem, vehicle) or vehicle_id not in timelines:
            continue
        events = timelines[vehicle_id]
        service[vehicle_id], movement[vehicle_id] = set(), set()
        home[vehicle_id] = set(complete_home_slots(problem, vehicle, events)).intersection(slot_indices)
        pending_movement = None
        for event in events:
            if event.event_type in {"waiting", "turnaround"}:
                continue
            occupied = {slot for slot in slot_indices if start + (slot + 1) * step > event.start_min
                        and start + slot * step < event.end_min}
            if event.event_type == "service_trip":
                service[vehicle_id].update(occupied)
                for slot in occupied:
                    overlap = min(start + (slot + 1) * step, event.end_min) - max(start + slot * step, event.start_min)
                    key = (vehicle_id, slot)
                    energy[key] = energy.get(key, 0.0) + event.energy_kwh * overlap / (event.end_min - event.start_min)
                dep_slot = (event.start_min - start) // step
                if pending_movement is not None:
                    posting, kwh = pending_movement
                    if posting == dep_slot and posting in slot_indices:
                        departure[(vehicle_id, event.trip_id)] = kwh
                pending_movement = None
            else:
                movement[vehicle_id].update(occupied)
                posting = (event.end_min - start + step - 1) // step - 1
                if posting in slot_indices:
                    key = (vehicle_id, posting)
                    energy[key] = energy.get(key, 0.0) + event.energy_kwh
                pending_movement = (posting, event.energy_kwh)
    return FixedPathSlotLoads(energy, service, movement, home, departure)
