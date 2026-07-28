"""Run one strict Phase 3 case from persisted frontend weather settings.

The script intentionally uses the same prepared-input materialization, weather
policy, canonical ProblemBuilder, and OptimizationEngine stack as the BFF.
It does not overwrite a scenario document; it creates a reproducible research
artifact directory instead.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import csv
from dataclasses import replace
from datetime import date
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bff.routers.optimization import _prepare_weather_policy_for_scenario, _prepared_inputs_root
from bff.services.run_preparation import load_prepared_input, materialize_scenario_from_prepared_input
from bff.store import scenario_store as store
from src.gurobi_runtime import is_gurobi_available
from src.optimization import OptimizationConfig, OptimizationEngine, OptimizationMode, ProblemBuilder, ResultSerializer
from src.optimization.common.initial_soc_policy import (
    InitialSocPolicy,
    initial_soc_input_metadata,
    normalize_initial_soc_policy,
)
from src.optimization.common.input_fingerprints import (
    INPUT_FINGERPRINT_SCHEMA,
    canonical_trip_input_hash,
    canonical_vehicle_input_hash,
)
from src.optimization.common.fleet_contract import (
    resolve_scenario_fleet_contract,
)
from src.optimization.common.bev_terminal_policy import (
    BevTerminalSocPolicy,
    normalize_bev_terminal_soc_policy,
)
from src.optimization.common.research_phase3_policy import (
    enforce_research_phase3_single_continuous_duty,
)
from src.optimization.rolling.acceptance import rolling_chain_acceptance_audit
from src.optimization.common.fast_cost_assignment import (
    build_fast_cost_aware_assignment,
)
from src.optimization.common.soc_helpers import is_electric_vehicle
from src.optimization.common.weather_strategy import weather_decision_policy_audit
from src.preprocess.weather.operation_policy import (
    apply_same_service_date_pv_counterfactual_to_problem,
    apply_weather_policy_to_problem,
)
from src.preprocess.weather.weather_proxy_builder import (
    load_weather_proxy_forecast_json,
)


DEFAULT_STAGE1_STRATEGY = "full_network_milp"
DEFAULT_FORMAL_MIP_GAP = 0.05


def _calendar_service_contract(
    service_date: str,
    service_id: str,
) -> dict[str, Any]:
    """Return the calendar/service-table alignment used by formal runs."""

    parsed_date = date.fromisoformat(str(service_date)[:10])
    normalized_service_id = str(service_id or "").strip().upper()
    weekday_index = parsed_date.weekday()
    if normalized_service_id == "WEEKDAY":
        matches = weekday_index <= 4
    elif normalized_service_id in {"SAT", "SATURDAY"}:
        matches = weekday_index == 5
    elif normalized_service_id in {"SUN_HOL", "SUN_HOLIDAY", "HOLIDAY", "SUNDAY"}:
        matches = weekday_index == 6
    elif normalized_service_id in {"SAT_HOL", "SAT_HOLIDAY"}:
        matches = weekday_index >= 5
    else:
        matches = False
    return {
        "service_date": parsed_date.isoformat(),
        "calendar_weekday_index": weekday_index,
        "calendar_day_name": parsed_date.strftime("%A"),
        "service_id": normalized_service_id,
        "matches": matches,
    }


class FastFixedPathSearchError(RuntimeError):
    """Raised with a complete audit when no fixed-path candidate is accepted."""

    def __init__(self, message: str, audit: dict[str, Any]) -> None:
        super().__init__(message)
        self.audit = audit


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _counterfactual_pv_curve_audit(
    *,
    comparison_role: str,
    raw_path: str | None,
) -> dict[str, Any]:
    """Load and fingerprint a PV-only counterfactual source when requested."""

    role = str(comparison_role or "").strip()
    path_text = str(raw_path or "").strip()
    if role == "baseline":
        if path_text:
            raise ValueError(
                "baseline comparison role must not receive a counterfactual PV "
                "curve file"
            )
        return {
            "enabled": False,
            "weather_difference_scope": "none",
            "curve_source_path": None,
        }
    if role != "pv_curve_counterfactual":
        raise ValueError(f"Unsupported weather comparison role: {role!r}")
    if not path_text:
        raise ValueError(
            "pv_curve_counterfactual requires --counterfactual-pv-curve-file"
        )
    path = Path(path_text).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Counterfactual PV curve file was not found: {path}")
    forecast = load_weather_proxy_forecast_json(path)
    return {
        "enabled": True,
        "weather_difference_scope": "pv_curve_only",
        "curve_source_path": str(path),
        "curve_source_sha256": _sha256(path),
        "curve_source_size_bytes": path.stat().st_size,
        "curve_source_forecast": {
            "service_date": str(forecast.service_date),
            "analog_date": str(forecast.analog_date),
            "forecast_type": str(forecast.forecast_type),
            "station_id": str(forecast.station_id),
            "weather_label": str(forecast.weather_label),
            "operation_mode": str(forecast.operation_mode),
            "no_future_leakage": bool(forecast.no_future_leakage),
        },
        "forecast": forecast,
    }


def _comparison_control_hash(
    *,
    scenario_id: str,
    prepared_input_id: str,
    prepared_input_sha256: str,
    service_date: str,
    service_id: str,
    expected_fleet: Mapping[str, int],
    trip_input_hash: str,
    vehicle_input_hash: str,
    initial_soc_input_hash: str,
    terminal_soc_policy: Mapping[str, Any],
    charger_configuration: list[dict[str, Any]],
    depot_energy_assets: Mapping[str, Mapping[str, Any]],
    weather_configuration: Mapping[str, Any],
    weather_operation_profile: Mapping[str, Any],
    time_limit_sec: int,
    stage1_time_limit_sec: int | None,
    stage2_time_limit_sec: int | None,
    stage1_best_obj_stop_enabled: bool,
    gurobi_threads: int | None,
    mip_gap: float,
    random_seed: int,
    git_sha: str | None,
) -> str:
    """Hash every fixed control while deliberately excluding PV curve values."""

    fixed_assets = {
        depot_id: {
            key: value
            for key, value in dict(asset).items()
            if key not in {"pv_case_id", "pv_generation_kwh", "pv_generation_hash"}
        }
        for depot_id, asset in sorted(depot_energy_assets.items())
    }
    return _canonical_hash(
        {
            "scenario_id": scenario_id,
            "prepared_input_id": prepared_input_id,
            "prepared_input_sha256": prepared_input_sha256,
            "service_date": service_date,
            "service_id": service_id,
            "expected_fleet": dict(expected_fleet),
            "trip_input_hash": trip_input_hash,
            "vehicle_input_hash": vehicle_input_hash,
            "initial_soc_input_hash": initial_soc_input_hash,
            "terminal_soc_policy": dict(terminal_soc_policy),
            "charger_configuration": charger_configuration,
            "depot_energy_assets_except_pv_curve": fixed_assets,
            "weather_configuration": dict(weather_configuration),
            "weather_operation_profile": dict(weather_operation_profile),
            "time_limit_sec": int(time_limit_sec),
            "stage1_time_limit_sec": stage1_time_limit_sec,
            "stage2_time_limit_sec": stage2_time_limit_sec,
            "stage1_best_obj_stop_enabled": bool(stage1_best_obj_stop_enabled),
            "gurobi_threads": gurobi_threads,
            "mip_gap": float(mip_gap),
            "random_seed": int(random_seed),
            "git_sha": git_sha,
        }
    )


def _finite(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _mip_gap_percent(value: Any) -> float | None:
    ratio = _finite(value)
    return ratio * 100.0 if ratio is not None else None


def _resolve_initial_soc_policy(scenario: dict[str, Any]) -> InitialSocPolicy:
    """Resolve an explicit SOC-input source without guessing from a number."""
    simulation_config = dict(scenario.get("simulation_config") or {})
    configured_policy = str(simulation_config.get("initial_soc_policy") or "").strip()
    if configured_policy:
        return normalize_initial_soc_policy(configured_policy)
    if bool(simulation_config.get("use_selected_depot_vehicle_inventory", False)):
        return InitialSocPolicy.ACTUAL_VEHICLE_INVENTORY
    raise ValueError(
        "Research weather run requires an explicit initial_soc_policy or "
        "use_selected_depot_vehicle_inventory=true"
    )


def _vehicle_is_available(vehicle: dict[str, Any]) -> bool:
    raw = vehicle.get("available")
    if raw is None:
        raw = vehicle.get("enabled", True)
    return bool(raw)


def _initial_soc_sort_value(vehicle: dict[str, Any]) -> float:
    try:
        value = float(vehicle.get("initialSoc"))
    except (TypeError, ValueError):
        return -1.0
    return value if math.isfinite(value) else -1.0


def _apply_bev_availability_sensitivity(
    scenario: dict[str, Any],
    available_bev_count: int | None,
) -> dict[str, Any]:
    """Apply an in-memory BEV-readiness cap without changing persisted input.

    The highest-initial-SOC vehicles remain available. This deterministic policy
    represents an optimistic operational-readiness case and avoids adding an
    arbitrary BEV-use constraint to the optimization model.
    """
    vehicles = list(scenario.get("vehicles") or ())
    bev_vehicles = [
        vehicle
        for vehicle in vehicles
        if str(vehicle.get("type") or vehicle.get("vehicleType") or "").upper()
        == "BEV"
    ]
    initially_available = [
        vehicle for vehicle in bev_vehicles if _vehicle_is_available(vehicle)
    ]
    audit = {
        "enabled": available_bev_count is not None,
        "requested_available_bev_count": available_bev_count,
        "initial_available_bev_count": len(initially_available),
        "effective_available_bev_count": len(initially_available),
        "selection_policy": "highest_initial_soc_then_vehicle_id",
        "selected_available_bev_ids": sorted(
            str(vehicle.get("id") or "") for vehicle in initially_available
        ),
        "forced_unavailable_bev_ids": [],
        "persisted_scenario_modified": False,
    }
    if available_bev_count is None:
        return audit
    requested = int(available_bev_count)
    if requested < 0 or requested > len(initially_available):
        raise ValueError(
            "available_bev_count must be between 0 and the persisted available "
            f"BEV count ({len(initially_available)}), got {requested}"
        )

    ranked = sorted(
        initially_available,
        key=lambda vehicle: (
            -_initial_soc_sort_value(vehicle),
            str(vehicle.get("id") or ""),
        ),
    )
    selected_ids = {
        str(vehicle.get("id") or "") for vehicle in ranked[:requested]
    }
    forced_unavailable_ids: list[str] = []
    for vehicle in initially_available:
        vehicle_id = str(vehicle.get("id") or "")
        is_selected = vehicle_id in selected_ids
        vehicle["available"] = is_selected
        vehicle["enabled"] = is_selected
        if not is_selected:
            forced_unavailable_ids.append(vehicle_id)

    audit.update(
        {
            "effective_available_bev_count": requested,
            "selected_available_bev_ids": sorted(selected_ids),
            "forced_unavailable_bev_ids": sorted(forced_unavailable_ids),
        }
    )
    return audit


def _validate_fleet_mutation_scope(
    *,
    available_bev_count: int | None,
    day_ahead_only_exploratory: bool,
) -> None:
    """Prevent a formal run from selecting vehicles outside Prepare."""

    if available_bev_count is not None and not day_ahead_only_exploratory:
        raise ValueError(
            "--available-bev-count mutates the prepared active fleet and is "
            "allowed only with --day-ahead-only-exploratory; formal runs use "
            "the exact prepared scenario fleet contract"
        )


def _configure_research_discretization(
    scenario: dict[str, Any],
    *,
    timestep_min: int,
) -> dict[str, int | bool]:
    """Apply the formal weather-comparison resolution without persisting it."""

    if int(timestep_min) not in {5, 15, 30, 60}:
        raise ValueError("research timestep must be one of 5, 15, 30, or 60 minutes")
    simulation_config = dict(scenario.get("simulation_config") or {})
    simulation_config["timestep_min"] = int(timestep_min)
    simulation_config["time_step_min"] = int(timestep_min)
    simulation_config["milp_max_successors_per_trip"] = 0
    scenario["simulation_config"] = simulation_config

    scenario_overlay = dict(scenario.get("scenario_overlay") or {})
    solver_config = dict(scenario_overlay.get("solver_config") or {})
    solver_config["timestep_min"] = int(timestep_min)
    solver_config["time_step_min"] = int(timestep_min)
    # Zero is the canonical full-network sentinel; ModelBuilder normalizes it
    # to no successor cap.
    solver_config["milp_max_successors_per_trip"] = 0
    scenario_overlay["solver_config"] = solver_config
    scenario["scenario_overlay"] = scenario_overlay
    return {
        "timestep_min": int(timestep_min),
        "milp_max_successors_per_trip": 0,
        "successor_pruning_enabled": False,
    }


def _trip_distance_audit(
    problem: Any,
    prepared_payload: dict[str, Any],
) -> dict[str, Any]:
    distances = [float(trip.distance_km) for trip in problem.trips]
    nonpositive_trip_ids = [
        str(trip.trip_id)
        for trip in problem.trips
        if not math.isfinite(float(trip.distance_km)) or float(trip.distance_km) <= 0.0
    ]
    if nonpositive_trip_ids:
        raise ValueError(
            "Research weather run refuses zero/missing trip distance: "
            + ", ".join(nonpositive_trip_ids[:10])
        )
    prepared_audit = dict(prepared_payload.get("prepared_scope_audit") or {})
    distance_join = dict(prepared_audit.get("distance_join_diagnosis") or {})
    source_summary = dict(distance_join.get("route_distance_source_summary") or {})
    distance_enrichment = dict(
        prepared_payload.get("trip_distance_enrichment") or {}
    )
    return {
        "trip_count": len(distances),
        "nonpositive_trip_count": 0,
        "minimum_trip_distance_km": min(distances) if distances else None,
        "maximum_trip_distance_km": max(distances) if distances else None,
        "prepared_trip_distance_audit": dict(
            prepared_audit.get("trip_distance_audit") or {}
        ),
        "prepared_route_distance_audit": dict(
            prepared_audit.get("route_distance_audit") or {}
        ),
        "prepared_trip_distance_enrichment": distance_enrichment,
        "prepared_distance_source_kind_counts": dict(
            source_summary.get("route_distance_source_kind_counts") or {}
        ),
    }


def _assignment_mix(problem: Any, result: Any) -> dict[str, dict[str, int]]:
    vehicle_type_by_id = {
        str(vehicle.vehicle_id): str(vehicle.vehicle_type).upper()
        for vehicle in problem.vehicles
    }
    used_by_type: dict[str, int] = {}
    trips_by_type: dict[str, int] = {}
    for vehicle_id, duties in result.plan.duties_by_vehicle().items():
        vehicle_type = vehicle_type_by_id.get(str(vehicle_id), "UNKNOWN")
        used_by_type[vehicle_type] = used_by_type.get(vehicle_type, 0) + 1
        trips_by_type[vehicle_type] = trips_by_type.get(vehicle_type, 0) + sum(
            len(duty.legs) for duty in duties
        )
    return {
        "used_vehicle_count_by_type": dict(sorted(used_by_type.items())),
        "served_trip_count_by_vehicle_type": dict(sorted(trips_by_type.items())),
    }


def _solve_fast_fixed_path_candidates(
    problem: Any,
    config: OptimizationConfig,
    *,
    total_time_limit_sec: int,
    per_case_time_limit_sec: int,
) -> tuple[Any, dict[str, Any]]:
    """Select a fixed-path vehicle mix and validate every candidate exactly.

    Assignment is heuristic.  Each accepted candidate has nevertheless passed
    the canonical Phase 1 charging/SOC MILP without fallback or post-solve
    repair.  The result must therefore not be described as a globally optimal
    dispatch assignment.
    """

    if total_time_limit_sec <= 0:
        raise ValueError("fast_assignment_time_limit_sec must be positive")
    if per_case_time_limit_sec <= 0:
        raise ValueError("fast_stage2_case_time_limit_sec must be positive")
    baseline = problem.baseline_plan
    if baseline is None or not baseline.duties:
        raise RuntimeError("Fast assignment requires a complete baseline path cover")
    duty_count = len(baseline.duties)
    available_vehicles = [
        vehicle for vehicle in problem.vehicles if bool(vehicle.available)
    ]
    available_bev_count = sum(
        1 for vehicle in available_vehicles if is_electric_vehicle(problem, vehicle)
    )
    available_non_bev_count = len(available_vehicles) - available_bev_count
    minimum_bev_count = max(0, duty_count - available_non_bev_count)
    maximum_bev_count = min(duty_count, available_bev_count)
    if minimum_bev_count > maximum_bev_count:
        raise RuntimeError("Available fleet cannot cover the fixed timetable duties")

    vehicle_by_id = {
        str(vehicle.vehicle_id): vehicle for vehicle in available_vehicles
    }
    baseline_vehicle_ids = set(baseline.duties_by_vehicle())
    unknown_baseline_vehicle_ids = baseline_vehicle_ids - set(vehicle_by_id)
    if unknown_baseline_vehicle_ids:
        raise RuntimeError(
            "Baseline path cover references unavailable vehicles: "
            + ", ".join(sorted(unknown_baseline_vehicle_ids))
        )
    baseline_bev_count = sum(
        1
        for vehicle_id in baseline_vehicle_ids
        if is_electric_vehicle(problem, vehicle_by_id[vehicle_id])
    )
    if not minimum_bev_count <= baseline_bev_count <= maximum_bev_count:
        raise RuntimeError("Baseline BEV count is outside the available fleet bounds")

    expected_trip_ids = {str(trip.trip_id) for trip in problem.trips}
    started = time.perf_counter()
    candidates: list[dict[str, Any]] = []
    best_result = None
    best_total_cost = math.inf
    best_requested_bev_count = None
    best_candidate_source = None
    candidate_specs = [
        ("canonical_baseline", baseline_bev_count),
        *(
            ("cost_aware", requested_bev_count)
            for requested_bev_count in range(
                baseline_bev_count + 1, maximum_bev_count + 1
            )
        ),
        ("cost_aware", baseline_bev_count),
        *(
            ("cost_aware", requested_bev_count)
            for requested_bev_count in range(
                baseline_bev_count - 1, minimum_bev_count - 1, -1
            )
        ),
    ]
    for candidate_source, requested_bev_count in candidate_specs:
        elapsed_before_case = time.perf_counter() - started
        remaining_time = float(total_time_limit_sec) - elapsed_before_case
        if remaining_time <= 0.0:
            break
        observed_case_wall_seconds = [
            float(candidate.get("elapsed_seconds") or 0.0)
            for candidate in candidates
        ]
        estimated_next_case_seconds = max(
            [float(per_case_time_limit_sec), *observed_case_wall_seconds]
        )
        if candidates and remaining_time < estimated_next_case_seconds:
            break
        case_limit = max(
            1,
            min(int(per_case_time_limit_sec), int(math.ceil(remaining_time))),
        )
        case_started = time.perf_counter()
        if candidate_source == "canonical_baseline":
            candidate_plan = baseline
            assignment_audit = {
                "requested_bev_count": baseline_bev_count,
                "actual_bev_count": baseline_bev_count,
                "duty_count": duty_count,
                "trip_count": len(expected_trip_ids),
                "proxy_total_cost_jpy": None,
                "timetable_chains_modified": False,
                "assignment_global_optimality": False,
            }
        else:
            try:
                candidate_plan, assignment_audit = build_fast_cost_aware_assignment(
                    problem,
                    requested_bev_count=requested_bev_count,
                )
            except ValueError as exc:
                candidates.append(
                    {
                        "candidate_source": candidate_source,
                        "requested_bev_count": requested_bev_count,
                        "accepted": False,
                        "rejection_reason": f"assignment_build_failed: {exc}",
                        "elapsed_seconds": time.perf_counter() - case_started,
                    }
                )
                continue

        candidate_config = replace(
            config,
            time_limit_sec=case_limit,
            stage1_time_limit_sec=None,
            stage2_time_limit_sec=case_limit,
            thesis_mode=False,
            research_run=True,
            allow_postsolve_repair=False,
            phase="phase1_charging_only",
            requested_phase_token="phase1_charging_only",
            requested_phase="phase1_charging_only",
            resolved_phase="phase1_charging_only",
            executed_phase="phase1_charging_only",
            fixed_assignment=candidate_plan,
        )
        candidate_result = OptimizationEngine().solve(problem, candidate_config)
        solver_metadata = dict(candidate_result.solver_metadata or {})
        served_trip_ids = {
            str(trip_id) for trip_id in candidate_result.plan.served_trip_ids
        }
        postsolve_modified = bool(
            solver_metadata.get("postsolve_repair_applied", False)
            or solver_metadata.get("postsolve_repaired", False)
        )
        total_cost = _finite(
            dict(candidate_result.cost_breakdown or {}).get("total_cost")
        )
        candidate_cost_breakdown = dict(candidate_result.cost_breakdown or {})
        stage2_solver_status = str(
            solver_metadata.get("stage2_solver_status") or ""
        ).strip().lower()
        stage2_cost_optimal = stage2_solver_status == "optimal"
        accepted = bool(
            candidate_result.feasible
            and served_trip_ids == expected_trip_ids
            and not candidate_result.plan.unserved_trip_ids
            and candidate_result.plan.max_fragments_observed() <= 1
            and not postsolve_modified
            and solver_metadata.get("research_run_accepted", False)
            and stage2_cost_optimal
            and total_cost is not None
        )
        rejection_reasons = []
        if not candidate_result.feasible:
            rejection_reasons.append("engine_reported_infeasible")
        if served_trip_ids != expected_trip_ids or candidate_result.plan.unserved_trip_ids:
            rejection_reasons.append("trip_coverage_mismatch")
        if candidate_result.plan.max_fragments_observed() > 1:
            rejection_reasons.append("multiple_fragments_per_vehicle")
        if postsolve_modified:
            rejection_reasons.append("postsolve_modification_detected")
        if not solver_metadata.get("research_run_accepted", False):
            rejection_reasons.append("research_acceptance_gate_failed")
        if not stage2_cost_optimal:
            rejection_reasons.append("fixed_assignment_charging_not_optimal")
        if total_cost is None:
            rejection_reasons.append("nonfinite_accounting_total")
        candidate_row = {
            **assignment_audit,
            "candidate_source": candidate_source,
            "accepted": accepted,
            "rejection_reason": ",".join(rejection_reasons) or None,
            "case_time_limit_sec": case_limit,
            "elapsed_seconds": time.perf_counter() - case_started,
            "solver_status": str(candidate_result.solver_status or ""),
            "stage2_solver_status": stage2_solver_status,
            "stage2_cost_optimal_for_fixed_assignment": stage2_cost_optimal,
            "research_run_accepted": bool(
                solver_metadata.get("research_run_accepted", False)
            ),
            "research_acceptance_checks": dict(
                solver_metadata.get("research_acceptance_checks") or {}
            ),
            "total_cost_jpy": total_cost,
            "costs_jpy": {
                key: _finite(candidate_cost_breakdown.get(key))
                for key in (
                    "electricity_cost",
                    "fuel_cost",
                    "co2_cost",
                    "vehicle_cost",
                    "vehicle_usage_cost",
                    "demand_cost",
                    "degradation_cost",
                    "contract_overage_cost",
                )
            },
            "energy_flows": {
                key: _finite(candidate_cost_breakdown.get(key))
                for key in (
                    "grid_to_bus_kwh",
                    "pv_to_bus_kwh",
                    "bess_to_bus_kwh",
                    "grid_import_kwh",
                    "peak_grid_kw",
                )
            },
            "full_cost_breakdown": candidate_cost_breakdown,
            **_assignment_mix(problem, candidate_result),
        }
        candidates.append(candidate_row)
        if accepted and total_cost is not None and total_cost < best_total_cost:
            best_result = candidate_result
            best_total_cost = total_cost
            best_requested_bev_count = requested_bev_count
            best_candidate_source = candidate_source

    total_elapsed = time.perf_counter() - started
    audit = {
        "strategy": "fast_fixed_path",
        "assignment_global_optimality": False,
        "timetable_chains_modified": False,
        "charging_and_soc_validation": "exact_phase1_charging_milp",
        "total_time_limit_sec": int(total_time_limit_sec),
        "per_case_time_limit_sec": int(per_case_time_limit_sec),
        "elapsed_seconds": total_elapsed,
        "duty_count": duty_count,
        "minimum_bev_count": minimum_bev_count,
        "maximum_bev_count": maximum_bev_count,
        "baseline_bev_count": baseline_bev_count,
        "selected_requested_bev_count": best_requested_bev_count,
        "selected_candidate_source": best_candidate_source,
        "selected_total_cost_jpy": (
            best_total_cost if math.isfinite(best_total_cost) else None
        ),
        "candidate_count_evaluated": len(candidates),
        "candidates": candidates,
    }
    if best_result is None:
        raise FastFixedPathSearchError(
            "No fast fixed-path candidate passed the exact charging/SOC acceptance gate",
            audit,
        )
    selected_plan = replace(
        best_result.plan,
        metadata={
            **dict(best_result.plan.metadata or {}),
            "source": (
                "canonical_baseline_revalidated_exact_charging"
                if best_candidate_source == "canonical_baseline"
                else "fast_cost_aware_fixed_path_assignment_exact_charging"
            ),
            "assignment_heuristic": True,
            "assignment_global_optimality": False,
            "assignment_timetable_chains_modified": False,
            "selected_requested_bev_count": best_requested_bev_count,
            "selected_candidate_source": best_candidate_source,
            "objective_semantics": (
                "cost_aware_fixed_path_assignment_heuristic_then_exact_"
                "charging_dispatch_and_accounting"
            ),
        },
    )
    selected_solver_metadata = {
        **dict(best_result.solver_metadata or {}),
        "stage1_strategy": "fast_fixed_path",
        "assignment_solution_method": (
            "canonical_baseline_revalidated"
            if best_candidate_source == "canonical_baseline"
            else "cost_aware_fixed_path_heuristic"
        ),
        "assignment_global_optimality": False,
        "charging_solution_method": "exact_phase1_charging_milp",
        "research_cost_optimality_eligible": False,
        "fast_assignment_candidate_count": len(candidates),
        "fast_assignment_selected_requested_bev_count": best_requested_bev_count,
        "fast_assignment_selected_candidate_source": best_candidate_source,
    }
    best_result = replace(
        best_result,
        plan=selected_plan,
        solver_metadata=selected_solver_metadata,
    )
    return best_result, audit


def _git_state() -> dict[str, Any]:
    git_executable = shutil.which("git")
    if git_executable is None:
        candidates = [
            Path(os.environ.get("ProgramFiles", "")) / "Git" / "cmd" / "git.exe",
            Path(os.environ.get("LOCALAPPDATA", ""))
            / "Programs"
            / "Git"
            / "cmd"
            / "git.exe",
        ]
        codex_runtime_root = (
            Path(os.environ.get("USERPROFILE", ""))
            / ".cache"
            / "codex-runtimes"
        )
        if codex_runtime_root.is_dir():
            candidates.extend(
                sorted(
                    codex_runtime_root.glob(
                        "*/dependencies/native/git/cmd/git.exe"
                    )
                )
            )
        git_executable = next(
            (str(path) for path in candidates if str(path) and path.is_file()),
            None,
        )
    if git_executable is None:
        return {
            "git_sha": None,
            "git_dirty": None,
            "git_state_available": False,
            "git_state_error": "Git executable was not found",
        }
    try:
        sha = subprocess.check_output(
            [git_executable, "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
        dirty = bool(
            subprocess.check_output(
                [git_executable, "status", "--porcelain"], cwd=REPO_ROOT, text=True
            ).strip()
        )
    except (FileNotFoundError, OSError, subprocess.CalledProcessError) as exc:
        # Provenance collection must never prevent the optimization itself.
        # Keep the missing state explicit so the artifact is not mistaken for
        # a fully commit-pinned run.
        return {
            "git_sha": None,
            "git_dirty": None,
            "git_state_available": False,
            "git_state_error": f"{type(exc).__name__}: {exc}",
        }
    return {
        "git_sha": sha,
        "git_dirty": dirty,
        "git_state_available": True,
        "git_state_error": None,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _compact_fast_assignment_audit(audit: dict[str, Any]) -> dict[str, Any]:
    compact = {
        key: value
        for key, value in audit.items()
        if key != "candidates"
    }
    compact["candidates"] = [
        {
            key: candidate.get(key)
            for key in (
                "candidate_source",
                "requested_bev_count",
                "actual_bev_count",
                "accepted",
                "rejection_reason",
                "solver_status",
                "stage2_solver_status",
                "stage2_cost_optimal_for_fixed_assignment",
                "total_cost_jpy",
                "elapsed_seconds",
                "used_vehicle_count_by_type",
                "served_trip_count_by_vehicle_type",
                "costs_jpy",
                "energy_flows",
            )
        }
        for candidate in audit.get("candidates", ())
    ]
    return compact


def _write_vehicle_schedule(path: Path, result: Any) -> None:
    rows: list[dict[str, Any]] = []
    for vehicle_id, duties in sorted(result.plan.duties_by_vehicle().items()):
        sequence = 0
        for duty in duties:
            for leg in duty.legs:
                sequence += 1
                rows.append(
                    {
                        "vehicle_id": str(vehicle_id),
                        "sequence": sequence,
                        "duty_id": str(duty.duty_id),
                        "trip_id": str(leg.trip.trip_id),
                        "departure_min": int(leg.trip.departure_min),
                        "arrival_min": int(leg.trip.arrival_min),
                    }
                )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]) if rows else ["vehicle_id"],
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_research_manifest(
    output_dir: Path,
    *,
    input_audit: dict[str, Any],
    run_state: str,
) -> None:
    artifact_names = (
        "effective_scenario.json",
        "effective_pv_profiles.json",
        "scenario_fleet_contract.json",
        "input_audit.json",
        "solver_result.json",
        "summary.json",
        "vehicle_schedule.csv",
        "rolling_hourly_chain/rolling_chain_summary.json",
        "rolling_hourly_chain/executed_day_accounting.json",
        "rolling_hourly_chain/day_ahead_vs_rolling_summary.json",
        "rolling_hourly_chain/hourly_energy_flow_chart.csv",
        "rolling_hourly_chain/charging_schedule.csv",
    )
    artifacts = {
        name: {
            "sha256": _sha256(output_dir / name),
            "size_bytes": (output_dir / name).stat().st_size,
        }
        for name in artifact_names
        if (output_dir / name).is_file()
    }
    declared_fields = (
        "case_name",
        "scenario_id",
        "prepared_input_id",
        "prepared_input_sha256",
        "service_date",
        "service_id",
        "weather_comparison_contract",
        "weather_decision_policy",
        "phase",
        "stage1_strategy",
        "time_limit_sec",
        "stage1_time_limit_sec",
        "stage2_time_limit_sec",
        "mip_gap",
        "random_seed",
        "expected_fleet",
        "fleet",
        "fleet_available",
        "timestep_min",
        "price_slot_count",
        "terminal_soc_policy",
        "charger_configuration_hash",
        "depot_energy_assets_fixed_hash",
        "effective_pv_profiles_artifact",
        "effective_pv_profiles_sha256",
        "vehicle_input_hash",
        "trip_input_hash",
        "git_sha",
        "git_dirty",
        "git_state_available",
        "git_state_error",
        "calendar_audit",
        "calendar_policy",
        "calendar_validation_status",
    )
    manifest = {
        "schema": "research_run_manifest_v1",
        "run_state": run_state,
        "declared_controls": {
            field: input_audit.get(field) for field in declared_fields
        },
        "artifacts": artifacts,
    }
    _write_json(output_dir / "manifest.json", manifest)


def _clock_hour_prices(problem: Any) -> dict[str, float]:
    horizon_start = str(problem.scenario.horizon_start or "00:00")
    start_hour, start_minute = (int(part) for part in horizon_start.split(":"))
    start_of_horizon_min = start_hour * 60 + start_minute
    prices: dict[str, float] = {}
    for slot in problem.price_slots:
        minute_of_day = (
            start_of_horizon_min + int(slot.slot_index) * int(problem.scenario.timestep_min)
        ) % (24 * 60)
        hour = minute_of_day // 60
        prices.setdefault(f"{hour:02d}:00", float(slot.grid_buy_yen_per_kwh))
    return prices


def _asset_snapshot(problem: Any) -> dict[str, Any]:
    return {
        str(depot_id): {
            "pv_enabled": bool(asset.pv_enabled),
            "pv_case_id": str(getattr(asset, "pv_case_id", "") or ""),
            "pv_capacity_kw": float(asset.pv_capacity_kw),
            "pv_generation_kwh": round(sum(asset.pv_generation_kwh_by_slot), 6),
            "pv_generation_hash": _canonical_hash(list(asset.pv_generation_kwh_by_slot)),
            "bess_enabled": bool(asset.bess_enabled),
            "bess_energy_kwh": float(asset.bess_energy_kwh),
            "bess_power_kw": float(asset.bess_power_kw),
            "bess_cycle_cost_yen_per_kwh": float(
                getattr(asset, "bess_cycle_cost_yen_per_kwh", 0.0) or 0.0
            ),
            "bess_charge_efficiency": float(
                getattr(asset, "bess_charge_efficiency", 0.0) or 0.0
            ),
            "bess_discharge_efficiency": float(
                getattr(asset, "bess_discharge_efficiency", 0.0) or 0.0
            ),
            "bess_initial_soc_kwh": float(asset.bess_initial_soc_kwh),
            "bess_soc_min_kwh": float(asset.bess_soc_min_kwh),
            "bess_soc_max_kwh": float(asset.bess_soc_max_kwh),
            "allow_pv_to_bess": bool(asset.allow_pv_to_bess),
            "allow_grid_to_bess": bool(asset.allow_grid_to_bess),
            "allow_bess_to_bus": bool(asset.allow_bess_to_bus),
            "grid_to_bess_price_mode": str(asset.grid_to_bess_price_mode),
            "grid_to_bess_price_threshold_yen_per_kwh": float(
                asset.grid_to_bess_price_threshold_yen_per_kwh
            ),
            "grid_to_bess_allowed_slot_indices": list(
                asset.grid_to_bess_allowed_slot_indices
            ),
            "bess_priority_mode": str(asset.bess_priority_mode),
            "bess_terminal_soc_min_kwh": float(asset.bess_terminal_soc_min_kwh),
            "bess_terminal_soc_policy": str(
                getattr(asset, "bess_terminal_soc_policy", "") or ""
            ),
            "bess_terminal_soc_target_kwh": float(asset.bess_terminal_soc_target_kwh),
            "bess_terminal_soc_deviation_penalty_yen_per_kwh": float(
                asset.bess_terminal_soc_deviation_penalty_yen_per_kwh
            ),
        }
        for depot_id, asset in sorted(problem.depot_energy_assets.items())
    }


def _effective_pv_profiles(problem: Any) -> dict[str, Any]:
    """Serialize the exact full-horizon PV curves passed to day-ahead solving.

    A weather counterfactual may replace the canonical scenario curve after
    scenario materialisation. Persisting this resolved input ensures rolling
    reproduces the day-ahead energy model rather than falling back to the
    original scenario PV data.
    """

    forecast_by_depot = {
        str(depot_id): [
            float(value or 0.0)
            for value in tuple(asset.pv_generation_kwh_by_slot or ())
        ]
        for depot_id, asset in sorted(problem.depot_energy_assets.items())
    }
    return {
        "schema_version": "effective_pv_profiles_v1",
        "semantics": (
            "Exact full-horizon kWh PV profiles supplied to the accepted "
            "day-ahead canonical problem; rolling must load these before "
            "applying any declared per-step forecast update."
        ),
        "forecast_by_depot": forecast_by_depot,
        "forecast_by_depot_hash": _canonical_hash(forecast_by_depot),
    }


def _depot_import_limit_snapshot(problem: Any) -> dict[str, float]:
    """Return the raw frontend-configured grid import limit for every depot.

    The Stage 2 MILP interprets a non-positive value as no finite contract
    limit. Preserve that raw value separately so a weather comparison cannot
    confuse an unbounded depot with a finite-contract experiment.
    """
    depot_by_id = {
        str(depot.depot_id): depot
        for depot in tuple(problem.depots or ())
        if str(depot.depot_id)
    }
    depot_ids = set(depot_by_id)
    depot_ids.update(str(depot_id) for depot_id in problem.depot_energy_assets)
    return {
        depot_id: float(
            getattr(depot_by_id.get(depot_id), "import_limit_kw", 0.0) or 0.0
        )
        for depot_id in sorted(depot_ids)
    }


def _charger_snapshot(problem: Any) -> list[dict[str, Any]]:
    return [
        {
            "charger_id": str(charger.charger_id),
            "depot_id": str(charger.depot_id),
            "power_kw": float(charger.power_kw),
            "bidirectional": bool(charger.bidirectional),
            "simultaneous_ports": int(charger.simultaneous_ports),
        }
        for charger in sorted(problem.chargers, key=lambda item: str(item.charger_id))
    ]


def _trip_input_hash(problem: Any) -> str:
    return canonical_trip_input_hash(problem)


def _vehicle_input_hash(problem: Any) -> str:
    return canonical_vehicle_input_hash(problem)


def _weather_configuration(scenario: dict[str, Any]) -> dict[str, Any]:
    simulation_config = dict(scenario.get("simulation_config") or {})
    return {
        key: simulation_config.get(key)
        for key in (
            "weather_mode",
            "weather_factor_scalar",
            "weather_operation_mode",
            "enable_weather_operation_policy",
            "pv_profile_id",
            "weather_proxy_forecast_path",
            "weather_proxy_station_id",
            "solcast_typical_weather_class",
            "random_seed",
        )
    }


def _validate_frontend_case(
    problem: Any,
    scenario: dict[str, Any],
    *,
    expected_service_date: str,
    assert_bev_count: int | None,
    assert_ice_count: int | None,
    assert_trip_count: int | None,
    assert_timestep_min: int | None,
    assert_price_slot_count: int | None,
    service_id: str,
    allow_fixed_weekday_timetable_pv_counterfactual: bool,
) -> None:
    if assert_trip_count is not None and len(problem.trips) != int(assert_trip_count):
        raise ValueError(
            f"Expected asserted trip count {int(assert_trip_count)}, got {len(problem.trips)}"
        )
    service_date = str(problem.metadata.get("service_date") or "")[:10]
    if service_date != expected_service_date:
        raise ValueError(
            f"Expected service date {expected_service_date}, got {service_date or 'missing'}"
        )
    calendar_contract = _calendar_service_contract(service_date, service_id)
    calendar_validation = dict(
        problem.metadata.get("service_calendar_validation") or {}
    )
    calendar_status = str(calendar_validation.get("status") or "").upper()
    calendar_waiver = dict(calendar_validation.get("waiver") or {})
    waiver_is_exact = bool(
        allow_fixed_weekday_timetable_pv_counterfactual
        and calendar_status == "WAIVED_BY_EXPERIMENT_POLICY"
        and str(calendar_waiver.get("calendar_policy") or "")
        == "fixed_weekday_timetable_pv_counterfactual"
        and str(calendar_waiver.get("scope") or "")
        == "weekday_timetable_on_sunday_for_pv_only_counterfactual"
        and str(service_id).upper() == "WEEKDAY"
        and date.fromisoformat(service_date).weekday() == 6
    )
    if not calendar_contract["matches"] and not waiver_is_exact:
        raise ValueError(
            "Formal frontend weather comparison rejects calendar/service-table "
            f"mismatch: contract={calendar_contract}, validation={calendar_validation}. "
            "Only the explicitly declared weekday-timetable-on-Sunday PV-only "
            "counterfactual may waive this gate."
        )
    fleet_validation = dict(problem.metadata.get("research_fleet_validation") or {})
    fleet = dict(fleet_validation.get("available_inventory") or {})
    if assert_bev_count is not None and int(fleet.get("BEV", 0)) != int(
        assert_bev_count
    ):
        raise ValueError(
            f"assert_bev_count={int(assert_bev_count)} does not match "
            f"scenario-derived BEV count {int(fleet.get('BEV', 0))}"
        )
    if assert_ice_count is not None and int(fleet.get("ICE", 0)) != int(
        assert_ice_count
    ):
        raise ValueError(
            f"assert_ice_count={int(assert_ice_count)} does not match "
            f"scenario-derived ICE count {int(fleet.get('ICE', 0))}"
        )
    if assert_timestep_min is not None and int(problem.scenario.timestep_min) != int(
        assert_timestep_min
    ):
        raise ValueError(
            f"assert_timestep_min={int(assert_timestep_min)} does not match "
            f"effective timestep {int(problem.scenario.timestep_min)}"
        )
    if assert_price_slot_count is not None and len(problem.price_slots) != int(
        assert_price_slot_count
    ):
        raise ValueError(
            f"assert_price_slot_count={int(assert_price_slot_count)} does not match "
            f"effective price slots {len(problem.price_slots)}"
        )
    if problem.metadata.get("milp_max_successors_per_trip") not in (None, 0, ""):
        raise ValueError("Formal frontend weather comparison forbids successor pruning")
    fragment_limits = {
        "max_start_fragments_per_vehicle": int(
            problem.metadata.get("max_start_fragments_per_vehicle", 0) or 0
        ),
        "max_end_fragments_per_vehicle": int(
            problem.metadata.get("max_end_fragments_per_vehicle", 0) or 0
        ),
        "daily_fragment_limit": int(
            problem.metadata.get("daily_fragment_limit", 0) or 0
        ),
    }
    if bool(problem.scenario.allow_same_day_depot_cycles) or any(
        value != 1 for value in fragment_limits.values()
    ):
        raise ValueError(
            "Phase 3 research comparison requires one continuous duty per "
            f"vehicle, got {fragment_limits} and "
            f"allow_same_day_depot_cycles={problem.scenario.allow_same_day_depot_cycles!r}"
        )
    if not any(asset.pv_enabled for asset in problem.depot_energy_assets.values()):
        raise ValueError("Frontend weather comparison requires an enabled PV asset")
    if not any(asset.bess_enabled for asset in problem.depot_energy_assets.values()):
        raise ValueError("Frontend weather comparison requires an enabled BESS asset")
    simulation_config = dict(scenario.get("simulation_config") or {})
    if not bool(simulation_config.get("enable_weather_operation_policy", False)):
        raise ValueError("Frontend weather operation policy must remain enabled")
    if problem.metadata.get("weather_pv_forecast_applied") is not True:
        raise ValueError(
            "Frontend weather comparison requires the forecast PV curve to be "
            "applied; skip_reason="
            f"{problem.metadata.get('weather_pv_forecast_skip_reason')!r}"
        )


def _calendar_audit(
    *,
    problem: Any,
    service_id: str,
    fixed_control_hash: str,
) -> dict[str, Any]:
    """Persist either a matched calendar or the one permitted experiment waiver."""

    service_date = str(problem.metadata.get("service_date") or "")[:10]
    contract = _calendar_service_contract(service_date, service_id)
    validation = dict(problem.metadata.get("service_calendar_validation") or {})
    waiver = dict(validation.get("waiver") or {})
    if str(validation.get("status") or "").upper() == "WAIVED_BY_EXPERIMENT_POLICY":
        if not (
            str(waiver.get("calendar_policy") or "")
            == "fixed_weekday_timetable_pv_counterfactual"
            and str(waiver.get("scope") or "")
            == "weekday_timetable_on_sunday_for_pv_only_counterfactual"
            and str(service_id).upper() == "WEEKDAY"
            and date.fromisoformat(service_date).weekday() == 6
        ):
            raise ValueError("Calendar waiver is not the permitted PV-only experiment")
        return {
            **contract,
            "timetable_service_id": "WEEKDAY",
            "weather_profile_date": service_date,
            "calendar_policy": "fixed_weekday_timetable_pv_counterfactual",
            "calendar_validation_status": "WAIVED_BY_EXPERIMENT_POLICY",
            "waiver": {
                **waiver,
                "fixed_control_hash": fixed_control_hash,
            },
        }
    if str(validation.get("status") or "").upper() != "OK" or not contract["matches"]:
        raise ValueError(f"Calendar contract is not accepted: {validation}")
    return {
        **contract,
        "timetable_service_id": str(service_id).upper(),
        "weather_profile_date": service_date,
        "calendar_policy": "matched_service_calendar",
        "calendar_validation_status": "matched",
        "waiver": None,
    }


def run(args: argparse.Namespace) -> int:
    day_ahead_only_exploratory = bool(
        getattr(args, "day_ahead_only_exploratory", False)
    )
    # Formal execution is day-ahead plus the complete rolling chain. The only
    # supported opt-out is explicitly diagnostic and cannot complete a release.
    args.run_hourly_rolling = not day_ahead_only_exploratory
    _validate_fleet_mutation_scope(
        available_bev_count=getattr(args, "available_bev_count", None),
        day_ahead_only_exploratory=day_ahead_only_exploratory,
    )
    gurobi_threads = getattr(args, "gurobi_threads", None)
    stage1_best_obj_stop_enabled = bool(
        getattr(args, "stage1_best_obj_stop_enabled", True)
    )
    if gurobi_threads is not None and int(gurobi_threads) < 1:
        raise ValueError("gurobi_threads must be at least 1 when specified")
    stage1_strategy = str(
        getattr(args, "stage1_strategy", DEFAULT_STAGE1_STRATEGY)
        or DEFAULT_STAGE1_STRATEGY
    ).strip()
    if stage1_strategy not in {
        "full_network_milp",
        "fast_fixed_path",
    }:
        raise ValueError(f"Unsupported stage1_strategy: {stage1_strategy}")
    comparison_design = str(
        getattr(args, "comparison_design", "same_service_date_pv_counterfactual")
        or "same_service_date_pv_counterfactual"
    ).strip()
    if comparison_design != "same_service_date_pv_counterfactual":
        raise ValueError(
            "Formal weather comparisons must use "
            "same_service_date_pv_counterfactual"
        )
    comparison_role = str(
        getattr(args, "comparison_role", "baseline") or "baseline"
    ).strip()
    counterfactual_curve_audit = _counterfactual_pv_curve_audit(
        comparison_role=comparison_role,
        raw_path=getattr(args, "counterfactual_pv_curve_file", None),
    )
    counterfactual_curve_forecast = counterfactual_curve_audit.pop(
        "forecast", None
    )
    fast_assignment_time_limit_sec = int(
        getattr(args, "fast_assignment_time_limit_sec", 30)
    )
    fast_stage2_case_time_limit_sec = int(
        getattr(args, "fast_stage2_case_time_limit_sec", 5)
    )
    executed_phase = (
        "phase1_charging_only"
        if stage1_strategy == "fast_fixed_path"
        else "phase3_two_stage"
    )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    print("[1/4] Loading persisted frontend scenario and prepared scope", flush=True)
    prepared_root = _prepared_inputs_root()
    prepared_path = prepared_root / args.scenario_id / f"{args.prepared_input_id}.json"
    prepared_payload = load_prepared_input(
        scenario_id=args.scenario_id,
        prepared_input_id=args.prepared_input_id,
        scenarios_dir=prepared_root,
    )
    scenario = deepcopy(
        materialize_scenario_from_prepared_input(
            store.get_scenario_document_shallow(args.scenario_id),
            prepared_payload,
        )
    )
    fixed_weekday_waiver_requested = bool(
        getattr(args, "allow_fixed_weekday_timetable_pv_counterfactual", False)
    )
    if fixed_weekday_waiver_requested:
        requested_service_date = date.fromisoformat(str(args.expected_service_date)[:10])
        if str(args.service_id).upper() != "WEEKDAY" or requested_service_date.weekday() != 6:
            raise ValueError(
                "--allow-fixed-weekday-timetable-pv-counterfactual is valid only "
                "for a WEEKDAY timetable on a Sunday service date"
            )
        waiver_config = dict(scenario.get("simulation_config") or {})
        waiver_config.update(
            {
                "allow_fixed_weekday_timetable_pv_counterfactual": True,
                "calendar_policy": "fixed_weekday_timetable_pv_counterfactual",
                "weather_profile_date": requested_service_date.isoformat(),
                # Keep the prepared WEEKDAY timetable rows, but make the
                # weather/service-date provenance explicit for the permitted
                # Sunday PV counterfactual.  The calendar waiver below is the
                # only reason a WEEKDAY service remains valid on this date.
                "service_date": requested_service_date.isoformat(),
                "service_dates": [requested_service_date.isoformat()],
            }
        )
        scenario["simulation_config"] = waiver_config
    discretization = _configure_research_discretization(
        scenario,
        timestep_min=int(args.time_step_min),
    )
    bev_availability_sensitivity = _apply_bev_availability_sensitivity(
        scenario,
        args.available_bev_count,
    )
    # A formal frontend weather run must apply the persisted forecast even when
    # a legacy prepared scenario has the old opt-out flag.  The effective flag
    # is captured in the run provenance; this is not a solver fallback.
    weather_config = dict(scenario.get("simulation_config") or {})
    weather_config["enable_weather_operation_policy"] = True
    scenario["simulation_config"] = weather_config
    scenario, weather_forecast, weather_profile = _prepare_weather_policy_for_scenario(
        scenario,
        enable_weather_operation_policy=True,
        weather_proxy_forecast_path=None,
    )
    bev_terminal_soc_policy = normalize_bev_terminal_soc_policy(
        getattr(args, "bev_terminal_soc_policy", "return_to_initial")
    )
    simulation_config = dict(scenario.get("simulation_config") or {})
    simulation_config["bev_terminal_soc_policy"] = bev_terminal_soc_policy.value
    simulation_config["bev_terminal_soc_equality_tolerance_kwh"] = float(
        args.bev_terminal_soc_equality_tolerance_kwh
    )
    vehicle_usage_cost_override = getattr(
        args,
        "vehicle_usage_cost_jpy_per_used_bus",
        None,
    )
    if vehicle_usage_cost_override is not None:
        if float(vehicle_usage_cost_override) < 0.0:
            raise ValueError(
                "vehicle_usage_cost_jpy_per_used_bus must be nonnegative"
            )
        scenario.setdefault("scenario_overlay", {}).setdefault(
            "cost_coefficients",
            {},
        )["vehicle_usage_cost_jpy_per_used_bus"] = float(
            vehicle_usage_cost_override
        )
    fleet_contract = resolve_scenario_fleet_contract(
        scenario,
        selected_depot_ids=(str(args.depot_id),),
        research_run=True,
    )
    simulation_config["research_vehicle_inventory"] = dict(
        fleet_contract.inventory_by_powertrain
    )
    simulation_config["research_vehicle_ids"] = list(
        fleet_contract.active_vehicle_ids
    )
    simulation_config["research_vehicle_id_hash"] = (
        fleet_contract.active_vehicle_id_hash
    )
    simulation_config["research_vehicle_parameter_hash"] = (
        fleet_contract.vehicle_parameter_hash
    )
    simulation_config["research_vehicle_initial_state_hash"] = (
        fleet_contract.initial_state_hash
    )
    simulation_config["research_fleet_contract_hash"] = (
        fleet_contract.fleet_contract_hash
    )
    simulation_config["scenario_fleet_contract"] = fleet_contract.to_dict(
        include_source_records=True
    )
    scenario["simulation_config"] = simulation_config
    fragment_policy = enforce_research_phase3_single_continuous_duty(scenario)
    initial_soc_policy = _resolve_initial_soc_policy(scenario)
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        time_limit_sec=int(args.time_limit_sec),
        stage1_time_limit_sec=args.stage1_time_limit_sec,
        stage2_time_limit_sec=args.stage2_time_limit_sec,
        stage1_best_obj_stop_enabled=stage1_best_obj_stop_enabled,
        gurobi_threads=gurobi_threads,
        mip_gap=float(args.mip_gap),
        random_seed=int(args.random_seed),
        warm_start=True,
        thesis_mode=True,
        research_run=True,
        allow_postsolve_repair=False,
        phase="phase3_two_stage",
        requested_phase="phase3_two_stage",
        resolved_phase="phase3_two_stage",
        executed_phase="phase3_two_stage",
    )
    print("[2/4] Building canonical problem and applying weather policy", flush=True)
    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id=args.depot_id,
        service_id=args.service_id,
        config=config,
        planning_days=1,
    )
    if isinstance(problem.metadata, dict):
        problem.metadata["stage2_feedback_max_iterations"] = 2
        problem.metadata["stage2_feedback_policy"] = (
            "retry_only_after_gurobi_infeasible_certificate_with_"
            "full_assignment_no_good_cut"
        )
    if weather_forecast is not None and weather_profile is not None:
        problem = apply_weather_policy_to_problem(
            problem,
            weather_forecast,
            weather_profile,
            random_seed=int(args.random_seed),
        )
    if counterfactual_curve_forecast is not None:
        problem = apply_same_service_date_pv_counterfactual_to_problem(
            problem,
            counterfactual_curve_forecast,
            source_descriptor={
                key: value
                for key, value in counterfactual_curve_audit.items()
                if key != "enabled"
            },
        )
    minimum_used_bev_count = int(args.minimum_used_bev_count)
    if bool(getattr(args, "require_all_available_bevs", False)):
        minimum_used_bev_count = int(
            fleet_contract.inventory_by_powertrain.get("BEV", 0)
        )
    problem = replace(
        problem,
        metadata={
            **dict(problem.metadata or {}),
            "bev_terminal_soc_equality_tolerance_kwh": float(
                args.bev_terminal_soc_equality_tolerance_kwh
            ),
            "minimum_used_bev_count": minimum_used_bev_count,
            "minimum_used_bev_count_policy_case": (
                minimum_used_bev_count > 0
            ),
            "require_all_available_bevs": bool(
                getattr(args, "require_all_available_bevs", False)
            ),
        },
    )
    if minimum_used_bev_count < 0:
        raise ValueError("minimum_used_bev_count must be nonnegative")
    initial_soc_metadata = initial_soc_input_metadata(
        problem,
        policy=initial_soc_policy,
    )
    active_bev_count = int(fleet_contract.inventory_by_powertrain.get("BEV", 0))
    if len(initial_soc_metadata["initial_soc_by_vehicle"]) != active_bev_count:
        raise ValueError(
            "Frontend weather comparison requires exact initial SOC inputs for "
            f"the scenario-derived {active_bev_count} BEVs"
        )
    trip_distance_audit = _trip_distance_audit(problem, prepared_payload)
    _validate_frontend_case(
        problem,
        scenario,
        expected_service_date=args.expected_service_date,
        assert_bev_count=getattr(args, "assert_bev_count", None),
        assert_ice_count=getattr(args, "assert_ice_count", None),
        assert_trip_count=getattr(args, "assert_trip_count", None),
        assert_timestep_min=getattr(args, "assert_timestep_min", None),
        assert_price_slot_count=getattr(args, "assert_price_slot_count", None),
        service_id=args.service_id,
        allow_fixed_weekday_timetable_pv_counterfactual=fixed_weekday_waiver_requested,
    )
    git_state = _git_state()
    trip_input_hash = _trip_input_hash(problem)
    vehicle_input_hash = _vehicle_input_hash(problem)
    charger_configuration = _charger_snapshot(problem)
    depot_energy_assets = _asset_snapshot(problem)
    depot_import_limit_kw_by_depot = _depot_import_limit_snapshot(problem)
    weather_configuration = _weather_configuration(scenario)
    weather_operation_profile = dict(
        problem.metadata.get("weather_operation_profile") or {}
    )
    if not weather_operation_profile:
        raise ValueError(
            "Frontend weather comparison requires the effective weather operation profile"
        )
    terminal_soc_policy = {
        "bev_terminal_soc_policy": str(
            problem.metadata.get("bev_terminal_soc_policy") or ""
        ),
        "post_return_soc_target_enabled": bool(
            problem.metadata.get("post_return_soc_target_enabled", False)
        ),
        "final_soc_floor_percent": problem.metadata.get("final_soc_floor_percent"),
        "final_soc_target_percent": problem.metadata.get("final_soc_target_percent"),
        "final_soc_target_tolerance_percent": problem.metadata.get(
            "final_soc_target_tolerance_percent"
        ),
        "bev_terminal_soc_equality_tolerance_kwh": problem.metadata.get(
            "bev_terminal_soc_equality_tolerance_kwh"
        ),
    }
    prepared_input_sha256 = _sha256(prepared_path)
    expected_fleet = dict(fleet_contract.inventory_by_powertrain)
    weather_decision_policy = weather_decision_policy_audit(problem.metadata)
    comparison_control_hash = _comparison_control_hash(
        scenario_id=args.scenario_id,
        prepared_input_id=args.prepared_input_id,
        prepared_input_sha256=prepared_input_sha256,
        service_date=str(problem.metadata.get("service_date") or "")[:10],
        service_id=str(args.service_id),
        expected_fleet=expected_fleet,
        trip_input_hash=trip_input_hash,
        vehicle_input_hash=vehicle_input_hash,
        initial_soc_input_hash=str(initial_soc_metadata["initial_soc_input_hash"]),
        terminal_soc_policy=terminal_soc_policy,
        charger_configuration=charger_configuration,
        depot_energy_assets=depot_energy_assets,
        weather_configuration=weather_configuration,
        weather_operation_profile=weather_operation_profile,
        time_limit_sec=int(args.time_limit_sec),
        stage1_time_limit_sec=args.stage1_time_limit_sec,
        stage2_time_limit_sec=args.stage2_time_limit_sec,
        stage1_best_obj_stop_enabled=stage1_best_obj_stop_enabled,
        gurobi_threads=gurobi_threads,
        mip_gap=float(args.mip_gap),
        random_seed=int(args.random_seed),
        git_sha=git_state.get("git_sha"),
    )
    calendar_audit = _calendar_audit(
        problem=problem,
        service_id=str(args.service_id),
        fixed_control_hash=comparison_control_hash,
    )
    weather_comparison_contract = {
        "schema_version": "weather_comparison_contract_v1",
        "comparison_design": comparison_design,
        "comparison_role": comparison_role,
        "weather_difference_scope": str(
            counterfactual_curve_audit.get("weather_difference_scope", "none")
        ),
        "base_service_date": str(problem.metadata.get("service_date") or "")[:10],
        "same_service_date_required": True,
        "same_timetable_required": True,
        "same_fleet_required": True,
        "same_initial_soc_required": True,
        "comparison_control_hash": comparison_control_hash,
        "counterfactual_pv_curve": counterfactual_curve_audit,
        "interpretation": (
            "Only the PV availability curve may differ across this pair. "
            "It does not establish a weather-dependent dispatch policy unless "
            "the separately reported decision-policy audit shows active controls."
        ),
    }
    scenario["research_execution_overrides"] = {
        "weather_comparison_contract": weather_comparison_contract,
        "weather_decision_policy": weather_decision_policy,
        "persisted_scenario_modified": False,
    }
    experiment_hash = _canonical_hash(
        {
            "service_date": str(problem.metadata.get("service_date") or "")[:10],
            "route_ids": sorted({str(trip.route_id) for trip in problem.trips}),
            "trip_input_hash": trip_input_hash,
            "vehicle_input_hash": vehicle_input_hash,
            "initial_soc_policy": initial_soc_metadata["initial_soc_policy"],
            "initial_soc_input_hash": initial_soc_metadata["initial_soc_input_hash"],
            "bev_terminal_soc_policy": bev_terminal_soc_policy.value,
            "charger_configuration": charger_configuration,
            "timestep_min": int(problem.scenario.timestep_min),
            "milp_max_successors_per_trip": problem.metadata.get(
                "milp_max_successors_per_trip"
            ),
            "depot_energy_assets": depot_energy_assets,
            "depot_import_limit_kw_by_depot": depot_import_limit_kw_by_depot,
            "depot_import_limit_semantics": "nonpositive_means_no_finite_contract_limit",
            "contract_overage_penalty_yen_per_kwh": float(
                problem.metadata.get("contract_overage_penalty_yen_per_kwh", 0.0)
                or 0.0
            ),
            "weather_configuration": weather_configuration,
            "weather_operation_profile": weather_operation_profile,
            "weather_decision_policy": weather_decision_policy,
            "weather_comparison_contract": weather_comparison_contract,
            "research_fragment_policy": fragment_policy,
            "bev_availability_sensitivity": bev_availability_sensitivity,
            "minimum_used_bev_count": minimum_used_bev_count,
            "vehicle_usage_cost_jpy_per_used_bus": float(
                problem.metadata.get("vehicle_usage_cost_jpy_per_used_bus", 0.0)
                or 0.0
            ),
            "phase": executed_phase,
            "stage1_strategy": stage1_strategy,
            "fast_assignment_time_limit_sec": fast_assignment_time_limit_sec,
            "fast_stage2_case_time_limit_sec": fast_stage2_case_time_limit_sec,
            "research_run": True,
            "time_limit_sec": int(args.time_limit_sec),
            "stage1_time_limit_sec": args.stage1_time_limit_sec,
            "stage2_time_limit_sec": args.stage2_time_limit_sec,
            "stage1_best_obj_stop_enabled": stage1_best_obj_stop_enabled,
            "gurobi_threads": gurobi_threads,
            "mip_gap": float(args.mip_gap),
            "random_seed": int(args.random_seed),
            "git_sha": git_state["git_sha"],
        }
    )
    effective_pv_profiles_path = output_dir / "effective_pv_profiles.json"
    _write_json(effective_pv_profiles_path, _effective_pv_profiles(problem))
    effective_pv_profiles_sha256 = _sha256(effective_pv_profiles_path)
    fixed_depot_energy_assets = {
        depot_id: {
            key: value
            for key, value in dict(asset).items()
            # ``pv_case_id`` identifies the weather/PV curve just like the
            # generation total and hash.  It must not enter the fixed-control
            # hash, otherwise Rolling rejects a valid PV-only update.
            if key
            not in {"pv_case_id", "pv_generation_kwh", "pv_generation_hash"}
        }
        for depot_id, asset in sorted(depot_energy_assets.items())
    }
    input_audit = {
        "effective_scenario_artifact": "effective_scenario.json",
        "manifest_artifact": "manifest.json",
        "effective_scenario_sha256": _canonical_hash(scenario),
        "input_fingerprint_schema": INPUT_FINGERPRINT_SCHEMA,
        "case_name": args.case_name,
        "scenario_id": args.scenario_id,
        "prepared_input_id": args.prepared_input_id,
        "prepared_input_sha256": prepared_input_sha256,
        "service_date": str(problem.metadata.get("service_date") or "")[:10],
        "service_id": str(args.service_id),
        "calendar_service_contract": _calendar_service_contract(
            str(problem.metadata.get("service_date") or "")[:10],
            str(args.service_id),
        ),
        "calendar_audit": calendar_audit,
        "calendar_policy": calendar_audit.get("calendar_policy"),
        "calendar_validation_status": calendar_audit.get(
            "calendar_validation_status"
        ),
        "actual_service_day_display_forbidden": True,
        "phase": executed_phase,
        "stage1_strategy": stage1_strategy,
        "assignment_global_optimality": (
            False if stage1_strategy == "fast_fixed_path" else None
        ),
        "assignment_global_optimality_scope": None,
        "full_network_global_optimality": None,
        "fast_assignment_time_limit_sec": fast_assignment_time_limit_sec,
        "fast_stage2_case_time_limit_sec": fast_stage2_case_time_limit_sec,
        "time_limit_sec": int(args.time_limit_sec),
        "stage1_time_limit_sec": args.stage1_time_limit_sec,
        "stage2_time_limit_sec": args.stage2_time_limit_sec,
        "stage1_best_obj_stop_enabled": stage1_best_obj_stop_enabled,
        "gurobi_threads": gurobi_threads,
        "mip_gap": float(args.mip_gap),
        "random_seed": int(args.random_seed),
        "postsolve_repair_enabled": False,
        "vehicle_soc_semantics": "slot_start",
        "weather_operation_policy_enabled": True,
        "weather_configuration": weather_configuration,
        "weather_operation_profile": weather_operation_profile,
        "weather_decision_policy": weather_decision_policy,
        "weather_comparison_contract": weather_comparison_contract,
        "weather_pv_forecast_applied": bool(
            problem.metadata.get("weather_pv_forecast_applied", False)
        ),
        "weather_pv_forecast_skip_reason": problem.metadata.get(
            "weather_pv_forecast_skip_reason"
        ),
        "trip_count": len(problem.trips),
        "fleet": dict(expected_fleet),
        "fleet_available": dict(expected_fleet),
        "scenario_fleet_contract": fleet_contract.to_dict(
            include_source_records=True
        ),
        "scenario_fleet_contract_hash": fleet_contract.fleet_contract_hash,
        "active_vehicle_id_hash": fleet_contract.active_vehicle_id_hash,
        "vehicle_parameter_hash": fleet_contract.vehicle_parameter_hash,
        "initial_state_hash": fleet_contract.initial_state_hash,
        "bev_availability_sensitivity": bev_availability_sensitivity,
        "minimum_used_bev_count": minimum_used_bev_count,
        "timestep_min": int(problem.scenario.timestep_min),
        "price_slot_count": len(problem.price_slots),
        "planning_horizon_hours": float(problem.scenario.planning_horizon_hours),
        "energy_horizon_duration_min": int(
            problem.metadata.get("energy_horizon_duration_min", 0) or 0
        ),
        "service_window_start_min": problem.metadata.get("service_window_start_min"),
        "service_window_end_min": problem.metadata.get("service_window_end_min"),
        "milp_max_successors_per_trip": problem.metadata.get(
            "milp_max_successors_per_trip"
        ),
        "successor_pruning_enabled": False,
        "research_discretization": discretization,
        "trip_distance_audit": trip_distance_audit,
        "clock_hour_grid_price_yen_per_kwh": _clock_hour_prices(problem),
        "demand_charge_monthly_yen_per_kw": float(problem.scenario.demand_charge_on_peak_yen_per_kw),
        "demand_charge_horizon_yen_per_kw": float(
            problem.scenario.demand_charge_on_peak_horizon_yen_per_kw
        ),
        "depot_import_limit_kw_by_depot": depot_import_limit_kw_by_depot,
        "depot_import_limit_semantics": "nonpositive_means_no_finite_contract_limit",
        "contract_overage_penalty_yen_per_kwh": float(
            problem.metadata.get("contract_overage_penalty_yen_per_kwh", 0.0)
            or 0.0
        ),
        "diesel_price_yen_per_l": float(problem.scenario.diesel_price_yen_per_l),
        "co2_price_yen_per_kg": float(problem.scenario.co2_price_per_kg),
        "vehicle_usage_cost_jpy_per_used_bus": float(
            problem.metadata.get("vehicle_usage_cost_jpy_per_used_bus", 0.0)
            or 0.0
        ),
        "cost_component_flags": dict(
            problem.metadata.get("cost_component_flags") or {}
        ),
        "objective_weights": {
            name: float(getattr(problem.objective_weights, name, 0.0) or 0.0)
            for name in (
                "energy",
                "fuel",
                "demand",
                "vehicle",
                "vehicle_usage",
                "degradation",
            )
        },
        "grid_co2_kg_per_kwh": {
            str(slot.slot_index): float(slot.co2_factor) for slot in problem.price_slots
        },
        "pv_marginal_charge_cost_yen_per_kwh": float(
            problem.metadata.get("pv_marginal_charge_cost_yen_per_kwh", 0.0)
        ),
        "pv_curtail_penalty_yen_per_kwh": float(
            problem.metadata.get("pv_curtail_penalty_yen_per_kwh", 0.0)
        ),
        "initial_soc_policy": initial_soc_metadata["initial_soc_policy"],
        "initial_soc_source": initial_soc_metadata["initial_soc_source"],
        "initial_soc_input_hash": initial_soc_metadata["initial_soc_input_hash"],
        "initial_soc_by_vehicle": initial_soc_metadata["initial_soc_by_vehicle"],
        "terminal_soc_policy": terminal_soc_policy,
        "research_fragment_policy": fragment_policy,
        "charger_configuration": charger_configuration,
        "charger_configuration_hash": _canonical_hash(charger_configuration),
        "depot_energy_assets": depot_energy_assets,
        "depot_energy_assets_fixed_hash": _canonical_hash(
            fixed_depot_energy_assets
        ),
        "effective_pv_profiles_artifact": effective_pv_profiles_path.name,
        "effective_pv_profiles_sha256": effective_pv_profiles_sha256,
        "vehicle_input_hash": vehicle_input_hash,
        "trip_input_hash": trip_input_hash,
        "experiment_hash": experiment_hash,
        "stage1_candidate_warm_start_configuration": {
            "enabled": (
                stage1_strategy == "full_network_milp"
                and int(args.stage1_candidate_time_limit_sec) > 0
            ),
            "time_limit_sec": int(args.stage1_candidate_time_limit_sec),
            "milp_max_successors_per_trip": int(
                args.stage1_candidate_successors
            ),
            "semantics": (
                "restricted_arc_relaxed_soc_primal_heuristic_only_final_stage1_"
                "uses_full_network_and_time_indexed_soc_relaxation"
            ),
        },
        "expected_fleet": expected_fleet,
        **git_state,
    }
    _write_json(output_dir / "effective_scenario.json", scenario)
    _write_json(output_dir / "input_audit.json", input_audit)
    _write_json(
        output_dir / "scenario_fleet_contract.json",
        fleet_contract.to_dict(include_source_records=True),
    )
    if args.build_only:
        _write_research_manifest(
            output_dir,
            input_audit=input_audit,
            run_state="build_only",
        )
        print(json.dumps(input_audit, ensure_ascii=False, indent=2), flush=True)
        return 0
    if not is_gurobi_available():
        raise RuntimeError("Gurobi is unavailable; no fallback is permitted for this research run")
    if isinstance(problem.metadata, dict):
        problem.metadata["phase3_diagnostics_dir"] = str(output_dir / "diagnostics")
        problem.metadata["vehicle_soc_semantics"] = "slot_start"
        problem.metadata["frontend_weather_cost_experiment"] = True
        problem.metadata["weather_comparison_contract"] = weather_comparison_contract
        problem.metadata["weather_decision_policy"] = weather_decision_policy
    candidate_audit: dict[str, Any] = {
        "enabled": False,
        "accepted_as_final_stage1_warm_start": False,
    }
    if (
        stage1_strategy == "full_network_milp"
        and int(args.stage1_candidate_time_limit_sec) > 0
    ):
        candidate_successors = int(args.stage1_candidate_successors)
        if candidate_successors <= 0:
            raise ValueError(
                "stage1_candidate_successors must be positive when candidate generation is enabled"
            )
        candidate_metadata = {
            **dict(problem.metadata or {}),
            "milp_max_successors_per_trip": candidate_successors,
            "stage1_candidate_generation": True,
            "stage1_candidate_final_network_unrestricted": True,
            # Candidate generation is a primal heuristic only.  Omitting the
            # expensive 15-minute SOC necessary-condition relaxation here
            # recovers a useful assignment quickly; the unrestricted final
            # Stage 1 restores it and rejects any incompatible MIP start.
            "stage1_time_indexed_soc_relaxation_enabled": False,
        }
        candidate_problem = replace(problem, metadata=candidate_metadata)
        candidate_limit = int(args.stage1_candidate_time_limit_sec)
        candidate_config = replace(
            config,
            time_limit_sec=candidate_limit,
            stage1_time_limit_sec=candidate_limit,
            stage2_time_limit_sec=None,
            phase="phase2_assignment_only",
            requested_phase="phase2_assignment_only",
            resolved_phase="phase2_assignment_only",
            executed_phase="phase2_assignment_only",
            fixed_assignment=None,
        )
        print(
            "[3/5] Generating a weather-specific Stage 1 primal warm start ",
            f"with {candidate_successors} successors per trip",
            flush=True,
        )
        candidate_started = time.perf_counter()
        candidate_result = OptimizationEngine().solve(
            candidate_problem,
            candidate_config,
        )
        candidate_elapsed = time.perf_counter() - candidate_started
        candidate_solver_metadata = dict(candidate_result.solver_metadata or {})
        candidate_stage1_has_incumbent = bool(
            candidate_solver_metadata.get("stage1_has_feasible_incumbent")
            or candidate_solver_metadata.get("has_feasible_incumbent")
        )
        expected_trip_ids = {str(trip.trip_id) for trip in candidate_problem.trips}
        candidate_trip_ids = {
            str(trip_id) for trip_id in candidate_result.plan.served_trip_ids
        }
        candidate_complete = (
            candidate_stage1_has_incumbent
            and candidate_trip_ids == expected_trip_ids
            and not candidate_result.plan.unserved_trip_ids
        )
        candidate_audit = {
            "enabled": True,
            "accepted_as_final_stage1_warm_start": candidate_complete,
            "time_limit_sec": candidate_limit,
            "milp_max_successors_per_trip": candidate_successors,
            "stage1_time_indexed_soc_relaxation_enabled": False,
            "elapsed_seconds": candidate_elapsed,
            "solver_status": candidate_result.solver_status,
            "stage1_has_feasible_incumbent": candidate_stage1_has_incumbent,
            "stage1_solver_status": candidate_solver_metadata.get(
                "stage1_solver_status"
            ),
            "stage1_objective": _finite(
                candidate_solver_metadata.get("stage1_objective")
            ),
            "stage1_best_bound": _finite(
                candidate_solver_metadata.get("stage1_best_bound")
            ),
            "stage1_mip_gap_percent": _mip_gap_percent(
                candidate_solver_metadata.get("stage1_mip_gap_ratio")
            ),
            "trip_count_served": len(candidate_trip_ids),
            **_assignment_mix(candidate_problem, candidate_result),
            "semantics": (
                "restricted_arc_relaxed_soc_primal_heuristic_only_final_stage1_"
                "uses_full_network_and_time_indexed_soc_relaxation"
            ),
        }
        if candidate_complete:
            candidate_plan = replace(
                candidate_result.plan,
                metadata={
                    **dict(candidate_result.plan.metadata or {}),
                    "source": "stage1_restricted_candidate_warm_start",
                    "candidate_milp_max_successors_per_trip": candidate_successors,
                },
            )
            config = replace(config, fixed_assignment=candidate_plan)
        _write_json(
            output_dir / "stage1_candidate_warm_start.json",
            candidate_audit,
        )
    fast_assignment_audit: dict[str, Any] = {
        "strategy": stage1_strategy,
        "enabled": stage1_strategy == "fast_fixed_path",
    }
    if stage1_strategy == "fast_fixed_path":
        print(
            "[4/5] Evaluating cost-aware fixed-path assignments with exact charging/SOC validation",
            flush=True,
        )
        try:
            result, fast_assignment_audit = _solve_fast_fixed_path_candidates(
                problem,
                config,
                total_time_limit_sec=fast_assignment_time_limit_sec,
                per_case_time_limit_sec=fast_stage2_case_time_limit_sec,
            )
        except FastFixedPathSearchError as exc:
            _write_json(output_dir / "fast_assignment_audit.json", exc.audit)
            raise
        elapsed = float(fast_assignment_audit["elapsed_seconds"])
        _write_json(output_dir / "fast_assignment_audit.json", fast_assignment_audit)
    else:
        print("[4/5] Solving full-network Phase 3 (no fallback, no repair)", flush=True)
        started = time.perf_counter()
        result = OptimizationEngine().solve(problem, config)
        elapsed = time.perf_counter() - started
    result = replace(
        result,
        solver_metadata={
            **dict(result.solver_metadata or {}),
            "weather_comparison_contract": weather_comparison_contract,
            "weather_decision_policy": weather_decision_policy,
            "git_provenance_captured_before_solve": True,
        },
    )
    metadata = dict(result.solver_metadata or {})
    breakdown = dict(result.cost_breakdown or {})
    flows = {
        key: _finite(breakdown.get(key))
        for key in (
            "grid_to_bus_kwh",
            "grid_to_bess_kwh",
            "pv_to_bus_kwh",
            "pv_to_bess_kwh",
            "bess_to_bus_kwh",
            "pv_generated_kwh",
            "pv_curtailed_kwh",
            "grid_import_kwh",
            "peak_grid_kw",
        )
    }
    costs = {
        key: _finite(breakdown.get(key))
        for key in (
            "total_cost",
            "electricity_cost",
            "grid_purchase_cost",
            "pv_to_bus_cost_jpy",
            "pv_to_bess_cost_jpy",
            "pv_curtail_cost_jpy",
            "bess_to_bus_cost_jpy",
            "demand_cost",
            "fuel_cost",
            "co2_cost",
            "vehicle_cost",
            "vehicle_usage_cost",
            "driver_cost",
            "unserved_penalty",
            "switch_cost",
            "degradation_cost",
            "deviation_cost",
            "contract_overage_cost",
        )
    }
    assignment_mix = _assignment_mix(problem, result)
    summary = {
        **input_audit,
        "stage1_candidate_warm_start": candidate_audit,
        "fast_assignment_audit": _compact_fast_assignment_audit(
            fast_assignment_audit
        ),
        "assignment_solution_method": metadata.get("assignment_solution_method"),
        "assignment_global_optimality": metadata.get(
            "assignment_global_optimality"
        ),
        "stage1_exact_optimality_certified": bool(
            metadata.get("stage1_exact_optimality_certified", False)
        ),
        "assignment_global_optimality_scope": metadata.get(
            "assignment_global_optimality_scope"
        ),
        "assignment_certified_mip_gap_ratio": _finite(
            metadata.get("assignment_certified_mip_gap_ratio")
        ),
        "full_network_global_optimality": metadata.get(
            "full_network_global_optimality"
        ),
        "charging_solution_method": metadata.get("charging_solution_method"),
        "charging_global_optimality_for_fixed_assignment": metadata.get(
            "charging_global_optimality_for_fixed_assignment"
        ),
        "solver_status": str(result.solver_status or ""),
        "feasible": bool(result.feasible),
        "elapsed_seconds": elapsed,
        "trip_count_served": len(result.plan.served_trip_ids),
        "trip_count_unserved": len(result.plan.unserved_trip_ids),
        "used_vehicle_count": len(result.plan.vehicle_paths()),
        **assignment_mix,
        "max_fragments_observed": int(result.plan.max_fragments_observed()),
        "stage1_solver_status": metadata.get("stage1_solver_status"),
        "stage2_solver_status": metadata.get("stage2_solver_status"),
        "stage2_exact_optimality_certified": bool(
            metadata.get("stage2_exact_optimality_certified", False)
        ),
        "stage1_objective": _finite(metadata.get("stage1_objective")),
        "stage2_objective": _finite(metadata.get("stage2_objective")),
        "stage1_best_bound": _finite(metadata.get("stage1_best_bound")),
        "stage1_solver_best_bound": _finite(
            metadata.get("stage1_solver_best_bound")
        ),
        "stage1_gurobi_raw_best_bound": _finite(
            metadata.get("stage1_gurobi_raw_best_bound")
        ),
        "stage1_gurobi_raw_mip_gap_ratio": _finite(
            metadata.get("stage1_gurobi_raw_mip_gap_ratio")
        ),
        "stage1_gurobi_raw_mip_gap_percent": _mip_gap_percent(
            metadata.get("stage1_gurobi_raw_mip_gap_ratio")
        ),
        "stage1_certified_best_bound": _finite(
            metadata.get("stage1_certified_best_bound")
        ),
        "stage1_certified_mip_gap_ratio": _finite(
            metadata.get("stage1_certified_mip_gap_ratio")
        ),
        "stage1_certified_mip_gap_percent": _mip_gap_percent(
            metadata.get("stage1_certified_mip_gap_ratio")
        ),
        "stage1_certified_mip_gap_semantics": metadata.get(
            "stage1_certified_mip_gap_semantics"
        ),
        "stage1_analytical_objective_lower_bound": _finite(
            metadata.get("stage1_analytical_objective_lower_bound")
        ),
        "stage1_analytical_objective_lower_bound_semantics": metadata.get(
            "stage1_analytical_objective_lower_bound_semantics"
        ),
        "stage1_certified_gap_stop_threshold": _finite(
            metadata.get("stage1_certified_gap_stop_threshold")
        ),
        "stage1_best_obj_stop_enabled": bool(
            metadata.get("stage1_best_obj_stop_enabled", stage1_best_obj_stop_enabled)
        ),
        "stage1_best_obj_stop_applied": bool(
            metadata.get("stage1_best_obj_stop_applied", False)
        ),
        "stage1_certified_gap_stop_triggered": bool(
            metadata.get("stage1_certified_gap_stop_triggered", False)
        ),
        "stage1_termination_reason": metadata.get("stage1_termination_reason"),
        "gurobi_threads": metadata.get("gurobi_threads", gurobi_threads),
        "runtime_comparison_eligible": not bool(
            metadata.get("stage1_best_obj_stop_applied", False)
        ),
        "stage2_best_bound": _finite(metadata.get("stage2_best_bound")),
        "stage1_mip_gap_ratio": _finite(metadata.get("stage1_mip_gap_ratio")),
        "stage2_mip_gap_ratio": _finite(metadata.get("stage2_mip_gap_ratio")),
        "stage1_mip_gap_percent": _mip_gap_percent(
            metadata.get("stage1_mip_gap_ratio")
        ),
        "stage2_mip_gap_percent": _mip_gap_percent(
            metadata.get("stage2_mip_gap_ratio")
        ),
        "stage1_runtime_seconds": _finite(metadata.get("stage1_runtime_seconds")),
        "stage1_pre_optimize_seconds": _finite(
            metadata.get("stage1_pre_optimize_seconds")
        ),
        "stage1_model_variable_count": metadata.get(
            "stage1_model_variable_count"
        ),
        "stage1_model_constraint_count": metadata.get(
            "stage1_model_constraint_count"
        ),
        "stage1_search_telemetry": dict(
            metadata.get("stage1_search_telemetry") or {}
        ),
        "stage2_runtime_seconds": _finite(metadata.get("stage2_runtime_seconds")),
        "physical_charger_assignment_semantics": metadata.get(
            "physical_charger_assignment_semantics"
        ),
        "physical_charger_assignment_variable_count": metadata.get(
            "physical_charger_assignment_variable_count"
        ),
        "physical_charger_power_variable_count": metadata.get(
            "physical_charger_power_variable_count"
        ),
        "implicit_home_depot_charger_compatibility_vehicle_ids": list(
            metadata.get(
                "implicit_home_depot_charger_compatibility_vehicle_ids"
            )
            or ()
        ),
        "stage1_time_limit_sec_effective": metadata.get(
            "stage1_time_limit_sec_effective"
        ),
        "stage2_time_limit_sec_effective": metadata.get(
            "stage2_time_limit_sec_effective"
        ),
        "stage1_energy_envelope_constraint_count": metadata.get(
            "stage1_energy_envelope_constraint_count"
        ),
        "stage1_vehicle_count_lower_bound": metadata.get(
            "stage1_vehicle_count_lower_bound"
        ),
        "stage1_vehicle_count_lower_bound_constraint_count": metadata.get(
            "stage1_vehicle_count_lower_bound_constraint_count"
        ),
        "stage1_vehicle_count_lower_bound_semantics": metadata.get(
            "stage1_vehicle_count_lower_bound_semantics"
        ),
        "stage1_redundant_arc_link_constraints_omitted": metadata.get(
            "stage1_redundant_arc_link_constraints_omitted"
        ),
        "fragment_pairwise_depot_reset_constraint_count": metadata.get(
            "fragment_pairwise_depot_reset_constraint_count"
        ),
        "fragment_temporal_occupancy_constraint_count": metadata.get(
            "fragment_temporal_occupancy_constraint_count"
        ),
        "overlap_clique_constraint_count": metadata.get(
            "overlap_clique_constraint_count"
        ),
        "stage1_single_path_redundancy_elimination_applied": bool(
            metadata.get(
                "stage1_single_path_redundancy_elimination_applied",
                False,
            )
        ),
        "stage1_energy_envelope_semantics": metadata.get(
            "stage1_energy_envelope_semantics"
        ),
        "stage1_time_indexed_soc_relaxation_constraint_count": metadata.get(
            "stage1_time_indexed_soc_relaxation_constraint_count"
        ),
        "stage1_time_indexed_soc_relaxation_enabled": metadata.get(
            "stage1_time_indexed_soc_relaxation_enabled"
        ),
        "stage1_time_indexed_soc_relaxation_semantics": metadata.get(
            "stage1_time_indexed_soc_relaxation_semantics"
        ),
        "stage1_shared_charger_relaxation": dict(
            metadata.get("stage1_shared_charger_relaxation") or {}
        ),
        "stage1_feasibility_no_good_cut_count": metadata.get(
            "stage1_feasibility_no_good_cut_count"
        ),
        "stage2_feedback_iteration": metadata.get(
            "stage2_feedback_iteration"
        ),
        "stage2_feedback_history": list(
            metadata.get("stage2_feedback_history") or ()
        ),
        "stage1_energy_cost_proxy_configuration": dict(
            metadata.get("stage1_energy_cost_proxy_configuration") or {}
        ),
        "stage1_energy_cost_proxy_weather_input": dict(
            metadata.get("stage1_energy_cost_proxy_weather_input") or {}
        ),
        "stage1_energy_cost_proxy_result": dict(
            metadata.get("stage1_energy_cost_proxy_result") or {}
        ),
        "stage1_ice_boundary_fuel_cost_terms_enabled": bool(
            metadata.get("stage1_ice_boundary_fuel_cost_terms_enabled", False)
        ),
        "stage1_ice_boundary_fuel_cost_semantics": metadata.get(
            "stage1_ice_boundary_fuel_cost_semantics"
        ),
        "research_run_accepted": bool(metadata.get("research_run_accepted", False)),
        "research_feasibility_eligible": bool(
            metadata.get("research_feasibility_eligible", False)
        ),
        "research_cost_kpi_eligible": bool(
            metadata.get("research_cost_kpi_eligible", False)
        ),
        "research_accounting_cost_eligible": bool(
            metadata.get("research_accounting_cost_eligible", False)
        ),
        "research_cost_optimality_eligible": bool(
            metadata.get("research_cost_optimality_eligible", False)
        ),
        "solver_objective_matches_accounting_total": bool(
            metadata.get("solver_objective_matches_accounting_total", False)
        ),
        "objective_semantics": metadata.get("objective_semantics"),
        "accounting_total_cost_jpy": _finite(breakdown.get("total_cost")),
        "validated_operating_cost_jpy": (
            _finite(breakdown.get("total_cost"))
            if bool(metadata.get("research_accounting_cost_eligible", False))
            else None
        ),
        "energy_cost_basis": breakdown.get("energy_cost_basis"),
        "energy_cash_purchase_cost_jpy": _finite(
            breakdown.get("energy_cash_purchase_cost_jpy")
        ),
        "energy_inventory_valuation_cost_jpy": _finite(
            breakdown.get("energy_inventory_valuation_cost_jpy")
        ),
        "ev_unreplenished_drive_energy_kwh": _finite(
            breakdown.get("ev_unreplenished_drive_energy_kwh")
        ),
        "bev_terminal_soc_total_drawdown_kwh": _finite(
            metadata.get("bev_terminal_soc_total_drawdown_kwh")
        ),
        "bev_terminal_soc_total_target_shortfall_kwh": _finite(
            metadata.get("bev_terminal_soc_total_target_shortfall_kwh")
        ),
        "bev_terminal_soc_total_target_surplus_kwh": _finite(
            metadata.get("bev_terminal_soc_total_target_surplus_kwh")
        ),
        "bev_terminal_soc_max_abs_target_deviation_kwh": _finite(
            metadata.get("bev_terminal_soc_max_abs_target_deviation_kwh")
        ),
        "bev_terminal_soc_balance_satisfied": bool(
            metadata.get("bev_terminal_soc_balance_satisfied", False)
        ),
        "cost_comparison_scope": (
            "validated_fixed_path_accounting_not_global_assignment_optimum"
            if result.feasible and stage1_strategy == "fast_fixed_path"
            else "feasible_schedule_accounting_not_global_total_cost_optimum"
            if result.feasible
            else "not_available_for_infeasible_result"
        ),
        "validation_metrics": dict(metadata.get("validation_metrics") or {}),
        "flows_kwh_or_kw": flows,
        "costs_jpy": costs,
        "warnings": list(result.warnings or ()),
        "infeasibility_reasons": list(result.infeasibility_reasons or ()),
        "day_ahead_only_exploratory": day_ahead_only_exploratory,
        "research_submission_ready": False,
        "teacher_release_status": "BLOCKED",
        "rolling_execution": {
            "status": (
                "not_executed_exploratory"
                if day_ahead_only_exploratory
                else "pending_full_chain"
            )
        },
    }
    print("[5/5] Writing reproducibility artifacts", flush=True)
    _write_json(output_dir / "solver_result.json", ResultSerializer.serialize_result(result))
    _write_json(output_dir / "summary.json", summary)
    if result.feasible:
        _write_vehicle_schedule(output_dir / "vehicle_schedule.csv", result)
    _write_research_manifest(
        output_dir,
        input_audit=input_audit,
        run_state="complete" if result.feasible else "infeasible",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str), flush=True)

    if not result.feasible:
        return 2
    if not bool(getattr(args, "run_hourly_rolling", False)):
        _finalize_day_ahead_rolling_artifacts(
            day_ahead_output_dir=output_dir,
            rolling_exit_code=2,
        )
        return 3
    try:
        _validate_day_ahead_rolling_start_contract(output_dir)
    except ValueError:
        _finalize_day_ahead_rolling_artifacts(
            day_ahead_output_dir=output_dir,
            rolling_exit_code=2,
        )
        raise
    rolling_result = _invoke_hourly_rolling_after_day_ahead(args, output_dir)
    _finalize_day_ahead_rolling_artifacts(
        day_ahead_output_dir=output_dir,
        rolling_exit_code=rolling_result,
    )
    return rolling_result


def _finalize_day_ahead_rolling_artifacts(
    *,
    day_ahead_output_dir: Path,
    rolling_exit_code: int,
) -> None:
    """Link the day-ahead artifact to the persisted rolling outcome."""

    summary_path = day_ahead_output_dir / "summary.json"
    input_audit_path = day_ahead_output_dir / "input_audit.json"
    chain_path = day_ahead_output_dir / "rolling_hourly_chain" / "rolling_chain_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    input_audit = json.loads(input_audit_path.read_text(encoding="utf-8"))
    chain: dict[str, Any] = {}
    chain_error: str | None = None
    if chain_path.is_file():
        try:
            chain = json.loads(chain_path.read_text(encoding="utf-8"))
        except Exception as exc:
            chain_error = f"{type(exc).__name__}: {exc}"
    acceptance_audit = rolling_chain_acceptance_audit(chain)
    acceptance_checks = dict(acceptance_audit["acceptance_checks"])
    accepted = bool(acceptance_audit["accepted"] and rolling_exit_code == 0)
    status = (
        "executed_and_accepted"
        if accepted
        else "executed_not_accepted"
        if chain_path.is_file()
        else "not_executed"
    )
    rolling_execution = {
        "status": status,
        "chain_summary_path": str(chain_path.relative_to(day_ahead_output_dir)),
        "chain_accepted": bool(chain.get("chain_accepted")),
        "rolling_exit_code": int(rolling_exit_code),
        "acceptance_checks": acceptance_checks,
        "rejection_reasons": (
            list(chain.get("rejection_reasons") or [])
            + [
                f"missing_required_check:{name}"
                for name in acceptance_audit["missing_required_checks"]
            ]
            + [
                f"failed_acceptance_check:{name}"
                for name in acceptance_audit["failing_checks"]
            ]
            or (
                ["hourly_rolling_chain_missing"]
                if not chain_path.is_file()
                else ["hourly_rolling_chain_not_accepted"]
                if not accepted
                else []
            )
        ),
        "chain_read_error": chain_error,
    }
    summary["rolling_execution"] = rolling_execution
    _write_json(summary_path, summary)
    # Rolling acceptance is only one gate.  The day-ahead summary already
    # records the complete research-release decision (cost semantics,
    # optimality scope, provenance, and all other gates).  Do not let a
    # successful rolling chain upgrade a blocked run in the human-readable
    # report while summary.json remains blocked.
    research_submission_ready = bool(
        summary.get("research_submission_ready") and accepted
    )
    report_lines = [
        "# 実験レポート — 日次Phase 3後の1時間Rolling",
        "",
    ]
    if not research_submission_ready:
        report_lines.extend(["> EXPLORATORY — RESEARCH SUBMISSION BLOCKED", ""])
    report_lines.extend(
        [
            "## 研究提出資格",
            f"- input_provenance_ready: {bool(input_audit)}",
            f"- day_ahead_research_run_accepted: {bool(summary.get('research_run_accepted'))}",
            f"- rolling_execution_status: {status}",
            f"- rolling_chain_accepted: {accepted}",
            f"- research_submission_ready: {research_submission_ready}",
            "- rolling_rejection_reasons: "
            + ", ".join(rolling_execution["rejection_reasons"] or ["none"]),
            "",
            "## 主張範囲",
            "- 日次配車を固定した残り日充電/PV/BESSの逐次再最適化であり、統合総費用の大域最適解ではない。",
            "- 各stepの残り地平目的値は加算せず、実行prefixを一度だけ接続した会計のみを用いる。",
        ]
    )
    (day_ahead_output_dir / "experiment_report.md").write_text(
        "\n".join(report_lines) + "\n", encoding="utf-8"
    )
    _write_research_manifest(
        day_ahead_output_dir,
        input_audit=input_audit,
        run_state="complete" if accepted else "rolling_not_accepted",
    )


def _validate_day_ahead_rolling_start_contract(day_ahead_output_dir: Path) -> None:
    """Fail closed before rolling from an unaccepted day-ahead artifact."""

    summary_path = day_ahead_output_dir / "summary.json"
    input_audit_path = day_ahead_output_dir / "input_audit.json"
    solver_result_path = day_ahead_output_dir / "solver_result.json"
    missing = [
        path.name
        for path in (summary_path, input_audit_path, solver_result_path)
        if not path.is_file()
    ]
    if missing:
        raise ValueError(
            "Hourly rolling requires a complete day-ahead artifact contract; "
            f"missing={missing}"
        )
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    blockers = []
    if not bool(summary.get("feasible")):
        blockers.append("day_ahead_not_feasible")
    if not bool(summary.get("research_run_accepted")):
        blockers.append("day_ahead_research_acceptance_failed")
    if not bool(summary.get("research_feasibility_eligible")):
        blockers.append("day_ahead_research_feasibility_ineligible")
    if str(summary.get("phase") or "") != "phase3_two_stage":
        blockers.append("day_ahead_not_phase3_two_stage")
    if blockers:
        raise ValueError(
            "Hourly rolling will not start from an unaccepted day-ahead result: "
            + ", ".join(blockers)
        )


def _invoke_hourly_rolling_after_day_ahead(
    args: argparse.Namespace,
    day_ahead_output_dir: Path,
) -> int:
    """Launch the mandatory formal rolling chain after a feasible day-ahead run.

    The formal profile enables this path by default. Only
    ``--day-ahead-only-exploratory`` may disable it, and that path is blocked
    from research submission. The chain runs in-process so it inherits the
    same source provenance as the day-ahead solve.
    """

    from scripts.run_hourly_charging_reoptimization import (
        RollingChainRequest,
        run_rolling_chain,
    )

    if not bool(getattr(args, "run_hourly_rolling", False)):
        raise ValueError(
            "Formal execution requires hourly rolling; use only "
            "--day-ahead-only-exploratory to produce a blocked diagnostic run"
        )
    rolling_current_time = getattr(args, "rolling_current_time", None) or None
    rolling_end_time = getattr(args, "rolling_end_time", None) or None
    execution_minutes = int(getattr(args, "rolling_execution_minutes", 60) or 60)
    if execution_minutes <= 0:
        raise ValueError("--rolling-execution-minutes must be positive")
    rolling_output_dir = day_ahead_output_dir / "rolling_hourly_chain"
    rolling_request = RollingChainRequest(
        scenario_id=args.scenario_id,
        prepared_input_id=args.prepared_input_id,
        expected_service_date=args.expected_service_date,
        day_ahead_result_path=str(day_ahead_output_dir / "solver_result.json"),
        output_dir=str(rolling_output_dir),
        current_time=rolling_current_time,
        end_time=rolling_end_time,
        full_chain=True,
        execution_minutes=execution_minutes,
        time_limit_sec=int(getattr(args, "rolling_time_limit_sec", 30) or 30),
        mip_gap=float(getattr(args, "rolling_mip_gap", 0.1) or 0.1),
        random_seed=int(getattr(args, "rolling_random_seed", args.random_seed) or args.random_seed),
        gurobi_threads=getattr(args, "gurobi_threads", None),
        depot_id=args.depot_id,
        service_id=args.service_id,
        state_json=None,
        pv_forecast_updates_json=getattr(args, "rolling_pv_forecast_updates_json", None),
        bess_terminal_policy=str(
            getattr(args, "rolling_bess_terminal_policy", "scenario") or "scenario"
        ),
        bess_terminal_min_kwh=getattr(args, "rolling_bess_terminal_min_kwh", None),
    )
    return run_rolling_chain(rolling_request, args=args)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-name", required=True)
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--prepared-input-id", required=True)
    parser.add_argument("--expected-service-date", required=True)
    parser.add_argument(
        "--assert-bev-count",
        type=int,
        default=None,
        help=(
            "Optional assertion against the scenario-derived active BEV count. "
            "This never defines or changes the fleet."
        ),
    )
    parser.add_argument(
        "--assert-ice-count",
        type=int,
        default=None,
        help=(
            "Optional assertion against the scenario-derived active ICE count. "
            "This never defines or changes the fleet."
        ),
    )
    parser.add_argument("--assert-trip-count", type=int, default=None)
    parser.add_argument("--assert-timestep-min", type=int, default=None)
    parser.add_argument("--assert-price-slot-count", type=int, default=None)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--depot-id", required=True)
    parser.add_argument("--service-id", required=True)
    parser.add_argument(
        "--comparison-design",
        choices=("same_service_date_pv_counterfactual",),
        default="same_service_date_pv_counterfactual",
        help=(
            "Hold service date, timetable, fleet, and initial SOC fixed; "
            "only an explicitly labelled PV curve may differ across the pair."
        ),
    )
    parser.add_argument(
        "--comparison-role",
        choices=("baseline", "pv_curve_counterfactual"),
        default="baseline",
        help=(
            "baseline uses the scenario's service-date PV curve. "
            "pv_curve_counterfactual substitutes only the curve source."
        ),
    )
    parser.add_argument(
        "--counterfactual-pv-curve-file",
        default=None,
        help=(
            "Required only for pv_curve_counterfactual. The source is hashed "
            "and recorded as a counterfactual curve, never as a forecast for "
            "the base service date."
        ),
    )
    parser.add_argument("--time-limit-sec", type=int, default=1500)
    parser.add_argument(
        "--stage1-strategy",
        choices=("full_network_milp", "fast_fixed_path"),
        default=DEFAULT_STAGE1_STRATEGY,
        help=(
            "full_network_milp preserves the formal Stage 1 solve. "
            "fast_fixed_path keeps the canonical timetable path cover, uses a "
            "cost-aware diagnostic heuristic vehicle mapping, and validates "
            "charging/SOC exactly; it is not a formal assignment optimum."
        ),
    )
    parser.add_argument(
        "--fast-assignment-time-limit-sec",
        type=int,
        default=30,
        help="Total wall-clock budget for fast fixed-path mix candidates.",
    )
    parser.add_argument(
        "--fast-stage2-case-time-limit-sec",
        type=int,
        default=5,
        help="Exact fixed-assignment charging/SOC MILP budget per mix candidate.",
    )
    parser.add_argument(
        "--stage1-time-limit-sec",
        type=int,
        default=None,
        help="Optional assignment-stage limit; default preserves the historical half split.",
    )
    parser.add_argument(
        "--stage2-time-limit-sec",
        type=int,
        default=None,
        help="Optional fixed-assignment charging-stage limit.",
    )
    parser.add_argument(
        "--stage1-best-obj-stop",
        dest="stage1_best_obj_stop_enabled",
        action="store_true",
        default=True,
        help=(
            "Enable Stage 1's analytical-lower-bound BestObjStop rule. This "
            "is the planning default but must be disabled for wall-clock "
            "comparisons."
        ),
    )
    parser.add_argument(
        "--no-stage1-best-obj-stop",
        dest="stage1_best_obj_stop_enabled",
        action="store_false",
        help=(
            "Disable Stage 1 BestObjStop. Use this for like-for-like runtime "
            "experiments, with the same seed, threads, and time limits."
        ),
    )
    parser.add_argument(
        "--gurobi-threads",
        type=int,
        default=None,
        help=(
            "Optional explicit Gurobi thread count. Runtime comparisons should "
            "set the same positive value in every repetition."
        ),
    )
    parser.add_argument(
        "--stage1-candidate-time-limit-sec",
        type=int,
        default=0,
        help=(
            "Optional time for a restricted-arc weather-specific primal heuristic. "
            "The formal default is 0 (disabled): measured full-network runs were "
            "faster and found a better sunny incumbent without it. Enabling this "
            "never restricts the final Stage 1 candidate network."
        ),
    )
    parser.add_argument(
        "--stage1-candidate-successors",
        type=int,
        default=8,
        help="Successor cap used only while generating the primal warm start.",
    )
    parser.add_argument(
        "--mip-gap",
        type=float,
        default=DEFAULT_FORMAL_MIP_GAP,
        help=(
            "Certified relative MIP-gap target. The formal default is 0.05; "
            "use an explicit value when reproducing older 0.10 runs."
        ),
    )
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument(
        "--time-step-min",
        type=int,
        choices=(5, 15, 30, 60),
        default=15,
        help=(
            "Canonical research discretization. Current formal experiment "
            "specs should assert 15 minutes; other values are explicit "
            "diagnostic/sensitivity settings."
        ),
    )
    parser.add_argument(
        "--bev-terminal-soc-policy",
        choices=(
            BevTerminalSocPolicy.RETURN_TO_INITIAL.value,
            BevTerminalSocPolicy.MINIMUM_ONLY.value,
        ),
        default=BevTerminalSocPolicy.RETURN_TO_INITIAL.value,
        help=(
            "End-of-day BEV energy rule. return_to_initial is required for "
            "fair cost comparison; minimum_only is diagnostic only."
        ),
    )
    parser.add_argument(
        "--bev-terminal-soc-equality-tolerance-kwh",
        type=float,
        default=1.0e-6,
        help="Absolute numerical tolerance for return_to_initial equality.",
    )
    parser.add_argument(
        "--available-bev-count",
        type=int,
        default=None,
        help=(
            "Exploratory-only in-memory BEV readiness sensitivity. It requires "
            "--day-ahead-only-exploratory because a formal run may not select "
            "a subset outside the prepared fleet contract."
        ),
    )
    parser.add_argument(
        "--minimum-used-bev-count",
        type=int,
        default=0,
        help=(
            "Explicit policy-sensitivity lower bound on BEVs assigned at least "
            "one trip. The formal cost-minimizing baseline is 0; never derive "
            "this value from a global fleet constant."
        ),
    )
    parser.add_argument(
        "--require-all-available-bevs",
        action="store_true",
        default=False,
        help=(
            "Policy sensitivity: set the minimum used BEV count to the exact "
            "active BEV count in the scenario fleet contract."
        ),
    )
    parser.add_argument(
        "--vehicle-usage-cost-jpy-per-used-bus",
        type=float,
        default=None,
        help=(
            "Optional in-memory vehicle-day cost sensitivity. It does not "
            "modify the persisted scenario."
        ),
    )
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument(
        "--allow-fixed-weekday-timetable-pv-counterfactual",
        action="store_true",
        default=False,
        help=(
            "Explicitly waive the calendar gate: hold the weekday timetable "
            "fixed on a Sunday PV-only counterfactual. Results are labelled "
            "fixed_weekday_timetable_pv_counterfactual and are never called "
            "actual Sunday operation or Sunday timetable."
        ),
    )
    parser.add_argument(
        "--day-ahead-only-exploratory",
        action="store_true",
        default=False,
        help=(
            "Explicitly stop after day-ahead for diagnostics. This mode writes "
            "teacher_release_status=BLOCKED and returns a non-completion exit "
            "code; formal runs execute the full rolling chain by default."
        ),
    )
    parser.add_argument(
        "--rolling-current-time",
        default=None,
        help=(
            "Optional HH:MM start. Formal full chains default to, and require, "
            "the day-ahead effective energy-horizon start."
        ),
    )
    parser.add_argument(
        "--rolling-end-time",
        default=None,
        help=(
            "Optional HH:MM end. Formal full chains default to, and require, "
            "the day-ahead effective energy-horizon end."
        ),
    )
    parser.add_argument(
        "--rolling-execution-minutes",
        type=int,
        default=60,
        help="Execution window length per rolling step. Must be a positive multiple of timestep_min.",
    )
    parser.add_argument(
        "--rolling-time-limit-sec",
        type=int,
        default=30,
        help="Per-step Gurobi time limit for the rolling charging re-optimization.",
    )
    parser.add_argument(
        "--rolling-mip-gap",
        type=float,
        default=0.1,
        help="Per-step certified MIP gap target for the rolling solve.",
    )
    parser.add_argument(
        "--rolling-random-seed",
        type=int,
        default=None,
        help=(
            "Random seed for the rolling solve. Defaults to the day-ahead "
            "--random-seed so the pair stays reproducible from one declared "
            "seed."
        ),
    )
    parser.add_argument(
        "--rolling-pv-forecast-updates-json",
        default=None,
        help=(
            "Optional JSON object keyed by HH:MM supplying per-step full-"
            "horizon PV forecasts for rolling forecast-error experiments."
        ),
    )
    parser.add_argument(
        "--rolling-bess-terminal-policy",
        choices=("scenario", "minimum_only"),
        default="scenario",
        help="BESS terminal SOC policy for the rolling solve.",
    )
    parser.add_argument(
        "--rolling-bess-terminal-min-kwh",
        type=float,
        default=None,
        help="Optional override for the rolling BESS terminal SOC floor [kWh].",
    )
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
