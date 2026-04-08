from __future__ import annotations

from typing import Any, Iterable, Sequence, Tuple

from .problem import CanonicalOptimizationProblem, ProblemTrip, normalize_required_soc_departure_ratio


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


def slot_absolute_min(problem: CanonicalOptimizationProblem, slot_idx: int) -> int:
    timestep_min = max(problem.scenario.timestep_min, 1)
    return horizon_start_min(problem) + int(slot_idx) * timestep_min


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
