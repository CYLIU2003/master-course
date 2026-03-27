from __future__ import annotations

from dataclasses import replace

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
        model = self._builder.build(problem)
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
                "model_stats": {
                    "variables": model.variable_counts,
                    "constraints": model.constraint_counts,
                    "objective_terms": model.objective_terms,
                    "variable_samples": [variable.name for variable in model.variables[:10]],
                    "constraint_samples": [constraint.name for constraint in model.constraints[:10]],
                },
                "time_limit_sec": config.time_limit_sec,
                "mip_gap": config.mip_gap,
                "warm_start_enabled": config.warm_start,
                "warm_start_source": (
                    (problem.baseline_plan.metadata or {}).get("source")
                    if problem.baseline_plan
                    else None
                ),
            },
        )

    def _termination_reason(self, solver_status: str) -> str:
        status = str(solver_status or "").strip().lower()
        if status == "optimal":
            return "optimal"
        if status == "time_limit":
            return "time_limit"
        if status in {"infeasible", "inf_or_unbd", "unbounded"}:
            return "infeasible_or_unbounded"
        if status == "suboptimal":
            return "stopped_with_feasible"
        return "unknown"
