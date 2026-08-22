"""Compare Phase 3 with a small integrated MILP on the same weather case.

The audit deliberately uses a deterministic, day-spanning trip subset.  It is
not a replacement for the full-day result; it is a tractable oracle check for
the two-stage decomposition and for 15-minute versus 5-minute discretization.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bff.routers.optimization import (  # noqa: E402
    _prepare_weather_policy_for_scenario,
    _prepared_inputs_root,
)
from bff.services.run_preparation import (  # noqa: E402
    load_prepared_input,
    materialize_scenario_from_prepared_input,
)
from bff.store import scenario_store as store  # noqa: E402
from scripts.run_research_phase3_frontend_weather import _assignment_mix  # noqa: E402
from src.optimization import (  # noqa: E402
    OptimizationConfig,
    OptimizationEngine,
    OptimizationMode,
    ProblemBuilder,
)
from src.optimization.common.problem import CanonicalOptimizationProblem  # noqa: E402
from src.optimization.common.research_phase3_policy import (  # noqa: E402
    enforce_research_phase3_single_continuous_duty,
)
from src.preprocess.weather.operation_policy import (  # noqa: E402
    apply_weather_policy_to_problem,
)


_PREPARED_WEATHER_COMPARISON_KEYS = (
    "comparison_type",
    "comparison_role",
    "counterfactual_pv_source_date",
    "weather_observation_date",
    "weather_profile_source",
    "calendar_policy",
    "allow_fixed_weekday_timetable_pv_counterfactual",
)


def _restore_prepared_weather_comparison_contract(
    scenario: dict[str, Any],
    prepared_payload: dict[str, Any],
) -> None:
    """Restore explicit prepared comparison metadata without changing inputs.

    Materialization merges the current scenario document with the frozen
    prepared input.  An empty current `comparison_type` must not erase the
    explicit counterfactual contract saved by Prepare.  Conversely, a
    conflicting non-empty current declaration is provenance drift and fails
    closed rather than being overwritten.
    """

    prepared_config = dict(prepared_payload.get("simulation_config") or {})
    scenario_config = dict(scenario.get("simulation_config") or {})
    for key in _PREPARED_WEATHER_COMPARISON_KEYS:
        prepared_value = prepared_config.get(key)
        if prepared_value in (None, ""):
            continue
        scenario_value = scenario_config.get(key)
        if scenario_value not in (None, "") and scenario_value != prepared_value:
            raise ValueError(
                "prepared weather comparison contract conflicts with current "
                f"scenario for {key}: prepared={prepared_value!r}, "
                f"scenario={scenario_value!r}"
            )
        scenario_config[key] = prepared_value
    scenario["simulation_config"] = scenario_config


def _day_spanning_trip_subset(problem: CanonicalOptimizationProblem, count: int) -> tuple[Any, ...]:
    ordered = sorted(
        problem.trips,
        key=lambda trip: (int(trip.departure_min), int(trip.arrival_min), str(trip.trip_id)),
    )
    if count <= 0 or count > len(ordered):
        raise ValueError(f"trip_count must be within 1..{len(ordered)}, got {count}")
    if count == 1:
        return (ordered[0],)
    indices = {
        round(position * (len(ordered) - 1) / (count - 1))
        for position in range(count)
    }
    if len(indices) != count:
        raise AssertionError("day-spanning selection did not produce the requested trip count")
    return tuple(ordered[index] for index in sorted(indices))


def _available_vehicle_subset(
    problem: CanonicalOptimizationProblem,
    *,
    per_type: int,
    vehicle_types: tuple[str, ...] = ("BEV", "ICE"),
) -> tuple[Any, ...]:
    selected: list[Any] = []
    for vehicle_type in vehicle_types:
        candidates = sorted(
            (
                vehicle
                for vehicle in problem.vehicles
                if bool(vehicle.available)
                and str(vehicle.vehicle_type).upper() == vehicle_type
            ),
            key=lambda vehicle: str(vehicle.vehicle_id),
        )
        if len(candidates) < per_type:
            raise ValueError(
                f"{vehicle_type} requires {per_type} available vehicles, found {len(candidates)}"
            )
        selected.extend(candidates[:per_type])
    return tuple(selected)


def _small_problem(
    problem: CanonicalOptimizationProblem,
    *,
    trip_count: int,
    vehicles_per_type: int,
    allowed_vehicle_type: str = "ALL",
) -> CanonicalOptimizationProblem:
    trips = _day_spanning_trip_subset(problem, trip_count)
    selected_vehicle_types = (
        ("BEV", "ICE")
        if allowed_vehicle_type == "ALL"
        else (allowed_vehicle_type,)
    )
    vehicles = _available_vehicle_subset(
        problem,
        per_type=vehicles_per_type,
        vehicle_types=selected_vehicle_types,
    )
    selected_trip_ids = {str(trip.trip_id) for trip in trips}
    feasible_connections = {
        str(from_trip_id): tuple(
            str(to_trip_id)
            for to_trip_id in to_trip_ids
            if str(to_trip_id) in selected_trip_ids
        )
        for from_trip_id, to_trip_ids in problem.feasible_connections.items()
        if str(from_trip_id) in selected_trip_ids
    }
    metadata = {
        **dict(problem.metadata or {}),
        "small_integrated_audit": True,
        "small_integrated_trip_selection": "evenly_spaced_over_ordered_service_day",
        "small_integrated_trip_count": len(trips),
        "small_integrated_vehicle_count_per_type": vehicles_per_type,
        "small_integrated_allowed_vehicle_type": allowed_vehicle_type,
    }
    return replace(
        problem,
        trips=trips,
        vehicles=vehicles,
        feasible_connections=feasible_connections,
        baseline_plan=None,
        metadata=metadata,
    )


def _align_objective_with_accounting(
    problem: CanonicalOptimizationProblem,
) -> CanonicalOptimizationProblem:
    """Remove non-accounting preference penalties from the oracle objective.

    The production model may prefer BESS/PV flows through soft priority terms.
    Those terms are operational tie-breakers, not ledger costs.  A comparison
    advertised as an integrated *cost* oracle must therefore optimize exactly
    the components later reported by accounting.  The oracle also uses a
    return-to-initial terminal SOC boundary so that neither formulation can
    consume unpriced initial battery inventory over the representative day.
    """

    component_flags = dict(problem.metadata.get("cost_component_flags") or {})
    disabled_non_accounting_terms = (
        "grid_to_bus_priority_penalty",
        "grid_to_bess_priority_penalty",
        "charge_session_start_penalty",
        "slot_concurrency_penalty",
        "early_charge_penalty",
        "soc_upper_buffer_penalty",
        "final_soc_target_penalty",
        "opportunistic_topup_deficit_penalty",
    )
    for key in disabled_non_accounting_terms:
        component_flags[key] = False
    return replace(
        problem,
        metadata={
            **dict(problem.metadata or {}),
            "cost_component_flags": component_flags,
            "small_integrated_objective_semantics": (
                "validated_accounting_cost_components_only"
            ),
            "small_integrated_disabled_non_accounting_terms": (
                disabled_non_accounting_terms
            ),
            "bev_terminal_soc_policy": "return_to_initial",
            "small_integrated_terminal_soc_boundary": "return_to_initial",
        },
    )


def _configure_small_discretization(
    scenario: dict[str, Any],
    *,
    timestep_min: int,
) -> None:
    if timestep_min not in {5, 15}:
        raise ValueError("small integrated audit supports only 5- or 15-minute slots")
    simulation_config = dict(scenario.get("simulation_config") or {})
    simulation_config["timestep_min"] = timestep_min
    simulation_config["time_step_min"] = timestep_min
    simulation_config["milp_max_successors_per_trip"] = 0
    scenario["simulation_config"] = simulation_config
    scenario_overlay = dict(scenario.get("scenario_overlay") or {})
    solver_config = dict(scenario_overlay.get("solver_config") or {})
    solver_config["timestep_min"] = timestep_min
    solver_config["time_step_min"] = timestep_min
    solver_config["milp_max_successors_per_trip"] = 0
    scenario_overlay["solver_config"] = solver_config
    scenario["scenario_overlay"] = scenario_overlay


def _scaled_uncertainty_problem(
    problem: CanonicalOptimizationProblem,
    *,
    pv_scale: float,
    bev_consumption_scale: float,
) -> CanonicalOptimizationProblem:
    if pv_scale <= 0.0 or bev_consumption_scale <= 0.0:
        raise ValueError("uncertainty scale factors must be positive")
    vehicles = tuple(
        replace(
            vehicle,
            energy_consumption_kwh_per_km=(
                float(vehicle.energy_consumption_kwh_per_km)
                * bev_consumption_scale
                if vehicle.energy_consumption_kwh_per_km is not None
                else None
            ),
        )
        for vehicle in problem.vehicles
    )
    vehicle_types = tuple(
        replace(
            vehicle_type,
            energy_consumption_kwh_per_km=(
                float(vehicle_type.energy_consumption_kwh_per_km)
                * bev_consumption_scale
                if vehicle_type.energy_consumption_kwh_per_km is not None
                else None
            ),
        )
        for vehicle_type in problem.vehicle_types
    )
    trips = tuple(
        replace(trip, energy_kwh=float(trip.energy_kwh) * bev_consumption_scale)
        for trip in problem.trips
    )
    assets = {
        str(depot_id): replace(
            asset,
            pv_generation_kwh_by_slot=tuple(
                float(value) * pv_scale
                for value in asset.pv_generation_kwh_by_slot
            ),
        )
        for depot_id, asset in problem.depot_energy_assets.items()
    }
    pv_slots = tuple(
        replace(slot, pv_available_kw=float(slot.pv_available_kw) * pv_scale)
        for slot in problem.pv_slots
    )
    return replace(
        problem,
        trips=trips,
        vehicles=vehicles,
        vehicle_types=vehicle_types,
        depot_energy_assets=assets,
        pv_slots=pv_slots,
        metadata={
            **dict(problem.metadata or {}),
            "pv_uncertainty_scale": pv_scale,
            "bev_consumption_uncertainty_scale": bev_consumption_scale,
        },
    )


def _build_problem(args: argparse.Namespace, timestep_min: int) -> CanonicalOptimizationProblem:
    prepared_payload = load_prepared_input(
        scenario_id=args.scenario_id,
        prepared_input_id=args.prepared_input_id,
        scenarios_dir=_prepared_inputs_root(),
    )
    scenario = deepcopy(
        materialize_scenario_from_prepared_input(
            store.get_scenario_document_shallow(args.scenario_id),
            prepared_payload,
        )
    )
    _restore_prepared_weather_comparison_contract(scenario, prepared_payload)
    _configure_small_discretization(scenario, timestep_min=timestep_min)
    enforce_research_phase3_single_continuous_duty(scenario)
    scenario, forecast, profile = _prepare_weather_policy_for_scenario(
        scenario,
        enable_weather_operation_policy=None,
        weather_proxy_forecast_path=None,
    )
    build_config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        phase="phase4_integrated",
        research_run=True,
        allow_postsolve_repair=False,
    )
    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id=args.depot_id,
        service_id=args.service_id,
        config=build_config,
        planning_days=1,
    )
    if forecast is not None and profile is not None:
        problem = apply_weather_policy_to_problem(
            problem,
            forecast,
            profile,
            random_seed=args.random_seed,
        )
    return _align_objective_with_accounting(
        _small_problem(
            problem,
            trip_count=args.trip_count,
            vehicles_per_type=args.vehicles_per_type,
            allowed_vehicle_type=args.allowed_vehicle_type,
        )
    )


def _run_case(
    problem: CanonicalOptimizationProblem,
    *,
    phase: str,
    time_limit_sec: int,
    random_seed: int,
) -> dict[str, Any]:
    is_two_stage = phase == "phase3_two_stage"
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        phase=phase,
        requested_phase=phase,
        resolved_phase=phase,
        executed_phase=phase,
        time_limit_sec=time_limit_sec,
        stage1_time_limit_sec=time_limit_sec if is_two_stage else None,
        stage2_time_limit_sec=time_limit_sec if is_two_stage else None,
        mip_gap=0.0,
        random_seed=random_seed,
        warm_start=False,
        thesis_mode=is_two_stage,
        research_run=True,
        allow_postsolve_repair=False,
        integrated_actual_cost_objective=not is_two_stage,
        phase4_phase3_seed_enabled=False,
    )
    started = time.perf_counter()
    result = OptimizationEngine().solve(problem, config)
    elapsed = time.perf_counter() - started
    metadata = dict(result.solver_metadata or {})
    cost_breakdown = dict(result.cost_breakdown or {})
    accounted_total_cost_jpy = float(
        cost_breakdown.get("total_cost", 0.0) or 0.0
    )
    plan_metadata = dict(result.plan.metadata or {})
    milp_objective_value = plan_metadata.get("objective_value")
    objective_accounting_residual_jpy = (
        float(milp_objective_value) - accounted_total_cost_jpy
        if milp_objective_value is not None
        else None
    )
    vehicle_by_id = {
        str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles
    }
    used_vehicle_trace: dict[str, Any] = {}
    for vehicle_id, trip_ids in result.plan.vehicle_paths().items():
        vehicle = vehicle_by_id.get(str(vehicle_id))
        if vehicle is None:
            continue
        used_vehicle_trace[str(vehicle_id)] = {
            "vehicle_type": str(vehicle.vehicle_type),
            "initial_soc": vehicle.initial_soc,
            "trip_ids": list(trip_ids),
            "charging_slots": [
                {
                    "slot_index": int(slot.slot_index),
                    "charge_kw": float(slot.charge_kw),
                    "charger_id": str(slot.charger_id or ""),
                }
                for slot in result.plan.charging_slots
                if str(slot.vehicle_id) == str(vehicle_id)
            ],
            "solver_soc_kwh_by_slot": dict(
                result.plan.vehicle_soc_kwh_by_vehicle_slot.get(
                    str(vehicle_id), {}
                )
            ),
        }
    assignment_rows = sorted(
        (
            {
                "trip_id": str(leg.trip.trip_id),
                "vehicle_id": str(
                    result.plan.vehicle_id_for_duty(duty.duty_id)
                ),
                "vehicle_type": str(duty.vehicle_type).upper(),
            }
            for duty in result.plan.duties
            for leg in duty.legs
        ),
        key=lambda row: (
            row["trip_id"],
            row["vehicle_id"],
            row["vehicle_type"],
        ),
    )
    assignment_hash = hashlib.sha256(
        json.dumps(
            assignment_rows,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assignment_powertrain_hash = hashlib.sha256(
        json.dumps(
            [
                {
                    "trip_id": row["trip_id"],
                    "vehicle_type": row["vehicle_type"],
                }
                for row in assignment_rows
            ],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "analysis_label": str(
            problem.metadata.get("sensitivity_analysis_label") or "primary"
        ),
        "pv_uncertainty_scale": float(
            problem.metadata.get("pv_uncertainty_scale", 1.0) or 1.0
        ),
        "bev_consumption_uncertainty_scale": float(
            problem.metadata.get("bev_consumption_uncertainty_scale", 1.0)
            or 1.0
        ),
        "phase": phase,
        "timestep_min": int(problem.scenario.timestep_min),
        "time_limit_sec": time_limit_sec,
        "random_seed": random_seed,
        "solver_status": str(result.solver_status),
        "feasible": bool(result.feasible),
        "warnings": list(result.warnings),
        "infeasibility_reasons": list(result.infeasibility_reasons),
        "elapsed_seconds": elapsed,
        "trip_count_served": len(result.plan.served_trip_ids),
        "trip_count_unserved": len(result.plan.unserved_trip_ids),
        "used_vehicle_count": len(result.plan.vehicle_paths()),
        **_assignment_mix(problem, result),
        "objective_value": float(result.objective_value),
        "accounted_total_cost_jpy": accounted_total_cost_jpy,
        "best_bound": metadata.get("best_bound"),
        "final_gap_ratio": metadata.get("final_gap"),
        "stage1_best_bound": metadata.get("stage1_best_bound"),
        "stage1_objective": metadata.get("stage1_objective"),
        "stage1_mip_gap_ratio": metadata.get("stage1_mip_gap_ratio"),
        "stage2_objective": metadata.get("stage2_objective"),
        "stage1_vehicle_count_lower_bound": metadata.get(
            "stage1_vehicle_count_lower_bound"
        ),
        "supports_exact_milp": bool(metadata.get("supports_exact_milp", False)),
        "supports_integrated_exact_milp": bool(
            metadata.get("supports_integrated_exact_milp", False)
        ),
        "research_kpi_eligible": bool(metadata.get("research_kpi_eligible", False)),
        "has_feasible_incumbent": bool(
            metadata.get("has_feasible_incumbent", False)
        ),
        "raw_plan_solver_status": str(result.plan.metadata.get("status") or ""),
        "milp_objective_value": milp_objective_value,
        "raw_solver_primary_objective_value": plan_metadata.get(
            "raw_solver_primary_objective_value"
        ),
        "objective_preset": plan_metadata.get("objective_preset"),
        "objective_hierarchy": list(
            plan_metadata.get("objective_hierarchy") or ()
        ),
        "objective_accounting_residual_jpy": objective_accounting_residual_jpy,
        "objective_matches_accounting": bool(
            objective_accounting_residual_jpy is not None
            and abs(objective_accounting_residual_jpy) <= 1.0e-5
        ),
        "ev_energy_inventory_balanced": bool(
            cost_breakdown.get("ev_energy_inventory_balanced", False)
        ),
        "energy_cost_basis": str(cost_breakdown.get("energy_cost_basis") or ""),
        "objective_is_actual_cost": bool(
            cost_breakdown.get("objective_is_actual_cost", False)
        ),
        "integrated_actual_cost_objective_requested": bool(
            metadata.get("integrated_actual_cost_objective_requested", False)
        ),
        "integrated_actual_cost_contract_applied": bool(
            metadata.get("integrated_actual_cost_contract_applied", False)
        ),
        "termination_reason": metadata.get("termination_reason"),
        "validation_metrics": dict(metadata.get("validation_metrics") or {}),
        "research_acceptance_checks": dict(
            metadata.get("research_acceptance_checks") or {}
        ),
        "service_calendar_validation": dict(
            problem.metadata.get("service_calendar_validation") or {}
        ),
        "weather_comparison_contract": dict(
            problem.metadata.get("weather_comparison_contract") or {}
        ),
        "used_vehicle_trace": used_vehicle_trace,
        "assignment_rows": assignment_rows,
        "assignment_hash": assignment_hash,
        "assignment_powertrain_hash": assignment_powertrain_hash,
    }


def _is_integrated_exact_oracle_case(case: dict[str, Any]) -> bool:
    validation = dict(case.get("validation_metrics") or {})
    gap = case.get("final_gap_ratio")
    solver_optimal = (
        str(case.get("solver_status") or "").lower() == "optimal"
        and str(case.get("raw_plan_solver_status") or "").lower()
        == "optimal"
    )
    # Gurobi does not expose a single MIPGap/ObjBound for a completed
    # hierarchical multi-objective solve.  OPTIMAL is still an exact
    # certificate for every priority level; non-optimal termination remains
    # rejected regardless of any separately reported gap.
    exact_gap_or_optimal_multiobjective = solver_optimal and (
        gap is None or abs(float(gap)) <= 1.0e-9
    )
    objective_preset = str(case.get("objective_preset") or "").strip()
    lexicographic_contract_valid = True
    if objective_preset == "research_lexicographic_v1":
        expected_hierarchy = [
            "coverage_if_partial",
            "used_vehicle_days",
            "canonical_operating_cost",
            "inter_trip_deadhead_km",
            "charge_session_count",
        ]
        primary_value = case.get("raw_solver_primary_objective_value")
        lexicographic_contract_valid = bool(
            list(case.get("objective_hierarchy") or ())
            == expected_hierarchy
            and primary_value is not None
            and abs(
                float(primary_value)
                - float(case.get("used_vehicle_count") or 0)
            )
            <= 1.0e-6
        )
    return bool(
        case.get("phase") == "phase4_integrated"
        and case.get("feasible")
        and int(case.get("trip_count_unserved") or 0) == 0
        and solver_optimal
        and case.get("supports_integrated_exact_milp")
        and exact_gap_or_optimal_multiobjective
        and lexicographic_contract_valid
        and case.get("integrated_actual_cost_objective_requested")
        and case.get("integrated_actual_cost_contract_applied")
        and case.get("objective_is_actual_cost")
        and case.get("objective_matches_accounting")
        and case.get("ev_energy_inventory_balanced")
        and validation.get("all_required_validation_checks_passed")
    )


def _primary_oracle_comparison(cases: list[dict[str, Any]]) -> dict[str, Any]:
    primary_cases = [
        case
        for case in cases
        if case.get("analysis_label") == "primary"
        and int(case.get("timestep_min") or 0) == 15
    ]
    integrated = next(
        (case for case in primary_cases if case.get("phase") == "phase4_integrated"),
        None,
    )
    two_stage = next(
        (case for case in primary_cases if case.get("phase") == "phase3_two_stage"),
        None,
    )
    exact_oracle = bool(
        integrated is not None and _is_integrated_exact_oracle_case(integrated)
    )
    comparison: dict[str, Any] = {
        "integrated_exact_oracle_eligible": exact_oracle,
        "terminal_soc_boundary": "return_to_initial",
        "objective_semantics": "validated_accounting_cost_components_only",
    }
    if integrated is None or two_stage is None:
        comparison["two_stage_comparison_available"] = False
        return comparison

    integrated_cost = float(integrated["accounted_total_cost_jpy"])
    two_stage_cost = float(two_stage["accounted_total_cost_jpy"])
    cost_delta = two_stage_cost - integrated_cost
    comparison.update(
        {
            "two_stage_comparison_available": True,
            "integrated_accounted_total_cost_jpy": integrated_cost,
            "two_stage_accounted_total_cost_jpy": two_stage_cost,
            "two_stage_minus_integrated_cost_jpy": cost_delta,
            "two_stage_cost_gap_ratio": cost_delta
            / max(abs(integrated_cost), 1.0),
            "two_stage_matches_integrated_cost": abs(cost_delta) <= 1.0e-5,
            "used_vehicle_count_delta": int(two_stage["used_vehicle_count"])
            - int(integrated["used_vehicle_count"]),
            "used_vehicle_type_mix_matches": dict(
                two_stage.get("used_vehicle_count_by_type") or {}
            )
            == dict(integrated.get("used_vehicle_count_by_type") or {}),
            "served_trip_type_mix_matches": dict(
                two_stage.get("served_trip_count_by_vehicle_type") or {}
            )
            == dict(integrated.get("served_trip_count_by_vehicle_type") or {}),
            "assignment_hash_matches": str(
                two_stage.get("assignment_hash") or ""
            )
            == str(integrated.get("assignment_hash") or ""),
            "two_stage_assignment_hash": two_stage.get("assignment_hash"),
            "integrated_assignment_hash": integrated.get(
                "assignment_hash"
            ),
            "assignment_powertrain_hash_matches": str(
                two_stage.get("assignment_powertrain_hash") or ""
            )
            == str(
                integrated.get("assignment_powertrain_hash") or ""
            ),
            "two_stage_assignment_powertrain_hash": two_stage.get(
                "assignment_powertrain_hash"
            ),
            "integrated_assignment_powertrain_hash": integrated.get(
                "assignment_powertrain_hash"
            ),
            "comparison_lower_bound_consistent": cost_delta >= -1.0e-5,
        }
    )
    stage1_objective = two_stage.get("stage1_objective")
    stage1_best_bound = two_stage.get("stage1_best_bound")
    comparison.update(
        {
            "two_stage_stage1_objective_jpy": stage1_objective,
            "two_stage_stage1_best_bound_jpy": stage1_best_bound,
            "two_stage_stage1_gap_ratio": two_stage.get(
                "stage1_mip_gap_ratio"
            ),
            "stage1_objective_minus_integrated_cost_jpy": (
                float(stage1_objective) - integrated_cost
                if stage1_objective is not None
                else None
            ),
            "integrated_cost_minus_stage1_best_bound_jpy": (
                integrated_cost - float(stage1_best_bound)
                if stage1_best_bound is not None
                else None
            ),
        }
    )
    return comparison


def _five_minute_sensitivity_comparison(
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compare exact integrated runs at 15- and 5-minute resolution."""
    integrated_by_timestep = {
        int(case.get("timestep_min") or 0): case
        for case in cases
        if case.get("analysis_label") == "primary"
        and case.get("phase") == "phase4_integrated"
    }
    fifteen_minute = integrated_by_timestep.get(15)
    five_minute = integrated_by_timestep.get(5)
    comparison: dict[str, Any] = {
        "comparison_available": fifteen_minute is not None and five_minute is not None,
        "both_exact_oracle_eligible": bool(
            fifteen_minute is not None
            and five_minute is not None
            and _is_integrated_exact_oracle_case(fifteen_minute)
            and _is_integrated_exact_oracle_case(five_minute)
        ),
    }
    if fifteen_minute is None or five_minute is None:
        return comparison

    fifteen_cost = float(fifteen_minute["accounted_total_cost_jpy"])
    five_cost = float(five_minute["accounted_total_cost_jpy"])
    comparison.update(
        {
            "fifteen_minute_accounted_total_cost_jpy": fifteen_cost,
            "five_minute_accounted_total_cost_jpy": five_cost,
            "five_minus_fifteen_cost_jpy": five_cost - fifteen_cost,
            "five_minus_fifteen_cost_ratio": (five_cost - fifteen_cost)
            / max(abs(fifteen_cost), 1.0),
            "used_vehicle_count_delta": int(five_minute["used_vehicle_count"])
            - int(fifteen_minute["used_vehicle_count"]),
            "used_vehicle_type_mix_matches": dict(
                five_minute.get("used_vehicle_count_by_type") or {}
            )
            == dict(fifteen_minute.get("used_vehicle_count_by_type") or {}),
            "served_trip_type_mix_matches": dict(
                five_minute.get("served_trip_count_by_vehicle_type") or {}
            )
            == dict(fifteen_minute.get("served_trip_count_by_vehicle_type") or {}),
        }
    )
    return comparison


