from __future__ import annotations

from dataclasses import replace
from typing import Dict, List

from src.dispatch.dispatcher import DispatchGenerator
from src.dispatch.models import DispatchContext, DutyLeg, VehicleDuty
from src.optimization.common.problem import AssignmentPlan, CanonicalOptimizationProblem, ChargingSlot, OptimizationConfig, OptimizationMode
from src.optimization.milp.engine import MILPOptimizer


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
        refuel_slots=plan.refuel_slots,
        served_trip_ids=served,
        unserved_trip_ids=tuple(unserved),
        metadata={**dict(plan.metadata), "repair_operator": "greedy_trip_insertion"},
    )


def baseline_dispatch_repair(
    problem: CanonicalOptimizationProblem,
    plan: AssignmentPlan,
) -> AssignmentPlan:
    baseline = problem.baseline_plan
    if baseline is None or not baseline.duties:
        return greedy_trip_insertion(problem, plan)

    existing = list(plan.duties)
    served = set(plan.served_trip_ids)
    missing = set(plan.unserved_trip_ids)

    for duty in baseline.duties:
        duty_trip_ids = set(duty.trip_ids)
        if not duty_trip_ids.intersection(missing):
            continue
        if duty_trip_ids.issubset(served):
            continue
        if duty_trip_ids.intersection(served):
            continue
        existing.append(
            VehicleDuty(
                duty_id=f"{duty.duty_id}-B",
                vehicle_type=duty.vehicle_type,
                legs=tuple(
                    DutyLeg(
                        trip=leg.trip,
                        deadhead_from_prev_min=leg.deadhead_from_prev_min,
                    )
                    for leg in duty.legs
                ),
            )
        )
        served.update(duty_trip_ids)
        missing.difference_update(duty_trip_ids)

    if missing:
        repaired = AssignmentPlan(
            duties=tuple(existing),
            charging_slots=plan.charging_slots,
            refuel_slots=plan.refuel_slots,
            served_trip_ids=tuple(sorted(served)),
            unserved_trip_ids=tuple(sorted(missing)),
            metadata={**dict(plan.metadata), "repair_operator": "baseline_dispatch_repair"},
        )
        return greedy_trip_insertion(problem, repaired)

    return AssignmentPlan(
        duties=tuple(existing),
        charging_slots=plan.charging_slots,
        refuel_slots=plan.refuel_slots,
        served_trip_ids=tuple(sorted(served)),
        unserved_trip_ids=tuple(),
        metadata={**dict(plan.metadata), "repair_operator": "baseline_dispatch_repair"},
    )


def partial_milp_repair(problem: CanonicalOptimizationProblem, plan: AssignmentPlan) -> AssignmentPlan:
    if not plan.unserved_trip_ids:
        return plan

    limit = max(1, min(40, len(plan.unserved_trip_ids)))
    target_ids = set(plan.unserved_trip_ids[:limit])
    sub_trips = tuple(trip for trip in problem.trips if trip.trip_id in target_ids)
    if not sub_trips:
        return plan

    sub_dispatch_trips = [
        trip
        for trip in problem.dispatch_context.trips
        if trip.trip_id in target_ids
    ]
    sub_dispatch_context = DispatchContext(
        service_date=problem.dispatch_context.service_date,
        trips=sub_dispatch_trips,
        turnaround_rules=problem.dispatch_context.turnaround_rules,
        deadhead_rules=problem.dispatch_context.deadhead_rules,
        vehicle_profiles=problem.dispatch_context.vehicle_profiles,
        default_turnaround_min=problem.dispatch_context.default_turnaround_min,
    )
    sub_feasible = {
        trip_id: tuple(next_id for next_id in next_ids if next_id in target_ids)
        for trip_id, next_ids in problem.feasible_connections.items()
        if trip_id in target_ids
    }

    sub_problem = replace(
        problem,
        dispatch_context=sub_dispatch_context,
        trips=sub_trips,
        feasible_connections=sub_feasible,
        baseline_plan=None,
    )
    sub_result = MILPOptimizer().solve(
        sub_problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            time_limit_sec=30,
            mip_gap=0.05,
            random_seed=42,
        ),
    )

    existing_duties = list(plan.duties)
    existing_served = set(plan.served_trip_ids)
    for duty in sub_result.plan.duties:
        new_trip_ids = [trip_id for trip_id in duty.trip_ids if trip_id not in existing_served]
        if not new_trip_ids:
            continue
        filtered_legs = tuple(leg for leg in duty.legs if leg.trip.trip_id in new_trip_ids)
        if not filtered_legs:
            continue
        existing_duties.append(
            VehicleDuty(
                duty_id=f"{duty.duty_id}-PMR",
                vehicle_type=duty.vehicle_type,
                legs=filtered_legs,
            )
        )
        existing_served.update(new_trip_ids)

    all_eligible = set(problem.eligible_trip_ids())
    unserved = tuple(sorted(all_eligible - existing_served))
    return AssignmentPlan(
        duties=tuple(existing_duties),
        charging_slots=plan.charging_slots,
        refuel_slots=plan.refuel_slots,
        served_trip_ids=tuple(sorted(existing_served)),
        unserved_trip_ids=unserved,
        metadata={**dict(plan.metadata), "repair_operator": "partial_milp_repair"},
    )


