"""Vehicle location and liquid-fuel state from only the executed prefix."""
from __future__ import annotations

from dataclasses import asdict
import math
from typing import Any, Mapping

from src.optimization.common.soc_helpers import horizon_start_min, is_electric_vehicle
from src.optimization.common.vehicle_timeline import build_vehicle_timeline


def vehicle_positions_at(problem: Any, plan: Any, boundary_min: int) -> dict[str, dict]:
    """Do not report an event starting at the boundary as already executed."""
    timelines = build_vehicle_timeline(problem, plan)
    positions = {}
    for vehicle in problem.vehicles:
        events = timelines.get(str(vehicle.vehicle_id), ())
        location = str(vehicle.home_depot_id)
        motion = None
        for event in events:
            if event.event_type in {"waiting", "turnaround"}:
                continue
            if event.end_min <= boundary_min:
                location = event.end_location
            elif event.start_min < boundary_min < event.end_min:
                motion = {key:value for key,value in asdict(event).items()
                          if key in ("event_type","start_min","end_min","start_location","end_location","trip_id")}
                motion.update(elapsed_minutes=boundary_min-event.start_min,
                              remaining_minutes=event.end_min-boundary_min)
                location = None
                break
        positions[str(vehicle.vehicle_id)] = {"location_id":location,"in_progress_event":motion}
    return positions


def advance_vehicle_prefix(problem: Any, plan: Any, *, start_min: int, stop_min: int,
                           prior_fuel_l: Mapping[str, float] | None = None) -> tuple[dict, dict, dict, dict]:
    timelines = build_vehicle_timeline(problem, plan)
    fuel = {}
    first_boundary = horizon_start_min(problem)
    step = int(problem.scenario.timestep_min)
    for vehicle in problem.vehicles:
        vid = str(vehicle.vehicle_id)
        if is_electric_vehicle(problem, vehicle):
            continue
        if start_min > first_boundary and vid not in (prior_fuel_l or {}):
            raise ValueError(f"Executed fuel handoff is missing vehicle {vid}")
        value = float((prior_fuel_l or {}).get(vid, vehicle.initial_fuel_l))
        capacity = float(vehicle.fuel_tank_capacity_l or 0.0)
        minimum = float(vehicle.fuel_reserve_l or 0.0)
        if not math.isfinite(value) or not minimum <= value <= capacity or capacity <= 0:
            raise ValueError(f"Invalid executed fuel start for {vid}")
        changes = []
        for event in timelines.get(vid, ()):
            overlap = max(0, min(event.end_min,stop_min)-max(event.start_min,start_min))
            if overlap and event.fuel_l:
                changes.append((min(event.end_min,stop_min), -event.fuel_l*overlap/(event.end_min-event.start_min)))
        for refuel in plan.refuel_slots:
            end = first_boundary + (int(refuel.slot_index)+1)*step
            if refuel.vehicle_id == vid and start_min < end <= stop_min:
                changes.append((end,float(refuel.refuel_liters)))
        for _, delta in sorted(changes):
            value += delta
            if not minimum-1e-6 <= value <= capacity+1e-6:
                raise ValueError(f"Executed fuel inventory violated for {vid}: {value}")
        fuel[vid] = value
    positions = vehicle_positions_at(problem, plan, stop_min)
    unfinished = {vid:row["in_progress_event"] for vid,row in positions.items() if row["in_progress_event"] is not None}
    last_slot = (stop_min-first_boundary)//step-1
    connected = {}
    for charge in plan.charging_slots:
        if charge.slot_index != last_slot or charge.charge_kw <= 1e-9:
            continue
        if not charge.charger_id:
            raise ValueError("Executed charging has no physical charger id")
        prior = connected.setdefault(str(charge.vehicle_id),str(charge.charger_id))
        if prior != str(charge.charger_id):
            raise ValueError("One vehicle is connected to multiple physical chargers")
    return fuel,positions,unfinished,connected
