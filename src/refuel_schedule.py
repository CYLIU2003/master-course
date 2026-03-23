from __future__ import annotations

from typing import Dict, List


def _safe_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def compute_refuel_schedule_l(data, ms, dp, assignment: Dict[str, List[str]]) -> Dict[str, List[float]]:
    """Infer ICE refueling liters per slot from assignment and fuel policy settings.

    This fallback is used for solver modes that do not expose explicit refuel variables.
    """
    num_periods = int(getattr(data, "num_periods", 0) or 0)
    if num_periods <= 0:
        return {}

    delta_h = float(getattr(data, "delta_t_hour", 0.0) or 0.0)
    if delta_h <= 0.0:
        return {}

    initial_pct = max(0.0, min(_safe_float(getattr(data, "initial_ice_fuel_percent", 100.0), 100.0), 100.0))
    min_pct = max(0.0, min(_safe_float(getattr(data, "min_ice_fuel_percent", 10.0), 10.0), 100.0))
    max_pct = max(min_pct, min(_safe_float(getattr(data, "max_ice_fuel_percent", 90.0), 90.0), 100.0))
    default_tank_l = max(0.0, _safe_float(getattr(data, "default_ice_tank_capacity_l", 300.0), 300.0))

    refuel_duration_h = 5.0 / 60.0
    result: Dict[str, List[float]] = {}

    for vehicle_id in getattr(ms, "K_ICE", []):
        vehicle = dp.vehicle_lut.get(vehicle_id)
        if vehicle is None:
            continue

        tank_l = max(0.0, _safe_float(getattr(vehicle, "fuel_tank_capacity", None), 0.0))
        if tank_l <= 0.0:
            tank_l = default_tank_l
        if tank_l <= 0.0:
            continue

        reserve_l = tank_l * (min_pct / 100.0)
        upper_l = max(reserve_l, tank_l * (max_pct / 100.0))
        refuel_rate_l_per_h = ((upper_l - reserve_l) / refuel_duration_h) if upper_l > reserve_l else 0.0
        refuel_per_slot_l = max(0.0, refuel_rate_l_per_h * delta_h)

        assigned_task_ids = sorted(
            list(assignment.get(vehicle_id, [])),
            key=lambda task_id: getattr(dp.task_lut.get(task_id), "start_time_idx", 0),
        )
        if not assigned_task_ids:
            continue

        fuel_rate_l_per_km = 0.0
        distance_sum = 0.0
        fuel_sum = 0.0
        for task_id in assigned_task_ids:
            task = dp.task_lut.get(task_id)
            if task is None:
                continue
            distance = max(0.0, _safe_float(getattr(task, "distance_km", 0.0), 0.0))
            fuel_l = max(0.0, _safe_float(dp.task_fuel_ice.get(task_id, 0.0), 0.0))
            distance_sum += distance
            fuel_sum += fuel_l
        if distance_sum > 1.0e-9:
            fuel_rate_l_per_km = fuel_sum / distance_sum

        consume_by_slot = [0.0 for _ in range(num_periods)]
        running_slots = set()
        prev_task_id = None
        for task_id in assigned_task_ids:
            task = dp.task_lut.get(task_id)
            if task is None:
                continue

            depart_slot = int(getattr(task, "start_time_idx", 0) or 0)
            if 0 <= depart_slot < num_periods:
                consume_by_slot[depart_slot] += max(0.0, _safe_float(dp.task_fuel_ice.get(task_id, 0.0), 0.0))

            task_active = dp.task_active.get(task_id, [])
            for slot_idx, active in enumerate(task_active[:num_periods]):
                if int(active or 0) > 0:
                    running_slots.add(slot_idx)

            if prev_task_id is not None and fuel_rate_l_per_km > 0.0:
                dh_km = max(
                    0.0,
                    _safe_float(
                        (dp.deadhead_distance_km.get(prev_task_id) or {}).get(task_id, 0.0),
                        0.0,
                    ),
                )
                if 0 <= depart_slot < num_periods and dh_km > 0.0:
                    consume_by_slot[depart_slot] += dh_km * fuel_rate_l_per_km

            prev_task_id = task_id

        fuel_l = max(reserve_l, min(tank_l, tank_l * (initial_pct / 100.0)))
        refuel_series = [0.0 for _ in range(num_periods)]

        for slot_idx in range(num_periods):
            fuel_after_use = max(0.0, fuel_l - consume_by_slot[slot_idx])
            can_refuel = slot_idx not in running_slots
            refuel_l = 0.0
            if can_refuel and refuel_per_slot_l > 0.0 and fuel_after_use <= reserve_l + 1.0e-9 and upper_l > fuel_after_use:
                refuel_l = min(refuel_per_slot_l, upper_l - fuel_after_use, tank_l - fuel_after_use)
            fuel_l = min(tank_l, fuel_after_use + refuel_l)
            refuel_series[slot_idx] = round(max(refuel_l, 0.0), 4)

        if any(value > 1.0e-9 for value in refuel_series):
            result[vehicle_id] = refuel_series

    return result