def regret_k_insertion(problem: CanonicalOptimizationProblem, plan: AssignmentPlan) -> AssignmentPlan:
    if not plan.unserved_trip_ids:
        return plan

    trip_map = problem.dispatch_context.trips_by_id()
    duties = list(plan.duties)
    unserved = [trip_id for trip_id in plan.unserved_trip_ids if trip_id in trip_map]

    def insertion_cost(duty: VehicleDuty, trip_id: str) -> float | None:
        trip = trip_map[trip_id]
        if duty.vehicle_type not in trip.allowed_vehicle_types:
            return None
        if not duty.legs:
            return 0.0
        last_trip = duty.legs[-1].trip
        if trip.trip_id not in problem.feasible_connections.get(last_trip.trip_id, ()):  # append-only insertion
            return None
        deadhead = problem.dispatch_context.get_deadhead_min(last_trip.destination, trip.origin)
        slack = trip.departure_min - (last_trip.arrival_min + deadhead)
        if slack < 0:
            return None
        return float(deadhead + max(slack, 0) * 0.1)

    while unserved:
        best_trip_id = None
        best_duty_index = None
        best_regret = float("-inf")
        best_cost = float("inf")

        for trip_id in unserved:
            costs: List[tuple[float, int]] = []
            for idx, duty in enumerate(duties):
                cost = insertion_cost(duty, trip_id)
                if cost is not None:
                    costs.append((cost, idx))

            if not costs:
                continue
            costs.sort(key=lambda item: item[0])
            first_cost, first_idx = costs[0]
            second_cost = costs[1][0] if len(costs) > 1 else first_cost + 1000.0
            regret = second_cost - first_cost
            if regret > best_regret or (regret == best_regret and first_cost < best_cost):
                best_regret = regret
                best_trip_id = trip_id
                best_duty_index = first_idx
                best_cost = first_cost

        if best_trip_id is None or best_duty_index is None:
            break

        target_trip = trip_map[best_trip_id]
        duty = duties[best_duty_index]
        prev_deadhead = 0
        if duty.legs:
            prev_deadhead = problem.dispatch_context.get_deadhead_min(
                duty.legs[-1].trip.destination,
                target_trip.origin,
            )
        updated_duty = VehicleDuty(
            duty_id=duty.duty_id,
            vehicle_type=duty.vehicle_type,
            legs=duty.legs + (DutyLeg(trip=target_trip, deadhead_from_prev_min=prev_deadhead),),
        )
        duties[best_duty_index] = updated_duty
        unserved.remove(best_trip_id)

    if unserved:
        fallback_plan = AssignmentPlan(
            duties=tuple(duties),
            charging_slots=plan.charging_slots,
            refuel_slots=plan.refuel_slots,
            served_trip_ids=tuple(sorted({trip_id for duty in duties for trip_id in duty.trip_ids})),
            unserved_trip_ids=tuple(unserved),
            metadata=plan.metadata,
        )
        return greedy_trip_insertion(problem, fallback_plan)

    served = tuple(sorted({trip_id for duty in duties for trip_id in duty.trip_ids}))
    return AssignmentPlan(
        duties=tuple(duties),
        charging_slots=plan.charging_slots,
        refuel_slots=plan.refuel_slots,
        served_trip_ids=served,
        unserved_trip_ids=tuple(),
        metadata={**dict(plan.metadata), "repair_operator": "regret_k_insertion"},
    )


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
            refuel_slots=plan.refuel_slots,
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
        refuel_slots=plan.refuel_slots,
        served_trip_ids=plan.served_trip_ids,
        unserved_trip_ids=plan.unserved_trip_ids,
        metadata={**dict(plan.metadata), "repair_operator": "charger_reassignment_repair"},
    )


def soc_repair(problem: CanonicalOptimizationProblem, plan: AssignmentPlan) -> AssignmentPlan:
    if not problem.chargers:
        return plan

    vehicle_map = {vehicle.vehicle_id: vehicle for vehicle in problem.vehicles}
    trip_map = problem.trip_by_id()
    charger = problem.chargers[0]
    slot_power = min(charger.power_kw, 50.0)

    repaired_slots = list(plan.charging_slots)
    existing_slot_keys = {(slot.vehicle_id, slot.slot_index) for slot in repaired_slots}

    for duty in plan.duties:
        duty_vehicle_id = None
        if duty.duty_id.startswith("milp_"):
            duty_vehicle_id = duty.duty_id.replace("milp_", "", 1)
        if duty_vehicle_id is None or duty_vehicle_id not in vehicle_map:
            continue
        vehicle = vehicle_map[duty_vehicle_id]
        if vehicle.vehicle_type.upper() not in {"BEV", "PHEV", "FCEV"}:
            continue

        capacity = max(vehicle.battery_capacity_kwh or 300.0, 1.0)
        reserve = vehicle.reserve_soc if vehicle.reserve_soc is not None else 0.15 * capacity
        current_soc = vehicle.initial_soc if vehicle.initial_soc is not None else 0.8 * capacity
        if current_soc <= 1.0:
            current_soc *= capacity

        for leg in duty.legs:
            trip = trip_map.get(leg.trip.trip_id)
            if trip is None:
                continue
            current_soc -= max(trip.energy_kwh, 0.0)
            if current_soc < reserve:
                slot_index = leg.trip.arrival_min // max(problem.scenario.timestep_min, 1)
                slot_key = (duty_vehicle_id, slot_index)
                if slot_key not in existing_slot_keys:
                    repaired_slots.append(
                        ChargingSlot(
                            vehicle_id=duty_vehicle_id,
                            slot_index=slot_index,
                            charger_id=charger.charger_id,
                            charge_kw=slot_power,
                            discharge_kw=0.0,
                        )
                    )
                    existing_slot_keys.add(slot_key)
                    current_soc += slot_power * (max(problem.scenario.timestep_min, 1) / 60.0) * 0.95

    return AssignmentPlan(
        duties=plan.duties,
        charging_slots=tuple(repaired_slots),
        refuel_slots=plan.refuel_slots,
        served_trip_ids=plan.served_trip_ids,
        unserved_trip_ids=plan.unserved_trip_ids,
        metadata={**dict(plan.metadata), "repair_operator": "soc_repair"},
    )
