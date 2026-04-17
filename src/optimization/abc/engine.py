from __future__ import annotations

import random
import time
from typing import Callable, Dict, List

from src.optimization.alns.operators_destroy import (
    peak_hour_removal,
    random_trip_removal,
    unlocked_future_only_removal,
    vehicle_path_removal,
    worst_trip_removal,
)
from src.optimization.alns.operators_repair import (
    baseline_dispatch_repair,
    charger_reassignment_repair,
    energy_aware_insertion,
    greedy_trip_insertion,
    partial_milp_repair,
    regret_k_insertion,
    soc_repair,
)
from src.optimization.common.benchmarking import exact_repair_policy, solver_benchmark_eligibility
from src.optimization.common.metaheuristic_utils import build_solution_state, solution_state_rank_key
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    IncumbentSnapshot,
    OptimizationConfig,
    OptimizationEngineResult,
    OptimizationMode,
    SolutionState,
)
from src.optimization.common.search_profile import SearchProfile


class ABCOptimizer:
    """Independent artificial-bee-colony search optimizer."""

    def __init__(self) -> None:
        from src.optimization.common.evaluator import CostEvaluator
        from src.optimization.common.feasibility import FeasibilityChecker

        self._feasibility = FeasibilityChecker()
        self._evaluator = CostEvaluator()

    def solve(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> OptimizationEngineResult:
        started_at = time.perf_counter()
        rng = random.Random(config.random_seed)
        profile = SearchProfile(started_at=started_at)

        destroy_ops = self._build_destroy_ops(problem, config, rng)
        repair_ops = self._build_repair_ops(problem, config)
        exact_repair_limits = exact_repair_policy(config)
        exact_repair_call_limit = exact_repair_limits.call_limit
        exact_repair_time_budget_sec = exact_repair_limits.time_budget_sec
        food_source_count = max(8, min(24, max(1, len(problem.trips) // 50 + 8)))
        onlooker_count = max(2, food_source_count)
        trial_limit = max(6, min(30, max(1, int(config.no_improvement_limit // 2) or 6)))
        cycle_limit = max(1, int(config.alns_iterations))

        food_sources = self._seed_population(
            problem,
            config,
            rng,
            profile,
            started_at,
            destroy_ops,
            repair_ops,
            food_source_count,
            exact_repair_call_limit,
            exact_repair_time_budget_sec,
        )
        food_sources.sort(key=self._state_key)
        trial_counters = [0 for _ in food_sources]
        best = food_sources[0]
        incumbent_history = [
            IncumbentSnapshot(
                iteration=0,
                objective_value=best.objective(),
                feasible=best.is_feasible(),
                wall_clock_sec=0.0,
            )
        ]

        cycle = 0
        employed_updates = 0
        onlooker_updates = 0
        scout_resets = 0
        stagnation = 0
        stop_reason = "cycle_limit"
        while cycle < cycle_limit:
            elapsed = time.perf_counter() - started_at
            if elapsed >= float(config.time_limit_sec):
                stop_reason = "time_limit"
                break
            if stagnation >= int(config.no_improvement_limit):
                stop_reason = "stagnation"
                break

            cycle_improved = False
            # Employed bee phase
            for idx in range(len(food_sources)):
                elapsed = time.perf_counter() - started_at
                if elapsed >= float(config.time_limit_sec):
                    stop_reason = "time_limit"
                    break
                neighbor_plan = self._mutate(
                    problem,
                    food_sources[idx].plan,
                    rng,
                    destroy_ops,
                    repair_ops,
                    profile,
                    exact_repair_call_limit,
                    exact_repair_time_budget_sec,
                )
                candidate = build_solution_state(
                    problem,
                    neighbor_plan,
                    feasibility=self._feasibility,
                    evaluator=self._evaluator,
                    profile=profile,
                    started_at=started_at,
                )
                employed_updates += 1
                if self._state_key(candidate) < self._state_key(food_sources[idx]):
                    food_sources[idx] = candidate
                    trial_counters[idx] = 0
                    cycle_improved = True
                    if self._state_key(candidate) < self._state_key(best):
                        best = candidate
                        profile.record_incumbent(
                            feasible=best.is_feasible(),
                            elapsed_sec=time.perf_counter() - started_at,
                        )
                        incumbent_history.append(
                            IncumbentSnapshot(
                                iteration=cycle + 1,
                                objective_value=best.objective(),
                                feasible=best.is_feasible(),
                                wall_clock_sec=round(time.perf_counter() - started_at, 6),
                            )
                        )
                else:
                    trial_counters[idx] += 1
            if stop_reason == "time_limit":
                break

            # Onlooker bee phase
            selection_weights = self._selection_weights(food_sources)
            for _ in range(onlooker_count):
                elapsed = time.perf_counter() - started_at
                if elapsed >= float(config.time_limit_sec):
                    stop_reason = "time_limit"
                    break
                idx = self._roulette_select(selection_weights, rng)
                neighbor_plan = self._mutate(
                    problem,
                    food_sources[idx].plan,
                    rng,
                    destroy_ops,
                    repair_ops,
                    profile,
                    exact_repair_call_limit,
                    exact_repair_time_budget_sec,
                )
                candidate = build_solution_state(
                    problem,
                    neighbor_plan,
                    feasibility=self._feasibility,
                    evaluator=self._evaluator,
                    profile=profile,
                    started_at=started_at,
                )
                onlooker_updates += 1
                if self._state_key(candidate) < self._state_key(food_sources[idx]):
                    food_sources[idx] = candidate
                    trial_counters[idx] = 0
                    cycle_improved = True
                    if self._state_key(candidate) < self._state_key(best):
                        best = candidate
                        profile.record_incumbent(
                            feasible=best.is_feasible(),
                            elapsed_sec=time.perf_counter() - started_at,
                        )
                        incumbent_history.append(
                            IncumbentSnapshot(
                                iteration=cycle + 1,
                                objective_value=best.objective(),
                                feasible=best.is_feasible(),
                                wall_clock_sec=round(time.perf_counter() - started_at, 6),
                            )
                        )
                else:
                    trial_counters[idx] += 1
            if stop_reason == "time_limit":
                break

            # Scout bee phase
            for idx, trial_count in enumerate(list(trial_counters)):
                if trial_count < trial_limit:
                    continue
                scout_plan = self._scout_reset(
                    problem,
                    config,
                    rng,
                    profile,
                    started_at,
                    destroy_ops,
                    repair_ops,
                    exact_repair_call_limit,
                    exact_repair_time_budget_sec,
                )
                scout_state = build_solution_state(
                    problem,
                    scout_plan,
                    feasibility=self._feasibility,
                    evaluator=self._evaluator,
                    profile=profile,
                    started_at=started_at,
                )
                scout_resets += 1
                food_sources[idx] = scout_state
                trial_counters[idx] = 0
                cycle_improved = True
                if self._state_key(scout_state) < self._state_key(best):
                    best = scout_state
                    profile.record_incumbent(
                        feasible=best.is_feasible(),
                        elapsed_sec=time.perf_counter() - started_at,
                    )
                    incumbent_history.append(
                        IncumbentSnapshot(
                            iteration=cycle + 1,
                            objective_value=best.objective(),
                            feasible=best.is_feasible(),
                            wall_clock_sec=round(time.perf_counter() - started_at, 6),
                        )
                    )

            paired = sorted(zip(food_sources, trial_counters), key=lambda item: self._state_key(item[0]))
            food_sources = [state for state, _trial in paired]
            trial_counters = [trial for _state, trial in paired]
            cycle += 1
            stagnation = 0 if cycle_improved else stagnation + 1

        has_incumbent = len(incumbent_history) > 0
        if best.is_feasible() and has_incumbent:
            result_category = "SOLVED_FEASIBLE"
        elif not best.is_feasible() and has_incumbent:
            result_category = "SOLVED_INFEASIBLE"
        elif not has_incumbent:
            result_category = "NO_INCUMBENT"
        else:
            result_category = "SOLVED_INFEASIBLE"

        vehicle_fragment_counts = best.plan.vehicle_fragment_counts()
        vehicles_with_multiple_fragments = best.plan.vehicles_with_multiple_fragments()
        max_fragments_observed = best.plan.max_fragments_observed()
        same_day_depot_cycles_enabled = bool(
            problem.metadata.get(
                "allow_same_day_depot_cycles",
                getattr(problem.scenario, "allow_same_day_depot_cycles", True),
            )
        )
        profile_snapshot = profile.snapshot(total_wall_clock_sec=time.perf_counter() - started_at)
        warm_start_source = "baseline_plan" if problem.baseline_plan is not None else "generated_seed"
        uses_exact_repair = bool(profile.exact_repair_calls > 0)
        return OptimizationEngineResult(
            mode=OptimizationMode.ABC,
            solver_status=result_category,
            objective_value=best.objective(),
            plan=best.plan,
            feasible=best.is_feasible(),
            warnings=(),
            infeasibility_reasons=best.infeasibility_reasons,
            cost_breakdown=best.cost_breakdown,
            solver_metadata={
                "metaheuristic": "abc",
                "delegates_to": "none",
                "true_solver_family": "abc",
                "independent_implementation": True,
                "solver_display_name": "ABC prototype",
                "solver_maturity": "prototype",
                "same_day_depot_cycles_enabled": same_day_depot_cycles_enabled,
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
                **solver_benchmark_eligibility(
                    OptimizationMode.ABC,
                    solver_maturity="prototype",
                    true_solver_family="abc",
                    solver_display_name="ABC prototype",
                ),
                "candidate_generation_mode": "bee_colony_search",
                "evaluation_mode": problem.scenario.objective_mode,
                "warm_start_applied": problem.baseline_plan is not None,
                "warm_start_source": warm_start_source,
                "fallback_applied": False,
                "fallback_reason": "none",
                "supports_exact_milp": False,
                "has_feasible_incumbent": best.is_feasible(),
                "incumbent_count": len(incumbent_history),
                "uses_exact_repair": uses_exact_repair,
                "food_source_count": food_source_count,
                "onlooker_count": onlooker_count,
                "trial_limit": trial_limit,
                "cycle_limit": cycle_limit,
                "cycle_count": cycle,
                "employed_updates": employed_updates,
                "onlooker_updates": onlooker_updates,
                "scout_resets": scout_resets,
                "repair_count": profile.repair_calls,
                "exact_repair_count": profile.exact_repair_calls,
                "exact_repair_time_budget_sec": exact_repair_time_budget_sec,
                "exact_repair_call_limit": exact_repair_call_limit,
                "search_profile": profile_snapshot,
                "effective_limits": {
                    "time_limit_sec": int(config.time_limit_sec),
                    "alns_iterations": int(config.alns_iterations),
                    "no_improvement_limit": int(config.no_improvement_limit),
                },
                "objective_weights": {
                    "electricity_cost": float(problem.objective_weights.energy),
                    "demand_charge_cost": float(problem.objective_weights.demand),
                    "vehicle_fixed_cost": float(problem.objective_weights.vehicle),
                    "unserved_penalty": float(problem.objective_weights.unserved),
                    "switch_cost": float(problem.objective_weights.switch),
                    "deviation_cost": float(problem.objective_weights.deviation),
                    "degradation": float(problem.objective_weights.degradation),
                    "utilization": float(problem.objective_weights.utilization),
                    "return_leg_bonus": float(problem.objective_weights.return_leg_bonus),
                },
                "termination_reason": stop_reason,
            },
            operator_stats={},
            incumbent_history=tuple(incumbent_history),
        )

    def _seed_population(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
        rng: random.Random,
        profile: SearchProfile,
        started_at: float,
        destroy_ops: Dict[str, Callable[[AssignmentPlan], AssignmentPlan]],
        repair_ops: Dict[str, Callable[[CanonicalOptimizationProblem, AssignmentPlan], AssignmentPlan]],
        food_source_count: int,
        exact_repair_call_limit: int,
        exact_repair_time_budget_sec: float,
    ) -> List[SolutionState]:
        base_plan = problem.baseline_plan or AssignmentPlan()
        food_sources: List[SolutionState] = [
            build_solution_state(
                problem,
                base_plan,
                feasibility=self._feasibility,
                evaluator=self._evaluator,
                profile=profile,
                started_at=started_at,
            )
        ]
        destroy_names = list(destroy_ops.keys()) or ["random_trip_removal"]
        repair_names = list(repair_ops.keys()) or ["baseline_dispatch_repair"]
        for seed_index in range(1, food_source_count):
            if time.perf_counter() - started_at >= float(config.time_limit_sec):
                break
            destroy_name = destroy_names[seed_index % len(destroy_names)]
            repair_name = repair_names[seed_index % len(repair_names)]
            if repair_name == "partial_milp_repair" and not self._exact_repair_available(
                profile,
                exact_repair_call_limit,
                exact_repair_time_budget_sec,
            ):
                repair_name = "baseline_dispatch_repair"
                profile.record_fallback()
            destroyed_plan = destroy_ops[destroy_name](base_plan)
            repaired_plan, repair_elapsed = self._apply_repair(
                problem,
                destroyed_plan,
                repair_ops[repair_name],
            )
            profile.record_repair(repair_elapsed, exact=(repair_name == "partial_milp_repair"))
            food_sources.append(
                build_solution_state(
                    problem,
                    repaired_plan,
                    feasibility=self._feasibility,
                    evaluator=self._evaluator,
                    profile=profile,
                    started_at=started_at,
                )
            )
        return food_sources

    def _mutate(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
        rng: random.Random,
        destroy_ops: Dict[str, Callable[[AssignmentPlan], AssignmentPlan]],
        repair_ops: Dict[str, Callable[[CanonicalOptimizationProblem, AssignmentPlan], AssignmentPlan]],
        profile: SearchProfile,
        exact_repair_call_limit: int,
        exact_repair_time_budget_sec: float,
    ) -> AssignmentPlan:
        destroy_name = rng.choice(list(destroy_ops.keys()))
        repair_names = list(repair_ops.keys())
        if not self._exact_repair_available(profile, exact_repair_call_limit, exact_repair_time_budget_sec):
            repair_names = [name for name in repair_names if name != "partial_milp_repair"] or repair_names
        repair_name = rng.choice(repair_names)
        if repair_name == "partial_milp_repair" and not self._exact_repair_available(
            profile,
            exact_repair_call_limit,
            exact_repair_time_budget_sec,
        ):
            repair_name = "baseline_dispatch_repair"
            profile.record_fallback()
        destroyed_plan = destroy_ops[destroy_name](plan)
        repaired_plan, repair_elapsed = self._apply_repair(problem, destroyed_plan, repair_ops[repair_name])
        profile.record_repair(repair_elapsed, exact=(repair_name == "partial_milp_repair"))
        return repaired_plan

    def _scout_reset(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
        rng: random.Random,
        profile: SearchProfile,
        started_at: float,
        destroy_ops: Dict[str, Callable[[AssignmentPlan], AssignmentPlan]],
        repair_ops: Dict[str, Callable[[CanonicalOptimizationProblem, AssignmentPlan], AssignmentPlan]],
        exact_repair_call_limit: int,
        exact_repair_time_budget_sec: float,
    ) -> AssignmentPlan:
        base_plan = problem.baseline_plan or AssignmentPlan()
        destroyed_plan = destroy_ops["vehicle_path_removal"](base_plan)
        repair_name = "greedy_trip_insertion"
        if not self._exact_repair_available(profile, exact_repair_call_limit, exact_repair_time_budget_sec):
            profile.record_fallback()
        repaired_plan, repair_elapsed = self._apply_repair(problem, destroyed_plan, repair_ops[repair_name])
        profile.record_repair(repair_elapsed, exact=False)
        return repaired_plan

    def _apply_repair(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
        repair: Callable[[CanonicalOptimizationProblem, AssignmentPlan], AssignmentPlan],
    ) -> tuple[AssignmentPlan, float]:
        repair_started = time.perf_counter()
        repaired_plan = repair(problem, plan)
        return repaired_plan, time.perf_counter() - repair_started

    def _state_key(self, state: SolutionState) -> tuple[int, int, float, int]:
        return solution_state_rank_key(state)

    def _selection_weights(self, food_sources: List[SolutionState]) -> List[float]:
        ranked = sorted(enumerate(food_sources), key=lambda item: self._state_key(item[1]))
        weights = [0.0 for _ in food_sources]
        total = len(food_sources)
        for rank, (idx, _state) in enumerate(ranked):
            weights[idx] = float(total - rank)
        return weights

    def _roulette_select(self, weights: List[float], rng: random.Random) -> int:
        total = sum(max(weight, 0.0) for weight in weights)
        if total <= 0.0:
            return rng.randrange(len(weights))
        pick = rng.random() * total
        running = 0.0
        for idx, weight in enumerate(weights):
            running += max(weight, 0.0)
            if running >= pick:
                return idx
        return len(weights) - 1

    def _exact_repair_available(
        self,
        profile: SearchProfile,
        exact_repair_call_limit: int,
        exact_repair_time_budget_sec: float,
    ) -> bool:
        return (
            profile.exact_repair_calls < exact_repair_call_limit
            and profile.exact_repair_time_sec < exact_repair_time_budget_sec
        )

    def _build_destroy_ops(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
        rng: random.Random,
    ) -> Dict[str, Callable[[AssignmentPlan], AssignmentPlan]]:
        return {
            "random_trip_removal": lambda plan: random_trip_removal(plan, rng, max(config.destroy_fraction, 0.15)),
            "peak_hour_removal": lambda plan: peak_hour_removal(
                plan,
                rng,
                max(config.destroy_fraction, 0.15),
                problem=problem,
                use_data_driven_peak=bool(config.use_data_driven_peak_removal),
                fallback_windows_min=tuple(config.peak_hour_windows_min),
            ),
            "worst_trip_removal": lambda plan: worst_trip_removal(
                plan,
                rng,
                max(config.destroy_fraction, 0.15),
            ),
            "vehicle_path_removal": lambda plan: vehicle_path_removal(plan, rng, max(config.destroy_fraction, 0.15)),
            "unlocked_future_only_removal": lambda plan: unlocked_future_only_removal(
                plan,
                rng,
                max(config.destroy_fraction, 0.15),
                config.rolling_current_min,
            ),
        }

    def _build_repair_ops(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> Dict[str, Callable[[CanonicalOptimizationProblem, AssignmentPlan], AssignmentPlan]]:
        return {
            "greedy_trip_insertion": lambda prob, plan: greedy_trip_insertion(prob, plan),
            "regret_k_insertion": lambda prob, plan: regret_k_insertion(prob, plan),
            "energy_aware_insertion": lambda prob, plan: energy_aware_insertion(prob, plan),
            "baseline_dispatch_repair": lambda prob, plan: baseline_dispatch_repair(prob, plan),
            "charger_reassignment_repair": lambda prob, plan: charger_reassignment_repair(prob, plan),
            "soc_repair": lambda prob, plan: soc_repair(prob, plan),
            "partial_milp_repair": lambda prob, plan: partial_milp_repair(prob, plan, config=config),
        }
