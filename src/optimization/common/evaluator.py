from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .problem import AssignmentPlan, CanonicalOptimizationProblem


@dataclass(frozen=True)
class CostBreakdown:
    energy_cost: float = 0.0
    demand_cost: float = 0.0
    vehicle_cost: float = 0.0
    driver_cost: float = 0.0
    unserved_penalty: float = 0.0
    switch_cost: float = 0.0
    degradation_cost: float = 0.0
    deviation_cost: float = 0.0
    total_cost: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "energy_cost": self.energy_cost,
            "demand_cost": self.demand_cost,
            "vehicle_cost": self.vehicle_cost,
            "driver_cost": self.driver_cost,
            "unserved_penalty": self.unserved_penalty,
            "switch_cost": self.switch_cost,
            "degradation_cost": self.degradation_cost,
            "deviation_cost": self.deviation_cost,
            "total_cost": self.total_cost,
        }


class CostEvaluator:
    def evaluate(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> CostBreakdown:
        prep_time_min = 30
        wage_regular_jpy_per_h = 2000.0
        regular_hours_per_day = 8.0
        overtime_factor = 1.25

        weights = problem.objective_weights
        vehicle_cost = 0.0
        driver_cost = 0.0
        energy_cost = 0.0
        demand_cost = 0.0

        # Create a lookup for vehicle profiles to get their fixed costs
        vehicle_by_id = {v.vehicle_id: v for v in problem.vehicles}
        vehicle_type_by_id = {vt.vehicle_type_id: vt for vt in problem.vehicle_types}

        for duty in plan.duties:
            v_type = vehicle_type_by_id.get(duty.vehicle_type)
            fixed_use_cost = v_type.fixed_use_cost_jpy if v_type else 0.0
            vehicle_cost += weights.vehicle * fixed_use_cost
            
            # Driver cost heuristic: 2000 JPY/hr + 1hr padding
            if duty.legs:
                first_trip = duty.legs[0].trip
                last_trip = duty.legs[-1].trip
                duty_duration_min = last_trip.arrival_min - first_trip.departure_min
                total_hours = (max(0, duty_duration_min) + prep_time_min) / 60.0
                regular_hours = min(total_hours, regular_hours_per_day)
                overtime_hours = max(0.0, total_hours - regular_hours_per_day)
                driver_cost += (
                    regular_hours * wage_regular_jpy_per_h
                    + overtime_hours * wage_regular_jpy_per_h * overtime_factor
                )

            for leg in duty.legs:
                energy_cost += self._trip_energy_cost(problem, leg.trip.trip_id)
                energy_cost += self._deadhead_energy_cost(
                    problem,
                    leg.deadhead_from_prev_min,
                    leg.trip.departure_min,
                )

        slot_totals: Dict[int, float] = {}
        for slot in plan.charging_slots:
            net_kw = max(slot.charge_kw - slot.discharge_kw, 0.0)
            slot_totals[slot.slot_index] = slot_totals.get(slot.slot_index, 0.0) + net_kw
        peak_demand_kw = max(slot_totals.values(), default=0.0)
        demand_cost = weights.demand * peak_demand_kw

        baseline_map = self._trip_vehicle_type_map(problem.baseline_plan) if problem.baseline_plan else {}
        current_map = self._trip_vehicle_type_map(plan)
        switch_count = sum(
            1
            for trip_id, vehicle_type in current_map.items()
            if trip_id in baseline_map and baseline_map[trip_id] != vehicle_type
        )
        switch_cost = weights.switch * float(switch_count)

        slot_hours = max(problem.scenario.timestep_min, 1) / 60.0
        degradation_cycles = 0.0
        for slot in plan.charging_slots:
            vehicle = vehicle_by_id.get(slot.vehicle_id)
            if vehicle is None:
                continue
            capacity_kwh = max(vehicle.battery_capacity_kwh or 300.0, 1.0)
            charged_kwh = max(slot.charge_kw, 0.0) * slot_hours
            degradation_cycles += charged_kwh / capacity_kwh
        degradation_cost = weights.degradation * degradation_cycles * 50.0

        unserved_penalty = weights.unserved * len(plan.unserved_trip_ids)

        baseline_ids = set(problem.baseline_plan.served_trip_ids) if problem.baseline_plan else set()
        deviation_count = len(set(plan.served_trip_ids).symmetric_difference(baseline_ids))
        deviation_cost = weights.deviation * deviation_count

        total_cost = (
            energy_cost
            + demand_cost
            + vehicle_cost
            + driver_cost
            + unserved_penalty
            + switch_cost
            + degradation_cost
            + deviation_cost
        )
        return CostBreakdown(
            energy_cost=energy_cost,
            demand_cost=demand_cost,
            vehicle_cost=vehicle_cost,
            driver_cost=driver_cost,
            unserved_penalty=unserved_penalty,
            switch_cost=switch_cost,
            degradation_cost=degradation_cost,
            deviation_cost=deviation_cost,
            total_cost=total_cost,
        )

    def _trip_energy_cost(
        self,
        problem: CanonicalOptimizationProblem,
        trip_id: str,
    ) -> float:
        trip = problem.trip_by_id().get(trip_id)
        if trip is None:
            return 0.0

        slot_index = self._slot_index_for_departure(problem, trip.departure_min)
        selected_buy_price = self._slot_buy_price(problem, slot_index)
        selected_sell_price = self._slot_sell_price(problem, slot_index)

        timestep_h = max(problem.scenario.timestep_min, 1) / 60.0
        pv_kw_map = {slot.slot_index: slot.pv_available_kw for slot in problem.pv_slots}
        pv_kw = pv_kw_map.get(slot_index, 0.0)
        pv_kwh_available = max(pv_kw, 0.0) * timestep_h
        pv_self_consumed_kwh = min(max(trip.energy_kwh, 0.0), pv_kwh_available)

        # Self-consumed PV avoids buying from grid but forgoes sell-back revenue.
        pv_credit = pv_self_consumed_kwh * max(selected_buy_price - selected_sell_price, 0.0)
        return max(trip.energy_kwh * selected_buy_price - pv_credit, 0.0)

    def _deadhead_energy_cost(
        self,
        problem: CanonicalOptimizationProblem,
        deadhead_from_prev_min: int,
        next_trip_departure_min: int,
    ) -> float:
        if not problem.price_slots or deadhead_from_prev_min <= 0:
            return 0.0

        deadhead_departure_min = max(0, next_trip_departure_min - deadhead_from_prev_min)
        slot_index = self._slot_index_for_departure(problem, deadhead_departure_min)
        price = self._slot_buy_price(problem, slot_index)

        avg_speed_kmph = 20.0
        distance_km = (deadhead_from_prev_min / 60.0) * avg_speed_kmph
        energy_kwh = distance_km * 1.2
        return max(energy_kwh * price, 0.0)

    def _slot_buy_price(self, problem: CanonicalOptimizationProblem, slot_index: int) -> float:
        price_map = {slot.slot_index: slot.grid_buy_yen_per_kwh for slot in problem.price_slots}
        selected_price = price_map.get(slot_index)
        if selected_price is None and problem.price_slots:
            nearest_slot = min(problem.price_slots, key=lambda slot: abs(slot.slot_index - slot_index))
            selected_price = nearest_slot.grid_buy_yen_per_kwh
        return selected_price or 0.0

    def _slot_sell_price(self, problem: CanonicalOptimizationProblem, slot_index: int) -> float:
        price_map = {slot.slot_index: slot.grid_sell_yen_per_kwh for slot in problem.price_slots}
        selected_price = price_map.get(slot_index)
        if selected_price is None and problem.price_slots:
            nearest_slot = min(problem.price_slots, key=lambda slot: abs(slot.slot_index - slot_index))
            selected_price = nearest_slot.grid_sell_yen_per_kwh
        return selected_price or 0.0

    def _trip_vehicle_type_map(self, plan: AssignmentPlan | None) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        if plan is None:
            return mapping
        for duty in plan.duties:
            for trip_id in duty.trip_ids:
                mapping[trip_id] = duty.vehicle_type
        return mapping

    def _slot_index_for_departure(
        self,
        problem: CanonicalOptimizationProblem,
        departure_min: int,
    ) -> int:
        timestep_min = max(problem.scenario.timestep_min, 1)
        horizon_start = problem.scenario.horizon_start
        if not horizon_start:
            return departure_min // timestep_min

        try:
            hour_str, minute_str = horizon_start.split(":")
            start_min = int(hour_str) * 60 + int(minute_str)
        except ValueError:
            return departure_min // timestep_min

        adjusted_departure = departure_min
        if adjusted_departure < start_min:
            adjusted_departure += 24 * 60
        return (adjusted_departure - start_min) // timestep_min
