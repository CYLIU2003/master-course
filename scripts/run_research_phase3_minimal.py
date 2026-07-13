"""Run the strict, grid-only Phase 3 thesis experiment.

This script deliberately materializes the prepared scope in memory and never
updates the scenario store.  It is the reproducible first experiment in the
research sequence: fixed timetable scope, BEV/ICE fleet assignment in Stage 1,
then grid-only charging/SOC feasibility in Stage 2.  PV, BESS, and weather
operation policy are disabled explicitly; they are separate later experiments.
"""

from __future__ import annotations

import argparse
import csv
from copy import deepcopy
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

from bff.routers.optimization import _prepared_inputs_root
from bff.services.run_preparation import (
    load_prepared_input,
    materialize_scenario_from_prepared_input,
)
from bff.store import scenario_store as store
from src.gurobi_runtime import is_gurobi_available
from src.optimization import (
    OptimizationConfig,
    OptimizationEngine,
    OptimizationMode,
    ProblemBuilder,
    ResultSerializer,
)
from src.optimization.common.initial_soc_policy import (
    InitialSocPolicy,
    apply_initial_soc_policy_to_scenario,
    initial_soc_input_metadata,
    normalize_initial_soc_policy,
)


DEFAULT_SCENARIO_ID = "b23fd26c-1233-4c73-bb9e-bdb8b1584760"
DEFAULT_PREPARED_INPUT_ID = "prepared-789ce8197d83c758-0b337aa1f091e729"
EXPECTED_ROUTE_CODES = {"渋21", "渋22", "渋23"}


def _git_state() -> tuple[str, bool]:
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True
        ).strip()
    )
    return sha, dirty


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_payload_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finite_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _mip_gap_percent(gap_ratio: Any) -> float | None:
    finite_gap = _finite_float_or_none(gap_ratio)
    if finite_gap is None:
        return None
    return finite_gap * 100.0


def _build_experiment_identity(
    problem: Any,
    scenario: dict[str, Any],
    *,
    initial_soc_policy: InitialSocPolicy,
    initial_soc_input_hash: str,
    time_limit_sec: int,
    mip_gap: float,
    random_seed: int,
    git_sha: str,
) -> dict[str, Any]:
    """Hash every controlled input that changes the experiment's meaning."""
    trip_inputs = [
        {
            "trip_id": str(trip.trip_id),
            "route_id": str(trip.route_id),
            "route_family_code": str(trip.route_family_code),
            "direction": str(trip.direction),
            "departure_min": int(trip.departure_min),
            "arrival_min": int(trip.arrival_min),
            "distance_km": float(trip.distance_km),
            "energy_kwh": float(trip.energy_kwh),
            "fuel_l": float(trip.fuel_l),
            "allowed_vehicle_types": list(trip.allowed_vehicle_types),
        }
        for trip in sorted(problem.trips, key=lambda item: str(item.trip_id))
    ]
    vehicle_inputs = [
        {
            "vehicle_id": str(vehicle.vehicle_id),
            "vehicle_type": str(vehicle.vehicle_type),
            "home_depot_id": str(vehicle.home_depot_id),
            "available": bool(vehicle.available),
            "initial_soc": vehicle.initial_soc,
            "battery_capacity_kwh": vehicle.battery_capacity_kwh,
            "reserve_soc": vehicle.reserve_soc,
            "energy_consumption_kwh_per_km": vehicle.energy_consumption_kwh_per_km,
            "fuel_consumption_l_per_km": vehicle.fuel_consumption_l_per_km,
        }
        for vehicle in sorted(problem.vehicles, key=lambda item: str(item.vehicle_id))
    ]
    charger_inputs = [
        {
            "charger_id": str(charger.charger_id),
            "depot_id": str(charger.depot_id),
            "power_kw": float(charger.power_kw),
            "simultaneous_ports": int(charger.simultaneous_ports),
            "bidirectional": bool(charger.bidirectional),
        }
        for charger in sorted(problem.chargers, key=lambda item: str(item.charger_id))
    ]
    energy_assets = [
        {
            "depot_id": str(depot_id),
            "pv_enabled": bool(asset.pv_enabled),
            "pv_case_id": str(asset.pv_case_id),
            "pv_capacity_kw": float(asset.pv_capacity_kw),
            "pv_generation_hash": _canonical_payload_hash(
                list(asset.pv_generation_kwh_by_slot)
            ),
            "bess_enabled": bool(asset.bess_enabled),
            "bess_energy_kwh": float(asset.bess_energy_kwh),
            "bess_power_kw": float(asset.bess_power_kw),
            "bess_initial_soc_kwh": float(asset.bess_initial_soc_kwh),
        }
        for depot_id, asset in sorted(problem.depot_energy_assets.items())
    ]
    simulation_config = dict(scenario.get("simulation_config") or {})
    fingerprint_payload = {
        "service_date": str(problem.metadata.get("service_date") or ""),
        "route_ids": sorted({str(trip.route_id) for trip in problem.trips}),
        "trip_input_hash": _canonical_payload_hash(trip_inputs),
        "vehicle_input_hash": _canonical_payload_hash(vehicle_inputs),
        "initial_soc_policy": initial_soc_policy.value,
        "initial_soc_input_hash": str(initial_soc_input_hash),
        "charger_configuration_hash": _canonical_payload_hash(charger_inputs),
        "time_step_min": int(problem.scenario.timestep_min),
        "pv_configuration": energy_assets,
        "bess_configuration": energy_assets,
        "weather_configuration": {
            "enabled": bool(
                simulation_config.get("enable_weather_operation_policy", False)
            ),
            "mode": simulation_config.get("weather_mode"),
            "forecast_path": simulation_config.get("weather_proxy_forecast_path"),
        },
        "phase": "phase3_two_stage",
        "research_run": True,
        "time_limit_sec": int(time_limit_sec),
        "mip_gap_ratio": float(mip_gap),
        "random_seed": int(random_seed),
        "git_sha": str(git_sha),
    }
    return {
        **fingerprint_payload,
        "experiment_hash": _canonical_payload_hash(fingerprint_payload),
    }


