from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from src.dispatch.models import VehicleDuty
from src.dispatch.route_band import (
    duty_route_band_ids,
    duties_route_band_ids,
    fragment_transition_is_feasible,
)

from .problem import ProblemVehicle
from .problem import day_index_for_minute


def assign_duty_fragments_to_vehicles(
    duties: Sequence[VehicleDuty],
    *,
    vehicles: Sequence[ProblemVehicle],
    max_fragments_per_vehicle: int,
    max_fragments_per_vehicle_per_day: int = 1,
    allow_same_day_depot_cycles: bool = True,
    horizon_start_min: int = 0,
    existing_duties: Sequence[VehicleDuty] = (),
    existing_duty_vehicle_map: Mapping[str, str] | None = None,
    dispatch_context: Any | None = None,
    fixed_route_band_mode: bool = False,
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
    day_fragment_cap = (
        max(int(max_fragments_per_vehicle_per_day or 1), 1)
        if allow_same_day_depot_cycles
        else 1
    )
    fragment_counts_by_vehicle_day: Dict[tuple[str, int], int] = {}
    for vehicle_id, fragments in grouped.items():
        for fragment in fragments:
            day_idx = _duty_day_index(fragment, horizon_start_min=horizon_start_min)
            key = (str(vehicle_id), day_idx)
            fragment_counts_by_vehicle_day[key] = fragment_counts_by_vehicle_day.get(key, 0) + 1
    for duty in sorted(duties, key=_duty_sort_key):
        if fixed_route_band_mode and len(duty_route_band_ids(duty)) > 1:
            skipped_trip_ids.extend(duty.trip_ids)
            continue
        vehicle_id = _select_vehicle_id_for_duty(
            duty,
            grouped,
            vehicle_ids_by_type.get(str(duty.vehicle_type), []),
            fragment_cap,
            day_fragment_cap,
            fragment_counts_by_vehicle_day,
            vehicle_by_id=vehicle_by_id,
            dispatch_context=dispatch_context,
            fixed_route_band_mode=fixed_route_band_mode,
            allow_same_day_depot_cycles=allow_same_day_depot_cycles,
            horizon_start_min=horizon_start_min,
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
        day_idx = _duty_day_index(materialized, horizon_start_min=horizon_start_min)
        key = (vehicle_id, day_idx)
        fragment_counts_by_vehicle_day[key] = fragment_counts_by_vehicle_day.get(key, 0) + 1
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
    day_fragment_cap: int,
    fragment_counts_by_vehicle_day: Mapping[tuple[str, int], int],
    *,
    vehicle_by_id: Mapping[str, ProblemVehicle],
    dispatch_context: Any | None,
    fixed_route_band_mode: bool,
    allow_same_day_depot_cycles: bool,
    horizon_start_min: int,
) -> str:
    duty_start, duty_end = _duty_time_bounds(duty)
    duty_day_idx = _duty_day_index(duty, horizon_start_min=horizon_start_min)
    duty_bands = duty_route_band_ids(duty)
    duty_band = duty_bands[0] if len(duty_bands) == 1 else ""
    best_score: tuple[int, int, int, int, str] | None = None
    best_vehicle_id = ""
    for vehicle_id in candidate_vehicle_ids:
        fragments = sorted(grouped.get(vehicle_id, ()), key=_duty_sort_key)
        if len(fragments) >= fragment_cap:
            continue
        day_count = int(fragment_counts_by_vehicle_day.get((str(vehicle_id), duty_day_idx), 0))
        if day_count >= day_fragment_cap:
            continue
        if fragments and not _fragment_insert_is_feasible_via_depot_reset(
            fragments,
            duty,
            vehicle=vehicle_by_id.get(str(vehicle_id)),
            dispatch_context=dispatch_context,
            fixed_route_band_mode=fixed_route_band_mode,
            allow_same_day_depot_cycles=allow_same_day_depot_cycles,
        ):
            continue
        band_change_rank = 0
        if fixed_route_band_mode and duty_band:
            fragment_bands = duties_route_band_ids(fragments)
            if fragment_bands and duty_band not in fragment_bands:
                band_change_rank = 1
        fit_score = _fragment_fit_score(fragments, duty_start, duty_end)
        if fit_score is None:
            continue
        if not _startup_path_exists_for_assignment(
            duty,
            vehicle=vehicle_by_id.get(str(vehicle_id)),
            fragments=fragments,
            dispatch_context=dispatch_context,
        ):
            continue
        score = (band_change_rank, fit_score[0], fit_score[1], len(fragments), str(vehicle_id))
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


def _startup_path_exists_for_assignment(
    duty: VehicleDuty,
    *,
    vehicle: ProblemVehicle | None,
    fragments: Sequence[VehicleDuty],
    dispatch_context: Any | None,
) -> bool:
    if vehicle is None or dispatch_context is None or not duty.legs:
        return True
    duty_start, duty_end = _duty_time_bounds(duty)
    if fragments:
        ordered = sorted(fragments, key=_duty_sort_key)
        first_start, _first_end = _duty_time_bounds(ordered[0])
        if duty_start >= first_start or duty_end > first_start:
            return True
    home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "").strip()
    first_trip = duty.legs[0].trip
    origin_key = str(
        getattr(first_trip, "origin_stop_id", "")
        or getattr(first_trip, "origin", "")
        or ""
    ).strip()
    if not home_depot_id or not origin_key:
        return True
    locations_equivalent = getattr(dispatch_context, "locations_equivalent", None)
    if callable(locations_equivalent) and locations_equivalent(home_depot_id, origin_key):
        return True
    has_location_data = getattr(dispatch_context, "has_location_data", None)
    get_deadhead_min = getattr(dispatch_context, "get_deadhead_min", None)
    if not callable(get_deadhead_min):
        return True
    try:
        if int(get_deadhead_min(home_depot_id, origin_key) or 0) > 0:
            return True
        if callable(has_location_data) and has_location_data(home_depot_id):
            return False
        return True
    except Exception:
        return True


