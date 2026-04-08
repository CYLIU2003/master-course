from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict

from .model_builder import MILPModelBuilder
from .solver_adapter import GurobiMILPAdapter
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationEngineResult,
    OptimizationMode,
)


class MILPOptimizer:
    def __init__(self) -> None:
        self._builder = MILPModelBuilder()
        self._adapter = GurobiMILPAdapter()
        self._feasibility = FeasibilityChecker()
        self._evaluator = CostEvaluator()

    def solve(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> OptimizationEngineResult:
        model_stats = self._lightweight_model_stats(problem)
        outcome, plan = self._adapter.solve(problem, config)
        report = self._feasibility.evaluate(problem, plan)
        breakdown = self._evaluator.evaluate(problem, plan)
        vehicle_ledger, daily_ledger = self._evaluator.build_plan_ledgers(problem, plan, breakdown)
        plan = replace(plan, vehicle_cost_ledger=vehicle_ledger, daily_cost_ledger=daily_ledger)
        costs = breakdown.to_dict()
        return OptimizationEngineResult(
            mode=OptimizationMode.MILP,
            solver_status=outcome.solver_status,
            objective_value=costs["objective_value"],
            plan=plan,
            feasible=report.feasible,
            warnings=report.warnings,
            infeasibility_reasons=report.errors,
            cost_breakdown=costs,
            solver_metadata={
                "backend": outcome.used_backend,
                "supports_exact_milp": outcome.supports_exact_milp,
                "true_solver_family": "milp",
                "independent_implementation": True,
                "has_feasible_incumbent": outcome.has_feasible_incumbent,
                "incumbent_count": outcome.incumbent_count,
                "warm_start_applied": outcome.warm_start_applied,
                "warm_start_source": outcome.warm_start_source or (
                    (problem.baseline_plan.metadata or {}).get("source")
                    if problem.baseline_plan
                    else None
                ),
                "objective_mode": problem.scenario.objective_mode,
                "objective_weights": {
                    "electricity_cost": float(problem.objective_weights.energy),
                    "demand_charge_cost": float(problem.objective_weights.demand),
                    "vehicle_fixed_cost": float(problem.objective_weights.vehicle),
                    "unserved_penalty": float(problem.objective_weights.unserved),
                    "switch_cost": float(problem.objective_weights.switch),
                    "deviation_cost": float(problem.objective_weights.deviation),
                    "degradation": float(problem.objective_weights.degradation),
                    "utilization": float(problem.objective_weights.utilization),
                },
                "termination_reason": self._termination_reason(outcome.solver_status),
                "effective_limits": {
                    "time_limit_sec": int(config.time_limit_sec),
                    "mip_gap": float(config.mip_gap),
                },
                "model_stats": model_stats,
                "time_limit_sec": config.time_limit_sec,
                "mip_gap": config.mip_gap,
                "warm_start_enabled": config.warm_start,
            },
        )

    def _termination_reason(self, solver_status: str) -> str:
        status = str(solver_status or "").strip().lower()
        if status == "optimal":
            return "optimal"
        if status in {"time_limit", "time_limit_baseline"}:
            return "time_limit"
        if status in {"infeasible", "inf_or_unbd", "unbounded"}:
            return "infeasible_or_unbounded"
        if status == "suboptimal":
            return "stopped_with_feasible"
        if status == "auto_relaxed_baseline":
            return "baseline_after_relax"
        return "unknown"

    def _lightweight_model_stats(
        self,
        problem: CanonicalOptimizationProblem,
    ) -> Dict[str, Any]:
        trip_by_id = problem.trip_by_id()
        assignment_pairs = self._builder.enumerate_assignment_pairs(problem)
        arc_pairs = self._builder.enumerate_arc_pairs(problem, trip_by_id)
        price_slot_count = len(problem.price_slots)
        bev_vehicle_count = sum(
            1
            for vehicle in problem.vehicles
            if str(vehicle.vehicle_type).upper() in {"BEV", "PHEV", "FCEV"}
        )
        return {
            "variables": {
                "assignment": len(assignment_pairs),
                "connection": len(arc_pairs),
                "start_arc": len(assignment_pairs),
                "end_arc": len(assignment_pairs),
                "unserved": len(problem.trips),
                "used_vehicle": len(problem.vehicles),
                "charge_kw": bev_vehicle_count * price_slot_count,
                "discharge_kw": bev_vehicle_count * price_slot_count,
                "soc_kwh": bev_vehicle_count * price_slot_count,
                "grid_import_kw": price_slot_count,
                "grid_export_kw": price_slot_count,
                "pv_use_kw": price_slot_count,
            },
            "constraints": {
                "trip_cover": len(problem.trips),
                "vehicle_use_link": len(assignment_pairs),
                "connection_link": len(arc_pairs) * 2,
            },
            "objective_terms": (),
            "variable_samples": [],
            "constraint_samples": [],
        }