def _disable_depot_assets(scenario: dict[str, Any]) -> None:
    simulation_config = scenario.setdefault("simulation_config", {})
    assets: list[dict[str, Any]] = []
    for raw_asset in list(simulation_config.get("depot_energy_assets") or []):
        asset = dict(raw_asset)
        asset.update(
            {
                "pv_enabled": False,
                "pv_generation_kwh_by_slot": [],
                "capacity_factor_by_slot": [],
                "pv_capacity_kw": 0.0,
                "bess_enabled": False,
                "bess_energy_kwh": 0.0,
                "bess_power_kw": 0.0,
                "bess_initial_soc_kwh": 0.0,
                "bess_soc_min_kwh": 0.0,
                "bess_soc_max_kwh": 0.0,
            }
        )
        assets.append(asset)
    simulation_config["depot_energy_assets"] = assets
    simulation_config["enable_weather_operation_policy"] = False
    simulation_config["weather_proxy_forecast_path"] = None
    simulation_config["weather_mode"] = "none"

    overlay = scenario.setdefault("scenario_overlay", {})
    overlay["depot_energy_assets"] = {
        str(asset["depot_id"]): dict(asset) for asset in assets
    }
    coefficients = dict(overlay.get("cost_coefficients") or {})
    coefficients.update({"pv_enabled": False, "pv_profile_id": None})
    overlay["cost_coefficients"] = coefficients


def _configure_controlled_model_validation_case(
    scenario: dict[str, Any],
    *,
    time_step_min: int,
    initial_soc_policy: InitialSocPolicy,
    initial_soc_percent: float | None,
) -> dict[str, Any]:
    """Build the disclosed grid-only validation input without changing the store."""
    if int(time_step_min) != 15:
        raise ValueError("The controlled Phase 3 validation case requires time_step_min=15")
    configured = apply_initial_soc_policy_to_scenario(
        scenario,
        policy=initial_soc_policy,
        uniform_percent=initial_soc_percent,
    )
    simulation_config = configured.setdefault("simulation_config", {})
    simulation_config.update(
        {
            "time_step_min": 15,
            "timestep_min": 15,
            "planning_days": 1,
            "start_time": "05:00",
            "end_time": "05:00",
            "planning_horizon_hours": 24.0,
            # This is a single-day physical-feasibility validation, not an
            # overnight continuity claim.  Preserve the normal target for a
            # subsequent sensitivity run rather than silently weakening it.
            "final_soc_floor_percent": None,
            "final_soc_target_percent": None,
            "final_soc_target_tolerance_percent": None,
            "experiment_case_tag": "CONTROLLED_MODEL_VALIDATION_CASE",
            "terminal_soc_policy": "minimum_soc",
        }
    )
    _disable_depot_assets(configured)
    return configured