def _sensitivity_summary(
    cases: list[dict[str, Any]],
    *,
    analysis_label: str,
) -> dict[str, Any]:
    """Return a compact, fail-closed summary for one sensitivity family."""
    selected = [
        case for case in cases if case.get("analysis_label") == analysis_label
    ]
    compact_cases = [
        {
            "random_seed": case.get("random_seed"),
            "time_limit_sec": case.get("time_limit_sec"),
            "pv_uncertainty_scale": case.get("pv_uncertainty_scale"),
            "bev_consumption_uncertainty_scale": case.get(
                "bev_consumption_uncertainty_scale"
            ),
            "feasible": case.get("feasible"),
            "trip_count_unserved": case.get("trip_count_unserved"),
            "accounted_total_cost_jpy": case.get("accounted_total_cost_jpy"),
            "stage1_objective_jpy": case.get("stage1_objective"),
            "stage1_best_bound_jpy": case.get("stage1_best_bound"),
            "stage1_gap_ratio": case.get("stage1_mip_gap_ratio"),
            "used_vehicle_count_by_type": case.get(
                "used_vehicle_count_by_type"
            ),
            "served_trip_count_by_vehicle_type": case.get(
                "served_trip_count_by_vehicle_type"
            ),
            "elapsed_seconds": case.get("elapsed_seconds"),
        }
        for case in selected
    ]
    costs = [
        float(case["accounted_total_cost_jpy"])
        for case in selected
        if case.get("accounted_total_cost_jpy") is not None
    ]
    return {
        "case_count": len(selected),
        "all_cases_feasible_and_complete": bool(selected)
        and all(
            case.get("feasible")
            and int(case.get("trip_count_unserved") or 0) == 0
            for case in selected
        ),
        "minimum_accounted_total_cost_jpy": min(costs) if costs else None,
        "maximum_accounted_total_cost_jpy": max(costs) if costs else None,
        "accounted_total_cost_range_jpy": (
            max(costs) - min(costs) if costs else None
        ),
        "cases": compact_cases,
    }


