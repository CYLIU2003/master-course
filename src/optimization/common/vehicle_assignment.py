from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from src.dispatch.models import VehicleDuty

from .problem import ProblemVehicle


def assign_duty_fragments_to_vehicles(
    duties: Sequence[VehicleDuty],
    *,
    vehicles: Sequence[ProblemVehicle],
    max_fragments_per_vehicle: int,
    existing_duties: Sequence[VehicleDuty] = (),
    existing_duty_vehicle_map: Mapping[str, str] | None = None,
    dispatch_context: Any | None = None,
) -> tuple[Tuple[VehicleDuty, ...], Dict[str, str], Tuple[str, ...]]:
    vehicle_ids_by_type: Dict[str, List[str]] = {}
    vehicle_by_id: Dict[str, ProblemVehicle] = {}
    for vehicle in vehicles:
        vehicle_ids_by_type.setdefault(str(vehicle.vehicle_type), []).append(str(vehicle.vehicle_id))
        vehicle_by_id[str(vehicle.vehicle_id)] = vehicle
    for vehicle_ids in vehicle_ids_by_type.values():
        vehicle_ids.sort()

    duty_vehicle_map: Dict[str, str] = {
        str(duty_id): str(vehicle_id)
        for duty_id, vehicle_id in dict(existing_duty_vehicle_map or {}).items()
        if str(duty_id).strip() and str(vehicle_id).strip()
    }
    grouped: Dict[str, List[VehicleDuty]] = {str(vehicle.vehicle_id): [] for vehicle in vehicles}
    assigned_duties: List[VehicleDuty] = list(existing_duties)
    for duty in existing_duties:
        vehicle_id = duty_vehicle_map.get(str(duty.duty_id)) or str(duty.duty_id)
        grouped.setdefault(vehicle_id, []).append(duty)
        duty_vehicle_map[str(duty.duty_id)] = vehicle_id

    skipped_trip_ids: List[str] = []
    fragment_cap = max(int(max_fragments_per_vehicle or 1), 1)
    for duty in sorted(duties, key=_duty_sort_key):
        vehicle_id = _select_vehicle_id_for_duty(
            duty,
            grouped,
            vehicle_ids_by_type.get(str(duty.vehicle_type), []),
            fragment_cap,
        )
        if not vehicle_id:
            skipped_trip_ids.extend(duty.trip_ids)
            continue
        fragment_index = len(grouped.setdefault(vehicle_id, [])) + 1
        duty_id = vehicle_id if fragment_index == 1 else f"{vehicle_id}__frag{fragment_index}"
        materialized = _materialize_duty_for_vehicle(
            duty,
            duty_id=duty_id,
            vehicle=vehicle_by_id.get(vehicle_id),
            dispatch_context=dispatch_context,
        )
        grouped[vehicle_id].append(materialized)
        duty_vehicle_map[duty_id] = vehicle_id
        assigned_duties.append(materialized)

    return tuple(assigned_duties), duty_vehicle_map, tuple(sorted(set(skipped_trip_ids)))


def merge_duty_vehicle_maps(
    *maps: Mapping[str, str] | None,
) -> Dict[str, str]:
    merged: Dict[str, str] = {}
    for mapping in maps:
        if not isinstance(mapping, Mapping):
            continue
        for duty_id, vehicle_id in mapping.items():
            duty_key = str(duty_id or "").strip()
            vehicle_key = str(vehicle_id or "").strip()
            if duty_key and vehicle_key:
                merged[duty_key] = vehicle_key
    return merged


def _select_vehicle_id_for_duty(
    duty: VehicleDuty,
    grouped: Mapping[str, Sequence[VehicleDuty]],
    candidate_vehicle_ids: Iterable[str],
    fragment_cap: int,
) -> str:
    duty_start, duty_end = _duty_time_bounds(duty)
    best_score: tuple[int, int, int, str] | None = None
    best_vehicle_id = ""
    for vehicle_id in candidate_vehicle_ids:
        fragments = sorted(grouped.get(vehicle_id, ()), key=_duty_sort_key)
        if len(fragments) >= fragment_cap:
            continue
        fit_score = _fragment_fit_score(fragments, duty_start, duty_end)
        if fit_score is None:
            continue
        score = (fit_score[0], fit_score[1], len(fragments), str(vehicle_id))
        if best_score is None or score < best_score:
            best_score = score
            best_vehicle_id = str(vehicle_id)
    return best_vehicle_id


def _fragment_fit_score(
    fragments: Sequence[VehicleDuty],
    duty_start: int,
    duty_end: int,
) -> tuple[int, int] | None:
    if not fragments:
        return (1, 0)
    ordered = sorted(fragments, key=_duty_sort_key)
    first_start, _ = _duty_time_bounds(ordered[0])
    if duty_end <= first_start:
        return (0, max(first_start - duty_end, 0))
    for prev, nxt in zip(ordered, ordered[1:]):
        _, prev_end = _duty_time_bounds(prev)
        next_start, _ = _duty_time_bounds(nxt)
        if prev_end <= duty_start and duty_end <= next_start:
            return (0, min(max(duty_start - prev_end, 0), max(next_start - duty_end, 0)))
    _, last_end = _duty_time_bounds(ordered[-1])
    if last_end <= duty_start:
        return (0, max(duty_start - last_end, 0))
    return None


def _duty_sort_key(duty: VehicleDuty) -> tuple[int, int, str]:
    start_min, end_min = _duty_time_bounds(duty)
    return (start_min, end_min, str(duty.duty_id))


def _duty_time_bounds(duty: VehicleDuty) -> tuple[int, int]:
    if not duty.legs:
        return (10**9, 10**9)
    return (int(duty.legs[0].trip.departure_min), int(duty.legs[-1].trip.arrival_min))


def _materialize_duty_for_vehicle(
    duty: VehicleDuty,
    *,
    duty_id: str,
    vehicle: ProblemVehicle | None,
    dispatch_context: Any | None,
) -> VehicleDuty:
    if not duty.legs:
        return replace(duty, duty_id=duty_id)

    first_leg = duty.legs[0]
    existing_deadhead = max(int(first_leg.deadhead_from_prev_min or 0), 0)
    startup_deadhead = _startup_deadhead_min(duty, vehicle=vehicle, dispatch_context=dispatch_context)
    effective_deadhead = existing_deadhead if existing_deadhead > 0 else startup_deadhead
    if effective_deadhead <= 0:
        return replace(duty, duty_id=duty_id)

    legs = (
        replace(first_leg, deadhead_from_prev_min=effective_deadhead),
        *duty.legs[1:],
    )
    return replace(duty, duty_id=duty_id, legs=tuple(legs))


def _startup_deadhead_min(
    duty: VehicleDuty,
    *,
    vehicle: ProblemVehicle | None,
    dispatch_context: Any | None,
) -> int:
    if vehicle is None or dispatch_context is None or not duty.legs:
        return 0
    first_trip = duty.legs[0].trip
    origin_key = str(getattr(first_trip, "origin_stop_id", "") or getattr(first_trip, "origin", "") or "").strip()
    if not origin_key:
        return 0
    from_location = str(getattr(vehicle, "home_depot_id", "") or "").strip()
    if not from_location:
        return 0
    get_deadhead_min = getattr(dispatch_context, "get_deadhead_min", None)
    if not callable(get_deadhead_min):
        return 0
    try:
        return max(int(get_deadhead_min(from_location, origin_key) or 0), 0)
    except Exception:
        return 0
