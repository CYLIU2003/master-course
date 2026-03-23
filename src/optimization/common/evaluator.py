from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Set, Tuple

from src.objective_modes import objective_value_for_mode

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
    co2_cost: float = 0.0
    total_co2_kg: float = 0.0
    utilization_score: float = 0.0
    pv_generated_kwh: float = 0.0
    pv_used_direct_kwh: float = 0.0
    pv_curtailed_kwh: float = 0.0
    grid_import_kwh: float = 0.0
    peak_grid_kw: float = 0.0
    total_cost: float = 0.0
    objective_value: float = 0.0

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
            "co2_cost": self.co2_cost,
            "total_co2_kg": self.total_co2_kg,
            "utilization_score": self.utilization_score,
            "pv_generated_kwh": self.pv_generated_kwh,
            "pv_used_direct_kwh": self.pv_used_direct_kwh,
            "pv_curtailed_kwh": self.pv_curtailed_kwh,
            "grid_import_kwh": self.grid_import_kwh,
            "peak_grid_kw": self.peak_grid_kw,
            "total_cost": self.total_cost,
            "objective_value": self.objective_value,
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
                # O1: apply fuel cost for non-electric powertrains.
                if self._is_non_electric_powertrain(duty.vehicle_type, vehicle_type_by_id):
                    energy_cost += self._trip_fuel_cost(problem, duty.vehicle_type, leg.trip.trip_id)
                    energy_cost += self._deadhead_fuel_cost(
                        problem,
                        duty.vehicle_type,
                        leg.deadhead_from_prev_min,
                    )

        charge_slot_totals: Dict[int, float] = {}
        for slot in plan.charging_slots:
            net_kw = max(slot.charge_kw - slot.discharge_kw, 0.0)
            charge_slot_totals[slot.slot_index] = charge_slot_totals.get(slot.slot_index, 0.0) + net_kw

        operating_slot_totals = self._operating_electric_energy_kwh_by_slot(problem, plan)
        energy_cost += self._operating_electric_energy_cost(problem, operating_slot_totals)
        demand_cost = self._operating_demand_charge_cost(problem, operating_slot_totals)
        pv_generated_kwh, pv_used_direct_kwh, grid_import_kwh, peak_grid_kw = self._pv_grid_summary(
            problem,
            operating_slot_totals,
        )
        pv_curtailed_kwh = max(pv_generated_kwh - pv_used_direct_kwh, 0.0)

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

        # CO₂ metrics: calculate from ICE fuel and grid electricity.
        total_co2_kg = self._total_co2_kg(problem, plan, operating_slot_totals)
        co2_cost = max(problem.scenario.co2_price_per_kg, 0.0) * total_co2_kg

        total_vehicle_count = max(len(problem.vehicles), 1)
        used_vehicle_count = sum(1 for duty in plan.duties if duty.legs)
        utilization_score = float(used_vehicle_count) / float(total_vehicle_count)

        objective_weights = {
            "electricity_cost": float(weights.energy),
            "demand_charge_cost": float(weights.demand),
            "vehicle_fixed_cost": float(weights.vehicle),
            "unserved_penalty": float(weights.unserved),
            "switch_cost": float(weights.switch),
            "degradation": float(weights.degradation),
            "deviation_cost": float(weights.deviation),
            "utilization": float(weights.utilization),
        }

        total_cost = (
            energy_cost
            + demand_cost
            + vehicle_cost
            + driver_cost
            + unserved_penalty
            + switch_cost
            + degradation_cost
            + deviation_cost
            + co2_cost
        )
        objective_value = objective_value_for_mode(
            objective_mode=problem.scenario.objective_mode,
            total_cost=total_cost,
            total_co2_kg=total_co2_kg,
            unserved_penalty=unserved_penalty,
            switch_cost=switch_cost,
            degradation_cost=degradation_cost,
            deviation_cost=deviation_cost,
            utilization_score=utilization_score,
            objective_weights=objective_weights,
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
            co2_cost=co2_cost,
            total_co2_kg=total_co2_kg,
            utilization_score=utilization_score,
            pv_generated_kwh=pv_generated_kwh,
            pv_used_direct_kwh=pv_used_direct_kwh,
            pv_curtailed_kwh=pv_curtailed_kwh,
            grid_import_kwh=grid_import_kwh,
            peak_grid_kw=peak_grid_kw,
            total_cost=total_cost,
            objective_value=objective_value,
        )

    def _pv_grid_summary(
        self,
        problem: CanonicalOptimizationProblem,
        slot_totals_kwh: Dict[int, float],
    ) -> Tuple[float, float, float, float]:
        if not problem.price_slots:
            return 0.0, 0.0, 0.0, 0.0
        timestep_h = max(problem.scenario.timestep_min, 1) / 60.0
        pv_by_slot_kwh = {
            slot.slot_index: max(float(slot.pv_available_kw or 0.0), 0.0) * timestep_h
            for slot in problem.pv_slots
        }
        pv_generated_kwh = 0.0
        pv_used_direct_kwh = 0.0
        grid_import_kwh = 0.0
        peak_grid_kw = 0.0
        for slot in problem.price_slots:
            slot_idx = slot.slot_index
            load_kwh = max(float(slot_totals_kwh.get(slot_idx, 0.0) or 0.0), 0.0)
            pv_kwh = max(float(pv_by_slot_kwh.get(slot_idx, 0.0) or 0.0), 0.0)
            used_pv_kwh = min(load_kwh, pv_kwh)
            import_kwh = max(load_kwh - used_pv_kwh, 0.0)
            pv_generated_kwh += pv_kwh
            pv_used_direct_kwh += used_pv_kwh
            grid_import_kwh += import_kwh
            peak_grid_kw = max(peak_grid_kw, import_kwh / timestep_h)
        return pv_generated_kwh, pv_used_direct_kwh, grid_import_kwh, peak_grid_kw

    def _trip_fuel_cost(
        self,
        problem: CanonicalOptimizationProblem,
        vehicle_type: str,
        trip_id: str,
    ) -> float:
        trip = problem.trip_by_id().get(trip_id)
        if trip is None:
            return 0.0

        fuel_rate = self._fuel_rate_l_per_km(problem, vehicle_type)
        fuel_l = max(trip.fuel_l, 0.0)
        if fuel_l <= 0.0 and fuel_rate > 0.0:
            fuel_l = max(trip.distance_km, 0.0) * fuel_rate
        return max(problem.scenario.diesel_price_yen_per_l, 0.0) * fuel_l

    def _deadhead_fuel_cost(
        self,
        problem: CanonicalOptimizationProblem,
        vehicle_type: str,
        deadhead_from_prev_min: int,
    ) -> float:
        if deadhead_from_prev_min <= 0:
            return 0.0

        fuel_rate = self._fuel_rate_l_per_km(problem, vehicle_type)
        if fuel_rate <= 0.0:
            return 0.0

        avg_speed_kmph = 20.0
        distance_km = (deadhead_from_prev_min / 60.0) * avg_speed_kmph
        fuel_l = distance_km * fuel_rate
        return max(problem.scenario.diesel_price_yen_per_l, 0.0) * fuel_l

    def _operating_electric_energy_kwh_by_slot(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> Dict[int, float]:
        slot_totals_kwh: Dict[int, float] = {}
        vehicle_type_by_id = {vt.vehicle_type_id: vt for vt in problem.vehicle_types}
        for duty in plan.duties:
            vt = vehicle_type_by_id.get(duty.vehicle_type)
            powertrain = str(getattr(vt, "powertrain_type", "") or duty.vehicle_type).upper()
            if powertrain not in {"BEV", "PHEV", "FCEV"}:
                continue
            for leg in duty.legs:
                trip_info = problem.trip_by_id().get(leg.trip.trip_id)
                trip_energy_kwh = max(getattr(trip_info, "energy_kwh", 0.0) or 0.0, 0.0)
                self._distribute_energy_to_trip_slots(
                    problem,
                    leg.trip.departure_min,
                    leg.trip.arrival_min,
                    trip_energy_kwh,
                    slot_totals_kwh,
                )
                if leg.deadhead_from_prev_min > 0:
                    self._distribute_energy_to_single_slot(
                        problem,
                        leg.trip.departure_min,
                        self._estimated_deadhead_energy_kwh(leg, trip_info),
                        slot_totals_kwh,
                    )
        return slot_totals_kwh

    def _operating_electric_energy_cost(
        self,
        problem: CanonicalOptimizationProblem,
        slot_totals_kwh: Dict[int, float],
    ) -> float:
        if not slot_totals_kwh:
            return 0.0
        total_cost = 0.0
        for slot_idx, energy_kwh in slot_totals_kwh.items():
            total_cost += max(energy_kwh, 0.0) * self._slot_buy_price(problem, slot_idx)
        return total_cost

    def _operating_demand_charge_cost(
        self,
        problem: CanonicalOptimizationProblem,
        slot_totals_kwh: Dict[int, float],
    ) -> float:
        if not slot_totals_kwh or not problem.price_slots:
            return 0.0

        timestep_h = max(problem.scenario.timestep_min, 1) / 60.0
        on_peak_slots, off_peak_slots = self._classify_peak_slots(problem)
        on_peak = [
            max(slot_totals_kwh.get(idx, 0.0), 0.0) / timestep_h
            for idx in on_peak_slots
        ]
        off_peak = [
            max(slot_totals_kwh.get(idx, 0.0), 0.0) / timestep_h
            for idx in off_peak_slots
        ]
        w_on = max(on_peak, default=0.0)
        w_off = max(off_peak, default=0.0)
        return (
            max(problem.scenario.demand_charge_on_peak_yen_per_kw, 0.0) * w_on
            + max(problem.scenario.demand_charge_off_peak_yen_per_kw, 0.0) * w_off
        )

    def _classify_peak_slots(self, problem: CanonicalOptimizationProblem) -> Tuple[Set[int], Set[int]]:
        if not problem.price_slots:
            return set(), set()

        explicit_slots = [
            slot for slot in problem.price_slots if abs(float(slot.demand_charge_weight or 0.0)) > 1.0e-9
        ]
        if explicit_slots:
            on_peak = {
                slot.slot_index
                for slot in problem.price_slots
                if float(slot.demand_charge_weight or 0.0) > 0.0
            }
            off_peak = {slot.slot_index for slot in problem.price_slots if slot.slot_index not in on_peak}
            return on_peak, off_peak

        sorted_prices = sorted(float(slot.grid_buy_yen_per_kwh or 0.0) for slot in problem.price_slots)
        threshold = sorted_prices[len(sorted_prices) // 2] if sorted_prices else 0.0
        on_peak = {
            slot.slot_index
            for slot in problem.price_slots
            if float(slot.grid_buy_yen_per_kwh or 0.0) >= threshold
        }
        off_peak = {slot.slot_index for slot in problem.price_slots if slot.slot_index not in on_peak}
        return on_peak, off_peak

    def _is_non_electric_powertrain(
        self,
        vehicle_type: str,
        vehicle_type_by_id: Dict[str, object],
    ) -> bool:
        vt = vehicle_type_by_id.get(vehicle_type)
        powertrain = getattr(vt, "powertrain_type", "") if vt else ""
        return str(powertrain).upper() not in {"BEV", "PHEV", "FCEV"}

    def _fuel_rate_l_per_km(
        self,
        problem: CanonicalOptimizationProblem,
        vehicle_type: str,
    ) -> float:
        vt = next((item for item in problem.vehicle_types if item.vehicle_type_id == vehicle_type), None)
        if vt and vt.fuel_consumption_l_per_km is not None:
            return max(vt.fuel_consumption_l_per_km, 0.0)
        return 0.0

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

    def _distribute_energy_to_trip_slots(
        self,
        problem: CanonicalOptimizationProblem,
        departure_min: int,
        arrival_min: int,
        total_energy_kwh: float,
        slot_totals_kwh: Dict[int, float],
    ) -> None:
        if total_energy_kwh <= 0.0:
            return
        slot_indices = self._slot_indices_for_interval(problem, departure_min, arrival_min)
        if not slot_indices:
            return
        energy_per_slot = total_energy_kwh / len(slot_indices)
        for slot_idx in slot_indices:
            slot_totals_kwh[slot_idx] = slot_totals_kwh.get(slot_idx, 0.0) + energy_per_slot

    def _distribute_energy_to_single_slot(
        self,
        problem: CanonicalOptimizationProblem,
        reference_min: int,
        energy_kwh: float,
        slot_totals_kwh: Dict[int, float],
    ) -> None:
        if energy_kwh <= 0.0:
            return
        slot_idx = self._slot_index_for_departure(problem, reference_min)
        slot_totals_kwh[slot_idx] = slot_totals_kwh.get(slot_idx, 0.0) + energy_kwh

    def _slot_indices_for_interval(
        self,
        problem: CanonicalOptimizationProblem,
        departure_min: int,
        arrival_min: int,
    ) -> Tuple[int, ...]:
        start_idx = self._slot_index_for_departure(problem, departure_min)
        adjusted_arrival = max(arrival_min - 1, departure_min)
        end_idx = self._slot_index_for_departure(problem, adjusted_arrival)
        if end_idx < start_idx:
            end_idx = start_idx
        return tuple(range(start_idx, end_idx + 1))

    def _estimated_deadhead_energy_kwh(self, leg: DutyLeg, trip_info: object | None) -> float:
        if leg.deadhead_from_prev_min <= 0:
            return 0.0
        distance_km = (leg.deadhead_from_prev_min / 60.0) * 20.0
        trip_distance = max(float(getattr(trip_info, "distance_km", 0.0) or 0.0), 1.0e-6)
        energy_per_km = max(float(getattr(trip_info, "energy_kwh", 0.0) or 0.0), 0.0) / trip_distance
        return distance_km * energy_per_km

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

    def _total_co2_kg(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
        slot_totals_kwh: Dict[int, float],
    ) -> float:
        ice_co2_kg_per_l = max(problem.scenario.ice_co2_kg_per_l, 0.0)
        vehicle_type_by_id = {vt.vehicle_type_id: vt for vt in problem.vehicle_types}
        total_co2_kg = 0.0

        # ICE trip and deadhead fuel CO₂.
        for duty in plan.duties:
            if not self._is_non_electric_powertrain(duty.vehicle_type, vehicle_type_by_id):
                continue
            for leg in duty.legs:
                fuel_rate = self._fuel_rate_l_per_km(problem, duty.vehicle_type)
                # Trip fuel CO₂.
                trip = problem.trip_by_id().get(leg.trip.trip_id)
                if trip is not None:
                    fuel_l = max(trip.fuel_l, 0.0)
                    if fuel_l <= 0 and fuel_rate > 0:
                        fuel_l = max(trip.distance_km, 0.0) * fuel_rate
                    total_co2_kg += ice_co2_kg_per_l * fuel_l
                # Deadhead fuel CO₂.
                if leg.deadhead_from_prev_min > 0 and fuel_rate > 0:
                    dh_km = (leg.deadhead_from_prev_min / 60.0) * 20.0
                    total_co2_kg += ice_co2_kg_per_l * dh_km * fuel_rate

        # BEV traction electricity CO₂.
        if slot_totals_kwh and problem.price_slots:
            co2_factor_map = {slot.slot_index: slot.co2_factor for slot in problem.price_slots}
            for slot_idx, energy_kwh in slot_totals_kwh.items():
                co2_factor = co2_factor_map.get(slot_idx, 0.0)
                if co2_factor <= 0:
                    continue
                total_co2_kg += co2_factor * max(energy_kwh, 0.0)

        return total_co2_kg
