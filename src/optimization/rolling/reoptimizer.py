from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Optional

from src.optimization.common.problem import CanonicalOptimizationProblem, OptimizationConfig
from src.optimization.engine import OptimizationEngine
from .state_locking import lock_started_trips


class RollingReoptimizer:
    def __init__(self) -> None:
        self._engine = OptimizationEngine()

    def reoptimize(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
        current_min: int,
        actual_soc: Optional[Mapping[str, float]] = None,
    ):
        if actual_soc:
            problem = self._apply_actual_soc(problem, actual_soc)

        if problem.baseline_plan is not None:
            locked_plan = lock_started_trips(problem.baseline_plan, current_min)
            problem = CanonicalOptimizationProblem(
                scenario=problem.scenario,
                dispatch_context=problem.dispatch_context,
                trips=problem.trips,
                vehicles=problem.vehicles,
                chargers=problem.chargers,
                price_slots=problem.price_slots,
                pv_slots=problem.pv_slots,
                feasible_connections=problem.feasible_connections,
                objective_weights=problem.objective_weights,
                baseline_plan=locked_plan,
                metadata=dict(problem.metadata),
            )
        return self._engine.solve(problem, config)

    def _apply_actual_soc(
        self,
        problem: CanonicalOptimizationProblem,
        actual_soc: Mapping[str, float],
    ) -> CanonicalOptimizationProblem:
        applied = 0
        updated_vehicles = []
        for vehicle in problem.vehicles:
            if vehicle.vehicle_id not in actual_soc:
                updated_vehicles.append(vehicle)
                continue
            raw = float(actual_soc[vehicle.vehicle_id])
            capacity = float(vehicle.battery_capacity_kwh or 0.0)
            if 0.0 <= raw <= 1.0 and capacity > 0.0:
                value = raw * capacity
            else:
                value = raw
            if capacity > 0.0:
                value = min(max(value, 0.0), capacity)
            updated_vehicles.append(replace(vehicle, initial_soc=value))
            applied += 1

        new_metadata = dict(problem.metadata)
        new_metadata["rolling_actual_soc_applied_count"] = int(applied)
        return CanonicalOptimizationProblem(
            scenario=problem.scenario,
            dispatch_context=problem.dispatch_context,
            trips=problem.trips,
            routes=problem.routes,
            depots=problem.depots,
            vehicle_types=problem.vehicle_types,
            vehicles=tuple(updated_vehicles),
            chargers=problem.chargers,
            price_slots=problem.price_slots,
            pv_slots=problem.pv_slots,
            depot_energy_assets=problem.depot_energy_assets,
            feasible_connections=problem.feasible_connections,
            objective_weights=problem.objective_weights,
            baseline_plan=problem.baseline_plan,
            metadata=new_metadata,
        )
