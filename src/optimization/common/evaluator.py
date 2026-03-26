from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Set, Tuple

from src.objective_modes import objective_value_for_mode

from .problem import AssignmentPlan, CanonicalOptimizationProblem, classify_peak_slots


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
    grid_to_bus_kwh: float = 0.0
    bess_to_bus_kwh: float = 0.0
    pv_to_bess_kwh: float = 0.0
    grid_to_bess_kwh: float = 0.0
    contract_over_limit_kwh: float = 0.0
    electricity_cost_final: float = 0.0
    electricity_cost_provisional_leftover: float = 0.0
    grid_purchase_cost: float = 0.0
    bess_discharge_cost: float = 0.0
    contract_overage_cost: float = 0.0
    stationary_battery_degradation_cost: float = 0.0
    pv_asset_cost: float = 0.0
    bess_asset_cost: float = 0.0
    total_cost_with_assets: float = 0.0
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
            "grid_to_bus_kwh": self.grid_to_bus_kwh,
            "bess_to_bus_kwh": self.bess_to_bus_kwh,
            "pv_to_bess_kwh": self.pv_to_bess_kwh,
            "grid_to_bess_kwh": self.grid_to_bess_kwh,
            "contract_over_limit_kwh": self.contract_over_limit_kwh,
            "electricity_cost_final": self.electricity_cost_final,
            "electricity_cost_provisional_leftover": self.electricity_cost_provisional_leftover,
            "grid_purchase_cost": self.grid_purchase_cost,
            "bess_discharge_cost": self.bess_discharge_cost,
            "contract_overage_cost": self.contract_overage_cost,
            "stationary_battery_degradation_cost": self.stationary_battery_degradation_cost,
            "pv_asset_cost": self.pv_asset_cost,
            "bess_asset_cost": self.bess_asset_cost,
            "total_cost_with_assets": self.total_cost_with_assets,
            "total_cost": self.total_cost,
            "objective_value": self.objective_value,
        }


# Driver cost heuristic constants – exposed as module-level so tests and
# future config overrides can reference them without digging into the method body.
_DRIVER_PREP_TIME_MIN: int = 30
_DRIVER_WAGE_JPY_PER_H: float = 2000.0
_DRIVER_REGULAR_HOURS_PER_DAY: float = 8.0
_DRIVER_OVERTIME_FACTOR: float = 1.25


