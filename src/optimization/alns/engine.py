from __future__ import annotations

import random
import time
from dataclasses import replace
from typing import Callable, Dict

from .acceptance import (
    AcceptanceCriterion,
    BeeColonyAcceptance,
    GeneticLikeAcceptance,
    HillClimbingAcceptance,
    SimulatedAnnealingAcceptance,
)
from .local_search import identity_local_search
from .operators_destroy import (
    peak_hour_removal,
    random_trip_removal,
    unlocked_future_only_removal,
    vehicle_path_removal,
    worst_trip_removal,
)
from .operators_repair import (
    baseline_dispatch_repair,
    charger_reassignment_repair,
    energy_aware_insertion,
    greedy_trip_insertion,
    partial_milp_repair,
    regret_k_insertion,
    soc_repair,
)
from .selection import AdaptiveRouletteSelector, OperatorSelector, UniformRandomSelector
from .stopping import CompositeStop
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    IncumbentSnapshot,
    OptimizationConfig,
    OptimizationEngineResult,
    OptimizationMode,
    OperatorStats,
    SolutionState,
)


class ALNSOptimizer:
    def __init__(self) -> None:
        self._feasibility = FeasibilityChecker()
        self._evaluator = CostEvaluator()

    def solve(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
        initial_state: SolutionState | None = None,
    ) -> OptimizationEngineResult:
        rng = random.Random(config.random_seed)
        selector = self._make_selector(config)
        if isinstance(selector, AdaptiveRouletteSelector):
            selector.weights = self._default_selector_weights()
        destroy_ops: Dict[str, Callable[..., object]] = {
            "random_trip_removal": lambda plan: random_trip_removal(plan, rng, config.destroy_fraction),
            "peak_hour_removal": lambda plan: peak_hour_removal(
                plan,
                rng,
                config.destroy_fraction,
                problem=problem,
                use_data_driven_peak=bool(config.use_data_driven_peak_removal),
                fallback_windows_min=tuple(config.peak_hour_windows_min),
            ),
            "worst_trip_removal": lambda plan: worst_trip_removal(
                plan,
                rng,
                config.destroy_fraction,
                objective_fn=(
                    (lambda p: self._evaluator.evaluate(problem, p).objective_value)
                    if str(config.worst_trip_scoring).lower() == "marginal_cost"
                    else None
                ),
            ),
            "vehicle_path_removal": lambda plan: vehicle_path_removal(plan, rng, config.destroy_fraction),
            "unlocked_future_only_removal": lambda plan: unlocked_future_only_removal(
                plan,
                rng,
                config.destroy_fraction,
                config.rolling_current_min,
            ),
        }
        repair_ops: Dict[str, Callable[..., object]] = {
            "greedy_trip_insertion": greedy_trip_insertion,
            "regret_k_insertion": regret_k_insertion,
            "energy_aware_insertion": energy_aware_insertion,
            "baseline_dispatch_repair": baseline_dispatch_repair,
            "charger_reassignment_repair": charger_reassignment_repair,
            "soc_repair": soc_repair,
            "partial_milp_repair": lambda problem, plan: partial_milp_repair(problem, plan, config=config),
        }
        acceptance = self._make_acceptance(config)
        stopper = CompositeStop(
            max_iterations=config.alns_iterations,
            max_runtime_sec=config.time_limit_sec,
            no_improvement_limit=config.no_improvement_limit,
        )
        incumbent = initial_state or self._make_state(problem, problem.baseline_plan)
        best = incumbent
        iteration = 0
        no_improve = 0
        started_at = time.perf_counter()
        operator_stats = {
            name: OperatorStats()
            for name in [*destroy_ops.keys(), *repair_ops.keys()]
        }
        incumbent_history = [
            IncumbentSnapshot(
                iteration=0,
                objective_value=best.objective(),
                feasible=best.is_feasible(),
            )
        ]
        accepted_count = 0
        rejected_count = 0

        while not stopper.should_stop(iteration, no_improve, started_at):
            destroy_name = selector.choose(destroy_ops.keys(), rng)
            repair_name = selector.choose(repair_ops.keys(), rng)
            operator_stats[destroy_name] = replace(
                operator_stats[destroy_name],
                selected=operator_stats[destroy_name].selected + 1,
            )
            operator_stats[repair_name] = replace(
                operator_stats[repair_name],
                selected=operator_stats[repair_name].selected + 1,
            )
            destroyed_plan = destroy_ops[destroy_name](incumbent.plan)
            repaired_plan = repair_ops[repair_name](problem, destroyed_plan)
            candidate_plan = identity_local_search(repaired_plan)
            candidate = self._make_state(problem, candidate_plan)

            if acceptance.accept(candidate, incumbent, best, rng):
                incumbent = candidate
                accepted_count += 1
                reward = 2.0
                # Feasibility-first comparison:
                # 1. If best is infeasible and candidate is feasible, always prefer candidate
                # 2. If both feasible, prefer lower objective
                # 3. If both infeasible, prefer lower objective (less penalty)
                is_new_best = False
                if not best.is_feasible() and candidate.is_feasible():
                    # Major improvement: found a feasible solution!
                    is_new_best = True
                    reward = 10.0  # Higher reward for achieving feasibility
                elif candidate.is_feasible() and best.is_feasible() and candidate.objective() < best.objective():
                    # Both feasible, candidate has better objective
                    is_new_best = True
                    reward = 5.0
                elif not candidate.is_feasible() and not best.is_feasible() and candidate.objective() < best.objective():
                    # Both infeasible but candidate has less penalty
                    is_new_best = True
                    reward = 3.0
                
                if is_new_best:
                    best = candidate
                    no_improve = 0
                    incumbent_history.append(
                        IncumbentSnapshot(
                            iteration=iteration + 1,
                            objective_value=best.objective(),
                            feasible=best.is_feasible(),
                        )
                    )
                else:
                    no_improve += 1
                selector.update(destroy_name, reward)
                selector.update(repair_name, reward)
                operator_stats[destroy_name] = replace(
                    operator_stats[destroy_name],
                    accepted=operator_stats[destroy_name].accepted + 1,
                    reward=operator_stats[destroy_name].reward + reward,
                )
                operator_stats[repair_name] = replace(
                    operator_stats[repair_name],
                    accepted=operator_stats[repair_name].accepted + 1,
                    reward=operator_stats[repair_name].reward + reward,
                )
            else:
                rejected_count += 1
                no_improve += 1
                selector.update(destroy_name, 0.5)
                selector.update(repair_name, 0.5)
                operator_stats[destroy_name] = replace(
                    operator_stats[destroy_name],
                    rejected=operator_stats[destroy_name].rejected + 1,
                    reward=operator_stats[destroy_name].reward + 0.5,
                )
                operator_stats[repair_name] = replace(
                    operator_stats[repair_name],
                    rejected=operator_stats[repair_name].rejected + 1,
                    reward=operator_stats[repair_name].reward + 0.5,
                )
            iteration += 1

        # Map to 4-category result classification
        has_incumbent = len(incumbent_history) > 0
        if best.is_feasible() and has_incumbent:
            result_category = "SOLVED_FEASIBLE"
        elif not best.is_feasible() and has_incumbent:
            result_category = "SOLVED_INFEASIBLE"
        elif not has_incumbent:
            result_category = "NO_INCUMBENT"
        else:
            result_category = "feasible" if best.is_feasible() else "infeasible_candidate"

        return OptimizationEngineResult(
            mode=OptimizationMode.ALNS,
            solver_status=result_category,
            objective_value=best.objective(),
            plan=best.plan,
            feasible=best.is_feasible(),
            warnings=(),
            infeasibility_reasons=best.infeasibility_reasons,
            cost_breakdown=best.cost_breakdown,
            solver_metadata={
                "final_plan_metadata": dict(best.plan.metadata or {}),
                "last_repair_operator": str((best.plan.metadata or {}).get("repair_operator") or ""),
                "partial_milp_repair_settings": (best.plan.metadata or {}).get("partial_milp_repair_settings"),
                "partial_milp_repair_target_trip_ids": (best.plan.metadata or {}).get(
                    "partial_milp_repair_target_trip_ids"
                ),
                "iterations": iteration,
                "true_solver_family": "alns",  # This is the true ALNS implementation
                "independent_implementation": True,  # True independent solver
                "has_feasible_incumbent": best.is_feasible(),
                "incumbent_count": len(incumbent_history),
                "best_destroy_operator": max(
                    destroy_ops.keys(),
                    key=lambda name: (
                        operator_stats[name].accepted,
                        operator_stats[name].selected,
                        name,
                    ),
                ),
                "acceptance_strategy": str(config.acceptance or "simulated_annealing"),
                "operator_selection_strategy": str(config.operator_selection or "adaptive_roulette"),
                "accepted_neighborhoods": accepted_count,
                "rejected_neighborhoods": rejected_count,
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
                "termination_reason": (
                    "iteration_limit" if iteration >= int(config.alns_iterations) else "time_limit_or_early_stop"
                ),
                "effective_limits": {
                    "time_limit_sec": int(config.time_limit_sec),
                    "alns_iterations": int(config.alns_iterations),
                    "no_improvement_limit": int(config.no_improvement_limit),
                },
            },
            operator_stats=operator_stats,
            incumbent_history=tuple(incumbent_history),
        )

    def _default_selector_weights(self) -> Dict[str, float]:
        return {
            "random_trip_removal": 1.0,
            "peak_hour_removal": 1.0,
            "worst_trip_removal": 1.0,
            "vehicle_path_removal": 1.0,
            "unlocked_future_only_removal": 1.0,
            "greedy_trip_insertion": 1.0,
            "regret_k_insertion": 1.0,
            "energy_aware_insertion": 1.0,
            "baseline_dispatch_repair": 1.0,
            "charger_reassignment_repair": 1.0,
            "soc_repair": 1.0,
            "partial_milp_repair": 1.0,
        }

    def _make_acceptance(self, config: OptimizationConfig) -> AcceptanceCriterion:
        strategy = str(config.acceptance or "simulated_annealing").strip().lower()
        if strategy in {"hill_climbing", "hillclimbing"}:
            return HillClimbingAcceptance()
        if strategy in {"genetic_like", "genetic"}:
            return GeneticLikeAcceptance()
        if strategy in {"bee_colony_like", "bee", "abc"}:
            return BeeColonyAcceptance()
        return SimulatedAnnealingAcceptance()

    def _make_selector(self, config: OptimizationConfig) -> OperatorSelector:
        strategy = str(config.operator_selection or "adaptive_roulette").strip().lower()
        if strategy in {"uniform_random", "uniform"}:
            return UniformRandomSelector()
        return AdaptiveRouletteSelector()

    def _make_state(
        self,
        problem: CanonicalOptimizationProblem,
        plan,
    ) -> SolutionState:
        report = self._feasibility.evaluate(problem, plan)
        breakdown = self._evaluator.evaluate(problem, plan)
        vehicle_ledger, daily_ledger = self._evaluator.build_plan_ledgers(problem, plan, breakdown)
        plan = replace(plan, vehicle_cost_ledger=vehicle_ledger, daily_cost_ledger=daily_ledger)
        costs = breakdown.to_dict()
        return SolutionState(
            problem=problem,
            plan=plan,
            cost_breakdown=costs,
            feasible=report.feasible,
            infeasibility_reasons=report.errors,
            metadata={"warnings": report.warnings},
        )