def _validate_target_input(
    problem: Any,
    scenario: dict[str, Any],
    config: OptimizationConfig,
) -> None:
    if len(problem.trips) != 264:
        raise ValueError(f"target scope must contain 264 trips, got {len(problem.trips)}")
    counts = {
        vehicle_type: sum(
            1
            for vehicle in problem.vehicles
            if str(vehicle.vehicle_type).upper() == vehicle_type
        )
        for vehicle_type in ("BEV", "ICE")
    }
    available_counts = {
        vehicle_type: sum(
            1
            for vehicle in problem.vehicles
            if bool(getattr(vehicle, "available", True))
            and str(vehicle.vehicle_type).upper() == vehicle_type
        )
        for vehicle_type in ("BEV", "ICE")
    }
    if counts != {"BEV": 35, "ICE": 25}:
        raise ValueError(f"target fleet must be BEV35+ICE25, got {counts}")
    if available_counts != counts:
        raise ValueError(
            f"target available fleet must equal BEV35+ICE25, got {available_counts}"
        )
    service_date = str(problem.metadata.get("service_date") or "")[:10]
    if service_date != "2025-08-10":
        raise ValueError(f"target service_date must be 2025-08-10, got {service_date!r}")
    operator_ids = {
        str(getattr(trip, "operator_id", "") or "").strip()
        for trip in tuple(problem.dispatch_context.trips or ())
    }
    if not operator_ids or "" in operator_ids or "UNKNOWN_OPERATOR" in operator_ids:
        raise ValueError(f"operator_id is missing/unknown: {sorted(operator_ids)}")
    route_codes = {
        str(getattr(trip, "route_family_code", "") or "").strip()
        for trip in problem.trips
    }
    if not route_codes.issubset(EXPECTED_ROUTE_CODES):
        raise ValueError(f"target scope contains unexpected route codes: {sorted(route_codes)}")
    for depot_id, asset in problem.depot_energy_assets.items():
        if bool(asset.pv_enabled) or bool(asset.bess_enabled):
            raise ValueError(f"PV/BESS must be disabled for grid-only run at {depot_id}")
    if int(problem.scenario.timestep_min) != 15:
        raise ValueError(f"controlled run must use 15-minute slots, got {problem.scenario.timestep_min}")
    if len(problem.price_slots) != 96:
        raise ValueError(f"controlled one-day run must contain 96 slots, got {len(problem.price_slots)}")
    simulation_config = dict(scenario.get("simulation_config") or {})
    if bool(simulation_config.get("enable_weather_operation_policy", False)):
        raise ValueError("weather operation policy must be disabled")
    if simulation_config.get("experiment_case_tag") != "CONTROLLED_MODEL_VALIDATION_CASE":
        raise ValueError("missing CONTROLLED_MODEL_VALIDATION_CASE tag")
    if simulation_config.get("terminal_soc_policy") != "minimum_soc":
        raise ValueError("controlled run must disclose terminal_soc_policy=minimum_soc")
    if (problem.metadata or {}).get("final_soc_floor_percent") is not None:
        raise ValueError("controlled run must not inherit a configured final SOC floor")
    if (problem.metadata or {}).get("final_soc_target_percent") is not None:
        raise ValueError("controlled run must not inherit a configured final SOC target")
    if not bool(config.research_run):
        raise ValueError("controlled run must set research_run=true")
    if str(config.phase) != "phase3_two_stage":
        raise ValueError(f"controlled run must execute phase3_two_stage, got {config.phase!r}")
    if bool(config.allow_postsolve_repair):
        raise ValueError("controlled run must disable postsolve repair")


