"""Engine-bus refueling policies for daily-return fixed paths.

``no_refueling`` (default, unchanged): the materialized initial liters minus the
reserve are one budget for the whole horizon.

``depot_top_up``: the home depot has a refueling facility. A bus refuels only
while it is home for a complete slot (the same slots that permit charging), so
refueling never adds a movement. Fuel stays between the reserve
(``fuel_reserve_l``) and the tank capacity. The refueling decisions follow one
deterministic rule from the fixed paths, not a post-solve repair: at each home
residence, when the fuel left on reaching the next refueling opportunity would
fall below the reserve, the bus is filled to the tank capacity in the last
complete home slot of that residence. A path that needs more than one tank
between two opportunities is infeasible and raises.
"""
from __future__ import annotations

from typing import Any

from .problem import RefuelSlot
from .soc_helpers import horizon_start_min
from .vehicle_timeline import build_vehicle_timeline, complete_home_slots

NO_REFUELING = "no_refueling"
DEPOT_TOP_UP = "depot_top_up"
POLICIES = (NO_REFUELING, DEPOT_TOP_UP)
TOLERANCE_L = 1e-6


def ice_refueling_policy(problem: Any) -> str:
    policy = str((problem.metadata or {}).get("ice_refueling_policy") or NO_REFUELING)
    if policy not in POLICIES:
        raise ValueError(f"Unsupported ice_refueling_policy: {policy!r}")
    return policy


def is_engine_vehicle(vehicle: Any) -> bool:
    return str(vehicle.vehicle_type).upper() not in {"BEV", "PHEV", "FCEV"}


def depot_top_up_refuel_slots(problem: Any, plan: Any) -> tuple[RefuelSlot, ...]:
    """Refueling decisions of the depot_top_up rule over the whole horizon."""
    start = horizon_start_min(problem)
    step = int(problem.scenario.timestep_min)
    vehicles = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
    slots: list[RefuelSlot] = []
    for vehicle_id, events in build_vehicle_timeline(problem, plan).items():
        vehicle = vehicles[str(vehicle_id)]
        if not is_engine_vehicle(vehicle):
            continue
        capacity = float(vehicle.fuel_tank_capacity_l or 0.0)
        reserve = float(vehicle.fuel_reserve_l or 0.0)
        fuel = float(vehicle.initial_fuel_l if vehicle.initial_fuel_l is not None else capacity)
        if capacity <= 0.0 or not reserve - TOLERANCE_L <= fuel <= capacity + TOLERANCE_L:
            raise ValueError(f"Invalid ICE fuel inventory for depot_top_up: {vehicle_id}")
        home = complete_home_slots(problem, vehicle, events)
        # One opportunity per home residence: its last complete home slot.
        opportunities = []
        for event in events:
            if event.event_type != "waiting":
                continue
            inside = [slot for slot in home
                      if event.start_min <= start + slot * step and start + (slot + 1) * step <= event.end_min]
            if inside:
                opportunities.append(max(inside))
        opportunities = sorted(set(opportunities))
        consumption = sorted((int(event.end_min), float(event.fuel_l)) for event in events if event.fuel_l > 0.0)
        bounds = [start + (slot + 1) * step for slot in opportunities] + [float("inf")]
        before_first = sum(liters for minute, liters in consumption if minute <= bounds[0])
        if fuel - before_first < reserve - TOLERANCE_L:
            raise ValueError(f"ICE fuel falls below the reserve before the first depot refuel: {vehicle_id}")
        fuel -= before_first
        for index, slot in enumerate(opportunities):
            need = sum(liters for minute, liters in consumption if bounds[index] < minute <= bounds[index + 1])
            if need > capacity - reserve + TOLERANCE_L:
                raise ValueError(
                    f"ICE path needs {need:.3f} L between depot refuels, above the usable tank "
                    f"{capacity - reserve:.3f} L: {vehicle_id}")
            if fuel - need < reserve - TOLERANCE_L:
                slots.append(RefuelSlot(vehicle_id=str(vehicle_id), slot_index=int(slot),
                                        refuel_liters=capacity - fuel,
                                        location_id=str(vehicle.home_depot_id)))
                fuel = capacity
            fuel -= need
    return tuple(sorted(slots, key=lambda item: (item.vehicle_id, item.slot_index)))


def replay_fixed_ice_fuel(problem: Any, plan: Any, first_slot: int, stop_slot: int) -> dict[str, Any]:
    """Replay consumption and refuels inside [first_slot, stop_slot) from each bus's state.

    The vehicle's ``initial_fuel_l`` is its state at the window start (rolling
    locks it from the executed chain). Movement fuel is posted at the movement
    end and prorated at the window edges; a refuel is posted at its slot end.
    """
    start = horizon_start_min(problem)
    step = int(problem.scenario.timestep_min)
    lower, upper = start + first_slot * step, start + stop_slot * step
    vehicles = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
    timelines = build_vehicle_timeline(problem, plan)
    result: dict[str, Any] = {"vehicles": {}, "violations": []}
    refuels_by_vehicle: dict[str, list[Any]] = {}
    for refuel in plan.refuel_slots:
        refuels_by_vehicle.setdefault(str(refuel.vehicle_id), []).append(refuel)
    for vehicle_id, vehicle in vehicles.items():
        if not is_engine_vehicle(vehicle) or not vehicle.available:
            continue
        events = timelines.get(vehicle_id, ())
        refuels = refuels_by_vehicle.get(vehicle_id, [])
        if not events and not refuels:
            continue
        if not events:
            result["violations"].append(f"{vehicle_id}:refuels_without_a_path")
            continue
        capacity = float(vehicle.fuel_tank_capacity_l or 0.0)
        reserve = float(vehicle.fuel_reserve_l or 0.0)
        fuel = float(vehicle.initial_fuel_l or 0.0)
        home = complete_home_slots(problem, vehicle, events)
        changes = []
        for event in events:
            if event.fuel_l <= 0.0 or event.end_min <= event.start_min:
                continue
            overlap = max(0, min(event.end_min, upper) - max(event.start_min, lower))
            if overlap:
                changes.append((min(event.end_min, upper), -event.fuel_l * overlap / (event.end_min - event.start_min)))
        refueled = 0.0
        for refuel in refuels:
            if not first_slot <= int(refuel.slot_index) < stop_slot:
                continue
            if int(refuel.slot_index) not in home:
                result["violations"].append(f"{vehicle_id}:refuel_outside_a_complete_home_slot:{refuel.slot_index}")
            changes.append((start + (int(refuel.slot_index) + 1) * step, float(refuel.refuel_liters)))
            refueled += float(refuel.refuel_liters)
        lowest, highest, consumed = fuel, fuel, 0.0
        for _minute, change in sorted(changes):
            fuel += change
            consumed += max(-change, 0.0)
            lowest, highest = min(lowest, fuel), max(highest, fuel)
        if lowest < reserve - TOLERANCE_L or highest > capacity + TOLERANCE_L:
            result["violations"].append(
                f"{vehicle_id}:fuel_range={lowest:.6f}..{highest:.6f}:bounds={reserve}..{capacity}")
        result["vehicles"][vehicle_id] = {
            "initial_fuel_l": float(vehicle.initial_fuel_l or 0.0), "reserve_fuel_l": reserve,
            "tank_capacity_l": capacity, "consumed_fuel_l": consumed, "refueled_l": refueled,
            "minimum_fuel_l": lowest, "terminal_fuel_l": fuel,
        }
    return result
