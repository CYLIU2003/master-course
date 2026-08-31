"""Compare Phase 3 with a small integrated MILP on the same weather case.

The audit deliberately uses a deterministic, day-spanning trip subset.  It is
not a replacement for the full-day result; it is a tractable oracle check for
the two-stage decomposition and for 15-minute versus 5-minute discretization.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import math
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
from bff.services.optimization_run.input_provenance import (  # noqa: E402
    _runtime_environment,
    collect_git_state,
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
from src.optimization.common.soc_helpers import (  # noqa: E402
    slot_absolute_min,
    vehicle_capacity_kwh,
    vehicle_initial_soc_kwh,
    vehicle_reserve_soc_kwh,
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

SMALL_ORACLE_SCHEMA_VERSION = "small_oracle_result_v2"
P3_SCALAR_SUPPORT = "P3_SCALAR_UNSUPPORTED"
P3_SCALAR_BLOCKER = (
    "Phase 3 minimizes an assignment-energy proxy and then a fixed-assignment "
    "charging objective; the scalar canonical actual-cost contract is only "
    "reachable through phase4_integrated. Metadata alone cannot align them."
)
_ACCOUNTING_COST_COMPONENT_KEYS = (
    "electricity_cost",
    "fuel_cost",
    "demand_cost",
    "contract_overage_cost",
    "vehicle_cost",
    "vehicle_usage_cost",
    "driver_cost",
    "unserved_penalty",
    "switch_cost",
    "degradation_cost",
    "deviation_cost",
    "co2_cost",
)
_SOC_SCOPE = "used BEV solver trace: all saved slots, including initial slot"
_PHASE3_REFERENCE_SHA = "bb0c0050883a91dd86a9e8813ae88d4b6d8c361d"
_PHASE3_REFERENCE_CONTRACT = {
    "phase": "phase3_two_stage",
    "time_limit_sec": 585,
    "stage1_time_limit_sec": 435,
    "stage2_time_limit_sec": 30,
    "mip_gap": 0.1,
    "random_seed": 42,
    "gurobi_threads": 1,
    "warm_start": True,
    "thesis_mode": True,
    "research_run": True,
    "allow_postsolve_repair": False,
    "integrated_actual_cost_objective": False,
    "objective_preset": "scalar_total_cost_v1",
    "bev_terminal_soc_policy": "return_to_initial",
    "milp_max_successors_per_trip": 0,
    "allow_partial_service": False,
    "fixed_route_band_mode": True,
    "trip_count": 264,
}


def _canonical_sha256(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _p3_scalar_support() -> dict[str, Any]:
    """Declare the audited Phase-3 scalar-objective capability."""

    return {
        "status": P3_SCALAR_SUPPORT,
        "pure_decomposition_gap_available": False,
        "blocker": P3_SCALAR_BLOCKER,
    }


def _cost_accounting_adapter(cost_breakdown: dict[str, Any]) -> dict[str, Any]:
    """Serialize all raw fields and independently reconcile canonical costs."""

    missing = [key for key in _ACCOUNTING_COST_COMPONENT_KEYS if key not in cost_breakdown]
    if missing:
        raise ValueError(f"missing canonical accounting cost components: {missing}")
    if "total_cost" not in cost_breakdown:
        raise ValueError("missing canonical accounting total_cost")
    components = {key: float(cost_breakdown[key]) for key in _ACCOUNTING_COST_COMPONENT_KEYS}
    if not all(math.isfinite(value) for value in components.values()):
        raise ValueError("canonical accounting cost components must be finite")
    component_sum = sum(components.values())
    total = float(cost_breakdown["total_cost"])
    if not math.isfinite(total):
        raise ValueError("canonical accounting total_cost must be finite")
    residual = component_sum - total
    return {
        "cost_breakdown": dict(cost_breakdown),
        "accounting_cost_components_jpy": components,
        "cost_component_sum_jpy": component_sum,
        "accounted_total_cost_jpy": total,
        "cost_reconciliation_residual_jpy": residual,
        "cost_reconciliation_passed": bool(
            math.isfinite(residual) and abs(residual) <= 1.0e-6
        ),
    }


def _format_slot_time(problem: CanonicalOptimizationProblem, slot_index: int) -> str:
    absolute_min = slot_absolute_min(problem, slot_index)
    day_offset, minute_of_day = divmod(absolute_min, 24 * 60)
    hour, minute = divmod(minute_of_day, 60)
    prefix = f"D+{day_offset} " if day_offset else ""
    return f"{prefix}{hour:02d}:{minute:02d}"


def _minimum_used_bev_soc(
    problem: CanonicalOptimizationProblem,
    result: Any,
) -> dict[str, Any]:
    """Find the minimum over every saved used-BEV SOC point and initial state."""

    used_ids = set(result.plan.vehicle_paths())
    candidates: list[dict[str, Any]] = []
    trace_errors: list[str] = []
    for vehicle in problem.vehicles:
        vehicle_id = str(vehicle.vehicle_id)
        if vehicle_id not in used_ids or str(vehicle.vehicle_type).upper() != "BEV":
            continue
        capacity = vehicle_capacity_kwh(problem, vehicle)
        if capacity <= 0.0:
            trace_errors.append(f"{vehicle_id}:missing_positive_capacity")
            continue
        reserve = vehicle_reserve_soc_kwh(problem, vehicle, cap_kwh=capacity)
        points: list[tuple[int, float, str]] = [
            (0, vehicle_initial_soc_kwh(problem, vehicle, cap_kwh=capacity), "initial")
        ]
        solver_trace = dict(
            result.plan.vehicle_soc_kwh_by_vehicle_slot.get(vehicle_id, {})
        )
        if not solver_trace:
            trace_errors.append(f"{vehicle_id}:missing_solver_soc_trace")
        points.extend(
            (int(slot), float(soc), "solver_trace")
            for slot, soc in solver_trace.items()
        )
        for slot, soc, source in points:
            candidates.append(
                {
                    "soc_kwh": soc,
                    "soc_percent": 100.0 * soc / capacity,
                    "margin_kwh": soc - reserve,
                    "margin_percent": 100.0 * (soc - reserve) / capacity,
                    "vehicle_id": vehicle_id,
                    "slot_index": slot,
                    "time": _format_slot_time(problem, slot),
                    "source": source,
                }
            )
    if not candidates:
        return {
            "minimum_recorded_bev_soc_kwh": None,
            "minimum_recorded_bev_soc_percent": None,
            "minimum_recorded_bev_soc_margin_kwh": None,
            "minimum_recorded_bev_soc_margin_percent": None,
            "minimum_soc_vehicle_id": None,
            "minimum_soc_slot_index": None,
            "minimum_soc_time": None,
            "minimum_soc_scope": None,
            "used_bev_soc_trace_complete": not trace_errors,
            "used_bev_soc_trace_errors": trace_errors,
        }
    minimum = min(
        candidates,
        key=lambda row: (row["soc_kwh"], row["vehicle_id"], row["slot_index"], row["source"]),
    )
    return {
        "minimum_recorded_bev_soc_kwh": minimum["soc_kwh"],
        "minimum_recorded_bev_soc_percent": minimum["soc_percent"],
        "minimum_recorded_bev_soc_margin_kwh": minimum["margin_kwh"],
        "minimum_recorded_bev_soc_margin_percent": minimum["margin_percent"],
        "minimum_soc_vehicle_id": minimum["vehicle_id"],
        "minimum_soc_slot_index": minimum["slot_index"],
        "minimum_soc_time": minimum["time"],
        "minimum_soc_scope": _SOC_SCOPE,
        "used_bev_soc_trace_complete": not trace_errors,
        "used_bev_soc_trace_errors": trace_errors,
    }


def _phase3_contract_comparison(
    problem: CanonicalOptimizationProblem,
    config: OptimizationConfig,
) -> dict[str, Any]:
    """Label Phase 3 as deployed only on an exact bb0c005 contract match."""

    actual = {
        "phase": config.phase,
        "time_limit_sec": config.time_limit_sec,
        "stage1_time_limit_sec": config.stage1_time_limit_sec,
        "stage2_time_limit_sec": config.stage2_time_limit_sec,
        "mip_gap": config.mip_gap,
        "random_seed": config.random_seed,
        "gurobi_threads": config.gurobi_threads,
        "warm_start": config.warm_start,
        "thesis_mode": config.thesis_mode,
        "research_run": config.research_run,
        "allow_postsolve_repair": config.allow_postsolve_repair,
        "integrated_actual_cost_objective": config.integrated_actual_cost_objective,
        "objective_preset": problem.metadata.get("objective_preset"),
        "bev_terminal_soc_policy": problem.metadata.get("bev_terminal_soc_policy"),
        "milp_max_successors_per_trip": problem.metadata.get("milp_max_successors_per_trip"),
        "allow_partial_service": problem.metadata.get("allow_partial_service"),
        "fixed_route_band_mode": problem.metadata.get("fixed_route_band_mode"),
        "trip_count": len(problem.trips),
    }
    mismatches = {
        key: {"reference": expected, "actual": actual.get(key)}
        for key, expected in _PHASE3_REFERENCE_CONTRACT.items()
        if actual.get(key) != expected
    }
    return {
        "reference_execution_sha": _PHASE3_REFERENCE_SHA,
        "reference_contract": dict(_PHASE3_REFERENCE_CONTRACT),
        "actual_contract": actual,
        "matched": not mismatches,
        "mismatches": mismatches,
        "formulation_id": (
            "P3_SUBSET_DEPLOYED_POLICY"
            if len(problem.trips) < _PHASE3_REFERENCE_CONTRACT["trip_count"]
            and set(mismatches) == {"trip_count"}
            else "P3_ALIGNED_REFERENCE"
        ),
    }


def _small_oracle_solver_controls(args: argparse.Namespace) -> dict[str, Any]:
    """Return the fully declared controls shared by all audit cases."""

    return {
        "mode": "MILP",
        "mip_gap_ratio": 0.0,
        "random_seed": int(args.random_seed),
        "gurobi_threads": int(args.gurobi_threads),
        "time_limit_sec_per_phase": int(args.time_limit_sec),
        "warm_start": False,
        "allow_postsolve_repair": False,
        "phase4_phase3_seed_enabled": False,
    }


def _small_oracle_reproducibility_snapshot(
    *,
    args: argparse.Namespace,
    prepared_payload: dict[str, Any],
    code_provenance_before: dict[str, Any],
    code_provenance_after: dict[str, Any],
) -> dict[str, Any]:
    """Capture the environment, immutable inputs, and run controls together."""

    solver_controls = _small_oracle_solver_controls(args)
    return {
        "schema_version": "small_integrated_oracle_reproducibility_v1",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_environment": _runtime_environment(),
        "code_provenance_before": code_provenance_before,
        "code_provenance_after": code_provenance_after,
        "code_sha_matches_before_after": (
            code_provenance_before.get("git_sha")
            == code_provenance_after.get("git_sha")
        ),
        "clean_worktree_before": (
            code_provenance_before.get("git_state_available") is True
            and code_provenance_before.get("git_dirty") is False
        ),
        "clean_worktree_after": (
            code_provenance_after.get("git_state_available") is True
            and code_provenance_after.get("git_dirty") is False
        ),
        "prepared_input_sha256": _canonical_sha256(prepared_payload),
        "solver_controls": solver_controls,
        "solver_controls_sha256": _canonical_sha256(solver_controls),
    }


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


def _without_pv_bess_problem(
    problem: CanonicalOptimizationProblem,
) -> CanonicalOptimizationProblem:
    """Return a bounded ablation input with PV and BESS unavailable.

    The helper changes both representations consumed by the solver: the
    depot-level asset configuration and the time-indexed PV supply.  Leaving
    either nonzero would make an ostensibly ``no PV/BESS`` comparison depend
    on a hidden energy source.
    """

    assets = {
        str(depot_id): replace(
            asset,
            pv_enabled=False,
            pv_generation_kwh_by_slot=tuple(
                0.0 for _ in asset.pv_generation_kwh_by_slot
            ),
            available_pv_surplus_kwh_by_slot=tuple(
                0.0 for _ in asset.available_pv_surplus_kwh_by_slot
            ),
            capacity_factor_by_slot=tuple(
                0.0 for _ in asset.capacity_factor_by_slot
            ),
            pv_case_id="small_m0_m3_no_pv",
            pv_capacity_kw=0.0,
            pv_supply_scale=0.0,
            bess_enabled=False,
            bess_energy_kwh=0.0,
            bess_power_kw=0.0,
            bess_initial_soc_kwh=0.0,
            bess_soc_min_kwh=0.0,
            bess_soc_max_kwh=0.0,
            bess_terminal_soc_min_kwh=0.0,
            bess_terminal_soc_target_kwh=0.0,
            allow_pv_to_bess=False,
            allow_grid_to_bess=False,
            allow_bess_to_bus=False,
        )
        for depot_id, asset in problem.depot_energy_assets.items()
    }
    return replace(
        problem,
        depot_energy_assets=assets,
        pv_slots=tuple(
            replace(slot, pv_available_kw=0.0) for slot in problem.pv_slots
        ),
        metadata={
            **dict(problem.metadata or {}),
            "small_m0_m3_pv_bess_contract": "disabled_at_asset_and_slot_layers",
        },
    )


def _all_ice_case_args(args: argparse.Namespace) -> argparse.Namespace:
    """Use an ICE fleet with the mixed conditions' total vehicle count.

    ``vehicles_per_type`` selects that many BEVs and ICE vehicles for the
    mixed conditions.  M0 therefore needs twice that count of ICE vehicles,
    rather than silently cutting the fleet budget in half.
    """

    values = dict(vars(args))
    values["allowed_vehicle_type"] = "ICE"
    values["vehicles_per_type"] = int(args.vehicles_per_type) * 2
    return argparse.Namespace(**values)


def _with_small_m0_m3_method_contract(
    problem: CanonicalOptimizationProblem,
    *,
    method_id: str,
    method_definition: str,
) -> CanonicalOptimizationProblem:
    """Attach claim-scope metadata without changing the mathematical input."""

    return replace(
        problem,
        metadata={
            **dict(problem.metadata or {}),
            "sensitivity_analysis_label": "small_m0_m3",
            "small_m0_m3_method_id": method_id,
            "small_m0_m3_method_definition": method_definition,
            "small_m0_m3_claim_scope": "small_subset_only_not_full_264_trip_evidence",
        },
    )


def _small_m0_m3_solver_input_hash(problem: CanonicalOptimizationProblem) -> str:
    """Hash model-relevant inputs while excluding comparison-only labels."""

    metadata = {
        key: value
        for key, value in dict(problem.metadata or {}).items()
        if not key.startswith("small_m0_m3_")
        and key != "sensitivity_analysis_label"
    }
    payload = {
        "scenario": asdict(problem.scenario),
        "trips": [asdict(trip) for trip in problem.trips],
        "vehicles": [asdict(vehicle) for vehicle in problem.vehicles],
        "vehicle_types": [asdict(vehicle_type) for vehicle_type in problem.vehicle_types],
        "chargers": [asdict(charger) for charger in problem.chargers],
        "price_slots": [asdict(slot) for slot in problem.price_slots],
        "pv_slots": [asdict(slot) for slot in problem.pv_slots],
        "depot_energy_assets": {
            str(depot_id): asdict(asset)
            for depot_id, asset in sorted(problem.depot_energy_assets.items())
        },
        "feasible_connections": {
            str(trip_id): list(connection_ids)
            for trip_id, connection_ids in sorted(problem.feasible_connections.items())
        },
        "objective_weights": asdict(problem.objective_weights),
        "metadata": metadata,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _input_vehicle_count_by_type(
    problem: CanonicalOptimizationProblem,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for vehicle in problem.vehicles:
        vehicle_type = str(vehicle.vehicle_type).upper()
        counts[vehicle_type] = counts.get(vehicle_type, 0) + 1
    return dict(sorted(counts.items()))


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


def _integrated_actual_cost_oracle_problem(
    problem: CanonicalOptimizationProblem,
) -> CanonicalOptimizationProblem:
    """Remove the production lexicographic policy from the reference MILP.

    Phase 3 retains its deployed policy and is evaluated by final canonical
    accounting.  The Phase-4 reference must instead minimize that scalar
    canonical actual cost directly; otherwise a minimum-vehicle-days policy
    would answer a different research question despite using the same costs.
    """

    metadata = dict(problem.metadata or {})
    original_preset = metadata.get("objective_preset")
    return replace(
        problem,
        metadata={
            **metadata,
            "objective_preset": None,
            "small_integrated_phase4_reference_objective": (
                "scalar_canonical_actual_cost"
            ),
            "small_integrated_original_objective_preset": original_preset,
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
    gurobi_threads: int,
) -> dict[str, Any]:
    is_two_stage = phase == "phase3_two_stage"
    declared_problem_input_hash = _small_m0_m3_solver_input_hash(problem)
    input_pv_available_kw_total = sum(
        float(slot.pv_available_kw or 0.0) for slot in problem.pv_slots
    )
    input_bess_enabled = any(
        bool(asset.bess_enabled) for asset in problem.depot_energy_assets.values()
    )
    if not is_two_stage:
        problem = _integrated_actual_cost_oracle_problem(problem)
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
        gurobi_threads=gurobi_threads,
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
    cost_adapter = _cost_accounting_adapter(cost_breakdown)
    accounted_total_cost_jpy = cost_adapter["accounted_total_cost_jpy"]
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
    phase3_contract = _phase3_contract_comparison(problem, config) if is_two_stage else None
    formulation_id = (
        phase3_contract["formulation_id"]
        if phase3_contract
        else "P4_SCALAR_EXACT_REFERENCE"
    )
    exact_oracle_gate = None
    case = {
        "schema_version": SMALL_ORACLE_SCHEMA_VERSION,
        "formulation_id": formulation_id,
        "phase3_contract_comparison": phase3_contract,
        "objective_semantics": (
            "deployed_phase3_assignment_proxy_then_fixed_charging"
            if is_two_stage
            else "scalar_canonical_actual_cost"
        ),
        "analysis_label": str(
            problem.metadata.get("sensitivity_analysis_label") or "primary"
        ),
        "small_m0_m3_method_id": problem.metadata.get("small_m0_m3_method_id"),
        "small_m0_m3_method_definition": problem.metadata.get(
            "small_m0_m3_method_definition"
        ),
        "small_m0_m3_claim_scope": problem.metadata.get(
            "small_m0_m3_claim_scope"
        ),
        "small_m0_m3_pv_bess_contract": problem.metadata.get(
            "small_m0_m3_pv_bess_contract"
        ),
        "small_m0_m3_fleet_contract": problem.metadata.get(
            "small_m0_m3_fleet_contract"
        ),
        "declared_problem_input_hash": declared_problem_input_hash,
        "input_vehicle_count_by_type": _input_vehicle_count_by_type(problem),
        "input_pv_available_kw_total": input_pv_available_kw_total,
        "input_bess_enabled": input_bess_enabled,
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
        "gurobi_threads": gurobi_threads,
        "solver_status": str(result.solver_status),
        "feasible": bool(result.feasible),
        "warnings": list(result.warnings),
        "infeasibility_reasons": list(result.infeasibility_reasons),
        "elapsed_seconds": elapsed,
        "runtime_seconds": elapsed,
        "trip_count_served": len(result.plan.served_trip_ids),
        "trip_count_unserved": len(result.plan.unserved_trip_ids),
        "used_vehicle_count": len(result.plan.vehicle_paths()),
        **_assignment_mix(problem, result),
        "objective_value": float(result.objective_value),
        **cost_adapter,
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
        "small_integrated_phase4_reference_objective": problem.metadata.get(
            "small_integrated_phase4_reference_objective"
        ),
        "small_integrated_original_objective_preset": problem.metadata.get(
            "small_integrated_original_objective_preset"
        ),
        "used_vehicle_trace": used_vehicle_trace,
        "assignment_rows": assignment_rows,
        "assignment_hash": assignment_hash,
        "assignment_powertrain_hash": assignment_powertrain_hash,
        **_minimum_used_bev_soc(problem, result),
    }
    if not is_two_stage:
        exact_oracle_gate = _is_integrated_exact_oracle_case(case)
    case["exact_oracle_gate"] = exact_oracle_gate
    return case


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
        and case.get("cost_reconciliation_passed")
        and case.get("ev_energy_inventory_balanced")
        and case.get("used_bev_soc_trace_complete")
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
        "comparison_schema_version": "small_oracle_comparison_v2",
        "comparison_name": (
            "phase3_aligned_subset_to_scalar_integrated_reference_distance"
        ),
        "p3_scalar_support": _p3_scalar_support(),
        "integrated_exact_oracle_eligible": exact_oracle,
        "terminal_soc_boundary": "return_to_initial",
        "objective_semantics": "validated_accounting_cost_components_only",
    }
    if integrated is None or two_stage is None:
        comparison["two_stage_comparison_available"] = False
        return comparison

    phase3_blockers: list[str] = []
    if two_stage.get("feasible") is not True:
        phase3_blockers.append("phase3_infeasible")
    if int(two_stage.get("trip_count_unserved") or 0) != 0:
        phase3_blockers.append("phase3_unserved_trips")
    if two_stage.get("cost_reconciliation_passed") is not True:
        phase3_blockers.append("phase3_accounting_reconciliation_failed")
    if two_stage.get("used_bev_soc_trace_complete") is not True:
        phase3_blockers.append("phase3_used_bev_soc_trace_incomplete")
    if phase3_blockers:
        comparison.update(
            {
                "status": "BLOCKED",
                "two_stage_comparison_available": False,
                "blocking_reasons": phase3_blockers,
            }
        )
        return comparison

    component_maps = {
        "phase3": dict(two_stage.get("accounting_cost_components_jpy") or {}),
        "integrated": dict(integrated.get("accounting_cost_components_jpy") or {}),
    }
    missing_components = {
        name: sorted(set(_ACCOUNTING_COST_COMPONENT_KEYS) - set(values))
        for name, values in component_maps.items()
        if set(_ACCOUNTING_COST_COMPONENT_KEYS) - set(values)
    }
    if missing_components:
        comparison.update(
            {
                "status": "BLOCKED",
                "two_stage_comparison_available": False,
                "blocking_reasons": ["missing_canonical_cost_components"],
                "missing_cost_components": missing_components,
            }
        )
        return comparison

    integrated_cost = float(integrated["accounted_total_cost_jpy"])
    two_stage_cost = float(two_stage["accounted_total_cost_jpy"])
    cost_delta = two_stage_cost - integrated_cost
    cost_comparison_tolerance_jpy = 1.0e-5
    cost_delta_within_tolerance = abs(cost_delta) <= cost_comparison_tolerance_jpy
    # A relative gap is undefined when the exact reference cost is numerically
    # zero.  Dividing by an arbitrary JPY floor would turn solver noise into a
    # misleading signed performance claim, so retain the raw delta and mark
    # the relative metric as not identifiable instead.
    relative_identifiable = abs(integrated_cost) > 1.0e-9
    relative_cost_difference_percent = (
        100.0 * cost_delta / abs(integrated_cost)
        if relative_identifiable
        else None
    )
    component_keys = sorted(_ACCOUNTING_COST_COMPONENT_KEYS)
    comparison.update(
        {
            "status": "COMPUTED",
            "two_stage_comparison_available": True,
            "integrated_accounted_total_cost_jpy": integrated_cost,
            "two_stage_accounted_total_cost_jpy": two_stage_cost,
            "two_stage_minus_integrated_cost_jpy": cost_delta,
            "cost_comparison_tolerance_jpy": cost_comparison_tolerance_jpy,
            "two_stage_cost_delta_within_tolerance": cost_delta_within_tolerance,
            "absolute_cost_difference_jpy": abs(cost_delta),
            "relative_cost_difference_percent": relative_cost_difference_percent,
            "relative_cost_difference_status": (
                "computed"
                if relative_identifiable
                else "not_identifiable_zero_reference_cost"
            ),
            "two_stage_matches_integrated_cost": cost_delta_within_tolerance,
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
            "assignment_equal": str(two_stage.get("assignment_hash") or "")
            == str(integrated.get("assignment_hash") or ""),
            "assignment_powertrain_hash_matches": str(
                two_stage.get("assignment_powertrain_hash") or ""
            )
            == str(
                integrated.get("assignment_powertrain_hash") or ""
            ),
            "powertrain_assignment_equal": str(
                two_stage.get("assignment_powertrain_hash") or ""
            )
            == str(integrated.get("assignment_powertrain_hash") or ""),
            "two_stage_assignment_powertrain_hash": two_stage.get(
                "assignment_powertrain_hash"
            ),
            "integrated_assignment_powertrain_hash": integrated.get(
                "assignment_powertrain_hash"
            ),
            "comparison_lower_bound_consistent": (
                cost_delta >= -cost_comparison_tolerance_jpy
            ),
            "used_vehicle_difference": int(two_stage["used_vehicle_count"])
            - int(integrated["used_vehicle_count"]),
            "cost_component_differences": {
                key: float(component_maps["phase3"][key])
                - float(component_maps["integrated"][key])
                for key in component_keys
            },
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


def _small_m0_m3_comparison(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize the bounded M0--M3 study without promoting it to full scale.

    M0/M1 deliberately alter the fleet or energy-asset treatment, whereas
    M2/M3 share the same mixed-fleet, PV/BESS-enabled input.  Consequently,
    only M2--M3 is an algorithmic comparison against the exact integrated
    oracle; the other deltas are descriptive small-scope ablations.
    """

    by_method = {
        str(case.get("small_m0_m3_method_id")): case
        for case in cases
        if case.get("analysis_label") == "small_m0_m3"
        and case.get("small_m0_m3_method_id") in {"M0", "M1", "M2", "M3"}
    }
    expected_methods = ("M0", "M1", "M2", "M3")
    missing_methods = [
        method for method in expected_methods if method not in by_method
    ]
    comparison: dict[str, Any] = {
        "claim_scope": "small_subset_only_not_full_264_trip_evidence",
        "expected_methods": list(expected_methods),
        "missing_methods": missing_methods,
        "all_methods_present": not missing_methods,
        "method_contracts": {
            method: {
                "definition": case.get("small_m0_m3_method_definition"),
                "phase": case.get("phase"),
                "pv_bess_contract": case.get("small_m0_m3_pv_bess_contract"),
                "fleet_contract": case.get("small_m0_m3_fleet_contract"),
            }
            for method, case in by_method.items()
        },
    }
    if missing_methods:
        comparison["comparison_status"] = "BLOCKED_MISSING_METHODS"
        return comparison

    def is_feasible_complete(case: dict[str, Any]) -> bool:
        return bool(case.get("feasible")) and int(
            case.get("trip_count_unserved") or 0
        ) == 0

    m0, m1, m2, m3 = (by_method[method] for method in expected_methods)
    exact_oracle_eligibility = {
        "M0": _is_integrated_exact_oracle_case(m0),
        "M3": _is_integrated_exact_oracle_case(m3),
    }
    method_feasibility = {
        method: is_feasible_complete(by_method[method]) for method in expected_methods
    }
    costs = {
        method: float(by_method[method]["accounted_total_cost_jpy"])
        for method in expected_methods
    }
    comparison.update(
        {
            "method_feasible_and_complete": method_feasibility,
            "exact_oracle_eligibility": exact_oracle_eligibility,
            "accounted_total_cost_jpy": costs,
            "descriptive_cost_deltas_jpy": {
                "M1_minus_M0": costs["M1"] - costs["M0"],
                "M2_minus_M1": costs["M2"] - costs["M1"],
                "M3_minus_M2": costs["M3"] - costs["M2"],
            },
            "m2_m3_same_input_algorithmic_pair": bool(
                m2.get("small_m0_m3_pv_bess_contract") is None
                and m3.get("small_m0_m3_pv_bess_contract") is None
                and m2.get("small_m0_m3_fleet_contract") is None
                and m3.get("small_m0_m3_fleet_contract") is None
                and bool(m2.get("declared_problem_input_hash"))
                and m2.get("declared_problem_input_hash")
                == m3.get("declared_problem_input_hash")
            ),
            "m2_declared_problem_input_hash": m2.get("declared_problem_input_hash"),
            "m3_declared_problem_input_hash": m3.get("declared_problem_input_hash"),
            "m2_minus_m3_cost_jpy": costs["M2"] - costs["M3"],
            "m2_m3_lower_bound_consistent": (
                costs["M2"] - costs["M3"] >= -1.0e-5
            ),
        }
    )
    comparison["comparison_status"] = (
        "PASS_SMALL_SCOPE_ONLY"
        if all(method_feasibility.values())
        and all(exact_oracle_eligibility.values())
        and comparison["m2_m3_same_input_algorithmic_pair"]
        and comparison["m2_m3_lower_bound_consistent"]
        else "BLOCKED_SMALL_SCOPE"
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


def _small_oracle_plan(
    *,
    args: argparse.Namespace,
    problem: CanonicalOptimizationProblem,
    prepared_payload: dict[str, Any],
    code_provenance: dict[str, Any],
) -> dict[str, Any]:
    """Return a complete immutable plan without invoking the solver."""

    vehicle_rows = [
        {
            "vehicle_id": str(vehicle.vehicle_id),
            "vehicle_type": str(vehicle.vehicle_type).upper(),
        }
        for vehicle in problem.vehicles
    ]
    controls = _small_oracle_solver_controls(args)
    plan_core = {
        "scenario_id": args.scenario_id,
        "prepared_input_id": args.prepared_input_id,
        "prepared_input_sha256": _canonical_sha256(prepared_payload),
        "depot_id": args.depot_id,
        "service_id": args.service_id,
        "trip_ids": [str(trip.trip_id) for trip in problem.trips],
        "selected_vehicles": vehicle_rows,
        "formulations": ["P3_ALIGNED_REFERENCE", "P4_SCALAR_EXACT_REFERENCE"],
        "p3_scalar_support": _p3_scalar_support(),
        "solver_controls": controls,
        "expected_output_paths": [str(Path(args.output))],
    }
    return {
        "schema_version": "small_oracle_plan_v1",
        "mode": "PLAN_ONLY_NO_SOLVE",
        "adapter_git_sha": code_provenance.get("git_sha"),
        **plan_core,
        "input_hash": _canonical_sha256(plan_core),
    }


def run(args: argparse.Namespace) -> int:
    output_path = Path(args.output)
    if int(args.gurobi_threads) < 1:
        raise ValueError("--gurobi-threads must be a positive integer")
    code_provenance_before = collect_git_state(repo_root=REPO_ROOT)
    if (
        code_provenance_before.get("git_state_available") is not True
        or code_provenance_before.get("git_dirty") is not False
    ):
        raise RuntimeError(
            "small integrated oracle requires a clean, Git-attested worktree"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    prepared_payload = load_prepared_input(
        scenario_id=args.scenario_id,
        prepared_input_id=args.prepared_input_id,
        scenarios_dir=_prepared_inputs_root(),
    )
    problem_15 = _build_problem(args, 15)
    if args.plan_only:
        payload = _small_oracle_plan(
            args=args,
            problem=problem_15,
            prepared_payload=prepared_payload,
            code_provenance=code_provenance_before,
        )
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
        return 0
    if args.run_small_m0_m3 and args.allowed_vehicle_type != "ALL":
        raise ValueError("--run-small-m0-m3 requires --allowed-vehicle-type ALL")
    problem_5 = (
        None
        if args.skip_five_minute or args.run_small_m0_m3
        else _build_problem(args, 5)
    )
    case_specs: list[tuple[CanonicalOptimizationProblem, str, int, int]] = []
    if args.run_small_m0_m3:
        m0_problem = _with_small_m0_m3_method_contract(
            _without_pv_bess_problem(
                _build_problem(_all_ice_case_args(args), 15)
            ),
            method_id="M0",
            method_definition=(
                "all_ICE_small_exact_cost_baseline_no_PV_or_BESS_"
                "with_mixed_condition_total_fleet_count"
            ),
        )
        m1_problem = _with_small_m0_m3_method_contract(
            _without_pv_bess_problem(problem_15),
            method_id="M1",
            method_definition="mixed_BEV_ICE_phase3_without_PV_or_BESS",
        )
        m2_problem = _with_small_m0_m3_method_contract(
            problem_15,
            method_id="M2",
            method_definition="mixed_BEV_ICE_deployed_phase3_two_stage",
        )
        m3_problem = _with_small_m0_m3_method_contract(
            problem_15,
            method_id="M3",
            method_definition="mixed_BEV_ICE_integrated_scalar_actual_cost_oracle",
        )
        case_specs.extend(
            (
                (m0_problem, "phase4_integrated", args.time_limit_sec, args.random_seed),
                (m1_problem, "phase3_two_stage", args.time_limit_sec, args.random_seed),
                (m2_problem, "phase3_two_stage", args.time_limit_sec, args.random_seed),
                (m3_problem, "phase4_integrated", args.time_limit_sec, args.random_seed),
            )
        )
    else:
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
    if args.run_seed_time_sensitivity and not args.run_small_m0_m3:
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
    if args.run_uncertainty_sensitivity and not args.run_small_m0_m3:
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
                gurobi_threads=args.gurobi_threads,
            )
        )
    primary_comparison = _primary_oracle_comparison(cases)
    small_m0_m3_comparison = _small_m0_m3_comparison(cases)
    five_minute_comparison = _five_minute_sensitivity_comparison(cases)
    seed_time_summary = _sensitivity_summary(
        cases,
        analysis_label="small_phase3_seed_time",
    )
    uncertainty_summary = _sensitivity_summary(
        cases,
        analysis_label="small_phase3_pv_consumption",
    )
    code_provenance_after = collect_git_state(repo_root=REPO_ROOT)
    payload = {
        "schema_version": SMALL_ORACLE_SCHEMA_VERSION,
        "p3_scalar_support": _p3_scalar_support(),
        "purpose": (
            "small_m0_m3_method_comparison"
            if args.run_small_m0_m3
            else "small_integrated_oracle_and_five_minute_sensitivity"
        ),
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
        "reproducibility": _small_oracle_reproducibility_snapshot(
            args=args,
            prepared_payload=prepared_payload,
            code_provenance_before=code_provenance_before,
            code_provenance_after=code_provenance_after,
        ),
        "primary_comparison": primary_comparison,
        "small_m0_m3_comparison": small_m0_m3_comparison,
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
    if args.run_small_m0_m3:
        return (
            0
            if small_m0_m3_comparison["comparison_status"]
            == "PASS_SMALL_SCOPE_ONLY"
            else 3
        )
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
    parser.add_argument(
        "--gurobi-threads",
        type=int,
        default=4,
        help="Explicit Gurobi thread count; never rely on the solver default.",
    )
    parser.add_argument("--integrated-only", action="store_true")
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Materialize and hash the small input plan, but never call solve.",
    )
    parser.add_argument("--skip-five-minute", action="store_true")
    parser.add_argument("--run-seed-time-sensitivity", action="store_true")
    parser.add_argument("--run-uncertainty-sensitivity", action="store_true")
    parser.add_argument(
        "--run-small-m0-m3",
        action="store_true",
        help=(
            "Run the bounded M0--M3 comparison only: M0 all-ICE exact baseline, "
            "M1 mixed Phase 3 without PV/BESS, M2 deployed Phase 3, and M3 "
            "integrated scalar-actual-cost oracle. This is never full-day evidence."
        ),
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(run(build_parser().parse_args()))