def _fragment_insert_is_feasible_via_depot_reset(
    fragments: Sequence[VehicleDuty],
    duty: VehicleDuty,
    *,
    vehicle: ProblemVehicle | None,
    dispatch_context: Any | None,
    fixed_route_band_mode: bool,
    allow_same_day_depot_cycles: bool,
) -> bool:
    if vehicle is None or dispatch_context is None:
        return True
    ordered: List[Tuple[int, VehicleDuty]] = [
        (idx, fragment)
        for idx, fragment in enumerate(fragments)
    ]
    ordered.append((len(ordered), duty))
    ordered.sort(
        key=lambda item: (
            _duty_sort_key(item[1])[0],
            _duty_sort_key(item[1])[1],
            item[0],
        )
    )
    insert_pos = next(
        idx
        for idx, (_ordinal, candidate) in enumerate(ordered)
        if candidate is duty
    )
    prev_duty = ordered[insert_pos - 1][1] if insert_pos > 0 else None
    next_duty = ordered[insert_pos + 1][1] if insert_pos + 1 < len(ordered) else None
    home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "").strip()
    if prev_duty is not None:
        if not fragment_transition_is_feasible(
            prev_duty,
            duty,
            home_depot_id=home_depot_id,
            dispatch_context=dispatch_context,
            fixed_route_band_mode=fixed_route_band_mode,
            allow_same_day_depot_cycles=allow_same_day_depot_cycles,
        ):
            return False
    if next_duty is not None:
        if not fragment_transition_is_feasible(
            duty,
            next_duty,
            home_depot_id=home_depot_id,
            dispatch_context=dispatch_context,
            fixed_route_band_mode=fixed_route_band_mode,
            allow_same_day_depot_cycles=allow_same_day_depot_cycles,
        ):
            return False
    return True


def _duty_day_index(duty: VehicleDuty, *, horizon_start_min: int = 0) -> int:
    if not duty.legs:
        return 0
    return day_index_for_minute(int(duty.legs[0].trip.departure_min), horizon_start_min)
