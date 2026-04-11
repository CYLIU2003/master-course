from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict

from .model_builder import MILPModelBuilder
from .solver_adapter import GurobiMILPAdapter
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.benchmarking import solver_benchmark_eligibility
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
        vehicle_fragment_counts = plan.vehicle_fragment_counts()
        vehicles_with_multiple_fragments = plan.vehicles_with_multiple_fragments()
        max_fragments_observed = plan.max_fragments_observed()
        available_vehicle_count_total = sum(
            1 for vehicle in problem.vehicles if bool(getattr(vehicle, "available", True))
        )
        unused_available_vehicle_ids = plan.unused_available_vehicle_ids(problem)
        trip_count_unserved = len(plan.unserved_trip_ids)
        secondary_objective_value = float(costs.get("objective_value", 0.0)) - float(costs.get("unserved_penalty", 0.0) or 0.0)
        allow_same_day_depot_cycles = bool(
            problem.metadata.get(
                "allow_same_day_depot_cycles",
                getattr(problem.scenario, "allow_same_day_depot_cycles", True),
            )
        )
        service_coverage_mode = str(getattr(problem.scenario, "service_coverage_mode", "strict") or "strict")
        allow_partial_service = service_coverage_mode == "penalized"
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
                "delegates_to": "none",
                "solver_display_name": "MILP",
                "solver_maturity": "core",
                "service_coverage_mode": service_coverage_mode,
                "allow_partial_service": allow_partial_service,
                "strict_coverage_enforced": service_coverage_mode == "strict",
                "same_day_depot_cycles_enabled": allow_same_day_depot_cycles,
                "max_depot_cycles_per_vehicle_per_day": int(
                    problem.metadata.get(
                        "max_depot_cycles_per_vehicle_per_day",
                        getattr(problem.scenario, "max_depot_cycles_per_vehicle_per_day", 1),
                    )
                    or 1
                ),
                "max_start_fragments_per_vehicle": int(
                    problem.metadata.get("max_start_fragments_per_vehicle") or 1
                ),
                "max_end_fragments_per_vehicle": int(
                    problem.metadata.get("max_end_fragments_per_vehicle") or 1
                ),
                "vehicle_fragment_counts": vehicle_fragment_counts,
                "vehicles_with_multiple_fragments": list(vehicles_with_multiple_fragments),
                "max_fragments_observed": int(max_fragments_observed),
                "available_vehicle_count_total": available_vehicle_count_total,
                "unused_available_vehicle_ids": list(unused_available_vehicle_ids),
                "trip_count_served": len(plan.served_trip_ids),
                "trip_count_unserved": trip_count_unserved,
                "coverage_rank_primary": trip_count_unserved,
                "secondary_objective_value": secondary_objective_value,
                "startup_infeasible_assignment_count": int(
                    (plan.metadata or {}).get("startup_infeasible_assignment_count") or 0
                ),
                "startup_infeasible_trip_ids": list(
                    (plan.metadata or {}).get("startup_infeasible_trip_ids") or []
                ),
                "startup_infeasible_vehicle_ids": list(
                    (plan.metadata or {}).get("startup_infeasible_vehicle_ids") or []
                ),
                **solver_benchmark_eligibility(
                    OptimizationMode.MILP,
                    solver_maturity="core",
                    true_solver_family="milp",
                    solver_display_name="MILP",
                ),
                "candidate_generation_mode": "exact_branch_and_cut",
                "evaluation_mode": problem.scenario.objective_mode,
                "has_feasible_incumbent": outcome.has_feasible_incumbent,
                "incumbent_count": outcome.incumbent_count,
                "warm_start_applied": outcome.warm_start_applied,
                "warm_start_source": outcome.warm_start_source or (
                    (problem.baseline_plan.metadata or {}).get("source")
                    if problem.baseline_plan
                    else None
                ),
                "best_bound": outcome.best_bound,
                "final_gap": outcome.final_gap,
                "nodes_explored": outcome.nodes_explored,
                "runtime_sec": outcome.runtime_sec,
                "first_feasible_sec": outcome.first_feasible_sec,
                "uses_exact_repair": False,
                "presolve_reduction_summary": dict(outcome.presolve_reduction_summary or {}),
                "iis_generated": outcome.iis_generated,
                "fallback_reason": outcome.fallback_reason,
                "fallback_applied": bool(outcome.fallback_reason or outcome.solver_status == "BASELINE_FALLBACK"),
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
                "search_profile": {
                    "total_wall_clock_sec": round(float(outcome.runtime_sec or 0.0), 6),
                    "first_feasible_sec": None if outcome.first_feasible_sec is None else round(float(outcome.first_feasible_sec), 6),
                    "incumbent_updates": int(outcome.incumbent_count),
                    "evaluator_calls": 0,
                    "avg_evaluator_sec": 0.0,
                    "repair_calls": 0,
                    "avg_repair_sec": 0.0,
                    "exact_repair_calls": 0,
                    "avg_exact_repair_sec": 0.0,
                    "feasible_candidate_ratio": 1.0 if outcome.has_feasible_incumbent else 0.0,
                    "rejected_candidate_ratio": 0.0 if outcome.has_feasible_incumbent else 1.0,
                    "fallback_count": 1 if outcome.fallback_reason or outcome.solver_status == "BASELINE_FALLBACK" else 0,
                },
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
