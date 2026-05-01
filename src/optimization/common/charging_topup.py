from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Any, DefaultDict, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple

from .problem import AssignmentPlan, CanonicalOptimizationProblem, ChargingSlot, day_index_for_minute
from .soc_helpers import (
    day_start_min,
    effective_final_soc_target_kwh,
    horizon_start_min,
    is_electric_vehicle,
    percent_like_to_ratio,
    post_return_target_slot_index,
    return_deadhead_energy_kwh,
    return_deadhead_min_to_home,
    slot_index,
    slot_index_ceil,
    trip_active_slot_indices,
    trip_energy_kwh,
    trip_slot_energy_fraction,
    deadhead_energy_kwh,
    vehicle_capacity_kwh,
    vehicle_initial_soc_kwh,
)


def apply_opportunistic_topup(
    problem: CanonicalOptimizationProblem,
    plan: AssignmentPlan,
) -> AssignmentPlan:
    """Add best-effort depot waiting charges up to the configured SOC upper buffer.

    Existing charging slots are preserved. If new opportunistic slots are added,
    the stale depot flow maps are cleared so the evaluator re-derives realized
    electricity, PV, grid, and demand quantities from charging slots.
    """

    timestep_min = max(int(problem.scenario.timestep_min or 1), 1)
    timestep_h = timestep_min / 60.0
    slots_per_day = max(1, (24 * 60) // timestep_min)
    horizon_start = horizon_start_min(problem)
    planning_days = max(int(problem.scenario.planning_days or 1), 1)

    upper_buffer_ratio = percent_like_to_ratio((problem.metadata or {}).get("charge_upper_buffer_ratio"))
    if upper_buffer_ratio is None:
        upper_buffer_ratio = 0.9
    upper_buffer_ratio = min(max(float(upper_buffer_ratio or 0.0), 0.0), 1.0)

    vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
    if not vehicle_by_id or not problem.chargers or upper_buffer_ratio <= 0.0:
        return _with_topup_metadata(
            plan,
            charge_upper_buffer_ratio=upper_buffer_ratio,
            added_slot_count=0,
            added_kwh=0.0,
            unfilled_by_vehicle_day={},
            skipped_vehicle_days=(),
        )

    trip_by_id = problem.trip_by_id()
    depot_chargers_by_id: Dict[str, Tuple[Any, ...]] = {}
    chargers_by_depot: Dict[str, List[Any]] = defaultdict(list)
    for charger in problem.chargers:
        depot_id = str(getattr(charger, "depot_id", "") or "depot_default")
        chargers_by_depot[depot_id].append(charger)
    for depot_id, chargers in chargers_by_depot.items():
        depot_chargers_by_id[depot_id] = tuple(chargers)

    electric_vehicle_ids = {
        vehicle_id
        for vehicle_id, vehicle in vehicle_by_id.items()
        if bool(getattr(vehicle, "available", True)) and is_electric_vehicle(problem, vehicle)
    }
    if not electric_vehicle_ids:
        return _with_topup_metadata(
            plan,
            charge_upper_buffer_ratio=upper_buffer_ratio,
            added_slot_count=0,
            added_kwh=0.0,
            unfilled_by_vehicle_day={},
            skipped_vehicle_days=(),
        )

    vehicle_type_by_id = {vehicle.vehicle_id: str(vehicle.vehicle_type or "").upper() for vehicle in problem.vehicles}
    vehicle_day_last_duty: Dict[Tuple[str, int], Any] = {}
    for duty in plan.duties:
        vehicle_id = str(plan.vehicle_id_for_duty(duty.duty_id) or duty.duty_id)
        if vehicle_id not in electric_vehicle_ids or not duty.legs:
            continue
        day_idx = day_index_for_minute(int(duty.legs[-1].trip.departure_min), horizon_start)
        key = (vehicle_id, day_idx)
        incumbent = vehicle_day_last_duty.get(key)
        if incumbent is None:
            vehicle_day_last_duty[key] = duty
            continue
        incumbent_end = int(incumbent.legs[-1].trip.arrival_min) if incumbent.legs else -1
        current_end = int(duty.legs[-1].trip.arrival_min)
        if current_end >= incumbent_end:
            vehicle_day_last_duty[key] = duty

    existing_charge_events: DefaultDict[Tuple[str, int], float] = defaultdict(float)
    slot_port_usage: DefaultDict[Tuple[str, int], int] = defaultdict(int)
    slot_kw_usage: DefaultDict[Tuple[str, int], float] = defaultdict(float)
    for slot in plan.charging_slots:
        vehicle_id = str(slot.vehicle_id)
        if vehicle_id not in vehicle_by_id:
            continue
        depot_id = str(getattr(slot, "charging_depot_id", None) or vehicle_by_id[vehicle_id].home_depot_id or "depot_default")
        charge_kw = max(float(getattr(slot, "charge_kw", 0.0) or 0.0) - max(float(getattr(slot, "discharge_kw", 0.0) or 0.0), 0.0), 0.0)
        if charge_kw <= 0.0:
            continue
        usage_key = (depot_id, int(slot.slot_index))
        existing_charge_events[(vehicle_id, int(slot.slot_index))] += charge_kw * timestep_h
        slot_port_usage[usage_key] += 1
        slot_kw_usage[usage_key] += charge_kw

    trip_energy_by_vehicle_slot: DefaultDict[Tuple[str, int], float] = defaultdict(float)
    deadhead_energy_by_vehicle_slot: DefaultDict[Tuple[str, int], float] = defaultdict(float)
    return_energy_by_vehicle_slot: DefaultDict[Tuple[str, int], float] = defaultdict(float)
    active_slots_by_vehicle: Dict[str, set[int]] = defaultdict(set)

    for duty in plan.duties:
        vehicle_id = str(plan.vehicle_id_for_duty(duty.duty_id) or duty.duty_id)
        vehicle = vehicle_by_id.get(vehicle_id)
        if vehicle_id not in electric_vehicle_ids or vehicle is None:
            continue
        previous_trip = None
        for leg_index, leg in enumerate(duty.legs):
            trip = trip_by_id.get(str(leg.trip.trip_id))
            if trip is None:
                continue
            active_slots = trip_active_slot_indices(problem, trip.departure_min, trip.arrival_min)
            if not active_slots:
                continue
            trip_energy = trip_energy_kwh(problem, vehicle, trip)
            fraction_by_slot = {
                slot_idx: trip_slot_energy_fraction(problem, trip.departure_min, trip.arrival_min, slot_idx)
                for slot_idx in active_slots
            }
            for slot_idx, fraction in fraction_by_slot.items():
                if fraction <= 0.0:
                    continue
                active_slots_by_vehicle[vehicle_id].add(int(slot_idx))
                trip_energy_by_vehicle_slot[(vehicle_id, int(slot_idx))] += trip_energy * fraction
            if leg_index > 0 and previous_trip is not None:
                deadhead_energy = deadhead_energy_kwh(problem, vehicle, previous_trip, trip)
                if deadhead_energy > 0.0:
                    deadhead_slot = int(active_slots[0])
                    deadhead_energy_by_vehicle_slot[(vehicle_id, deadhead_slot)] += deadhead_energy
            previous_trip = trip

    for (vehicle_id, day_idx), last_duty in vehicle_day_last_duty.items():
        vehicle = vehicle_by_id.get(vehicle_id)
        if vehicle is None or not is_electric_vehicle(problem, vehicle):
            continue
        last_trip = trip_by_id.get(str(last_duty.legs[-1].trip.trip_id))
        if last_trip is None:
            continue
        return_exists, return_deadhead_min = return_deadhead_min_to_home(problem, vehicle, last_trip)
        if not return_exists:
            continue
        return_energy = return_deadhead_energy_kwh(problem, vehicle, last_trip)
        if return_energy <= 0.0:
            continue
        return_slot = slot_index_ceil(problem, int(last_duty.legs[-1].trip.arrival_min) + int(return_deadhead_min))
        return_energy_by_vehicle_slot[(vehicle_id, int(return_slot))] += return_energy

    topup_windows: Dict[Tuple[str, int], Tuple[int, int, float]] = {}
    skipped_vehicle_days: List[str] = []
    for vehicle_id in electric_vehicle_ids:
        vehicle = vehicle_by_id.get(vehicle_id)
        if vehicle is None:
            continue
        capacity = max(float(vehicle_capacity_kwh(problem, vehicle) or 0.0), 0.0)
        if capacity <= 0.0:
            continue
        hard_target = effective_final_soc_target_kwh(problem, vehicle, cap_kwh=capacity)
        target_kwh = max(float(hard_target or 0.0), upper_buffer_ratio * capacity)
        for day_idx in range(planning_days):
            day_key = (vehicle_id, day_idx)
            last_duty = vehicle_day_last_duty.get(day_key)
            if last_duty is None:
                start_slot = slot_index(problem, day_start_min(problem, day_idx))
            else:
                last_trip = trip_by_id.get(str(last_duty.legs[-1].trip.trip_id))
                if last_trip is None:
                    skipped_vehicle_days.append(f"{vehicle_id}:d{day_idx}")
                    continue
                return_exists, return_deadhead_min = return_deadhead_min_to_home(problem, vehicle, last_trip)
                if not return_exists:
                    skipped_vehicle_days.append(f"{vehicle_id}:d{day_idx}")
                    continue
                return_complete_min = int(last_duty.legs[-1].trip.arrival_min) + int(return_deadhead_min)
                start_slot = slot_index_ceil(problem, return_complete_min)
            end_slot = post_return_target_slot_index(problem, day_idx)
            if end_slot < start_slot or target_kwh <= 0.0:
                continue
            topup_windows[day_key] = (int(start_slot), int(end_slot), float(target_kwh))

    if not topup_windows:
        return _with_topup_metadata(
            plan,
            charge_upper_buffer_ratio=upper_buffer_ratio,
            added_slot_count=0,
            added_kwh=0.0,
            unfilled_by_vehicle_day={},
            skipped_vehicle_days=tuple(sorted(set(skipped_vehicle_days))),
        )

    max_slot_from_prices = max((int(slot.slot_index) for slot in problem.price_slots), default=0)
    max_window_slot = max(window[1] for window in topup_windows.values())
    max_event_slot = max(
        [max_slot_from_prices, max_window_slot]
        + [slot for _vehicle_slot, slot in existing_charge_events.keys()]
        + [slot for _vehicle_slot, slot in trip_energy_by_vehicle_slot.keys()]
        + [slot for _vehicle_slot, slot in deadhead_energy_by_vehicle_slot.keys()]
        + [slot for _vehicle_slot, slot in return_energy_by_vehicle_slot.keys()],
        default=0,
    )

    soc_by_vehicle: Dict[str, float] = {
        vehicle_id: min(max(vehicle_initial_soc_kwh(problem, vehicle, cap_kwh=vehicle_capacity_kwh(problem, vehicle)), 0.0), vehicle_capacity_kwh(problem, vehicle))
        for vehicle_id, vehicle in vehicle_by_id.items()
        if bool(getattr(vehicle, "available", True)) and is_electric_vehicle(problem, vehicle)
    }
    if not soc_by_vehicle:
        return _with_topup_metadata(
            plan,
            charge_upper_buffer_ratio=upper_buffer_ratio,
            added_slot_count=0,
            added_kwh=0.0,
            unfilled_by_vehicle_day={},
            skipped_vehicle_days=tuple(sorted(set(skipped_vehicle_days))),
        )

    added_slots: List[ChargingSlot] = []
    added_kwh = 0.0
    unfilled_by_vehicle_day: Dict[Tuple[str, int], float] = {}
    returned_windows: set[Tuple[str, int]] = set()

    for slot_idx in range(max_event_slot + 1):
        day_idx = slot_idx // slots_per_day
        for vehicle_id, vehicle in vehicle_by_id.items():
            if vehicle_id not in soc_by_vehicle:
                continue
            soc = soc_by_vehicle[vehicle_id]
            capacity = max(vehicle_capacity_kwh(problem, vehicle) or 0.0, 0.0)
            if capacity <= 0.0:
                continue

            return_energy = return_energy_by_vehicle_slot.get((vehicle_id, slot_idx), 0.0)
            if return_energy > 0.0:
                soc = max(soc - return_energy, 0.0)

            charge_kwh = existing_charge_events.get((vehicle_id, slot_idx), 0.0)
            if charge_kwh > 0.0:
                soc = min(capacity, soc + charge_kwh * 0.95)

            trip_energy = trip_energy_by_vehicle_slot.get((vehicle_id, slot_idx), 0.0)
            if trip_energy > 0.0:
                soc = max(soc - trip_energy, 0.0)
            deadhead_energy = deadhead_energy_by_vehicle_slot.get((vehicle_id, slot_idx), 0.0)
            if deadhead_energy > 0.0:
                soc = max(soc - deadhead_energy, 0.0)

            window = topup_windows.get((vehicle_id, day_idx))
            if window is not None:
                start_slot, end_slot, target_kwh = window
                if slot_idx == end_slot and (vehicle_id, day_idx) not in returned_windows:
                    if soc + 1.0e-9 < target_kwh:
                        unfilled_by_vehicle_day[(vehicle_id, day_idx)] = target_kwh - soc
                    returned_windows.add((vehicle_id, day_idx))
                if start_slot <= slot_idx <= end_slot and soc + 1.0e-9 < target_kwh:
                    if slot_idx in active_slots_by_vehicle.get(vehicle_id, set()):
                        soc_by_vehicle[vehicle_id] = soc
                        continue
                    depot_id = str(vehicle.home_depot_id or "depot_default")
                    depot_chargers = depot_chargers_by_id.get(depot_id) or depot_chargers_by_id.get("depot_default") or ()
                    if depot_chargers:
                        usage_key = (depot_id, int(slot_idx))
                        used_ports = slot_port_usage.get(usage_key, 0)
                        used_kw = slot_kw_usage.get(usage_key, 0.0)
                        port_limit = sum(max(int(getattr(charger, "simultaneous_ports", 1) or 1), 1) for charger in depot_chargers)
                        kw_limit = sum(
                            max(float(getattr(charger, "power_kw", 0.0) or 0.0), 0.0)
                            * max(int(getattr(charger, "simultaneous_ports", 1) or 1), 1)
                            for charger in depot_chargers
                        )
                        if used_ports < port_limit and used_kw < kw_limit:
                            charger = depot_chargers[(slot_idx + len(added_slots)) % len(depot_chargers)]
                            charger_power_kw = max(float(getattr(charger, "power_kw", 0.0) or 0.0), 0.0)
                            if charger_power_kw > 0.0:
                                allowed_kw = max(min(charger_power_kw, kw_limit - used_kw), 0.0)
                                if allowed_kw > 1.0e-9:
                                    need_kwh = max(target_kwh - soc, 0.0)
                                    charge_kwh = min(allowed_kw * timestep_h, need_kwh / 0.95)
                                    if charge_kwh > 1.0e-9:
                                        added_slots.append(
                                            ChargingSlot(
                                                vehicle_id=vehicle_id,
                                                slot_index=int(slot_idx),
                                                charger_id=str(getattr(charger, "charger_id", "") or f"grid:{depot_id}"),
                                                charge_kw=charge_kwh / timestep_h,
                                                discharge_kw=0.0,
                                                charging_depot_id=depot_id,
                                                charging_latitude=getattr(charger, "latitude", None),
                                                charging_longitude=getattr(charger, "longitude", None),
                                            )
                                        )
                                        slot_port_usage[usage_key] = used_ports + 1
                                        slot_kw_usage[usage_key] = used_kw + (charge_kwh / timestep_h)
                                        soc = min(capacity, soc + charge_kwh * 0.95)
                                        added_kwh += charge_kwh

            soc_by_vehicle[vehicle_id] = soc

    if added_slots:
        merged_slots = tuple(
            sorted(
                tuple(plan.charging_slots) + tuple(added_slots),
                key=lambda item: (str(item.vehicle_id), int(item.slot_index), str(item.charger_id or "")),
            )
        )
        plan = replace(
            plan,
            charging_slots=merged_slots,
            grid_to_bus_kwh_by_depot_slot={},
            pv_to_bus_kwh_by_depot_slot={},
            bess_to_bus_kwh_by_depot_slot={},
            pv_to_bess_kwh_by_depot_slot={},
            grid_to_bess_kwh_by_depot_slot={},
            pv_curtail_kwh_by_depot_slot={},
            bess_soc_kwh_by_depot_slot={},
            contract_over_limit_kwh_by_depot_slot={},
        )

    return _with_topup_metadata(
        plan,
        charge_upper_buffer_ratio=upper_buffer_ratio,
        added_slot_count=len(added_slots),
        added_kwh=added_kwh,
        unfilled_by_vehicle_day=unfilled_by_vehicle_day,
        skipped_vehicle_days=tuple(sorted(set(skipped_vehicle_days))),
    )


def _with_topup_metadata(
    plan: AssignmentPlan,
    *,
    charge_upper_buffer_ratio: float,
    added_slot_count: int,
    added_kwh: float,
    unfilled_by_vehicle_day: Mapping[Tuple[str, int], float],
    skipped_vehicle_days: Sequence[str],
) -> AssignmentPlan:
    metadata = dict(plan.metadata or {})
    unfilled_total = float(sum(max(float(value or 0.0), 0.0) for value in unfilled_by_vehicle_day.values()))
    metadata.update(
        {
            "charge_upper_buffer_ratio": float(charge_upper_buffer_ratio),
            "opportunistic_topup_applied": bool(added_slot_count > 0),
            "opportunistic_topup_added_slot_count": int(added_slot_count),
            "opportunistic_topup_added_kwh": round(float(added_kwh), 6),
            "opportunistic_topup_unfilled_kwh": round(unfilled_total, 6),
            "opportunistic_topup_unfilled_vehicle_day_ids": tuple(
                sorted(f"{vehicle_id}:d{day_idx}" for vehicle_id, day_idx in unfilled_by_vehicle_day.keys())
            ),
            "opportunistic_topup_unfilled_vehicle_ids": tuple(
                sorted({vehicle_id for vehicle_id, _day_idx in unfilled_by_vehicle_day.keys()})
            ),
            "opportunistic_topup_skipped_vehicle_days": tuple(sorted(set(skipped_vehicle_days))),
        }
    )
    return replace(plan, metadata=metadata)
