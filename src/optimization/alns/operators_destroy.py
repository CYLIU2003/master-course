from __future__ import annotations

import random
from typing import Callable, List, Optional, Sequence, Set, Tuple

from src.dispatch.models import DutyLeg, VehicleDuty
from src.optimization.common.problem import AssignmentPlan, CanonicalOptimizationProblem, classify_peak_slots


def random_trip_removal(plan: AssignmentPlan, rng: random.Random, fraction: float) -> AssignmentPlan:
    trip_ids = list(plan.served_trip_ids)
    if not trip_ids:
        return plan
    remove_count = max(1, int(len(trip_ids) * fraction))
    removed = set(rng.sample(trip_ids, min(remove_count, len(trip_ids))))
    duties: List[VehicleDuty] = []
    unserved = set(plan.unserved_trip_ids)
    for duty in plan.duties:
        kept = [leg for leg in duty.legs if leg.trip.trip_id not in removed]
        dropped = [leg.trip.trip_id for leg in duty.legs if leg.trip.trip_id in removed]
        unserved.update(dropped)
        if kept:
            duties.append(
                VehicleDuty(
                    duty_id=duty.duty_id,
                    vehicle_type=duty.vehicle_type,
                    legs=tuple(
                        DutyLeg(
                            trip=leg.trip,
                            deadhead_from_prev_min=0 if idx == 0 else leg.deadhead_from_prev_min,
                        )
                        for idx, leg in enumerate(kept)
                    ),
                )
            )
    served = tuple(
        trip_id
        for duty in duties
        for trip_id in duty.trip_ids
    )
    return AssignmentPlan(
        duties=tuple(duties),
        charging_slots=plan.charging_slots,
        refuel_slots=plan.refuel_slots,
        served_trip_ids=served,
        unserved_trip_ids=tuple(sorted(unserved)),
        metadata={**dict(plan.metadata), "destroy_operator": "random_trip_removal"},
    )


def _remove_trip_ids(plan: AssignmentPlan, removed: Set[str], operator_name: str) -> AssignmentPlan:
    duties: List[VehicleDuty] = []
    unserved = set(plan.unserved_trip_ids)
    unserved.update(removed)
    for duty in plan.duties:
        kept = [leg for leg in duty.legs if leg.trip.trip_id not in removed]
        if kept:
            duties.append(
                VehicleDuty(
                    duty_id=duty.duty_id,
                    vehicle_type=duty.vehicle_type,
                    legs=tuple(
                        DutyLeg(
                            trip=leg.trip,
                            deadhead_from_prev_min=0 if idx == 0 else leg.deadhead_from_prev_min,
                        )
                        for idx, leg in enumerate(kept)
                    ),
                )
            )
    served = tuple(trip_id for duty in duties for trip_id in duty.trip_ids)
    return AssignmentPlan(
        duties=tuple(duties),
        charging_slots=plan.charging_slots,
        refuel_slots=plan.refuel_slots,
        served_trip_ids=served,
        unserved_trip_ids=tuple(sorted(unserved)),
        metadata={**dict(plan.metadata), "destroy_operator": operator_name},
    )


def _slot_index_for_departure(problem: CanonicalOptimizationProblem, departure_min: int) -> int:
    timestep_min = max(problem.scenario.timestep_min, 1)
    horizon_start = problem.scenario.horizon_start
    if not horizon_start:
        return departure_min // timestep_min
    try:
        hh, mm = horizon_start.split(":", 1)
        start_min = int(hh) * 60 + int(mm)
    except ValueError:
        return departure_min // timestep_min
    adj = departure_min
    if adj < start_min:
        adj += 24 * 60
    return (adj - start_min) // timestep_min


def peak_hour_removal(
    plan: AssignmentPlan,
    rng: random.Random,
    fraction: float,
    *,
    problem: Optional[CanonicalOptimizationProblem] = None,
    use_data_driven_peak: bool = True,
    fallback_windows_min: Optional[Sequence[Tuple[int, int]]] = None,
) -> AssignmentPlan:
    removed: set[str] = set()
    peak_slots: Set[int] = set()
    if use_data_driven_peak and problem is not None and problem.price_slots:
        peak_slots, _ = classify_peak_slots(problem.price_slots)

    windows = tuple(fallback_windows_min or ((7 * 60, 9 * 60),))
    for duty in plan.duties:
        for leg in duty.legs:
            dep_min = int(leg.trip.departure_min)
            in_peak = False
            if peak_slots and problem is not None:
                in_peak = _slot_index_for_departure(problem, dep_min) in peak_slots
            else:
                in_peak = any(start <= dep_min <= end for start, end in windows)
            if in_peak and rng.random() < fraction:
                removed.add(leg.trip.trip_id)

    return _remove_trip_ids(plan, removed, "peak_hour_removal")


def worst_trip_removal(
    plan: AssignmentPlan,
    rng: random.Random,
    fraction: float,
    *,
    objective_fn: Optional[Callable[[AssignmentPlan], float]] = None,
) -> AssignmentPlan:
    served = list(plan.served_trip_ids)
    if not served:
        return plan
    remove_count = max(1, int(len(served) * fraction))

    if objective_fn is not None:
        base_obj = float(objective_fn(plan))
        ranked = []
        for trip_id in served:
            candidate = _remove_trip_ids(plan, {trip_id}, "worst_trip_probe")
            improvement = base_obj - float(objective_fn(candidate))
            ranked.append((improvement, trip_id))
        ranked.sort(reverse=True)
        removed = {trip_id for _gain, trip_id in ranked[:remove_count]}
        return _remove_trip_ids(plan, removed, "worst_trip_removal")

    ranked = sorted(
        (
            (leg.trip.distance_km + leg.deadhead_from_prev_min * 0.2, leg.trip.trip_id)
            for duty in plan.duties
            for leg in duty.legs
        ),
        reverse=True,
    )
    removed = {trip_id for _score, trip_id in ranked[:remove_count]}
    return _remove_trip_ids(plan, removed, "worst_trip_removal")


def vehicle_path_removal(plan: AssignmentPlan, rng: random.Random, fraction: float) -> AssignmentPlan:
    if not plan.duties:
        return plan
    selected = rng.choice(plan.duties)
    remaining = tuple(duty for duty in plan.duties if duty.duty_id != selected.duty_id)
    served = tuple(trip_id for duty in remaining for trip_id in duty.trip_ids)
    unserved = set(plan.unserved_trip_ids).union(selected.trip_ids)
    return AssignmentPlan(
        duties=remaining,
        charging_slots=plan.charging_slots,
        refuel_slots=plan.refuel_slots,
        served_trip_ids=served,
        unserved_trip_ids=tuple(sorted(unserved)),
        metadata={**dict(plan.metadata), "destroy_operator": "vehicle_path_removal"},
    )


def unlocked_future_only_removal(
    plan: AssignmentPlan,
    rng: random.Random,
    fraction: float,
    current_min: int | None,
) -> AssignmentPlan:
    if current_min is None:
        return random_trip_removal(plan, rng, fraction)
    removable = [
        leg.trip.trip_id
        for duty in plan.duties
        for leg in duty.legs
        if leg.trip.departure_min > current_min
    ]
    if not removable:
        return plan
    remove_count = max(1, int(len(removable) * fraction))
    removed = set(rng.sample(removable, min(remove_count, len(removable))))
    return _remove_trip_ids(plan, removed, "unlocked_future_only_removal")
