from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from .problem import AssignmentPlan, CanonicalOptimizationProblem


@dataclass(frozen=True)
class CostBreakdown:
    energy_cost: float = 0.0
    demand_cost: float = 0.0
    vehicle_cost: float = 0.0
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
        weights = problem.objective_weights
        vehicle_cost = 0.0
        energy_cost = 0.0
        total_charge_kw = 0.0
        for duty in plan.duties:
            vehicle_cost += weights.vehicle
            for leg in duty.legs:
                energy_cost += self._trip_energy_cost(problem, leg.trip.trip_id)
                energy_cost += self._deadhead_energy_cost(problem, leg.deadhead_from_prev_min)
        for slot in plan.charging_slots:
            total_charge_kw += max(slot.charge_kw - slot.discharge_kw, 0.0)

        unserved_penalty = weights.unserved * len(plan.unserved_trip_ids)

        baseline_ids = set(problem.baseline_plan.served_trip_ids) if problem.baseline_plan else set()
        deviation_count = len(set(plan.served_trip_ids).symmetric_difference(baseline_ids))
        deviation_cost = weights.deviation * deviation_count

        total_cost = (
            energy_cost
            + weights.demand * total_charge_kw
            + vehicle_cost
            + unserved_penalty
            + weights.switch * 0.0
            + weights.degradation * 0.0
            + deviation_cost
        )
        return CostBreakdown(
            energy_cost=energy_cost,
            demand_cost=weights.demand * total_charge_kw,
            vehicle_cost=vehicle_cost,
            unserved_penalty=unserved_penalty,
            switch_cost=0.0,
            degradation_cost=0.0,
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
        average_price = (
            sum(slot.grid_buy_yen_per_kwh for slot in problem.price_slots) / len(problem.price_slots)
            if problem.price_slots
            else 0.0
        )
        pv_credit = (
            sum(slot.pv_available_kw for slot in problem.pv_slots) / max(len(problem.pv_slots), 1)
            if problem.pv_slots
            else 0.0
        )
        return max(trip.energy_kwh * average_price - pv_credit * 0.05, 0.0)

    def _deadhead_energy_cost(
        self,
        problem: CanonicalOptimizationProblem,
        deadhead_from_prev_min: int,
    ) -> float:
        if not problem.price_slots:
            return 0.0
        average_price = sum(slot.grid_buy_yen_per_kwh for slot in problem.price_slots) / len(problem.price_slots)
        estimated_kwh = deadhead_from_prev_min * 0.2
        return estimated_kwh * average_price
