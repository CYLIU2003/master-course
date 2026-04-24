from __future__ import annotations

from typing import Any, Sequence, Tuple

from .problem import CanonicalOptimizationProblem, ProblemTrip, normalize_required_soc_departure_ratio

ELECTRIC_POWERTRAINS = {"BEV", "PHEV", "FCEV"}
DAY_MINUTES = 24 * 60


def horizon_start_min(problem: CanonicalOptimizationProblem) -> int:
    if not problem.scenario.horizon_start:
        return 0
    try:
        hh, mm = str(problem.scenario.horizon_start).split(":", 1)
        return int(hh) * 60 + int(mm)
    except ValueError:
        return 0


def slot_index(problem: CanonicalOptimizationProblem, minute: int) -> int:
    step = max(problem.scenario.timestep_min, 1)
    start = horizon_start_min(problem)
    m = int(minute)
    if m < start:
        m += 24 * 60
    return max((m - start) // step, 0)


def slot_index_ceil(problem: CanonicalOptimizationProblem, minute: int) -> int:
    step = max(problem.scenario.timestep_min, 1)
    start = horizon_start_min(problem)
    m = int(minute)
    if m < start:
        m += 24 * 60
    offset = max(m - start, 0)
    return (offset + step - 1) // step


def slot_absolute_min(problem: CanonicalOptimizationProblem, slot_idx: int) -> int:
    timestep_min = max(problem.scenario.timestep_min, 1)
    return horizon_start_min(problem) + int(slot_idx) * timestep_min


def day_start_min(problem: CanonicalOptimizationProblem, day_idx: int) -> int:
    return horizon_start_min(problem) + max(int(day_idx), 0) * DAY_MINUTES


def slot_to_minute_of_day(problem: CanonicalOptimizationProblem, slot_idx: int) -> int:
    return slot_absolute_min(problem, slot_idx) % DAY_MINUTES


def trip_active_in_slot(
    problem: CanonicalOptimizationProblem,
    departure_min: int,
    arrival_min: int,
    slot_idx: int,
) -> bool:
    timestep_min = max(problem.scenario.timestep_min, 1)
    slot_start = slot_absolute_min(problem, slot_idx)
    slot_end = slot_start + timestep_min
    dep = int(departure_min)
    arr = int(arrival_min)
    if arr < dep:
        arr += 24 * 60
    if dep < slot_start - 24 * 60:
        dep += 24 * 60
        arr += 24 * 60
    return dep < slot_end and arr > slot_start


def trip_slot_energy_fraction(
    problem: CanonicalOptimizationProblem,
    departure_min: int,
    arrival_min: int,
    slot_idx: int,
) -> float:
    timestep_min = max(problem.scenario.timestep_min, 1)
    slot_start = slot_absolute_min(problem, slot_idx)
    slot_end = slot_start + timestep_min

    dep = int(departure_min)
    arr = int(arrival_min)
    if arr < dep:
        arr += 24 * 60
    if dep < slot_start - 24 * 60:
        dep += 24 * 60
        arr += 24 * 60

    if dep >= slot_end or arr <= slot_start:
        return 0.0

    trip_duration = max(arr - dep, 1)
    overlap_start = max(dep, slot_start)
    overlap_end = min(arr, slot_end)
    overlap_duration = max(overlap_end - overlap_start, 0)
    return overlap_duration / trip_duration


def trip_active_slot_indices(
    problem: CanonicalOptimizationProblem,
    departure_min: int,
    arrival_min: int,
) -> Tuple[int, ...]:
    start_slot = slot_index(problem, departure_min)
    end_slot = slot_index(problem, max(arrival_min - 1, departure_min))
    return tuple(
        slot_idx
        for slot_idx in range(start_slot, end_slot + 1)
        if trip_active_in_slot(problem, departure_min, arrival_min, slot_idx)
    )


def trip_active_slot_count(
    problem: CanonicalOptimizationProblem,
    departure_min: int,
    arrival_min: int,
    slot_indices: Sequence[int],
) -> int:
    count = 0
    for slot_idx in slot_indices:
        if trip_active_in_slot(problem, departure_min, arrival_min, int(slot_idx)):
            count += 1
    return max(count, 1)


def vehicle_energy_rate_kwh_per_km(
    problem: CanonicalOptimizationProblem,
    vehicle: Any,
    fallback_trip: ProblemTrip,
) -> float:
    vehicle_rate = max(float(getattr(vehicle, "energy_consumption_kwh_per_km", 0.0) or 0.0), 0.0)
    if vehicle_rate > 0.0:
        return vehicle_rate
    vehicle_type_id = str(getattr(vehicle, "vehicle_type", "") or "")
    vt = next((item for item in problem.vehicle_types if item.vehicle_type_id == vehicle_type_id), None)
    if vt is not None:
        vt_rate = max(float(getattr(vt, "energy_consumption_kwh_per_km", 0.0) or 0.0), 0.0)
        if vt_rate > 0.0:
            return vt_rate
    return max(float(fallback_trip.energy_kwh or 0.0), 0.0) / max(float(fallback_trip.distance_km or 0.0), 1e-6)


def vehicle_powertrain_type(problem: CanonicalOptimizationProblem, vehicle: Any) -> str:
    vehicle_type_id = str(getattr(vehicle, "vehicle_type", "") or "")
    vt = next((item for item in problem.vehicle_types if item.vehicle_type_id == vehicle_type_id), None)
    return str(getattr(vt, "powertrain_type", "") or vehicle_type_id).upper()


def is_electric_vehicle(problem: CanonicalOptimizationProblem, vehicle: Any) -> bool:
    return vehicle_powertrain_type(problem, vehicle) in ELECTRIC_POWERTRAINS


def vehicle_capacity_kwh(problem: CanonicalOptimizationProblem, vehicle: Any) -> float:
    direct = getattr(vehicle, "battery_capacity_kwh", None)
    if direct is not None and float(direct or 0.0) > 0.0:
        return float(direct)
    vehicle_type_id = str(getattr(vehicle, "vehicle_type", "") or "")
    vt = next((item for item in problem.vehicle_types if item.vehicle_type_id == vehicle_type_id), None)
    return max(float(getattr(vt, "battery_capacity_kwh", 0.0) or 0.0), 0.0)


def percent_like_to_ratio(raw_value: Any) -> float | None:
    if raw_value is None:
        return None
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    if value < 0.0:
        return None
    if value > 1.0:
        value = value / 100.0
    return min(max(value, 0.0), 1.0)


def vehicle_reserve_soc_kwh(
    problem: CanonicalOptimizationProblem,
    vehicle: Any,
    *,
    cap_kwh: float | None = None,
) -> float:
    cap = max(float(cap_kwh if cap_kwh is not None else vehicle_capacity_kwh(problem, vehicle)), 0.0)
    vehicle_type_id = str(getattr(vehicle, "vehicle_type", "") or "")
    vt = next((item for item in problem.vehicle_types if item.vehicle_type_id == vehicle_type_id), None)
    reserve = getattr(vehicle, "reserve_soc", None)
    if reserve is None:
        reserve = getattr(vt, "reserve_soc", None)
    if reserve is None:
        reserve = 0.15 * cap
    reserve_kwh = float(reserve or 0.0)
    if cap > 0.0 and reserve_kwh <= 1.0:
        reserve_kwh *= cap
    return min(max(reserve_kwh, 0.0), cap) if cap > 0.0 else max(reserve_kwh, 0.0)


def vehicle_initial_soc_kwh(
    problem: CanonicalOptimizationProblem,
    vehicle: Any,
    *,
    cap_kwh: float | None = None,
) -> float:
    cap = max(float(cap_kwh if cap_kwh is not None else vehicle_capacity_kwh(problem, vehicle)), 0.0)
    initial = getattr(vehicle, "initial_soc", None)
    if initial is None:
        return 0.8 * cap
    value = float(initial or 0.0)
    if cap > 0.0 and value <= 1.0:
        value *= cap
    return min(max(value, 0.0), cap) if cap > 0.0 else max(value, 0.0)


def final_soc_floor_kwh(
    problem: CanonicalOptimizationProblem,
    vehicle: Any,
    *,
    cap_kwh: float | None = None,
) -> float:
    cap = max(float(cap_kwh if cap_kwh is not None else vehicle_capacity_kwh(problem, vehicle)), 0.0)
    floor = vehicle_reserve_soc_kwh(problem, vehicle, cap_kwh=cap)
    floor_ratio = percent_like_to_ratio((problem.metadata or {}).get("final_soc_floor_percent"))
    if floor_ratio is not None:
        floor = max(floor, floor_ratio * cap)
    return min(max(floor, 0.0), cap) if cap > 0.0 else max(floor, 0.0)


def effective_final_soc_target_kwh(
    problem: CanonicalOptimizationProblem,
    vehicle: Any,
    *,
    cap_kwh: float | None = None,
) -> float | None:
    target_ratio = percent_like_to_ratio((problem.metadata or {}).get("final_soc_target_percent"))
    if target_ratio is None:
        return None
    cap = max(float(cap_kwh if cap_kwh is not None else vehicle_capacity_kwh(problem, vehicle)), 0.0)
    if cap <= 0.0:
        return None
    tolerance_ratio = percent_like_to_ratio(
        (problem.metadata or {}).get("final_soc_target_tolerance_percent")
    )
    tolerance_ratio = 0.0 if tolerance_ratio is None else tolerance_ratio
    target_lower = max(target_ratio - max(tolerance_ratio, 0.0), 0.0) * cap
    return min(max(final_soc_floor_kwh(problem, vehicle, cap_kwh=cap), target_lower), cap)


def final_soc_target_enabled(problem: CanonicalOptimizationProblem) -> bool:
    return effective_final_soc_target_ratio(problem) is not None


def effective_final_soc_target_ratio(problem: CanonicalOptimizationProblem) -> float | None:
    target_ratio = percent_like_to_ratio((problem.metadata or {}).get("final_soc_target_percent"))
    if target_ratio is None:
        return None
    tolerance_ratio = percent_like_to_ratio(
        (problem.metadata or {}).get("final_soc_target_tolerance_percent")
    )
    tolerance_ratio = 0.0 if tolerance_ratio is None else tolerance_ratio
    floor_ratio = percent_like_to_ratio((problem.metadata or {}).get("final_soc_floor_percent"))
    floor_ratio = 0.0 if floor_ratio is None else floor_ratio
    return min(max(floor_ratio, target_ratio - max(tolerance_ratio, 0.0)), 1.0)


def trip_energy_kwh(
    problem: CanonicalOptimizationProblem,
    vehicle: Any,
    trip: ProblemTrip,
) -> float:
    drive_rate = vehicle_energy_rate_kwh_per_km(problem, vehicle, trip)
    if drive_rate > 0.0:
        return max(float(trip.distance_km or 0.0), 0.0) * drive_rate
    return max(float(trip.energy_kwh or 0.0), 0.0)


def deadhead_distance_km(problem: CanonicalOptimizationProblem, deadhead_min: int) -> float:
    speed_kmh = max(float((problem.metadata or {}).get("deadhead_speed_kmh") or 18.0), 0.0)
    return max(float(deadhead_min or 0), 0.0) * speed_kmh / 60.0


def deadhead_energy_kwh(
    problem: CanonicalOptimizationProblem,
    vehicle: Any,
    from_trip: ProblemTrip,
    to_trip: ProblemTrip,
) -> float:
    vehicle_type_id = str(getattr(vehicle, "vehicle_type", "") or "")
    vt = next((item for item in problem.vehicle_types if item.vehicle_type_id == vehicle_type_id), None)
    powertrain = str(getattr(vt, "powertrain_type", "") or vehicle_type_id).upper()
    if powertrain not in {"BEV", "PHEV", "FCEV"}:
        return 0.0
    deadhead_min = problem.dispatch_context.get_deadhead_min(
        from_trip.destination,
        to_trip.origin,
    )
    deadhead_km = deadhead_distance_km(problem, deadhead_min)
    drive_rate = vehicle_energy_rate_kwh_per_km(problem, vehicle, from_trip)
    return max(deadhead_km * drive_rate, 0.0)


def return_deadhead_min_to_home(
    problem: CanonicalOptimizationProblem,
    vehicle: Any,
    trip: Any,
) -> tuple[bool, int]:
    home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "").strip()
    if not home_depot_id:
        return False, 0
    destination = str(
        getattr(trip, "destination_stop_id", None)
        or getattr(trip, "destination", "")
        or ""
    ).strip()
    if not destination:
        return False, 0
    context = problem.dispatch_context
    locations_equivalent = getattr(context, "locations_equivalent", None)
    get_deadhead_min = getattr(context, "get_deadhead_min", None)
    if callable(locations_equivalent) and locations_equivalent(destination, home_depot_id):
        return True, 0
    if not callable(get_deadhead_min):
        return False, 0
    deadhead_min = max(int(get_deadhead_min(destination, home_depot_id) or 0), 0)
    if deadhead_min <= 0:
        return False, 0
    return True, deadhead_min