def run(args: argparse.Namespace) -> int:
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    problem_15 = _build_problem(args, 15)
    problem_5 = None if args.skip_five_minute else _build_problem(args, 5)
    case_specs: list[tuple[CanonicalOptimizationProblem, str, int, int]] = []
    if not args.integrated_only:
        case_specs.append(
            (problem_15, "phase3_two_stage", args.time_limit_sec, args.random_seed)
        )
    case_specs.append(
        (problem_15, "phase4_integrated", args.time_limit_sec, args.random_seed)
    )
    if not args.skip_five_minute:
        assert problem_5 is not None
        case_specs.append(
            (problem_5, "phase4_integrated", args.time_limit_sec, args.random_seed)
        )
    if args.run_seed_time_sensitivity:
        for seed in (17, 42, 73):
            for limit in (5, 15, 60):
                sensitivity_problem = replace(
                    problem_15,
                    metadata={
                        **dict(problem_15.metadata or {}),
                        "sensitivity_analysis_label": "small_phase3_seed_time",
                    },
                )
                case_specs.append(
                    (sensitivity_problem, "phase3_two_stage", limit, seed)
                )
    if args.run_uncertainty_sensitivity:
        for pv_scale in (0.8, 1.0, 1.2):
            for consumption_scale in (0.9, 1.0, 1.1):
                sensitivity_problem = _scaled_uncertainty_problem(
                    problem_15,
                    pv_scale=pv_scale,
                    bev_consumption_scale=consumption_scale,
                )
                sensitivity_problem = replace(
                    sensitivity_problem,
                    metadata={
                        **dict(sensitivity_problem.metadata or {}),
                        "sensitivity_analysis_label": "small_phase3_pv_consumption",
                    },
                )
                case_specs.append(
                    (
                        sensitivity_problem,
                        "phase3_two_stage",
                        args.time_limit_sec,
                        args.random_seed,
                    )
                )
    cases: list[dict[str, Any]] = []
    for index, (problem, phase, time_limit_sec, random_seed) in enumerate(
        case_specs,
        start=1,
    ):
        print(
            f"[{index}/{len(case_specs)}] {phase} at "
            f"{problem.scenario.timestep_min}-minute resolution",
            flush=True,
        )
        cases.append(
            _run_case(
                problem,
                phase=phase,
                time_limit_sec=time_limit_sec,
                random_seed=random_seed,
            )
        )
    primary_comparison = _primary_oracle_comparison(cases)
    five_minute_comparison = _five_minute_sensitivity_comparison(cases)
    seed_time_summary = _sensitivity_summary(
        cases,
        analysis_label="small_phase3_seed_time",
    )
    uncertainty_summary = _sensitivity_summary(
        cases,
        analysis_label="small_phase3_pv_consumption",
    )
    payload = {
        "purpose": "small_integrated_oracle_and_five_minute_sensitivity",
        "scope_warning": (
            "Deterministic day-spanning subset only; do not generalize these KPIs "
            "to the full 264-trip service day."
        ),
        "scenario_id": args.scenario_id,
        "prepared_input_id": args.prepared_input_id,
        "trip_ids": [str(trip.trip_id) for trip in problem_15.trips],
        "trip_count": len(problem_15.trips),
        "vehicles_per_type": args.vehicles_per_type,
        "allowed_vehicle_type": args.allowed_vehicle_type,
        "primary_comparison": primary_comparison,
        "five_minute_comparison": five_minute_comparison,
        "seed_time_sensitivity_summary": seed_time_summary,
        "pv_consumption_sensitivity_summary": uncertainty_summary,
        "cases": cases,
    }
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str), flush=True)
    if not all(case["feasible"] and case["trip_count_unserved"] == 0 for case in cases):
        return 2
    if not primary_comparison["integrated_exact_oracle_eligible"]:
        return 3
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--prepared-input-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--depot-id", default="tsurumaki")
    parser.add_argument("--service-id", default="WEEKDAY")
    parser.add_argument("--trip-count", type=int, default=10)
    parser.add_argument("--vehicles-per-type", type=int, default=5)
    parser.add_argument(
        "--allowed-vehicle-type",
        choices=("ALL", "BEV", "ICE"),
        default="ALL",
        help=(
            "Audit-only fleet restriction. ALL preserves the mixed-fleet oracle; "
            "BEV or ICE directly validates one propulsion path."
        ),
    )
    parser.add_argument("--time-limit-sec", type=int, default=60)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--integrated-only", action="store_true")
    parser.add_argument("--skip-five-minute", action="store_true")
    parser.add_argument("--run-seed-time-sensitivity", action="store_true")
    parser.add_argument("--run-uncertainty-sensitivity", action="store_true")
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
