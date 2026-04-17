from __future__ import annotations

import random
import time
from typing import Callable, Dict, List

from src.dispatch.models import VehicleDuty
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
from src.optimization.common.metaheuristic_utils import (
    build_solution_state,
    feasibility_first_better,
    solution_state_rank_key,
    rebuild_plan_from_duties,
)
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
from src.optimization.common.vehicle_assignment import merge_duty_vehicle_maps


class GAOptimizer:
    """Independent genetic-search optimizer."""

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
        population_size = max(8, min(24, max(1, len(problem.trips) // 50 + 8)))
        tournament_size = max(2, min(5, population_size // 3))
        elitism_count = max(1, min(3, population_size // 4))
        generation_limit = max(1, int(config.alns_iterations))

        population = self._seed_population(
            problem,
            config,
            rng,
            profile,
            started_at,
            destroy_ops,
            repair_ops,
            population_size,
            exact_repair_call_limit,
            exact_repair_time_budget_sec,
        )
        population.sort(key=self._state_key)
        best = population[0]
        incumbent_history = [
            IncumbentSnapshot(
                iteration=0,
                objective_value=best.objective(),
                feasible=best.is_feasible(),
                wall_clock_sec=0.0,
            )
        ]

        generation = 0
        stagnation = 0
        crossover_count = 0
        mutation_count = 0
        stop_reason = "generation_limit"
        while generation < generation_limit:
            elapsed = time.perf_counter() - started_at
            if elapsed >= float(config.time_limit_sec):
                stop_reason = "time_limit"
                break
            if stagnation >= int(config.no_improvement_limit):
                stop_reason = "stagnation"
                break

            next_population = population[:elitism_count]
            improved_in_generation = False
            while len(next_population) < population_size:
                elapsed = time.perf_counter() - started_at
                if elapsed >= float(config.time_limit_sec):
                    stop_reason = "time_limit"
                    break

                use_crossover = len(population) > 1 and rng.random() < 0.65
                if use_crossover:
                    parent_a = self._tournament_select(population, rng, tournament_size)
                    parent_b = self._tournament_select(population, rng, tournament_size)
                    child_plan = self._crossover(problem, parent_a.plan, parent_b.plan, rng)
                    crossover_count += 1
                else:
                    parent = self._tournament_select(population, rng, tournament_size)
                    child_plan = self._mutate(
                        problem,
                        parent.plan,
                        rng,
                        destroy_ops,
                        repair_ops,
                        profile,
                        started_at,
                        exact_repair_call_limit,
                        exact_repair_time_budget_sec,
                    )
                    mutation_count += 1

                candidate = build_solution_state(
                    problem,
                    child_plan,
                    feasibility=self._feasibility,
                    evaluator=self._evaluator,
                    profile=profile,
                    started_at=started_at,
                )
                next_population.append(candidate)

                if feasibility_first_better(candidate, best, best):
                    best = candidate
                    improved_in_generation = True
                    profile.record_incumbent(
                        feasible=best.is_feasible(),
                        elapsed_sec=time.perf_counter() - started_at,
                    )
                    incumbent_history.append(
                        IncumbentSnapshot(
                            iteration=generation + 1,
                            objective_value=best.objective(),
                            feasible=best.is_feasible(),
                            wall_clock_sec=round(time.perf_counter() - started_at, 6),
                        )
                    )

                if len(next_population) >= population_size:
                    break

            population = sorted(next_population, key=self._state_key)[:population_size]
            generation += 1
            stagnation = 0 if improved_in_generation else stagnation + 1

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
            mode=OptimizationMode.GA,
            solver_status=result_category,
            objective_value=best.objective(),
            plan=best.plan,
            feasible=best.is_feasible(),
            warnings=(),
            infeasibility_reasons=best.infeasibility_reasons,
            cost_breakdown=best.cost_breakdown,
            solver_metadata={
                "metaheuristic": "ga",
                "delegates_to": "none",
                "true_solver_family": "ga",
                "independent_implementation": True,
                "solver_display_name": "GA prototype",
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
                    OptimizationMode.GA,
                    solver_maturity="prototype",
                    true_solver_family="ga",
                    solver_display_name="GA prototype",
                ),
                "candidate_generation_mode": "genetic_population_search",
                "evaluation_mode": problem.scenario.objective_mode,
                "warm_start_applied": problem.baseline_plan is not None,
                "warm_start_source": warm_start_source,
                "fallback_applied": False,
                "fallback_reason": "none",
                "supports_exact_milp": False,
                "has_feasible_incumbent": best.is_feasible(),
                "incumbent_count": len(incumbent_history),
                "uses_exact_repair": uses_exact_repair,
                "population_size": population_size,
                "generation_limit": generation_limit,
                "generation_count": generation,
                "elitism_count": elitism_count,
                "tournament_size": tournament_size,
                "crossover_count": crossover_count,
                "mutation_count": mutation_count,
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
        population_size: int,
        exact_repair_call_limit: int,
        exact_repair_time_budget_sec: float,
    ) -> List[SolutionState]:
        base_plan = problem.baseline_plan or AssignmentPlan()
        population: List[SolutionState] = [
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
        for seed_index in range(1, population_size):
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
            population.append(
                build_solution_state(
                    problem,
                    repaired_plan,
                    feasibility=self._feasibility,
                    evaluator=self._evaluator,
                    profile=profile,
                    started_at=started_at,
                )
            )
        return population

    def _mutate(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
        rng: random.Random,
        destroy_ops: Dict[str, Callable[[AssignmentPlan], AssignmentPlan]],
        repair_ops: Dict[str, Callable[[CanonicalOptimizationProblem, AssignmentPlan], AssignmentPlan]],
        profile: SearchProfile,
        started_at: float,
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

    def _apply_repair(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
        repair: Callable[[CanonicalOptimizationProblem, AssignmentPlan], AssignmentPlan],
    ) -> tuple[AssignmentPlan, float]:
        repair_started = time.perf_counter()
        repaired_plan = repair(problem, plan)
        return repaired_plan, time.perf_counter() - repair_started

    def _crossover(
        self,
        problem: CanonicalOptimizationProblem,
        parent_a: AssignmentPlan,
        parent_b: AssignmentPlan,
        rng: random.Random,
    ) -> AssignmentPlan:
        merged_map = merge_duty_vehicle_maps(
            parent_a.metadata.get("duty_vehicle_map"),
            parent_b.metadata.get("duty_vehicle_map"),
        )
        selected_duties: List[VehicleDuty] = []
        seen_trip_ids: set[str] = set()
        shuffled_duties = list(parent_a.duties) + list(parent_b.duties)
        rng.shuffle(shuffled_duties)
        for duty in shuffled_duties:
            trip_ids = {str(trip_id) for trip_id in duty.trip_ids}
            if not trip_ids or seen_trip_ids.intersection(trip_ids):
                continue
            if rng.random() < 0.5 or not selected_duties:
                selected_duties.append(duty)
                seen_trip_ids.update(trip_ids)
        if not selected_duties:
            fallback_duties = list(parent_a.duties or parent_b.duties)
            if not fallback_duties:
                return rebuild_plan_from_duties(
                    problem,
                    parent_a,
                    (),
                    keep_energy_slots=False,
                    preserve_unserved=True,
                    metadata_updates={
                        "crossover_mode": "empty_fallback",
                        "duty_vehicle_map": merged_map,
                    },
                )
            selected_duties = [rng.choice(fallback_duties)]
        return rebuild_plan_from_duties(
            problem,
            parent_a,
            selected_duties,
            keep_energy_slots=False,
            preserve_unserved=False,
            metadata_updates={
                "crossover_mode": "duty_union",
                "duty_vehicle_map": merged_map,
            },
        )

    def _tournament_select(
        self,
        population: List[SolutionState],
        rng: random.Random,
        tournament_size: int,
    ) -> SolutionState:
        contenders = rng.sample(population, k=min(max(tournament_size, 1), len(population)))
        return min(contenders, key=self._state_key)

    def _state_key(self, state: SolutionState) -> tuple[int, int, float, int]:
        return solution_state_rank_key(state)

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
