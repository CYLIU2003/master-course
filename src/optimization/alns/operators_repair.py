from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Tuple

from src.dispatch.dispatcher import DispatchGenerator
from src.dispatch.models import DispatchContext, DutyLeg, VehicleDuty
from src.optimization.common.problem import AssignmentPlan, CanonicalOptimizationProblem, ChargingSlot, OptimizationConfig, OptimizationMode, RefuelSlot
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
    return _with_recomputed_charging(
        problem,
        AssignmentPlan(
        duties=tuple(existing),
        charging_slots=plan.charging_slots,
        refuel_slots=plan.refuel_slots,
        served_trip_ids=served,
        unserved_trip_ids=tuple(unserved),
        metadata={**dict(plan.metadata), "repair_operator": "greedy_trip_insertion"},
        ),
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

    return _with_recomputed_charging(
        problem,
        AssignmentPlan(
        duties=tuple(existing),
        charging_slots=plan.charging_slots,
        refuel_slots=plan.refuel_slots,
        served_trip_ids=tuple(sorted(served)),
        unserved_trip_ids=tuple(),
        metadata={**dict(plan.metadata), "repair_operator": "baseline_dispatch_repair"},
        ),
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
    return _with_recomputed_charging(
        problem,
        AssignmentPlan(
        duties=tuple(existing_duties),
        charging_slots=plan.charging_slots,
        refuel_slots=plan.refuel_slots,
        served_trip_ids=tuple(sorted(existing_served)),
        unserved_trip_ids=unserved,
        metadata={**dict(plan.metadata), "repair_operator": "partial_milp_repair"},
        ),
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
    return _with_recomputed_charging(
        problem,
        AssignmentPlan(
        duties=tuple(duties),
        charging_slots=plan.charging_slots,
        refuel_slots=plan.refuel_slots,
        served_trip_ids=served,
        unserved_trip_ids=tuple(),
        metadata={**dict(plan.metadata), "repair_operator": "regret_k_insertion"},
        ),
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


def _with_recomputed_charging(problem: CanonicalOptimizationProblem, plan: AssignmentPlan) -> AssignmentPlan:
    slots = _recompute_charging_slots(problem, plan)
    refuels = _recompute_refuel_slots(problem, plan)
    return AssignmentPlan(
        duties=plan.duties,
        charging_slots=slots,
        refuel_slots=refuels,
        vehicle_cost_ledger=plan.vehicle_cost_ledger,
        daily_cost_ledger=plan.daily_cost_ledger,
        served_trip_ids=plan.served_trip_ids,
        unserved_trip_ids=plan.unserved_trip_ids,
        metadata=plan.metadata,
    )


def _vehicle_id_from_duty_id(duty_id: str) -> str:
    if duty_id.startswith("milp_") and len(duty_id) > 5:
        return duty_id[5:]
    return duty_id


def _slot_index(problem: CanonicalOptimizationProblem, minute: int) -> int:
    step = max(problem.scenario.timestep_min, 1)
    start = 0
    if problem.scenario.horizon_start:
        try:
            hh, mm = problem.scenario.horizon_start.split(":", 1)
            start = int(hh) * 60 + int(mm)
        except ValueError:
            start = 0
    m = int(minute)
    if m < start:
        m += 24 * 60
    return max((m - start) // step, 0)


def _recompute_charging_slots(problem: CanonicalOptimizationProblem, plan: AssignmentPlan) -> Tuple[ChargingSlot, ...]:
    if not problem.chargers:
        return plan.charging_slots

    trip_map = problem.trip_by_id()
    vehicle_by_id = {v.vehicle_id: v for v in problem.vehicles}
    type_by_id = {vt.vehicle_type_id: vt for vt in problem.vehicle_types}
    chargers_by_depot: Dict[str, List] = {}
    for charger in problem.chargers:
        depot_id = str(charger.depot_id or "depot_default")
        chargers_by_depot.setdefault(depot_id, []).append(charger)
    dt_h = max(problem.scenario.timestep_min, 1) / 60.0
    trigger_margin_kwh = float((problem.metadata or {}).get("charge_trigger_soc_margin_kwh") or 0.0)
    target_extra_kwh = float((problem.metadata or {}).get("charge_target_extra_margin_kwh") or 0.0)
    overnight_mode = str(problem.scenario.allow_overnight_depot_moves or "forbid").strip().lower()
    overnight_start = str(problem.scenario.overnight_window_start or "23:00")
    overnight_end = str(problem.scenario.overnight_window_end or "05:00")

    slot_port_usage: Dict[Tuple[str, int], int] = {}
    slot_power_usage: Dict[Tuple[str, int], float] = {}
    out: List[ChargingSlot] = []

    for duty in plan.duties:
        vehicle_id = _vehicle_id_from_duty_id(duty.duty_id)
        vehicle = vehicle_by_id.get(vehicle_id)
        vtype = type_by_id.get(duty.vehicle_type)
        powertrain = str((vtype.powertrain_type if vtype else duty.vehicle_type) or "").upper()
        if powertrain not in {"BEV", "PHEV", "FCEV"}:
            continue

        home_depot = str((vehicle.home_depot_id if vehicle else None) or "depot_default")
        depot_chargers = chargers_by_depot.get(home_depot) or chargers_by_depot.get("depot_default") or []
        if not depot_chargers:
            continue
        port_limit = sum(max(int(getattr(ch, "simultaneous_ports", 1) or 1), 1) for ch in depot_chargers)
        kw_limit = sum(
            max(float(getattr(ch, "power_kw", 0.0) or 0.0), 0.0)
            * max(int(getattr(ch, "simultaneous_ports", 1) or 1), 1)
            for ch in depot_chargers
        )

        capacity = float((vehicle.battery_capacity_kwh if vehicle else None) or (vtype.battery_capacity_kwh if vtype else 0.0) or 300.0)
        reserve = float((vehicle.reserve_soc if vehicle else None) or (vtype.reserve_soc if vtype else None) or (0.15 * capacity))
        soc = float((vehicle.initial_soc if vehicle else None) or (0.8 * capacity))
        if soc <= 1.0 and capacity > 1.0:
            soc = soc * capacity
        soc = min(max(soc, 0.0), capacity)

        prev_arrival = duty.legs[0].trip.departure_min if duty.legs else 0
        for leg in duty.legs:
            trip = trip_map.get(leg.trip.trip_id)
            if trip is None:
                prev_arrival = leg.trip.arrival_min
                continue
            trip_energy = max(float(trip.energy_kwh or 0.0), 0.0)
            deadhead_energy = 0.0
            if leg.deadhead_from_prev_min > 0:
                dist_km = max(float(leg.deadhead_from_prev_min), 0.0) * 18.0 / 60.0
                per_km = trip_energy / max(float(trip.distance_km or 0.0), 1.0e-6)
                deadhead_energy = max(dist_km * per_km, 0.0)

            needed_before_depart = reserve + trip_energy + deadhead_energy + max(trigger_margin_kwh, 0.0)
            target_soc = min(capacity, needed_before_depart + max(target_extra_kwh, 0.0))
            first_slot = _slot_index(problem, prev_arrival)
            last_slot = _slot_index(problem, trip.departure_min) - 1
            candidate_slots = [
                idx
                for idx in range(first_slot, last_slot + 1)
                if _is_replenishment_slot_allowed(problem, idx, overnight_mode, overnight_start, overnight_end)
            ]
            for slot_idx in reversed(candidate_slots):
                if soc + 1.0e-9 >= needed_before_depart:
                    break
                charger = depot_chargers[(slot_idx + len(out)) % len(depot_chargers)]
                power_kw = max(float(charger.power_kw or 0.0), 0.0)
                if power_kw <= 0.0:
                    continue
                usage_key = (home_depot, int(slot_idx))
                used_ports = slot_port_usage.get(usage_key, 0)
                used_kw = slot_power_usage.get(usage_key, 0.0)
                if used_ports >= port_limit or used_kw >= kw_limit:
                    continue
                allowed_kw = max(min(power_kw, kw_limit - used_kw), 0.0)
                if allowed_kw <= 1.0e-9:
                    continue
                need_kwh = max(target_soc - soc, 0.0)
                charge_kwh = min(allowed_kw * dt_h, need_kwh)
                if charge_kwh <= 1.0e-9:
                    continue
                out.append(
                    ChargingSlot(
                        vehicle_id=vehicle_id,
                        slot_index=int(slot_idx),
                        charger_id=charger.charger_id,
                        charge_kw=charge_kwh / dt_h,
                        discharge_kw=0.0,
                    )
                )
                slot_port_usage[usage_key] = used_ports + 1
                slot_power_usage[usage_key] = used_kw + (charge_kwh / dt_h)
                soc = min(capacity, soc + charge_kwh * 0.95)

            soc -= (trip_energy + deadhead_energy)
            prev_arrival = leg.trip.arrival_min

    out.sort(key=lambda s: (str(s.vehicle_id), int(s.slot_index), str(s.charger_id or "")))
    return tuple(out)


def _recompute_refuel_slots(problem: CanonicalOptimizationProblem, plan: AssignmentPlan) -> Tuple[RefuelSlot, ...]:
    trip_map = problem.trip_by_id()
    vehicle_by_id = {v.vehicle_id: v for v in problem.vehicles}
    type_by_id = {vt.vehicle_type_id: vt for vt in problem.vehicle_types}
    dt_h = max(problem.scenario.timestep_min, 1) / 60.0
    trigger_margin_l = float((problem.metadata or {}).get("fuel_trigger_margin_l") or 0.0)
    target_extra_l = float((problem.metadata or {}).get("fuel_target_extra_margin_l") or 0.0)
    overnight_mode = str(problem.scenario.allow_overnight_depot_moves or "forbid").strip().lower()
    overnight_start = str(problem.scenario.overnight_window_start or "23:00")
    overnight_end = str(problem.scenario.overnight_window_end or "05:00")

    out: List[RefuelSlot] = []
    for duty in plan.duties:
        vehicle_id = _vehicle_id_from_duty_id(duty.duty_id)
        vehicle = vehicle_by_id.get(vehicle_id)
        vtype = type_by_id.get(duty.vehicle_type)
        powertrain = str((vtype.powertrain_type if vtype else duty.vehicle_type) or "").upper()
        if powertrain in {"BEV", "PHEV", "FCEV"}:
            continue
        if vehicle is None:
            continue

        tank = max(float(vehicle.fuel_tank_capacity_l or 0.0), 0.0)
        if tank <= 0.0:
            continue
        reserve = max(float(vehicle.fuel_reserve_l or 0.0), 0.0)
        fuel_rate = max(float(vehicle.fuel_consumption_l_per_km or 0.0), 0.0)
        if fuel_rate <= 0.0:
            continue
        fuel = float(vehicle.initial_fuel_l if vehicle.initial_fuel_l is not None else tank)
        fuel = min(max(fuel, reserve), tank)
        refuel_lph = max(float((problem.metadata or {}).get("refuel_rate_l_per_h") or 120.0), 1.0)
        refuel_per_slot = refuel_lph * dt_h
        prev_arrival = duty.legs[0].trip.departure_min if duty.legs else 0
        for leg in duty.legs:
            trip = trip_map.get(leg.trip.trip_id)
            if trip is None:
                prev_arrival = leg.trip.arrival_min
                continue
            trip_fuel = max(float(trip.fuel_l or 0.0), 0.0)
            if trip_fuel <= 0.0:
                trip_fuel = max(float(trip.distance_km or 0.0), 0.0) * fuel_rate
            deadhead_fuel = 0.0
            if leg.deadhead_from_prev_min > 0:
                deadhead_fuel = max(float(leg.deadhead_from_prev_min), 0.0) * 18.0 / 60.0 * fuel_rate

            needed_before_depart = reserve + trip_fuel + deadhead_fuel + max(trigger_margin_l, 0.0)
            target_fuel = min(tank, needed_before_depart + max(target_extra_l, 0.0))
            first_slot = _slot_index(problem, prev_arrival)
            last_slot = _slot_index(problem, trip.departure_min) - 1
            candidate_slots = [
                idx
                for idx in range(first_slot, last_slot + 1)
                if _is_replenishment_slot_allowed(problem, idx, overnight_mode, overnight_start, overnight_end)
            ]
            for slot_idx in reversed(candidate_slots):
                if fuel + 1.0e-9 >= needed_before_depart:
                    break
                add_l = min(refuel_per_slot, max(target_fuel - fuel, 0.0))
                if add_l <= 1.0e-9:
                    continue
                out.append(
                    RefuelSlot(
                        vehicle_id=vehicle_id,
                        slot_index=int(slot_idx),
                        refuel_liters=add_l,
                        location_id=str(vehicle.home_depot_id or "depot_default"),
                    )
                )
                fuel = min(tank, fuel + add_l)

            fuel -= (trip_fuel + deadhead_fuel)
            prev_arrival = leg.trip.arrival_min

    out.sort(key=lambda s: (str(s.vehicle_id), int(s.slot_index)))
    return tuple(out)


def _is_replenishment_slot_allowed(
    problem: CanonicalOptimizationProblem,
    slot_idx: int,
    mode: str,
    overnight_start: str,
    overnight_end: str,
) -> bool:
    if mode not in {"forbid", "allow_same_depot_only", "allow_with_penalty"}:
        return True
    if mode != "forbid":
        return True
    minute = _slot_to_minute_of_day(problem, slot_idx)
    return not _is_in_overnight_window(minute, overnight_start, overnight_end)


def _slot_to_minute_of_day(problem: CanonicalOptimizationProblem, slot_idx: int) -> int:
    step = max(problem.scenario.timestep_min, 1)
    base = 0
    if problem.scenario.horizon_start:
        try:
            hh, mm = problem.scenario.horizon_start.split(":", 1)
            base = int(hh) * 60 + int(mm)
        except ValueError:
            base = 0
    return int((base + int(slot_idx) * step) % (24 * 60))


def _is_in_overnight_window(minute_of_day: int, start_hhmm: str, end_hhmm: str) -> bool:
    def _parse(text: str, fallback: int) -> int:
        try:
            hh, mm = str(text).split(":", 1)
            return (int(hh) * 60 + int(mm)) % (24 * 60)
        except ValueError:
            return fallback

    start = _parse(start_hhmm, 23 * 60)
    end = _parse(end_hhmm, 5 * 60)
    value = int(minute_of_day) % (24 * 60)
    if start <= end:
        return start <= value <= end
    return value >= start or value <= end
