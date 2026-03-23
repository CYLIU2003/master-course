from __future__ import annotations

from src.dispatch.models import DutyLeg, VehicleDuty
from src.optimization.common.problem import AssignmentPlan


def lock_started_trips(plan: AssignmentPlan, current_min: int) -> AssignmentPlan:
    duties = []
    locked = []
    for duty in plan.duties:
        kept_legs = []
        for leg in duty.legs:
            if leg.trip.departure_min <= current_min:
                kept_legs.append(leg)
                locked.append(leg.trip.trip_id)
        if kept_legs:
            duties.append(
                VehicleDuty(
                    duty_id=duty.duty_id,
                    vehicle_type=duty.vehicle_type,
                    legs=tuple(
                        DutyLeg(
                            trip=leg.trip,
                            deadhead_from_prev_min=leg.deadhead_from_prev_min,
                        )
                        for leg in kept_legs
                    ),
                )
            )
    served = tuple(trip_id for duty in duties for trip_id in duty.trip_ids)
    return AssignmentPlan(
        duties=tuple(duties),
        charging_slots=plan.charging_slots,
        refuel_slots=plan.refuel_slots,
        served_trip_ids=served,
        unserved_trip_ids=tuple(sorted(set(plan.unserved_trip_ids))),
        metadata={**dict(plan.metadata), "locked_trip_ids": tuple(locked)},
    )