def return_deadhead_energy_kwh(
    problem: CanonicalOptimizationProblem,
    vehicle: Any,
    trip: ProblemTrip,
) -> float:
    if not is_electric_vehicle(problem, vehicle):
        return 0.0
    exists, deadhead_min = return_deadhead_min_to_home(problem, vehicle, trip)
    if not exists or deadhead_min <= 0:
        return 0.0
    return deadhead_distance_km(problem, deadhead_min) * vehicle_energy_rate_kwh_per_km(problem, vehicle, trip)


def post_return_target_slot_index(
    problem: CanonicalOptimizationProblem,
    day_idx: int,
) -> int:
    target_min = day_start_min(problem, day_idx + 1) - 1
    return slot_index(problem, target_min)


def required_departure_soc_kwh(
    problem: CanonicalOptimizationProblem,
    vehicle: Any,
    trip: ProblemTrip,
    *,
    cap_kwh: float,
    final_soc_floor_kwh: float,
) -> float:
    trip_energy = trip_energy_kwh(problem, vehicle, trip)
    required_kwh = trip_energy + max(float(final_soc_floor_kwh or 0.0), 0.0)
    required_ratio = normalize_required_soc_departure_ratio(
        trip.required_soc_departure_percent,
        treat_values_le_one_as_percent=(
            str((problem.metadata or {}).get("required_soc_departure_unit") or "").strip().lower()
            == "percent_0_100"
        ),
    )
    if required_ratio is not None and required_ratio > 0.0 and cap_kwh > 0.0:
        required_kwh = max(required_kwh, required_ratio * cap_kwh)
    return max(required_kwh, 0.0)