def _write_schedule(output_dir: Path, result: Any) -> None:
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
    with (output_dir / "vehicle_schedule.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["vehicle_id"])
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> int:
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
    initial_soc_policy = normalize_initial_soc_policy(args.initial_soc_policy)
    scenario = _configure_controlled_model_validation_case(
        scenario,
        time_step_min=args.time_step_min,
        initial_soc_policy=initial_soc_policy,
        initial_soc_percent=args.initial_soc_percent,
    )
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        time_limit_sec=int(args.time_limit_sec),
        mip_gap=float(args.mip_gap),
        random_seed=int(args.random_seed),
        warm_start=False,
        thesis_mode=True,
        research_run=True,
        allow_postsolve_repair=False,
        phase="phase3_two_stage",
        requested_phase="phase3_two_stage",
        resolved_phase="phase3_two_stage",
        executed_phase="phase3_two_stage",
    )
    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id=args.depot_id,
        service_id=args.service_id,
        config=config,
        planning_days=1,
    )
    soc_metadata = initial_soc_input_metadata(problem, policy=initial_soc_policy)
    if initial_soc_policy is InitialSocPolicy.UNIFORM_SCENARIO_VALUE:
        expected_ratio = float(args.initial_soc_percent) / 100.0
        invalid = [
            row["vehicle_id"]
            for row in soc_metadata["initial_soc_by_vehicle"]
            if abs(float(row["initial_soc_percent"] or 0.0) - expected_ratio) > 1.0e-9
        ]
        if invalid:
            raise ValueError("uniform initial SOC was not propagated to the model: " + ", ".join(invalid))
    if isinstance(problem.metadata, dict):
        problem.metadata.update(
            {
                **soc_metadata,
                "phase3_diagnostics_dir": str(Path(args.output_dir) / "diagnostics"),
                "experiment_case_tag": "CONTROLLED_MODEL_VALIDATION_CASE",
                "terminal_soc_policy": "minimum_soc",
                "vehicle_soc_semantics": "slot_start",
            }
        )
    _validate_target_input(problem, scenario, config)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    git_sha, git_dirty = _git_state()
    experiment_identity = _build_experiment_identity(
        problem,
        scenario,
        initial_soc_policy=initial_soc_policy,
        initial_soc_input_hash=str(soc_metadata["initial_soc_input_hash"]),
        time_limit_sec=int(args.time_limit_sec),
        mip_gap=float(args.mip_gap),
        random_seed=int(args.random_seed),
        git_sha=git_sha,
    )
    input_audit = {
        "experiment_case_tag": "CONTROLLED_MODEL_VALIDATION_CASE",
        "research_run": True,
        "phase": "phase3_two_stage",
        "requested_phase": "phase3_two_stage",
        "resolved_phase": "phase3_two_stage",
        "executed_phase": "phase3_two_stage",
        "time_step_min": problem.scenario.timestep_min,
        "slot_count": len(problem.price_slots),
        "target_trip_count": len(problem.trips),
        "route_family_codes": sorted(
            {
                str(getattr(trip, "route_family_code", "") or "")
                for trip in problem.trips
            }
        ),
        "fleet_count": {
            "BEV": sum(
                1
                for vehicle in problem.vehicles
                if str(vehicle.vehicle_type).upper() == "BEV"
            ),
            "ICE": sum(
                1
                for vehicle in problem.vehicles
                if str(vehicle.vehicle_type).upper() == "ICE"
            ),
        },
        "pv_enabled": False,
        "bess_enabled": False,
        "weather_operation_policy_enabled": False,
        "postsolve_repair_enabled": False,
        "fallback_enabled": False,
        "partial_service_enabled": False,
        "terminal_soc_policy": "minimum_soc",
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        **experiment_identity,
        **soc_metadata,
    }
    (output_dir / "controlled_model_validation_input.json").write_text(
        json.dumps(input_audit, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    if args.build_only:
        print(json.dumps(input_audit, ensure_ascii=False, indent=2, default=str))
        return 0
    if not is_gurobi_available():
        blocked = {
            **input_audit,
            "environment_status": "ENVIRONMENT_BLOCKED_GUROBI_LICENSE",
            "solver_invoked": False,
            "research_run_accepted": False,
            "research_feasibility_eligible": False,
            "research_cost_kpi_eligible": False,
            "objective_available": False,
            "stage1_solver_status": "not_run_gurobi_unavailable",
            "stage1_has_feasible_incumbent": False,
            "stage1_objective": None,
            "stage1_best_bound": None,
            "stage1_mip_gap_ratio": None,
            "stage1_mip_gap_percent": None,
            "stage1_runtime_seconds": None,
            "stage2_solver_status": "not_run_gurobi_unavailable",
            "stage2_has_feasible_incumbent": False,
            "stage2_objective": None,
            "stage2_best_bound": None,
            "stage2_mip_gap_ratio": None,
            "stage2_mip_gap_percent": None,
            "stage2_runtime_seconds": None,
            "solver_objective_value": None,
            "accounting_total_cost_jpy": None,
            "validated_operating_cost_jpy": None,
        }
        (output_dir / "summary.json").write_text(
            json.dumps(blocked, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        (output_dir / "research_run_manifest.json").write_text(
            json.dumps(blocked, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(json.dumps(blocked, ensure_ascii=False, indent=2, default=str))
        return 3

    started = time.perf_counter()
    result = OptimizationEngine().solve(problem, config)
    elapsed = time.perf_counter() - started
    solver_metadata = dict(result.solver_metadata or {})
    acceptance = dict(solver_metadata.get("research_acceptance_checks") or {})
    acceptance["git_clean"] = not git_dirty
    accepted = bool(
        solver_metadata.get("research_run_accepted", False)
        and acceptance["git_clean"]
    )
    solver_status = str(result.solver_status or "")
    solver_objective = (
        _finite_float_or_none(result.objective_value)
        if bool(result.feasible)
        else None
    )
    accounting_total = (
        _finite_float_or_none((result.cost_breakdown or {}).get("total_cost"))
        if bool(result.feasible)
        else None
    )
    validated_cost = accounting_total if accepted and bool(result.feasible) else None
    stage1_gap = _finite_float_or_none(
        solver_metadata.get("stage1_mip_gap_ratio")
    )
    stage2_gap = _finite_float_or_none(
        solver_metadata.get("stage2_mip_gap_ratio")
    )
    summary = {
        "scenario_id": args.scenario_id,
        "prepared_input_id": args.prepared_input_id,
        "prepared_input_sha256": _sha256(prepared_path),
        "service_date": problem.metadata.get("service_date"),
        "operator_ids": list(solver_metadata.get("operator_ids_observed") or ()),
        "phase": {
            "requested": solver_metadata.get("requested_phase"),
            "resolved": solver_metadata.get("resolved_phase"),
            "executed": solver_metadata.get("executed_phase"),
        },
        "requested_phase": solver_metadata.get("requested_phase"),
        "resolved_phase": solver_metadata.get("resolved_phase"),
        "executed_phase": solver_metadata.get("executed_phase"),
        "solver_status": solver_status,
        "feasible": bool(result.feasible),
        "research_run": True,
        "research_run_accepted": accepted,
        "research_feasibility_eligible": bool(
            accepted and solver_metadata.get("research_feasibility_eligible", False)
        ),
        "research_cost_kpi_eligible": bool(
            accepted and solver_metadata.get("research_cost_kpi_eligible", False)
        ),
        "trip_count_total": len(problem.trips),
        "trip_count_served": len(result.plan.served_trip_ids),
        "trip_count_unserved": len(result.plan.unserved_trip_ids),
        "fleet": {
            "BEV": 35,
            "ICE": 25,
            "total": len(problem.vehicles),
            "available_BEV": sum(
                1
                for vehicle in problem.vehicles
                if bool(getattr(vehicle, "available", True))
                and str(vehicle.vehicle_type).upper() == "BEV"
            ),
            "available_ICE": sum(
                1
                for vehicle in problem.vehicles
                if bool(getattr(vehicle, "available", True))
                and str(vehicle.vehicle_type).upper() == "ICE"
            ),
        },
        "stage1_solver_status": solver_metadata.get("stage1_solver_status"),
        "stage2_solver_status": solver_metadata.get("stage2_solver_status"),
        "stage1_has_feasible_incumbent": solver_metadata.get(
            "stage1_has_feasible_incumbent"
        ),
        "stage2_has_feasible_incumbent": solver_metadata.get(
            "stage2_has_feasible_incumbent"
        ),
        "stage1_objective": _finite_float_or_none(
            solver_metadata.get("stage1_objective")
        ),
        "stage2_objective": _finite_float_or_none(
            solver_metadata.get("stage2_objective")
        ),
        "stage1_best_bound": _finite_float_or_none(
            solver_metadata.get("stage1_best_bound")
        ),
        "stage2_best_bound": _finite_float_or_none(
            solver_metadata.get("stage2_best_bound")
        ),
        "stage1_mip_gap_ratio": stage1_gap,
        "stage2_mip_gap_ratio": stage2_gap,
        "stage1_mip_gap_percent": _mip_gap_percent(stage1_gap),
        "stage2_mip_gap_percent": _mip_gap_percent(stage2_gap),
        "stage1_runtime_seconds": _finite_float_or_none(
            solver_metadata.get("stage1_runtime_seconds")
        ),
        "stage2_runtime_seconds": _finite_float_or_none(
            solver_metadata.get("stage2_runtime_seconds")
        ),
        "stage1_feasible": solver_metadata.get("stage1_feasible"),
        "stage2_feasible": solver_metadata.get("stage2_feasible"),
        "supports_two_stage_milp": solver_metadata.get("supports_two_stage_milp"),
        "assignment_candidate_available": solver_metadata.get("assignment_candidate_available", False),
        "validation_metrics": dict(solver_metadata.get("validation_metrics") or {}),
        "research_acceptance_checks": acceptance,
        "objective_available": solver_objective is not None,
        "solver_objective_value": solver_objective,
        "accounting_total_cost_jpy": accounting_total,
        "validated_operating_cost_jpy": validated_cost,
        "mip_gap_requested_ratio": float(args.mip_gap),
        "mip_gap_achieved_ratio": _finite_float_or_none(
            solver_metadata.get("achieved_mip_gap")
        ),
        "elapsed_seconds": elapsed,
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        **experiment_identity,
        "pv_enabled": False,
        "bess_enabled": False,
        "weather_operation_policy_enabled": False,
        "experiment_case_tag": "CONTROLLED_MODEL_VALIDATION_CASE",
        "terminal_soc_policy": "minimum_soc",
        **soc_metadata,
        "warnings": list(result.warnings or ()),
        "infeasibility_reasons": list(result.infeasibility_reasons or ()),
    }

    (output_dir / "solver_result.json").write_text(
        json.dumps(ResultSerializer.serialize_result(result), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    (output_dir / "research_run_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "research_phase3_v1",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "git_sha": git_sha,
                "git_dirty": git_dirty,
                "input": summary,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    if bool(solver_metadata.get("assignment_candidate_available", False)):
        (output_dir / "assignment_candidate.json").write_text(
            json.dumps(
                {
                    "research_candidate_only": bool(solver_metadata.get("research_candidate_only", False)),
                    "trip_ids": list(solver_metadata.get("assignment_candidate_trip_ids") or ()),
                    "trip_count": solver_metadata.get("assignment_candidate_trip_count"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    if accepted and bool(result.feasible):
        _write_schedule(output_dir, result)
    else:
        print("No final research schedule written: acceptance gate failed.")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return 0 if accepted and bool(result.feasible) else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario-id", default=DEFAULT_SCENARIO_ID)
    parser.add_argument("--prepared-input-id", default=DEFAULT_PREPARED_INPUT_ID)
    parser.add_argument("--depot-id", default="tsurumaki")
    parser.add_argument("--service-id", default="WEEKDAY")
    parser.add_argument("--output-dir", default="output/research_phase3_minimal")
    parser.add_argument("--time-limit-sec", type=int, default=1500)
    parser.add_argument("--mip-gap", type=float, default=0.1)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--time-step-min", type=int, default=15)
    parser.add_argument(
        "--initial-soc-policy",
        default=InitialSocPolicy.UNIFORM_SCENARIO_VALUE.value,
        choices=[policy.value for policy in InitialSocPolicy],
    )
    parser.add_argument("--initial-soc-percent", type=float, default=80.0)
    parser.add_argument("--build-only", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