class CostEvaluator:
    def evaluate(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> CostBreakdown:
        prep_time_min = _DRIVER_PREP_TIME_MIN
        wage_regular_jpy_per_h = _DRIVER_WAGE_JPY_PER_H
        regular_hours_per_day = _DRIVER_REGULAR_HOURS_PER_DAY
        overtime_factor = _DRIVER_OVERTIME_FACTOR

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

        operating_slot_totals = self._operating_electric_energy_kwh_by_slot(problem, plan)

        energy_cost_components = self._evaluate_electricity_with_overwrite(problem, plan, operating_slot_totals)
        energy_cost += energy_cost_components["electricity_cost_final"]
        grid_import_by_slot = self._grid_import_kwh_by_slot_from_plan(plan)
        if grid_import_by_slot:
            demand_cost = self._operating_demand_charge_cost(problem, grid_import_by_slot)
            timestep_h = max(problem.scenario.timestep_min, 1) / 60.0
            grid_import_kwh = sum(max(float(v or 0.0), 0.0) for v in grid_import_by_slot.values())
            peak_grid_kw = (
                max((max(float(v or 0.0), 0.0) / timestep_h) for v in grid_import_by_slot.values())
                if grid_import_by_slot
                else 0.0
            )
            if problem.depot_energy_assets:
                pv_generated_kwh = sum(
                    max(float(v or 0.0), 0.0)
                    for asset in problem.depot_energy_assets.values()
                    for v in asset.pv_generation_kwh_by_slot
                )
            else:
                pv_generated_kwh = 0.0
            pv_used_direct_kwh = 0.0
        else:
            demand_cost = self._operating_demand_charge_cost(problem, operating_slot_totals)
            pv_generated_kwh, pv_used_direct_kwh, grid_import_kwh, peak_grid_kw = self._pv_grid_summary(
                problem,
                operating_slot_totals,
            )
        pv_curtailed_kwh = max(
            energy_cost_components.get("pv_curtailed_kwh", 0.0),
            max(pv_generated_kwh - pv_used_direct_kwh, 0.0),
        )

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
            charged_kwh = max(slot.charge_kw, 0.0) * slot_hours
            capacity_kwh = max(float(vehicle.battery_capacity_kwh or 0.0), 1.0)
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
        total_cost_with_assets = total_cost + float(energy_cost_components.get("pv_asset_cost", 0.0)) + float(
            energy_cost_components.get("bess_asset_cost", 0.0)
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
            grid_to_bus_kwh=float(energy_cost_components.get("grid_to_bus_kwh", 0.0)),
            bess_to_bus_kwh=float(energy_cost_components.get("bess_to_bus_kwh", 0.0)),
            pv_to_bess_kwh=float(energy_cost_components.get("pv_to_bess_kwh", 0.0)),
            grid_to_bess_kwh=float(energy_cost_components.get("grid_to_bess_kwh", 0.0)),
            contract_over_limit_kwh=float(energy_cost_components.get("contract_over_limit_kwh", 0.0)),
            electricity_cost_final=float(energy_cost_components.get("electricity_cost_final", 0.0)),
            electricity_cost_provisional_leftover=float(
                energy_cost_components.get("electricity_cost_provisional_leftover", 0.0)
            ),
            grid_purchase_cost=float(energy_cost_components.get("grid_purchase_cost", 0.0)),
            bess_discharge_cost=float(energy_cost_components.get("bess_discharge_cost", 0.0)),
            contract_overage_cost=float(energy_cost_components.get("contract_overage_cost", 0.0)),
            stationary_battery_degradation_cost=float(
                energy_cost_components.get("stationary_battery_degradation_cost", 0.0)
            ),
            pv_asset_cost=float(energy_cost_components.get("pv_asset_cost", 0.0)),
            bess_asset_cost=float(energy_cost_components.get("bess_asset_cost", 0.0)),
            total_cost_with_assets=total_cost_with_assets,
            total_cost=total_cost,
            objective_value=objective_value,
        )

    def _evaluate_electricity_with_overwrite(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
        operating_slot_totals: Dict[int, float],
    ) -> Dict[str, float]:
        timestep_h = max(problem.scenario.timestep_min, 1) / 60.0

        def _sum_flow(mapping: Dict[str, Dict[int, float]]) -> float:
            return sum(max(float(v or 0.0), 0.0) for by_slot in mapping.values() for v in by_slot.values())

        grid_to_bus = {
            str(k): {int(t): float(v or 0.0) for t, v in by_slot.items()}
            for k, by_slot in (plan.grid_to_bus_kwh_by_depot_slot or {}).items()
        }
        bess_to_bus = {
            str(k): {int(t): float(v or 0.0) for t, v in by_slot.items()}
            for k, by_slot in (plan.bess_to_bus_kwh_by_depot_slot or {}).items()
        }
        pv_to_bess = {
            str(k): {int(t): float(v or 0.0) for t, v in by_slot.items()}
            for k, by_slot in (plan.pv_to_bess_kwh_by_depot_slot or {}).items()
        }
        grid_to_bess = {
            str(k): {int(t): float(v or 0.0) for t, v in by_slot.items()}
            for k, by_slot in (plan.grid_to_bess_kwh_by_depot_slot or {}).items()
        }
        pv_curtail = {
            str(k): {int(t): float(v or 0.0) for t, v in by_slot.items()}
            for k, by_slot in (plan.pv_curtail_kwh_by_depot_slot or {}).items()
        }
        contract_over_limit = {
            str(k): {int(t): float(v or 0.0) for t, v in by_slot.items()}
            for k, by_slot in (plan.contract_over_limit_kwh_by_depot_slot or {}).items()
        }

        if not grid_to_bus and not bess_to_bus:
            # Backward-compatible fallback: operating energy priced by TOU.
            fallback_cost = self._operating_electric_energy_cost(problem, operating_slot_totals)
            return {
                "electricity_cost_final": fallback_cost,
                "electricity_cost_provisional_leftover": fallback_cost,
                "grid_purchase_cost": fallback_cost,
                "bess_discharge_cost": 0.0,
                "stationary_battery_degradation_cost": 0.0,
                "pv_asset_cost": 0.0,
                "bess_asset_cost": 0.0,
                "grid_to_bus_kwh": 0.0,
                "bess_to_bus_kwh": 0.0,
                "pv_to_bess_kwh": 0.0,
                "grid_to_bess_kwh": 0.0,
                "pv_curtailed_kwh": 0.0,
                "contract_over_limit_kwh": 0.0,
                "contract_overage_cost": 0.0,
            }

        vehicle_depot = self._vehicle_to_depot(problem)
        provisional_price_by_depot = self._provisional_price_by_depot(problem)

        drive_events = self._collect_drive_energy_events(problem, plan)
        debts: Dict[str, list[tuple[float, float]]] = {}
        provisional_total = 0.0
        for vehicle_id, depot_id, _slot_idx, energy_kwh in drive_events:
            provisional_price = provisional_price_by_depot.get(depot_id, 0.0)
            debts.setdefault(vehicle_id, []).append((float(energy_kwh), provisional_price))
            provisional_total += float(energy_kwh) * provisional_price

        charge_events: list[tuple[int, str, str, float]] = []
        for slot in plan.charging_slots:
            source, depot_id = self._charging_source_and_depot(slot.charger_id, vehicle_depot.get(slot.vehicle_id, "depot_default"))
            charge_kwh = max(float(slot.charge_kw or 0.0) - max(float(slot.discharge_kw or 0.0), 0.0), 0.0) * timestep_h
            if charge_kwh <= 0.0:
                continue
            charge_events.append((int(slot.slot_index), str(slot.vehicle_id), source, charge_kwh))
        charge_events.sort(key=lambda item: item[0])

        grid_purchase_cost = 0.0
        bess_discharge_cost = 0.0
        rollback_cost = 0.0
        for slot_idx, vehicle_id, source, charge_kwh in charge_events:
            depot_id = vehicle_depot.get(vehicle_id, "depot_default")
            if source == "bess":
                asset = (problem.depot_energy_assets or {}).get(depot_id)
                bess_unit = max(float(getattr(asset, "bess_cycle_cost_yen_per_kwh", 0.0) or 0.0), 0.0)
                bess_discharge_cost += charge_kwh * bess_unit
            else:
                grid_purchase_cost += charge_kwh * self._slot_buy_price(problem, slot_idx)

            remaining = charge_kwh
            queue = debts.get(vehicle_id, [])
            new_queue: list[tuple[float, float]] = []
            for debt_kwh, prov_price in queue:
                if remaining <= 1.0e-9:
                    new_queue.append((debt_kwh, prov_price))
                    continue
                matched = min(debt_kwh, remaining)
                rollback_cost += matched * prov_price
                rest = debt_kwh - matched
                if rest > 1.0e-9:
                    new_queue.append((rest, prov_price))
                remaining -= matched
            debts[vehicle_id] = new_queue

        provisional_leftover = sum(kwh * price for queue in debts.values() for kwh, price in queue)
        electricity_cost_final = (provisional_total - rollback_cost) + grid_purchase_cost + bess_discharge_cost
        contract_over_limit_kwh = _sum_flow(contract_over_limit)
        enable_contract_overage_penalty = bool(problem.metadata.get("enable_contract_overage_penalty", True))
        contract_overage_penalty = max(
            float(problem.metadata.get("contract_overage_penalty_yen_per_kwh", 500.0) or 0.0),
            0.0,
        )
        contract_overage_cost = (
            contract_over_limit_kwh * contract_overage_penalty
            if enable_contract_overage_penalty
            else 0.0
        )
        electricity_cost_final += contract_overage_cost

        stationary_battery_degradation_cost = 0.0
        pv_asset_cost = 0.0
        bess_asset_cost = 0.0
        for asset in (problem.depot_energy_assets or {}).values():
            pv_asset_cost += self._dailyized_capex_om(
                capacity=asset.pv_capacity_kw,
                capex_unit=asset.pv_capex_jpy_per_kw,
                om_unit_year=asset.pv_om_jpy_per_kw_year,
                life_years=asset.pv_life_years,
            )
            bess_asset_cost += self._dailyized_capex_om(
                capacity=asset.bess_energy_kwh,
                capex_unit=asset.bess_capex_jpy_per_kwh,
                om_unit_year=asset.bess_om_jpy_per_kwh_year,
                life_years=asset.bess_life_years,
            )
            stationary_battery_degradation_cost += _sum_flow({asset.depot_id: bess_to_bus.get(asset.depot_id, {})}) * max(
                float(asset.bess_cycle_cost_yen_per_kwh or 0.0),
                0.0,
            )

        return {
            "electricity_cost_final": electricity_cost_final,
            "electricity_cost_provisional_leftover": provisional_leftover,
            "grid_purchase_cost": grid_purchase_cost,
            "bess_discharge_cost": bess_discharge_cost,
            "stationary_battery_degradation_cost": stationary_battery_degradation_cost,
            "pv_asset_cost": pv_asset_cost,
            "bess_asset_cost": bess_asset_cost,
            "grid_to_bus_kwh": _sum_flow(grid_to_bus),
            "bess_to_bus_kwh": _sum_flow(bess_to_bus),
            "pv_to_bess_kwh": _sum_flow(pv_to_bess),
            "grid_to_bess_kwh": _sum_flow(grid_to_bess),
            "pv_curtailed_kwh": _sum_flow(pv_curtail),
            "contract_over_limit_kwh": contract_over_limit_kwh,
            "contract_overage_cost": contract_overage_cost,
        }

    def _collect_drive_energy_events(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> list[tuple[str, str, int, float]]:
        events: list[tuple[str, str, int, float]] = []
        trip_by_id = problem.trip_by_id()
        for duty in plan.duties:
            vehicle_id = self._vehicle_id_from_duty_id(duty.duty_id)
            depot_id = self._vehicle_to_depot(problem).get(vehicle_id, "depot_default")
            for leg in duty.legs:
                trip = trip_by_id.get(leg.trip.trip_id)
                if trip is None:
                    continue
                events.append((vehicle_id, depot_id, int(trip.departure_min), max(float(trip.energy_kwh or 0.0), 0.0)))
                if leg.deadhead_from_prev_min > 0:
                    events.append(
                        (
                            vehicle_id,
                            depot_id,
                            int(trip.departure_min),
                            max(float(self._estimated_deadhead_energy_kwh(problem, leg, trip) or 0.0), 0.0),
                        )
                    )
        events.sort(key=lambda item: item[2])
        return events

    def _vehicle_to_depot(self, problem: CanonicalOptimizationProblem) -> Dict[str, str]:
        return {str(v.vehicle_id): str(v.home_depot_id or "depot_default") for v in problem.vehicles}

    def _vehicle_id_from_duty_id(self, duty_id: str) -> str:
        if duty_id.startswith("milp_") and len(duty_id) > 5:
            return duty_id[5:]
        return duty_id

    def _provisional_price_by_depot(self, problem: CanonicalOptimizationProblem) -> Dict[str, float]:
        avg_price = 0.0
        if problem.price_slots:
            avg_price = sum(float(slot.grid_buy_yen_per_kwh or 0.0) for slot in problem.price_slots) / len(problem.price_slots)
        result: Dict[str, float] = {}
        for depot in problem.depots:
            asset = (problem.depot_energy_assets or {}).get(depot.depot_id)
            configured = float(getattr(asset, "provisional_energy_cost_yen_per_kwh", 0.0) or 0.0) if asset else 0.0
            result[depot.depot_id] = configured if configured > 0.0 else avg_price
        if not result:
            result["depot_default"] = avg_price
        return result

    def _charging_source_and_depot(self, charger_id: str | None, fallback_depot_id: str) -> tuple[str, str]:
        raw = str(charger_id or "")
        if ":" in raw:
            source, depot_id = raw.split(":", 1)
            source_norm = source.strip().lower()
            if source_norm in {"grid", "bess"}:
                return source_norm, depot_id.strip() or fallback_depot_id
        return "grid", fallback_depot_id

    def _dailyized_capex_om(self, capacity: float, capex_unit: float, om_unit_year: float, life_years: int) -> float:
        cap = max(float(capacity or 0.0), 0.0)
        capex = max(float(capex_unit or 0.0), 0.0)
        om = max(float(om_unit_year or 0.0), 0.0)
        life = max(int(life_years or 1), 1)
        return (cap * capex) / (365.0 * life) + (cap * om) / 365.0

    def _grid_import_kwh_by_slot_from_plan(self, plan: AssignmentPlan) -> Dict[int, float]:
        merged: Dict[int, float] = {}
        for by_slot in (plan.grid_to_bus_kwh_by_depot_slot or {}).values():
            for slot_idx, value in by_slot.items():
                merged[int(slot_idx)] = merged.get(int(slot_idx), 0.0) + max(float(value or 0.0), 0.0)
        for by_slot in (plan.grid_to_bess_kwh_by_depot_slot or {}).values():
            for slot_idx, value in by_slot.items():
                merged[int(slot_idx)] = merged.get(int(slot_idx), 0.0) + max(float(value or 0.0), 0.0)
        return merged

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

        distance_km = self._deadhead_distance_km(problem, deadhead_from_prev_min)
        fuel_l = distance_km * fuel_rate
        return max(problem.scenario.diesel_price_yen_per_l, 0.0) * fuel_l

    def _deadhead_distance_km(
        self,
        problem: CanonicalOptimizationProblem,
        deadhead_min: int,
    ) -> float:
        speed_kmh = self._safe_nonnegative_float(
            (problem.metadata or {}).get("deadhead_speed_kmh"),
            default=18.0,
        )
        return max(float(deadhead_min or 0), 0.0) * speed_kmh / 60.0

    def _safe_nonnegative_float(self, value: object, *, default: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return default
        return parsed if parsed >= 0.0 else default

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
                        self._estimated_deadhead_energy_kwh(problem, leg, trip_info),
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
        return classify_peak_slots(problem.price_slots)

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

    def _estimated_deadhead_energy_kwh(
        self,
        problem: CanonicalOptimizationProblem,
        leg: DutyLeg,
        trip_info: object | None,
    ) -> float:
        if leg.deadhead_from_prev_min <= 0:
            return 0.0
        distance_km = self._deadhead_distance_km(problem, leg.deadhead_from_prev_min)
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
                    dh_km = self._deadhead_distance_km(problem, leg.deadhead_from_prev_min)
                    total_co2_kg += ice_co2_kg_per_l * dh_km * fuel_rate

        # BEV electricity CO2: prefer actual grid-import flows (Grid->Bus + Grid->BESS).
        grid_import_by_slot = self._grid_import_kwh_by_slot_from_plan(plan)
        if grid_import_by_slot and problem.price_slots:
            co2_factor_map = {slot.slot_index: slot.co2_factor for slot in problem.price_slots}
            for slot_idx, imported_kwh in grid_import_by_slot.items():
                co2_factor = co2_factor_map.get(slot_idx, 0.0)
                if co2_factor <= 0:
                    continue
                total_co2_kg += co2_factor * max(imported_kwh, 0.0)
        # Backward-compatible fallback.
        elif slot_totals_kwh and problem.price_slots:
            co2_factor_map = {slot.slot_index: slot.co2_factor for slot in problem.price_slots}
            for slot_idx, energy_kwh in slot_totals_kwh.items():
                co2_factor = co2_factor_map.get(slot_idx, 0.0)
                if co2_factor <= 0:
                    continue
                total_co2_kg += co2_factor * max(energy_kwh, 0.0)

        return total_co2_kg
