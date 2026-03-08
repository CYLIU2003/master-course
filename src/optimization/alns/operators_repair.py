from __future__ import annotations

from typing import Dict, List

from src.dispatch.dispatcher import DispatchGenerator
from src.dispatch.models import DispatchContext, DutyLeg, VehicleDuty
from src.optimization.common.problem import AssignmentPlan, CanonicalOptimizationProblem


def greedy_trip_insertion(problem: CanonicalOptimizationProblem, plan: AssignmentPlan) -> AssignmentPlan:
    if not plan.unserved_trip_ids:
        return plan

    trip_map = problem.dispatch_context.trips_by_id()
    remaining = [trip_map[trip_id] for trip_id in plan.unserved_trip_ids if trip_id in trip_map]
    existing = list(plan.duties)
    by_type: Dict[str, List] = {}
    for trip in remaining:
        preferred_type = trip.allowed_vehicle_types[0] if trip.allowed_vehicle_types else None
        if preferred_type is None:
            continue
        by_type.setdefault(preferred_type, []).append(trip)

    next_index = len(existing) + 1
    for vehicle_type, trips in by_type.items():
        ctx = DispatchContext(
            service_date=problem.dispatch_context.service_date,
            trips=trips,
            turnaround_rules=problem.dispatch_context.turnaround_rules,
            deadhead_rules=problem.dispatch_context.deadhead_rules,
            vehicle_profiles={vehicle_type: problem.dispatch_context.vehicle_profiles[vehicle_type]},
            default_turnaround_min=problem.dispatch_context.default_turnaround_min,
        )
        new_duties = DispatchGenerator().generate_greedy_duties(ctx, vehicle_type)
        for duty in new_duties:
            existing.append(
                VehicleDuty(
                    duty_id=f"{duty.duty_id}-R{next_index:04d}",
                    vehicle_type=duty.vehicle_type,
                    legs=tuple(
                        DutyLeg(trip=leg.trip, deadhead_from_prev_min=leg.deadhead_from_prev_min)
                        for leg in duty.legs
                    ),
                )
            )
            next_index += 1

    served = tuple(trip_id for duty in existing for trip_id in duty.trip_ids)
    unserved = sorted(set(problem.eligible_trip_ids()) - set(served))
    return AssignmentPlan(
        duties=tuple(existing),
        charging_slots=plan.charging_slots,
        served_trip_ids=served,
        unserved_trip_ids=tuple(unserved),
        metadata={**dict(plan.metadata), "repair_operator": "greedy_trip_insertion"},
    )


def partial_milp_repair(problem: CanonicalOptimizationProblem, plan: AssignmentPlan) -> AssignmentPlan:
    return greedy_trip_insertion(problem, plan)


def regret_k_insertion(problem: CanonicalOptimizationProblem, plan: AssignmentPlan) -> AssignmentPlan:
    return greedy_trip_insertion(problem, plan)


def energy_aware_insertion(problem: CanonicalOptimizationProblem, plan: AssignmentPlan) -> AssignmentPlan:
    trip_map = problem.trip_by_id()
    if not plan.unserved_trip_ids:
        return plan
    ordered_unserved = tuple(
        trip_id
        for trip_id, _energy in sorted(
            ((trip_id, trip_map[trip_id].energy_kwh) for trip_id in plan.unserved_trip_ids if trip_id in trip_map),
            key=lambda item: item[1],
        )
    )
    return greedy_trip_insertion(
        problem,
        AssignmentPlan(
            duties=plan.duties,
            charging_slots=plan.charging_slots,
            served_trip_ids=plan.served_trip_ids,
            unserved_trip_ids=ordered_unserved,
            metadata={**dict(plan.metadata), "repair_operator": "energy_aware_insertion"},
        ),
    )


def charger_reassignment_repair(problem: CanonicalOptimizationProblem, plan: AssignmentPlan) -> AssignmentPlan:
    if not problem.chargers:
        return plan
    charger_ids = [charger.charger_id for charger in problem.chargers]
    reassigned = tuple(
        type(slot)(
            vehicle_id=slot.vehicle_id,
            slot_index=slot.slot_index,
            charger_id=slot.charger_id or charger_ids[slot.slot_index % len(charger_ids)],
            charge_kw=slot.charge_kw,
            discharge_kw=slot.discharge_kw,
        )
        for slot in plan.charging_slots
    )
    return AssignmentPlan(
        duties=plan.duties,
        charging_slots=reassigned,
        served_trip_ids=plan.served_trip_ids,
        unserved_trip_ids=plan.unserved_trip_ids,
        metadata={**dict(plan.metadata), "repair_operator": "charger_reassignment_repair"},
    )


def soc_repair(problem: CanonicalOptimizationProblem, plan: AssignmentPlan) -> AssignmentPlan:
    return plan
