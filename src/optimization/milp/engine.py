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
        plan_metadata = dict(plan.metadata or {})
        phase = str(plan_metadata.get("phase") or getattr(config, "phase", "") or "").strip()
        if phase:
            plan_metadata["executed_phase"] = phase
            plan_metadata["executed_phase_source"] = "milp_adapter_branch"
            plan = replace(plan, metadata=plan_metadata)
        stage2_failed = bool(
            phase == "phase3_two_stage"
            and plan_metadata.get("stage1_feasible") is True
            and plan_metadata.get("stage2_feasible") is False
        )
        if stage2_failed:
            # Stage 1 is a useful diagnostic candidate, but it is not a
            # dispatch result when Stage 2 cannot produce charging/SOC.  This
            # isolation applies to ordinary Phase 3 calls as well as research
            # runs; otherwise an infeasible charging stage would leak a
            # seemingly valid assignment into public output.
            plan_metadata["research_candidate_only"] = bool(
                getattr(config, "research_run", False)
            )
            plan_metadata["stage2_candidate_only"] = True
            plan_metadata["assignment_candidate_available"] = True
            plan_metadata["assignment_candidate_trip_ids"] = tuple(plan.served_trip_ids)
            plan_metadata["assignment_candidate_trip_count"] = len(plan.served_trip_ids)
            plan = replace(
                plan,
                duties=(),
                charging_slots=(),
                served_trip_ids=(),
                unserved_trip_ids=tuple(sorted(trip.trip_id for trip in problem.trips)),
                grid_to_bus_kwh_by_depot_slot={},
                pv_to_bus_kwh_by_depot_slot={},
                bess_to_bus_kwh_by_depot_slot={},
                pv_to_bess_kwh_by_depot_slot={},
                grid_to_bess_kwh_by_depot_slot={},
                pv_curtail_kwh_by_depot_slot={},
                vehicle_soc_kwh_by_vehicle_slot={},
                vehicle_cost_ledger=(),
                daily_cost_ledger=(),
                metadata=plan_metadata,
            )
            # Re-evaluate the published (empty) plan.  The Stage 1 report is
            # retained only as diagnostic metadata; it must not leak into the
            # direct MILP result's ``feasible`` flag or ledgers.
            report = self._feasibility.evaluate(problem, plan)
            breakdown = self._evaluator.evaluate(problem, plan)
            vehicle_ledger, daily_ledger = self._evaluator.build_plan_ledgers(
                problem, plan, breakdown
            )
            plan = replace(
                plan,
                vehicle_cost_ledger=vehicle_ledger,
                daily_cost_ledger=daily_ledger,
            )
        plan_metadata = dict(plan.metadata or {})
        diagnostic_mode = bool(plan_metadata.get("diagnostic_mode", getattr(config, "diagnostic_mode", False)))
        result_class = str(
            plan_metadata.get("result_class")
            or ("debug_result" if bool(getattr(config, "debug_mode", False)) else "optimization_result")
        )
        research_kpi_eligible = bool(
            plan_metadata.get(
                "research_kpi_eligible",
                not bool(getattr(config, "debug_mode", False)) and result_class == "optimization_result",
            )
        )
        if phase == "diagnostic" or diagnostic_mode:
            result_class = "debug_result"
            research_kpi_eligible = False
        binding_constraint_report = (
            self._binding_constraint_report(report, plan)
            if phase == "diagnostic" or diagnostic_mode
            else dict(plan_metadata.get("binding_constraint_report") or {})
        )
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
        # A phase helper can return a baseline while retaining a neutral solver
        # status such as ``gurobi_unavailable``.  Its plan metadata is the
        # authoritative provenance in that case.  Do not use fallback_reason
        # alone: research-mode no-incumbent failures carry a reason but never
        # substitute a baseline plan.
        is_baseline_fallback = bool(
            "fallback" in str(outcome.solver_status or "").lower()
            or "baseline" in str(outcome.solver_status or "").lower()
            or str(plan_metadata.get("result_class") or "") == "baseline_fallback"
            or bool(plan_metadata.get("fallback_applied", False))
        )
        final_solver_status = "debug_result" if bool(getattr(config, "debug_mode", False)) else outcome.solver_status
        return OptimizationEngineResult(
            mode=OptimizationMode.MILP,
            solver_status=final_solver_status,
            objective_value=costs["objective_value"],
            plan=plan,
            feasible=report.feasible,
            warnings=report.warnings,
            infeasibility_reasons=report.errors,
            cost_breakdown=costs,
            solver_metadata={
                "backend": outcome.used_backend,
                "supports_exact_milp": outcome.supports_exact_milp,
                "supports_two_stage_milp": bool((plan.metadata or {}).get("supports_two_stage_milp", False)),
                "supports_integrated_exact_milp": bool(
                    (plan.metadata or {}).get(
                        "supports_integrated_exact_milp",
                        outcome.supports_exact_milp if phase != "phase3_two_stage" else False,
                    )
                ),
                "optimization_structure": str((plan.metadata or {}).get("optimization_structure") or ("two_stage" if getattr(config, "thesis_mode", False) else "integrated")),
                "assignment_energy_coupling_mode": (plan.metadata or {}).get(
                    "assignment_energy_coupling_mode"
                ),
                "stage1_solver_status": (plan.metadata or {}).get("stage1_solver_status"),
                "assignment_solution_method": (plan.metadata or {}).get(
                    "assignment_solution_method"
                ),
                "assignment_global_optimality": bool(
                    (plan.metadata or {}).get("assignment_global_optimality", False)
                ),
                "stage1_exact_optimality_certified": bool(
                    (plan.metadata or {}).get(
                        "stage1_exact_optimality_certified", False
                    )
                ),
                "assignment_global_optimality_scope": (plan.metadata or {}).get(
                    "assignment_global_optimality_scope"
                ),
                "assignment_certified_mip_gap_ratio": (plan.metadata or {}).get(
                    "assignment_certified_mip_gap_ratio"
                ),
                "full_network_global_optimality": bool(
                    (plan.metadata or {}).get("full_network_global_optimality", False)
                ),
                "stage2_solver_status": (plan.metadata or {}).get("stage2_solver_status"),
                "stage2_exact_optimality_certified": bool(
                    (plan.metadata or {}).get(
                        "stage2_exact_optimality_certified", False
                    )
                ),
                "stage1_mip_gap": (plan.metadata or {}).get("stage1_mip_gap"),
                "stage2_mip_gap": (plan.metadata or {}).get("stage2_mip_gap"),
                "stage1_objective_value": (plan.metadata or {}).get("stage1_objective_value"),
                "stage2_objective_value": (plan.metadata or {}).get("stage2_objective_value"),
                "stage1_has_feasible_incumbent": (plan.metadata or {}).get("stage1_has_feasible_incumbent"),
                "stage1_objective": (plan.metadata or {}).get("stage1_objective"),
                "stage1_best_bound": (plan.metadata or {}).get("stage1_best_bound"),
                "stage1_solver_best_bound": (plan.metadata or {}).get(
                    "stage1_solver_best_bound"
                ),
                "stage1_solver_mip_gap_ratio": (plan.metadata or {}).get(
                    "stage1_solver_mip_gap_ratio"
                ),
                # Keep Gurobi's native certificate distinct from the stronger
                # reporting lower bound that may combine it with the analytic
                # path-cover certificate.
                "stage1_gurobi_raw_best_bound": (plan.metadata or {}).get(
                    "stage1_gurobi_raw_best_bound"
                ),
                "stage1_gurobi_raw_mip_gap_ratio": (plan.metadata or {}).get(
                    "stage1_gurobi_raw_mip_gap_ratio"
                ),
                "stage1_certified_best_bound": (plan.metadata or {}).get(
                    "stage1_certified_best_bound"
                ),
                "stage1_certified_mip_gap_ratio": (plan.metadata or {}).get(
                    "stage1_certified_mip_gap_ratio"
                ),
                "stage1_certified_mip_gap_semantics": (plan.metadata or {}).get(
                    "stage1_certified_mip_gap_semantics"
                ),
                "stage1_weather_aware_lower_bound": (
                    plan.metadata or {}
                ).get("stage1_weather_aware_lower_bound"),
                "stage1_weather_aware_lower_bound_semantics": (
                    plan.metadata or {}
                ).get("stage1_weather_aware_lower_bound_semantics"),
                "stage1_analytical_objective_lower_bound": (
                    plan.metadata or {}
                ).get("stage1_analytical_objective_lower_bound"),
                "stage1_vehicle_usage_analytical_lower_bound": (
                    plan.metadata or {}
                ).get("stage1_vehicle_usage_analytical_lower_bound"),
                "stage1_analytical_weather_energy_fuel_lower_bound": (
                    plan.metadata or {}
                ).get(
                    "stage1_analytical_weather_energy_fuel_lower_bound"
                ),
                "stage1_analytical_weather_energy_fuel_lower_bound_details": dict(
                    (plan.metadata or {}).get(
                        "stage1_analytical_weather_energy_fuel_lower_bound_details"
                    )
                    or {}
                ),
                "stage1_analytical_total_objective_certificate_eligible": bool(
                    (plan.metadata or {}).get(
                        "stage1_analytical_total_objective_certificate_eligible",
                        False,
                    )
                ),
                "stage1_analytical_total_objective_certificate_blockers": list(
                    (plan.metadata or {}).get(
                        "stage1_analytical_total_objective_certificate_blockers"
                    )
                    or []
                ),
                "stage1_analytical_objective_lower_bound_semantics": (
                    plan.metadata or {}
                ).get("stage1_analytical_objective_lower_bound_semantics"),
                "stage1_certified_gap_stop_threshold": (plan.metadata or {}).get(
                    "stage1_certified_gap_stop_threshold"
                ),
                "stage1_best_obj_stop_enabled": bool(
                    (plan.metadata or {}).get("stage1_best_obj_stop_enabled", True)
                ),
                "stage1_best_obj_stop_applied": bool(
                    (plan.metadata or {}).get("stage1_best_obj_stop_applied", False)
                ),
                "stage1_certified_gap_stop_triggered": (plan.metadata or {}).get(
                    "stage1_certified_gap_stop_triggered"
                ),
                "stage1_termination_reason": (plan.metadata or {}).get(
                    "stage1_termination_reason"
                ),
                "gurobi_threads": (plan.metadata or {}).get("gurobi_threads"),
                "stage1_gurobi_feasibility_tol": (
                    plan.metadata or {}
                ).get("stage1_gurobi_feasibility_tol"),
                "stage2_gurobi_feasibility_tol": (
                    plan.metadata or {}
                ).get("stage2_gurobi_feasibility_tol"),
                "stage2_gurobi_integrality_tol": (
                    plan.metadata or {}
                ).get("stage2_gurobi_integrality_tol"),
                "stage1_numeric_diagnostics": dict(
                    (plan.metadata or {}).get("stage1_numeric_diagnostics") or {}
                ),
                "stage2_numeric_diagnostics": dict(
                    (plan.metadata or {}).get("stage2_numeric_diagnostics") or {}
                ),
                "stage1_mip_gap_ratio": (plan.metadata or {}).get("stage1_mip_gap_ratio"),
                "stage1_runtime_seconds": (plan.metadata or {}).get("stage1_runtime_seconds"),
                "stage1_pre_optimize_seconds": (plan.metadata or {}).get(
                    "stage1_pre_optimize_seconds"
                ),
                "stage1_model_variable_count": (plan.metadata or {}).get(
                    "stage1_model_variable_count"
                ),
                "stage1_model_constraint_count": (plan.metadata or {}).get(
                    "stage1_model_constraint_count"
                ),
                "stage1_search_telemetry": dict(
                    (plan.metadata or {}).get("stage1_search_telemetry") or {}
                ),
                "stage1_vehicle_count_lower_bound": (plan.metadata or {}).get(
                    "stage1_vehicle_count_lower_bound"
                ),
                "stage1_vehicle_count_lower_bound_constraint_count": (
                    plan.metadata or {}
                ).get("stage1_vehicle_count_lower_bound_constraint_count"),
                "stage1_vehicle_count_lower_bound_semantics": (
                    plan.metadata or {}
                ).get("stage1_vehicle_count_lower_bound_semantics"),
                "stage1_identical_vehicle_groups": list(
                    (plan.metadata or {}).get(
                        "stage1_identical_vehicle_groups"
                    )
                    or ()
                ),
                "stage1_identical_vehicle_group_count": (
                    plan.metadata or {}
                ).get("stage1_identical_vehicle_group_count"),
                "stage1_identical_vehicle_activation_prefix_constraint_count": (
                    plan.metadata or {}
                ).get(
                    "stage1_identical_vehicle_activation_prefix_constraint_count"
                ),
                "stage1_redundant_arc_link_constraints_omitted": (
                    plan.metadata or {}
                ).get("stage1_redundant_arc_link_constraints_omitted"),
                "integrated_redundant_arc_link_constraints_omitted": (
                    plan.metadata or {}
                ).get("integrated_redundant_arc_link_constraints_omitted"),
                "integrated_activity_blocking_constraint_count": (
                    plan.metadata or {}
                ).get("integrated_activity_blocking_constraint_count"),
                "integrated_activity_blocking_implication_count": (
                    plan.metadata or {}
                ).get("integrated_activity_blocking_implication_count"),
                "integrated_activity_blocking_constraints_aggregated": (
                    plan.metadata or {}
                ).get("integrated_activity_blocking_constraints_aggregated"),
                "integrated_refuel_activation_binary_count": (
                    plan.metadata or {}
                ).get("integrated_refuel_activation_binary_count"),
                "stage1_time_limit_sec_effective": (plan.metadata or {}).get(
                    "stage1_time_limit_sec_effective"
                ),
                "stage2_has_feasible_incumbent": (plan.metadata or {}).get("stage2_has_feasible_incumbent"),
                "stage2_objective": (plan.metadata or {}).get("stage2_objective"),
                "stage2_best_bound": (plan.metadata or {}).get("stage2_best_bound"),
                "stage2_mip_gap_ratio": (plan.metadata or {}).get("stage2_mip_gap_ratio"),
                "stage2_runtime_seconds": (plan.metadata or {}).get("stage2_runtime_seconds"),
                "stage2_time_limit_sec_effective": (plan.metadata or {}).get(
                    "stage2_time_limit_sec_effective"
                ),
                "stage1_energy_cost_proxy_used_in_objective": bool(
                    (plan.metadata or {}).get(
                        "stage1_energy_cost_proxy_used_in_objective",
                        False,
                    )
                ),
                "stage1_time_indexed_energy_recourse_configuration": dict(
                    (plan.metadata or {}).get(
                        "stage1_time_indexed_energy_recourse_configuration"
                    )
                    or {}
                ),
                "stage1_time_indexed_energy_recourse_weather_input": dict(
                    (plan.metadata or {}).get(
                        "stage1_time_indexed_energy_recourse_weather_input"
                    )
                    or {}
                ),
                "stage1_time_indexed_energy_recourse_result": dict(
                    (plan.metadata or {}).get(
                        "stage1_time_indexed_energy_recourse_result"
                    )
                    or {}
                ),
                "stage1_accounting_objective_components": dict(
                    (plan.metadata or {}).get(
                        "stage1_accounting_objective_components"
                    )
                    or {}
                ),
                "stage1_driver_cost_constraint_count": (
                    plan.metadata or {}
                ).get("stage1_driver_cost_constraint_count"),
                "stage1_degradation_cost_term_count": (
                    plan.metadata or {}
                ).get("stage1_degradation_cost_term_count"),
                "stage1_switch_cost_term_count": (
                    plan.metadata or {}
                ).get("stage1_switch_cost_term_count"),
                "stage1_stage2_candidate_limit_requested": (
                    plan.metadata or {}
                ).get("stage1_stage2_candidate_limit_requested"),
                "stage1_composition_search_radius_requested": (
                    plan.metadata or {}
                ).get("stage1_composition_search_radius_requested"),
                "stage1_bev_frontier_enabled": bool(
                    (plan.metadata or {}).get(
                        "stage1_bev_frontier_enabled",
                        False,
                    )
                ),
                "stage1_composition_search_runtime_seconds": (
                    plan.metadata or {}
                ).get("stage1_composition_search_runtime_seconds"),
                "stage1_composition_search_certificate_evidence_wall_seconds": (
                    plan.metadata or {}
                ).get(
                    "stage1_composition_search_certificate_evidence_wall_seconds"
                ),
                "stage1_used_powertrain_composition_search": dict(
                    (plan.metadata or {}).get(
                        "stage1_used_powertrain_composition_search"
                    )
                    or {}
                ),
                "stage1_used_powertrain_composition_search_accepted": bool(
                    (plan.metadata or {}).get(
                        "stage1_used_powertrain_composition_search_accepted",
                        False,
                    )
                ),
                "bev_cost_frontier": dict(
                    (plan.metadata or {}).get("bev_cost_frontier") or {}
                ),
                "stage1_pool_solution_count": (plan.metadata or {}).get(
                    "stage1_pool_solution_count"
                ),
                "stage1_distinct_candidate_count": (
                    plan.metadata or {}
                ).get("stage1_distinct_candidate_count"),
                "stage1_stage2_candidate_count_evaluated": (
                    plan.metadata or {}
                ).get("stage1_stage2_candidate_count_evaluated"),
                "stage1_stage2_feasible_candidate_count": (
                    plan.metadata or {}
                ).get("stage1_stage2_feasible_candidate_count"),
                "stage1_stage2_selected_candidate_index": (
                    plan.metadata or {}
                ).get("stage1_stage2_selected_candidate_index"),
                "stage1_stage2_selected_candidate_hash": (
                    plan.metadata or {}
                ).get("stage1_stage2_selected_candidate_hash"),
                "stage1_stage2_selected_canonical_actual_cost_jpy": (
                    plan.metadata or {}
                ).get(
                    "stage1_stage2_selected_canonical_actual_cost_jpy"
                ),
                "stage1_primary_incumbent_objective_jpy": (
                    plan.metadata or {}
                ).get("stage1_primary_incumbent_objective_jpy"),
                "stage1_selected_candidate_relaxed_objective_jpy": (
                    plan.metadata or {}
                ).get(
                    "stage1_selected_candidate_relaxed_objective_jpy"
                ),
                "stage1_stage2_candidate_selection_semantics": (
                    plan.metadata or {}
                ).get("stage1_stage2_candidate_selection_semantics"),
                "stage1_stage2_candidate_global_optimality_claimed": bool(
                    (plan.metadata or {}).get(
                        "stage1_stage2_candidate_global_optimality_claimed",
                        False,
                    )
                ),
                "stage1_stage2_candidate_evaluation": list(
                    (plan.metadata or {}).get(
                        "stage1_stage2_candidate_evaluation"
                    )
                    or []
                ),
                "stage1_primary_runtime_seconds": (
                    plan.metadata or {}
                ).get("stage1_primary_runtime_seconds"),
                "stage1_primary_search_time_limit_seconds": (
                    plan.metadata or {}
                ).get("stage1_primary_search_time_limit_seconds"),
                "stage1_candidate_enumeration_reserve_seconds": (
                    plan.metadata or {}
                ).get("stage1_candidate_enumeration_reserve_seconds"),
                "stage1_cost_ranked_composition_budget_enabled": bool(
                    (plan.metadata or {}).get(
                        "stage1_cost_ranked_composition_budget_enabled",
                        False,
                    )
                ),
                "stage1_cost_ranked_composition_budget_semantics": (
                    plan.metadata or {}
                ).get("stage1_cost_ranked_composition_budget_semantics"),
                "stage1_candidate_enumeration_runtime_seconds": (
                    plan.metadata or {}
                ).get("stage1_candidate_enumeration_runtime_seconds"),
                "stage1_candidate_enumeration_events": list(
                    (plan.metadata or {}).get(
                        "stage1_candidate_enumeration_events"
                    )
                    or []
                ),
                "stage1_candidate_powertrain_pattern_no_good_cut_count": (
                    plan.metadata or {}
                ).get(
                    "stage1_candidate_powertrain_pattern_no_good_cut_count"
                ),
                "rolling_horizon_policy": (plan.metadata or {}).get(
                    "rolling_horizon_policy", ""
                ),
                "rolling_start_slot_index": (plan.metadata or {}).get(
                    "rolling_start_slot_index"
                ),
                "rolling_execution_minutes": (plan.metadata or {}).get(
                    "rolling_execution_minutes"
                ),
                "stage1_feasible": (plan.metadata or {}).get("stage1_feasible"),
                "stage2_feasible": (plan.metadata or {}).get("stage2_feasible"),
                "assignment_candidate_available": bool((plan.metadata or {}).get("assignment_candidate_available", False)),
                "research_candidate_only": bool((plan.metadata or {}).get("research_candidate_only", False)),
                "solver_objective_matches_accounting_total": bool(
                    (plan.metadata or {}).get(
                        "solver_objective_matches_accounting_total",
                        problem.metadata.get("solver_objective_matches_accounting_total", True),
                    )
                ),
                "objective_semantics": str(
                    (plan.metadata or {}).get("objective_semantics")
                    or problem.metadata.get("objective_semantics")
                    or "single_solver_objective"
                ),
                "phase": phase,
                "requested_phase_token": str(
                    (plan.metadata or {}).get("requested_phase_token")
                    or getattr(config, "requested_phase_token", "")
                    or ""
                ),
                "requested_phase": str(
                    (plan.metadata or {}).get("requested_phase")
                    or getattr(config, "requested_phase", "")
                    or phase
                ),
                "resolved_phase": str(
                    (plan.metadata or {}).get("resolved_phase")
                    or getattr(config, "resolved_phase", "")
                    or phase
                ),
                "executed_phase": str(
                    (plan.metadata or {}).get("executed_phase")
                    or getattr(config, "executed_phase", "")
                    or phase
                ),
                "true_solver_family": "milp",
                "independent_implementation": True,
                "delegates_to": "none",
                "solver_display_name": "MILP",
                "solver_maturity": "core",
                "service_coverage_mode": service_coverage_mode,
                "thesis_mode": bool(getattr(config, "thesis_mode", False)),
                "debug_mode": bool(getattr(config, "debug_mode", False)) or result_class == "debug_result",
                "research_run": bool(getattr(config, "research_run", False)),
                "diagnostic_mode": diagnostic_mode,
                "result_class": result_class,
                "research_kpi_eligible": research_kpi_eligible,
                "charging_dispatch_evaluated": plan_metadata.get("charging_dispatch_evaluated"),
                "soc_constraints_evaluated": plan_metadata.get("soc_constraints_evaluated"),
                "supports_assignment_milp": bool(plan_metadata.get("supports_assignment_milp", False)),
                "binding_constraint_report": binding_constraint_report,
                "assignment_validation_diagnostics": [
                    dict(item)
                    for item in tuple(getattr(report, "diagnostics", ()) or ())
                ],
                "allow_partial_service": allow_partial_service,
                "strict_coverage_enforced": service_coverage_mode == "strict",
                "strict_coverage_precheck": dict(
                    problem.metadata.get("strict_coverage_precheck") or {}
                ),
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
                "synthetic_pv_fallback_allowed": bool(
                    problem.metadata.get("synthetic_pv_fallback_allowed", False)
                ),
                "synthetic_pv_fallback_applied": bool(
                    problem.metadata.get("synthetic_pv_fallback_applied", False)
                ),
                "arc_pruning_summary": dict(
                    (plan.metadata or {}).get("arc_pruning_summary")
                    or model_stats.get("arc_pruning_summary")
                    or {}
                ),
                "successor_pruning_enabled": bool(
                    ((plan.metadata or {}).get("arc_pruning_summary") or model_stats.get("arc_pruning_summary") or {}).get(
                        "successor_pruning_enabled",
                        False,
                    )
                ),
                **(
                    solver_benchmark_eligibility(
                        OptimizationMode.MILP,
                        solver_maturity="core",
                        true_solver_family="milp",
                        solver_display_name="MILP",
                    )
                    if outcome.supports_exact_milp
                    else {
                        "eligible_for_main_benchmark": False,
                        "eligible_for_appendix_benchmark": True,
                        "comparison_note": (
                            "Successor-pruned reduced-network MILP; appendix "
                            "or sensitivity analysis only."
                        ),
                    }
                ),
                "candidate_generation_mode": (
                    "full_network_branch_and_cut"
                    if outcome.supports_exact_milp
                    else "successor_pruned_branch_and_cut"
                ),
                "evaluation_mode": problem.scenario.objective_mode,
                "has_feasible_incumbent": outcome.has_feasible_incumbent,
                "incumbent_count": outcome.incumbent_count,
                "warm_start_applied": outcome.warm_start_applied,
                "warm_start_source": outcome.warm_start_source or (
                    (problem.baseline_plan.metadata or {}).get("source")
                    if problem.baseline_plan
                    else None
                ),
                "phase4_phase3_seed_audit": dict(
                    (problem.metadata or {}).get(
                        "phase4_phase3_seed_audit"
                    )
                    or {}
                ),
                "integrated_warm_start_audit": dict(
                    (plan.metadata or {}).get(
                        "integrated_warm_start_audit"
                    )
                    or {}
                ),
                "integrated_verified_start_search_bounds": dict(
                    (plan.metadata or {}).get(
                        "integrated_verified_start_search_bounds"
                    )
                    or {}
                ),
                "integrated_verified_start_objective_cap_constraint_count": (
                    (plan.metadata or {}).get(
                        "integrated_verified_start_objective_cap_constraint_count"
                    )
                ),
                "integrated_verified_start_vehicle_day_cap_constraint_count": (
                    (plan.metadata or {}).get(
                        "integrated_verified_start_vehicle_day_cap_constraint_count"
                    )
                ),
                "integrated_verified_start_search_bound_semantics": (
                    (plan.metadata or {}).get(
                        "integrated_verified_start_search_bound_semantics"
                    )
                ),
                "integrated_mip_focus": (plan.metadata or {}).get(
                    "integrated_mip_focus"
                ),
                "integrated_heuristics": (plan.metadata or {}).get(
                    "integrated_heuristics"
                ),
                "integrated_symmetry": (plan.metadata or {}).get(
                    "integrated_symmetry"
                ),
                "integrated_nodefile_start_gb": (plan.metadata or {}).get(
                    "integrated_nodefile_start_gb"
                ),
                "integrated_nodefile_dir": (plan.metadata or {}).get(
                    "integrated_nodefile_dir"
                ),
                "integrated_search_profile": dict(
                    (plan.metadata or {}).get(
                        "integrated_search_profile"
                    )
                    or {}
                ),
                "integrated_analytical_objective_lower_bound": (
                    (plan.metadata or {}).get(
                        "integrated_analytical_objective_lower_bound"
                    )
                ),
                "integrated_vehicle_usage_analytical_lower_bound": (
                    (plan.metadata or {}).get(
                        "integrated_vehicle_usage_analytical_lower_bound"
                    )
                ),
                "integrated_analytical_weather_energy_fuel_lower_bound": (
                    (plan.metadata or {}).get(
                        "integrated_analytical_weather_energy_fuel_lower_bound"
                    )
                ),
                "integrated_analytical_weather_energy_fuel_lower_bound_details": dict(
                    (plan.metadata or {}).get(
                        "integrated_analytical_weather_energy_fuel_lower_bound_details"
                    )
                    or {}
                ),
                "integrated_analytical_objective_floor_constraint_count": (
                    (plan.metadata or {}).get(
                        "integrated_analytical_objective_floor_constraint_count"
                    )
                ),
                "integrated_analytical_objective_floor_certificate_eligible": bool(
                    (plan.metadata or {}).get(
                        "integrated_analytical_objective_floor_certificate_eligible",
                        False,
                    )
                ),
                "integrated_analytical_objective_floor_blockers": list(
                    (plan.metadata or {}).get(
                        "integrated_analytical_objective_floor_blockers"
                    )
                    or ()
                ),
                "integrated_analytical_objective_lower_bound_semantics": (
                    (plan.metadata or {}).get(
                        "integrated_analytical_objective_lower_bound_semantics"
                    )
                ),
                "integrated_identical_vehicle_groups": list(
                    (plan.metadata or {}).get(
                        "integrated_identical_vehicle_groups"
                    )
                    or ()
                ),
                "integrated_identical_vehicle_group_count": (
                    (plan.metadata or {}).get(
                        "integrated_identical_vehicle_group_count"
                    )
                ),
                "integrated_identical_vehicle_activation_prefix_constraint_count": (
                    (plan.metadata or {}).get(
                        "integrated_identical_vehicle_activation_prefix_constraint_count"
                    )
                ),
                "integrated_identical_vehicle_symmetry_semantics": (
                    (plan.metadata or {}).get(
                        "integrated_identical_vehicle_symmetry_semantics"
                    )
                ),
                "best_bound": outcome.best_bound,
                "raw_best_bound": outcome.best_bound,
                "certified_best_bound": outcome.certified_best_bound,
                # A gap is meaningful only when the returned solver outcome
                # has an incumbent.  Infeasible/no-incumbent runs must not
                # expose a stale or stage-1 gap as an achieved gap.
                "final_gap": outcome.final_gap if outcome.has_feasible_incumbent else None,
                "raw_mip_gap_ratio": (
                    outcome.final_gap
                    if outcome.has_feasible_incumbent
                    else None
                ),
                "certified_mip_gap_ratio": (
                    outcome.certified_gap
                    if outcome.has_feasible_incumbent
                    else None
                ),
                "certified_mip_gap_semantics": (
                    outcome.certified_gap_semantics
                ),
                "requested_mip_gap": float(config.mip_gap),
                "achieved_mip_gap": outcome.final_gap if outcome.has_feasible_incumbent else None,
                "nodes_explored": outcome.nodes_explored,
                "runtime_sec": outcome.runtime_sec,
                "solve_time_sec": outcome.runtime_sec,
                "first_feasible_sec": outcome.first_feasible_sec,
                "uses_exact_repair": False,
                "presolve_reduction_summary": dict(outcome.presolve_reduction_summary or {}),
                "iis_generated": outcome.iis_generated,
                "fallback_reason": outcome.fallback_reason,
                "fallback_applied": bool(is_baseline_fallback),
                "objective_mode": problem.scenario.objective_mode,
                "objective_weights": {
                    "electricity_cost": float(problem.objective_weights.energy),
                    "fuel_cost": float(problem.objective_weights.fuel),
                    "demand_charge_cost": float(problem.objective_weights.demand),
                    "vehicle_fixed_cost": float(problem.objective_weights.vehicle),
                    "vehicle_usage_cost": float(problem.objective_weights.vehicle_usage),
                    "unserved_penalty": float(problem.objective_weights.unserved),
                    "switch_cost": float(problem.objective_weights.switch),
                    "deviation_cost": float(problem.objective_weights.deviation),
                    "degradation": float(problem.objective_weights.degradation),
                    "utilization": float(problem.objective_weights.utilization),
                    "return_leg_bonus": float(problem.objective_weights.return_leg_bonus),
                },
                "termination_reason": self._termination_reason(outcome.solver_status),
                "effective_limits": {
                    "time_limit_sec": int(config.time_limit_sec),
                    "stage1_time_limit_sec": (plan.metadata or {}).get(
                        "stage1_time_limit_sec_effective"
                    ),
                    "stage2_time_limit_sec": (plan.metadata or {}).get(
                        "stage2_time_limit_sec_effective"
                    ),
                    "mip_gap": float(config.mip_gap),
                    "requested_mip_gap": float(config.mip_gap),
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
                    "fallback_count": 1 if is_baseline_fallback else 0,
                },
            },
        )

    def _termination_reason(self, solver_status: str) -> str:
        status = str(solver_status or "").strip().lower()
        if status == "optimal":
            return "optimal"
        if status == "feasible":
            return "stopped_with_feasible"
        if status == "debug_result":
            return "debug_result"
        if status == "repaired_heuristic":
            return "postsolve_repaired_heuristic"
        if status in {"time_limit", "time_limit_baseline"}:
            return "time_limit"
        if status in {"baseline_fallback", "partial_baseline_fallback"}:
            return "baseline_fallback"
        if status in {"infeasible", "inf_or_unbd", "unbounded"}:
            return "infeasible_or_unbounded"
        if status == "suboptimal":
            return "stopped_with_feasible"
        if status == "auto_relaxed_baseline":
            return "baseline_after_relax"
        if status == "phase2_assignment_feasible":
            return "assignment_only_feasible"
        return "unknown"

    def _binding_constraint_report(self, report: Any, plan: Any) -> Dict[str, Any]:
        metrics = dict(getattr(report, "metrics", {}) or {})
        metadata = dict(getattr(plan, "metadata", {}) or {})
        slack_summary = dict(metadata.get("diagnostic_slack_summary") or {})

        def _int_metric(key: str, default: int = 0) -> int:
            try:
                return int(metrics.get(key, default) or 0)
            except (TypeError, ValueError):
                return default

        def _float_value(raw: Any) -> float:
            try:
                return float(raw or 0.0)
            except (TypeError, ValueError):
                return 0.0

        families = {
            "coverage": max(_int_metric("unassigned_trip_count"), int(slack_summary.get("unserved_trip_count", 0) or 0)),
            "duplicate_assignment": _int_metric("duplicate_trip_count"),
            "vehicle_time_overlap": _int_metric("vehicle_time_overlap_count"),
            "dispatch_transition": _int_metric("infeasible_transition_count"),
            "ev_soc": max(
                _int_metric("ev_soc_violation_count"),
                1 if _float_value(slack_summary.get("soc_lower_deficit_kwh")) > 1.0e-9 else 0,
                1 if _float_value(slack_summary.get("soc_upper_excess_kwh")) > 1.0e-9 else 0,
            ),
            "bess_soc": _int_metric("bess_soc_violation_count"),
            "contract_power": max(
                _int_metric("contract_power_violation_count"),
                1 if _float_value(slack_summary.get("contract_over_limit_kwh")) > 1.0e-9 else 0,
            ),
            "charger_concurrency": _int_metric("charger_concurrency_violation_count"),
        }
        binding_families = tuple(sorted(name for name, count in families.items() if int(count or 0) > 0))
        return {
            "source": "postsolve_validation_metrics_and_diagnostic_slacks",
            "binding_families": binding_families,
            "family_counts": families,
            "validation_metrics": metrics,
            "diagnostic_slack_summary": slack_summary,
            "research_kpi_eligible": False,
            "limitations": tuple(metadata.get("diagnostic_limitations") or ()),
        }

    def _lightweight_model_stats(
        self,
        problem: CanonicalOptimizationProblem,
    ) -> Dict[str, Any]:
        trip_by_id = problem.trip_by_id()
        assignment_pairs = self._builder.enumerate_assignment_pairs(problem)
        arc_pairs = self._builder.enumerate_arc_pairs(problem, trip_by_id)
        arc_pruning_summary_fn = getattr(self._builder, "arc_pruning_summary", None)
        arc_pruning_summary = (
            arc_pruning_summary_fn(problem, trip_by_id)
            if callable(arc_pruning_summary_fn)
            else {}
        )
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
                # Both Phase 3 and Phase 4 use node-flow equalities; explicit
                # x<=y endpoint rows are intentionally omitted as redundant.
                "connection_link": 0,
                "connection_link_omitted": len(arc_pairs) * 2,
                "connection_node_flow": len(assignment_pairs) * 2,
            },
            "objective_terms": (),
            "variable_samples": [],
            "constraint_samples": [],
            "arc_pruning_summary": arc_pruning_summary,
        }
