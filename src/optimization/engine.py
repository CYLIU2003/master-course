from __future__ import annotations

from dataclasses import replace

from src.optimization.abc.engine import ABCOptimizer
from src.optimization.alns.engine import ALNSOptimizer
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationEngineResult,
    OptimizationMode,
)
from src.optimization.common.benchmarking import solver_benchmark_eligibility
from src.optimization.common.strict_precheck import (
    StrictCoveragePrecheckResult,
    evaluate_strict_coverage_precheck,
)
from src.optimization.common.vehicle_assignment import assign_duty_fragments_to_vehicles
from src.optimization.ga.engine import GAOptimizer
from src.optimization.hybrid.hybrid_engine import HybridOptimizer
from src.optimization.milp.engine import MILPOptimizer


class OptimizationEngine:
    def __init__(self) -> None:
        self._milp = MILPOptimizer()
        self._alns = ALNSOptimizer()
        self._ga = GAOptimizer()
        self._abc = ABCOptimizer()
        self._hybrid = HybridOptimizer()
        self._feasibility = FeasibilityChecker()
        self._evaluator = CostEvaluator()

    def solve(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
    ) -> OptimizationEngineResult:
        precheck = evaluate_strict_coverage_precheck(problem)
        if precheck.infeasible:
            result = self._strict_precheck_infeasible_result(problem, config, precheck)
            return self._finalize_result(problem, result)

        if config.mode == OptimizationMode.MILP:
            result = self._milp.solve(problem, config)
        elif config.mode == OptimizationMode.ALNS:
            result = self._alns.solve(problem, config)
        elif config.mode == OptimizationMode.GA:
            result = self._ga.solve(problem, config)
        elif config.mode == OptimizationMode.ABC:
            result = self._abc.solve(problem, config)
        else:
            result = self._hybrid.solve(problem, config)
        return self._finalize_result(problem, result)

    def _strict_precheck_infeasible_result(
        self,
        problem: CanonicalOptimizationProblem,
        config: OptimizationConfig,
        precheck: StrictCoveragePrecheckResult,
    ) -> OptimizationEngineResult:
        mode = config.mode
        display_name, maturity, true_family = self._solver_identity(mode)
        plan = problem.baseline_plan or AssignmentPlan(
            served_trip_ids=(),
            unserved_trip_ids=tuple(sorted(problem.eligible_trip_ids())),
            metadata={"source": "strict_coverage_precheck"},
        )
        profile = {
            "total_wall_clock_sec": 0.0,
            "first_feasible_sec": None,
            "incumbent_updates": 0,
            "evaluator_calls": 0,
            "avg_evaluator_sec": 0.0,
            "repair_calls": 0,
            "avg_repair_sec": 0.0,
            "exact_repair_calls": 0,
            "avg_exact_repair_sec": 0.0,
            "feasible_candidate_ratio": 0.0,
            "rejected_candidate_ratio": 0.0,
            "fallback_count": 0,
        }
        solver_metadata = {
            "true_solver_family": true_family,
            "independent_implementation": True,
            "delegates_to": "none",
            "solver_display_name": display_name,
            "solver_maturity": maturity,
            **solver_benchmark_eligibility(
                mode,
                solver_maturity=maturity,
                true_solver_family=true_family,
                solver_display_name=display_name,
            ),
            "candidate_generation_mode": "strict_coverage_precheck",
            "evaluation_mode": problem.scenario.objective_mode,
            "objective_mode": problem.scenario.objective_mode,
            "service_coverage_mode": problem.scenario.service_coverage_mode,
            "termination_reason": "strict_coverage_precheck_infeasible",
            "fallback_applied": False,
            "fallback_reason": "none",
            "supports_exact_milp": False,
            "has_feasible_incumbent": False,
            "incumbent_count": 0,
            "warm_start_applied": bool(problem.baseline_plan is not None),
            "warm_start_source": "baseline_plan" if problem.baseline_plan is not None else "none",
            "strict_coverage_precheck": precheck.to_metadata(),
            "available_vehicle_count_total": int(precheck.available_vehicle_count),
            "strict_coverage_relaxed_vehicle_lower_bound": int(
                precheck.relaxed_vehicle_lower_bound
            ),
            "search_profile": profile,
            "effective_limits": {
                "time_limit_sec": int(config.time_limit_sec),
                "mip_gap": float(config.mip_gap),
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
        }
        return OptimizationEngineResult(
            mode=mode,
            solver_status="SOLVED_INFEASIBLE",
            objective_value=float("inf"),
            plan=plan,
            feasible=False,
            warnings=(
                "Strict coverage precheck proved this input infeasible before solver invocation.",
            ),
            infeasibility_reasons=(
                "strict coverage relaxed path-cover lower bound "
                f"requires at least {precheck.relaxed_vehicle_lower_bound} vehicles, "
                f"but only {precheck.available_vehicle_count} are available",
            ),
            cost_breakdown={"objective_value": float("inf"), "total_cost": float("inf")},
            solver_metadata=solver_metadata,
            incumbent_history=(),
        )

    @staticmethod
    def _solver_identity(mode: OptimizationMode) -> tuple[str, str, str]:
        if mode == OptimizationMode.MILP:
            return ("MILP", "core", "milp")
        if mode == OptimizationMode.ALNS:
            return ("ALNS", "core", "alns")
        if mode == OptimizationMode.GA:
            return ("GA prototype", "prototype", "ga")
        if mode == OptimizationMode.ABC:
            return ("ABC prototype", "prototype", "abc")
        return ("MILPSeededALNS", "prototype", "milp_seeded_alns")

    def _finalize_result(
        self,
        problem: CanonicalOptimizationProblem,
        result: OptimizationEngineResult,
    ) -> OptimizationEngineResult:
        plan, assignment_rebuilt, charging_recomputed, soc_repaired = self._normalize_postsolve_plan(
            problem,
            result.plan,
        )
        report = self._feasibility.evaluate(problem, plan)
        breakdown = self._evaluator.evaluate(problem, plan)
        vehicle_ledger, daily_ledger = self._evaluator.build_plan_ledgers(problem, plan, breakdown)
        plan = replace(plan, vehicle_cost_ledger=vehicle_ledger, daily_cost_ledger=daily_ledger)
        costs = breakdown.to_dict()
        candidate_plan = plan
        candidate_report = report
        candidate_costs = costs

        solver_metadata = dict(result.solver_metadata or {})
        final_solver_status = result.solver_status
        solver_metadata["backend_objective_value_raw"] = float(result.objective_value)
        solver_metadata["postsolve_assignment_rebuilt"] = bool(assignment_rebuilt)
        solver_metadata["postsolve_charging_recomputed"] = bool(charging_recomputed)
        solver_metadata["postsolve_soc_repair_applied"] = bool(soc_repaired)
        solver_metadata["postsolve_feasible"] = bool(report.feasible)
        solver_metadata["postsolve_objective_value"] = float(
            costs.get("objective_value", result.objective_value)
        )

        warnings = list(result.warnings or ())
        warnings.extend(report.warnings)
        if assignment_rebuilt:
            warnings.append(
                "Post-solve vehicle fragment reassignment rebuilt depot-reset-compatible duties."
            )
        if charging_recomputed:
            warnings.append(
                "Post-solve charging schedule was recomputed after vehicle fragment reassignment."
            )
        if soc_repaired:
            warnings.append(
                "Post-solve SOC repair adjusted charging to restore battery feasibility."
            )

        if result.mode == OptimizationMode.MILP and problem.baseline_plan is not None:
            (
                plan,
                report,
                costs,
                solver_metadata,
                warnings,
            ) = self._apply_milp_truthful_baseline_guardrail(
                problem=problem,
                candidate_plan=candidate_plan,
                candidate_report=candidate_report,
                candidate_costs=candidate_costs,
                solver_status=result.solver_status,
                solver_metadata=solver_metadata,
                warnings=warnings,
            )
            if bool(solver_metadata.get("truthful_baseline_guardrail_applied")):
                final_solver_status = "truthful_baseline_guardrail"
                solver_metadata["fallback_applied"] = True
                solver_metadata["fallback_reason"] = "truthful_baseline_guardrail"
                profile = dict(solver_metadata.get("search_profile") or {})
                profile["fallback_count"] = int(profile.get("fallback_count", 0) or 0) + 1
                solver_metadata["search_profile"] = profile
        warnings = tuple(dict.fromkeys(str(item) for item in warnings if str(item).strip()))

        return replace(
            result,
            solver_status=final_solver_status,
            objective_value=float(costs.get("objective_value", result.objective_value)),
            plan=plan,
            feasible=report.feasible,
            warnings=warnings,
            infeasibility_reasons=report.errors,
            cost_breakdown=costs,
            solver_metadata=solver_metadata,
        )

    def _normalize_postsolve_plan(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> tuple[AssignmentPlan, bool, bool, bool]:
        rebuilt_plan = self._reassign_vehicle_fragments(problem, plan)
        assignment_rebuilt = rebuilt_plan != plan
        charging_recomputed = False
        soc_repaired = False

        if rebuilt_plan.duties:
            from src.optimization.alns.operators_repair import _with_recomputed_charging, soc_repair

            recomputed_plan = _with_recomputed_charging(problem, rebuilt_plan)
            charging_recomputed = recomputed_plan != rebuilt_plan
            rebuilt_plan = recomputed_plan
            repaired_plan = soc_repair(problem, rebuilt_plan)
            soc_repaired = repaired_plan != rebuilt_plan
            rebuilt_plan = repaired_plan

        return rebuilt_plan, assignment_rebuilt, charging_recomputed, soc_repaired

    def _apply_milp_truthful_baseline_guardrail(
        self,
        *,
        problem: CanonicalOptimizationProblem,
        candidate_plan: AssignmentPlan,
        candidate_report,
        candidate_costs: dict,
        solver_status: str,
        solver_metadata: dict,
        warnings: list[str],
    ) -> tuple[AssignmentPlan, object, dict, dict, list[str]]:
        baseline_plan, baseline_assignment_rebuilt, baseline_charge_recomputed, baseline_soc_repaired = (
            self._normalize_postsolve_plan(problem, problem.baseline_plan or AssignmentPlan())
        )
        baseline_report = self._feasibility.evaluate(problem, baseline_plan)
        baseline_breakdown = self._evaluator.evaluate(problem, baseline_plan)
        baseline_vehicle_ledger, baseline_daily_ledger = self._evaluator.build_plan_ledgers(
            problem,
            baseline_plan,
            baseline_breakdown,
        )
        baseline_plan = replace(
            baseline_plan,
            vehicle_cost_ledger=baseline_vehicle_ledger,
            daily_cost_ledger=baseline_daily_ledger,
        )
        baseline_costs = baseline_breakdown.to_dict()

        candidate_served = len(candidate_plan.served_trip_ids)
        baseline_served = len(baseline_plan.served_trip_ids)
        baseline_better = baseline_report.feasible and (
            baseline_served > candidate_served
            or (
                baseline_served == candidate_served
                and float(baseline_costs.get("objective_value", float("inf")))
                + 1.0e-6
                < float(candidate_costs.get("objective_value", float("inf")))
            )
        )
        if not baseline_better:
            return candidate_plan, candidate_report, candidate_costs, solver_metadata, warnings

        solver_metadata["milp_candidate_solver_status"] = str(solver_status or "")
        solver_metadata["milp_candidate_supports_exact_milp"] = bool(
            solver_metadata.get("supports_exact_milp", False)
        )
        solver_metadata["milp_candidate_trip_count_served"] = int(candidate_served)
        solver_metadata["milp_candidate_trip_count_unserved"] = int(len(candidate_plan.unserved_trip_ids))
        solver_metadata["milp_candidate_postsolve_objective_value"] = float(
            candidate_costs.get("objective_value", 0.0)
        )
        solver_metadata["truthful_baseline_guardrail_applied"] = True
        solver_metadata["truthful_baseline_trip_count_served"] = int(baseline_served)
        solver_metadata["truthful_baseline_trip_count_unserved"] = int(len(baseline_plan.unserved_trip_ids))
        solver_metadata["truthful_baseline_objective_value"] = float(
            baseline_costs.get("objective_value", 0.0)
        )
        solver_metadata["truthful_baseline_postsolve_assignment_rebuilt"] = bool(
            baseline_assignment_rebuilt
        )
        solver_metadata["truthful_baseline_postsolve_charging_recomputed"] = bool(
            baseline_charge_recomputed
        )
        solver_metadata["truthful_baseline_postsolve_soc_repair_applied"] = bool(
            baseline_soc_repaired
        )
        solver_metadata["supports_exact_milp"] = False
        solver_metadata["termination_reason"] = "truthful_baseline_guardrail"
        warnings = [
            item
            for item in warnings
            if "Uncovered trips:" not in str(item)
        ]
        warnings.append(
            "Truthful repaired baseline replaced a weaker MILP candidate after post-solve validation."
        )
        if baseline_assignment_rebuilt:
            warnings.append(
                "Truthful baseline guardrail rebuilt vehicle fragments before final export."
            )
        if baseline_charge_recomputed:
            warnings.append(
                "Truthful baseline guardrail recomputed charging before final export."
            )
        if baseline_soc_repaired:
            warnings.append(
                "Truthful baseline guardrail applied SOC repair before final export."
            )
        return baseline_plan, baseline_report, baseline_costs, solver_metadata, warnings

    def _reassign_vehicle_fragments(
        self,
        problem: CanonicalOptimizationProblem,
        plan: AssignmentPlan,
    ) -> AssignmentPlan:
        if not plan.duties:
            return plan

        from src.dispatch.route_band import duty_route_band_ids, fragment_transition_is_feasible

        fixed_route_band_mode = bool(problem.metadata.get("fixed_route_band_mode", False))
        allow_same_day_depot_cycles = bool(
            problem.metadata.get(
                "allow_same_day_depot_cycles",
                getattr(problem.scenario, "allow_same_day_depot_cycles", True),
            )
        )
        max_fragments_per_vehicle_per_day = max(
            int(
                problem.metadata.get(
                    "daily_fragment_limit",
                    problem.metadata.get(
                        "max_depot_cycles_per_vehicle_per_day",
                        getattr(problem.scenario, "max_depot_cycles_per_vehicle_per_day", 1),
                    ),
                )
                or 1
            ),
            1,
        )
        horizon_start_min = int(problem.metadata.get("horizon_start_min") or 0)
        if horizon_start_min <= 0 and getattr(problem.scenario, "horizon_start", None):
            try:
                hh_text, mm_text = str(problem.scenario.horizon_start).split(":", 1)
                horizon_start_min = int(hh_text) * 60 + int(mm_text)
            except ValueError:
                horizon_start_min = 0
        max_fragments_per_vehicle = max(
            int(problem.metadata.get("max_start_fragments_per_vehicle") or 1),
            int(problem.metadata.get("max_end_fragments_per_vehicle") or 1),
            1,
        )
        vehicle_by_id = {
            str(vehicle.vehicle_id): vehicle
            for vehicle in problem.vehicles
        }
        kept_duties = []
        kept_map: dict[str, str] = {}
        duties_to_reassign = []

        for vehicle_id, duties in plan.duties_by_vehicle().items():
            vehicle = vehicle_by_id.get(str(vehicle_id))
            if vehicle is None:
                duties_to_reassign.extend(duty for duty in duties if duty.legs)
                continue
            if not bool(getattr(vehicle, "available", True)):
                duties_to_reassign.extend(duty for duty in duties if duty.legs)
                continue
            home_depot_id = str(getattr(vehicle, "home_depot_id", "") or "").strip()
            previous_kept = None
            for duty in duties:
                if not duty.legs:
                    continue
                if fixed_route_band_mode and len(duty_route_band_ids(duty)) > 1:
                    duties_to_reassign.append(duty)
                    continue
                if previous_kept is None:
                    kept_duties.append(duty)
                    kept_map[str(duty.duty_id)] = str(vehicle_id)
                    previous_kept = duty
                    continue
                if self._duties_overlap_in_time(previous_kept, duty):
                    duties_to_reassign.append(duty)
                    continue
                if fragment_transition_is_feasible(
                    previous_kept,
                    duty,
                    home_depot_id=home_depot_id,
                    dispatch_context=problem.dispatch_context,
                    fixed_route_band_mode=fixed_route_band_mode,
                    allow_same_day_depot_cycles=allow_same_day_depot_cycles,
                ):
                    kept_duties.append(duty)
                    kept_map[str(duty.duty_id)] = str(vehicle_id)
                    previous_kept = duty
                    continue
                duties_to_reassign.append(duty)

        rebuilt_duties, duty_vehicle_map, skipped_trip_ids = assign_duty_fragments_to_vehicles(
            tuple(duties_to_reassign),
            vehicles=problem.vehicles,
            max_fragments_per_vehicle=max_fragments_per_vehicle,
            max_fragments_per_vehicle_per_day=max_fragments_per_vehicle_per_day,
            allow_same_day_depot_cycles=allow_same_day_depot_cycles,
            horizon_start_min=horizon_start_min,
            existing_duties=tuple(kept_duties),
            existing_duty_vehicle_map=kept_map,
            dispatch_context=problem.dispatch_context,
            fixed_route_band_mode=fixed_route_band_mode,
        )
        rebuilt_duties, duty_vehicle_map = self._merge_directly_connectable_fragments(
            problem,
            rebuilt_duties,
            duty_vehicle_map,
        )
        served_trip_ids = tuple(sorted({trip_id for duty in rebuilt_duties for trip_id in duty.trip_ids}))
        unserved_trip_ids = tuple(
            sorted((set(problem.eligible_trip_ids()) - set(served_trip_ids)).union(set(skipped_trip_ids)))
        )
        metadata = dict(plan.metadata or {})
        metadata["duty_vehicle_map"] = dict(duty_vehicle_map)
        metadata["postsolve_vehicle_fragment_reassignment"] = True
        return replace(
            plan,
            duties=rebuilt_duties,
            served_trip_ids=served_trip_ids,
            unserved_trip_ids=unserved_trip_ids,
            metadata=metadata,
        )

    @staticmethod
    def _duties_overlap_in_time(
        duty_a,
        duty_b,
    ) -> bool:
        if not duty_a.legs or not duty_b.legs:
            return False
        duty_a_start = int(duty_a.legs[0].trip.departure_min)
        duty_a_end = int(duty_a.legs[-1].trip.arrival_min)
        duty_b_start = int(duty_b.legs[0].trip.departure_min)
        duty_b_end = int(duty_b.legs[-1].trip.arrival_min)
        return duty_a_start < duty_b_end and duty_b_start < duty_a_end

    def _merge_directly_connectable_fragments(
        self,
        problem: CanonicalOptimizationProblem,
        duties: tuple,
        duty_vehicle_map: dict[str, str],
    ) -> tuple[tuple, dict[str, str]]:
        from src.dispatch.route_band import (
            duty_route_band_ids,
            fragment_transition_allows_direct_connection,
            fragment_transition_direct_deadhead_min,
        )

        fixed_route_band_mode = bool(problem.metadata.get("fixed_route_band_mode", False))
        grouped: dict[str, list] = {}
        for duty in duties:
            vehicle_id = str(duty_vehicle_map.get(str(duty.duty_id)) or "")
            if vehicle_id:
                grouped.setdefault(vehicle_id, []).append(duty)

        merged_duties = []
        merged_map: dict[str, str] = {}
        for vehicle_id, vehicle_duties in grouped.items():
            ordered = sorted(
                vehicle_duties,
                key=lambda item: (
                    item.legs[0].trip.departure_min if item.legs else 10**9,
                    item.legs[-1].trip.arrival_min if item.legs else 10**9,
                    item.duty_id,
                ),
            )
            current = None
            fragment_index = 0
            for duty in ordered:
                if current is None:
                    current = duty
                    continue
                current_bands = duty_route_band_ids(current)
                next_bands = duty_route_band_ids(duty)
                band_mismatch = bool(
                    fixed_route_band_mode and current_bands and next_bands and current_bands != next_bands
                )
                can_direct = fragment_transition_allows_direct_connection(
                    current,
                    duty,
                    dispatch_context=problem.dispatch_context,
                )
                if can_direct and not band_mismatch and duty.legs:
                    direct_exists, direct_deadhead = fragment_transition_direct_deadhead_min(
                        current,
                        duty,
                        dispatch_context=problem.dispatch_context,
                    )
                    if direct_exists:
                        first_leg = replace(duty.legs[0], deadhead_from_prev_min=max(int(direct_deadhead), 0))
                        current = replace(
                            current,
                            legs=(
                                *current.legs,
                                first_leg,
                                *duty.legs[1:],
                            ),
                        )
                        continue
                fragment_index += 1
                duty_id = vehicle_id if fragment_index == 1 else f"{vehicle_id}__frag{fragment_index}"
                finalized = replace(current, duty_id=duty_id)
                merged_duties.append(finalized)
                merged_map[duty_id] = vehicle_id
                current = duty
            if current is not None:
                fragment_index += 1
                duty_id = vehicle_id if fragment_index == 1 else f"{vehicle_id}__frag{fragment_index}"
                finalized = replace(current, duty_id=duty_id)
                merged_duties.append(finalized)
                merged_map[duty_id] = vehicle_id

        return tuple(merged_duties), merged_map
