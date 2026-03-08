from __future__ import annotations

import random
from typing import List

from src.dispatch.models import DutyLeg, VehicleDuty
from src.optimization.common.problem import AssignmentPlan


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
        served_trip_ids=served,
        unserved_trip_ids=tuple(sorted(unserved)),
        metadata={**dict(plan.metadata), "destroy_operator": "random_trip_removal"},
    )


def peak_hour_removal(plan: AssignmentPlan, rng: random.Random, fraction: float) -> AssignmentPlan:
    duties: List[VehicleDuty] = []
    removed: set[str] = set()
    for duty in plan.duties:
        kept = []
        for leg in duty.legs:
            if 7 * 60 <= leg.trip.departure_min <= 9 * 60 and rng.random() < fraction:
                removed.add(leg.trip.trip_id)
                continue
            kept.append(leg)
        if kept:
            duties.append(
                VehicleDuty(
                    duty_id=duty.duty_id,
                    vehicle_type=duty.vehicle_type,
                    legs=tuple(kept),
                )
            )
    served = tuple(trip_id for duty in duties for trip_id in duty.trip_ids)
    return AssignmentPlan(
        duties=tuple(duties),
        charging_slots=plan.charging_slots,
        served_trip_ids=served,
        unserved_trip_ids=tuple(sorted(set(plan.unserved_trip_ids).union(removed))),
        metadata={**dict(plan.metadata), "destroy_operator": "peak_hour_removal"},
    )


def worst_trip_removal(plan: AssignmentPlan, rng: random.Random, fraction: float) -> AssignmentPlan:
    ranked = sorted(
        (
            (leg.trip.distance_km + leg.deadhead_from_prev_min * 0.2, leg.trip.trip_id)
            for duty in plan.duties
            for leg in duty.legs
        ),
        reverse=True,
    )
    remove_count = max(1, int(len(ranked) * fraction))
    removed = {trip_id for _score, trip_id in ranked[:remove_count]}
    return random_trip_removal(
        AssignmentPlan(
            duties=plan.duties,
            charging_slots=plan.charging_slots,
            served_trip_ids=plan.served_trip_ids,
            unserved_trip_ids=tuple(sorted(set(plan.unserved_trip_ids).union(removed))),
            metadata=plan.metadata,
        ),
        rng,
        0.0 if not removed else len(removed) / max(len(plan.served_trip_ids), 1),
    )


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
    duties: List[VehicleDuty] = []
    for duty in plan.duties:
        kept = [leg for leg in duty.legs if leg.trip.trip_id not in removed]
        if kept:
            duties.append(
                VehicleDuty(duty_id=duty.duty_id, vehicle_type=duty.vehicle_type, legs=tuple(kept))
            )
    served = tuple(trip_id for duty in duties for trip_id in duty.trip_ids)
    return AssignmentPlan(
        duties=tuple(duties),
        charging_slots=plan.charging_slots,
        served_trip_ids=served,
        unserved_trip_ids=tuple(sorted(set(plan.unserved_trip_ids).union(removed))),
        metadata={**dict(plan.metadata), "destroy_operator": "unlocked_future_only_removal"},
    )
