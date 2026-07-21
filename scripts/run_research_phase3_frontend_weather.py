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
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import time
from typing import Any


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
from src.optimization.common.bev_terminal_policy import (
    BevTerminalSocPolicy,
    normalize_bev_terminal_soc_policy,
)
from src.optimization.common.research_phase3_policy import (
    enforce_research_phase3_single_continuous_duty,
)
from src.optimization.common.fast_cost_assignment import (
    build_fast_cost_aware_assignment,
)
from src.optimization.common.soc_helpers import is_electric_vehicle
from src.preprocess.weather.operation_policy import apply_weather_policy_to_problem


DEFAULT_STAGE1_STRATEGY = "full_network_milp"
DEFAULT_FORMAL_MIP_GAP = 0.05


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


def _configure_research_discretization(
    scenario: dict[str, Any],
    *,
    timestep_min: int,
) -> dict[str, int | bool]:
    """Apply the formal weather-comparison resolution without persisting it."""

    if int(timestep_min) != 15:
        raise ValueError("Formal frontend weather comparison requires 15-minute slots")
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
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True
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
) -> None:
    if len(problem.trips) != 264:
        raise ValueError(f"Expected the 264-trip research scope, got {len(problem.trips)}")
    service_date = str(problem.metadata.get("service_date") or "")[:10]
    if service_date != expected_service_date:
        raise ValueError(
            f"Expected service date {expected_service_date}, got {service_date or 'missing'}"
        )
    fleet = {
        vehicle_type: sum(
            1
            for vehicle in problem.vehicles
            if str(vehicle.vehicle_type).upper() == vehicle_type
        )
        for vehicle_type in ("BEV", "ICE")
    }
    if fleet != {"BEV": 35, "ICE": 25}:
        raise ValueError(f"Expected BEV35 + ICE25, got {fleet}")
    if int(problem.scenario.timestep_min) != 15 or len(problem.price_slots) != 96:
        raise ValueError(
            "Formal frontend weather comparison requires 15-minute, 96-slot input"
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


def run(args: argparse.Namespace) -> int:
    stage1_strategy = str(
        getattr(args, "stage1_strategy", DEFAULT_STAGE1_STRATEGY)
        or DEFAULT_STAGE1_STRATEGY
    ).strip()
    if stage1_strategy not in {
        "full_network_milp",
        "fast_fixed_path",
    }:
        raise ValueError(f"Unsupported stage1_strategy: {stage1_strategy}")
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
    discretization = _configure_research_discretization(
        scenario,
        timestep_min=int(args.time_step_min),
    )
    bev_availability_sensitivity = _apply_bev_availability_sensitivity(
        scenario,
        args.available_bev_count,
    )
    scenario, weather_forecast, weather_profile = _prepare_weather_policy_for_scenario(
        scenario,
        enable_weather_operation_policy=None,
        weather_proxy_forecast_path=None,
    )
    bev_terminal_soc_policy = normalize_bev_terminal_soc_policy(
        getattr(args, "bev_terminal_soc_policy", "return_to_initial")
    )
    simulation_config = dict(scenario.get("simulation_config") or {})
    simulation_config["bev_terminal_soc_policy"] = bev_terminal_soc_policy.value
    scenario["simulation_config"] = simulation_config
    fragment_policy = enforce_research_phase3_single_continuous_duty(scenario)
    initial_soc_policy = _resolve_initial_soc_policy(scenario)
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        time_limit_sec=int(args.time_limit_sec),
        stage1_time_limit_sec=args.stage1_time_limit_sec,
        stage2_time_limit_sec=args.stage2_time_limit_sec,
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
    if weather_forecast is not None and weather_profile is not None:
        problem = apply_weather_policy_to_problem(
            problem,
            weather_forecast,
            weather_profile,
            random_seed=int(args.random_seed),
        )
    initial_soc_metadata = initial_soc_input_metadata(
        problem,
        policy=initial_soc_policy,
    )
    if len(initial_soc_metadata["initial_soc_by_vehicle"]) != 35:
        raise ValueError(
            "Frontend weather comparison requires exact initial SOC inputs for 35 BEVs"
        )
    trip_distance_audit = _trip_distance_audit(problem, prepared_payload)
    _validate_frontend_case(
        problem,
        scenario,
        expected_service_date=args.expected_service_date,
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
            "research_fragment_policy": fragment_policy,
            "bev_availability_sensitivity": bev_availability_sensitivity,
            "phase": executed_phase,
            "stage1_strategy": stage1_strategy,
            "fast_assignment_time_limit_sec": fast_assignment_time_limit_sec,
            "fast_stage2_case_time_limit_sec": fast_stage2_case_time_limit_sec,
            "research_run": True,
            "time_limit_sec": int(args.time_limit_sec),
            "stage1_time_limit_sec": args.stage1_time_limit_sec,
            "stage2_time_limit_sec": args.stage2_time_limit_sec,
            "mip_gap": float(args.mip_gap),
            "random_seed": int(args.random_seed),
            "git_sha": git_state["git_sha"],
        }
    )
    input_audit = {
        "effective_scenario_artifact": "effective_scenario.json",
        "effective_scenario_sha256": _canonical_hash(scenario),
        "input_fingerprint_schema": INPUT_FINGERPRINT_SCHEMA,
        "case_name": args.case_name,
        "scenario_id": args.scenario_id,
        "prepared_input_id": args.prepared_input_id,
        "prepared_input_sha256": _sha256(prepared_path),
        "service_date": str(problem.metadata.get("service_date") or "")[:10],
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
        "mip_gap": float(args.mip_gap),
        "random_seed": int(args.random_seed),
        "postsolve_repair_enabled": False,
        "vehicle_soc_semantics": "slot_start",
        "weather_operation_policy_enabled": True,
        "weather_configuration": weather_configuration,
        "weather_operation_profile": weather_operation_profile,
        "trip_count": len(problem.trips),
        "fleet": {
            "BEV": sum(1 for item in problem.vehicles if str(item.vehicle_type).upper() == "BEV"),
            "ICE": sum(1 for item in problem.vehicles if str(item.vehicle_type).upper() == "ICE"),
        },
        "fleet_available": {
            vehicle_type: sum(
                1
                for item in problem.vehicles
                if str(item.vehicle_type).upper() == vehicle_type
                and bool(item.available)
            )
            for vehicle_type in ("BEV", "ICE")
        },
        "bev_availability_sensitivity": bev_availability_sensitivity,
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
        **git_state,
    }
    _write_json(output_dir / "effective_scenario.json", scenario)
    _write_json(output_dir / "input_audit.json", input_audit)
    if args.build_only:
        print(json.dumps(input_audit, ensure_ascii=False, indent=2), flush=True)
        return 0
    if not is_gurobi_available():
        raise RuntimeError("Gurobi is unavailable; no fallback is permitted for this research run")
    if isinstance(problem.metadata, dict):
        problem.metadata["phase3_diagnostics_dir"] = str(output_dir / "diagnostics")
        problem.metadata["vehicle_soc_semantics"] = "slot_start"
        problem.metadata["frontend_weather_cost_experiment"] = True
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
        "stage1_analytical_objective_lower_bound": _finite(
            metadata.get("stage1_analytical_objective_lower_bound")
        ),
        "stage1_analytical_objective_lower_bound_semantics": metadata.get(
            "stage1_analytical_objective_lower_bound_semantics"
        ),
        "stage1_certified_gap_stop_threshold": _finite(
            metadata.get("stage1_certified_gap_stop_threshold")
        ),
        "stage1_certified_gap_stop_triggered": bool(
            metadata.get("stage1_certified_gap_stop_triggered", False)
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
    }
    print("[5/5] Writing reproducibility artifacts", flush=True)
    _write_json(output_dir / "solver_result.json", ResultSerializer.serialize_result(result))
    _write_json(output_dir / "summary.json", summary)
    if result.feasible:
        _write_vehicle_schedule(output_dir / "vehicle_schedule.csv", result)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str), flush=True)
    return 0 if result.feasible else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-name", required=True)
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument("--prepared-input-id", required=True)
    parser.add_argument("--expected-service-date", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--depot-id", default="tsurumaki")
    parser.add_argument("--service-id", default="WEEKDAY")
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
        choices=(15,),
        default=15,
        help="Formal weather comparison is fixed to 15-minute slots.",
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
        "--available-bev-count",
        type=int,
        default=None,
        help=(
            "Optional in-memory BEV readiness sensitivity. Keeps the N BEVs "
            "with highest persisted initial SOC available; never modifies the "
            "persisted scenario."
        ),
    )
    parser.add_argument("--build-only", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
