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
from src.optimization import (
    OptimizationConfig,
    OptimizationEngine,
    OptimizationMode,
    ProblemBuilder,
    ResultSerializer,
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


def _validate_target_input(problem: Any, scenario: dict[str, Any]) -> None:
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
    _disable_depot_assets(scenario)
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
    _validate_target_input(problem, scenario)

    started = time.perf_counter()
    result = OptimizationEngine().solve(problem, config)
    elapsed = time.perf_counter() - started
    solver_metadata = dict(result.solver_metadata or {})
    acceptance = dict(solver_metadata.get("research_acceptance_checks") or {})
    accepted = bool(solver_metadata.get("research_run_accepted", False))
    solver_status = str(result.solver_status or "")
    accounting_total = float((result.cost_breakdown or {}).get("total_cost", 0.0) or 0.0)
    validated_cost = accounting_total if accepted and bool(result.feasible) else None
    git_sha, git_dirty = _git_state()
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
        "solver_status": solver_status,
        "feasible": bool(result.feasible),
        "research_run": True,
        "research_run_accepted": accepted,
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
        "stage1_feasible": solver_metadata.get("stage1_feasible"),
        "stage2_feasible": solver_metadata.get("stage2_feasible"),
        "supports_two_stage_milp": solver_metadata.get("supports_two_stage_milp"),
        "assignment_candidate_available": solver_metadata.get("assignment_candidate_available", False),
        "validation_metrics": dict(solver_metadata.get("validation_metrics") or {}),
        "research_acceptance_checks": acceptance,
        "solver_objective_value": float(result.objective_value or 0.0),
        "accounting_total_cost_jpy": accounting_total,
        "validated_operating_cost_jpy": validated_cost,
        "mip_gap_requested_ratio": float(args.mip_gap),
        "mip_gap_achieved_ratio": solver_metadata.get("achieved_mip_gap"),
        "elapsed_seconds": elapsed,
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "pv_enabled": False,
        "bess_enabled": False,
        "weather_operation_policy_enabled": False,
        "warnings": list(result.warnings or ()),
        "infeasibility_reasons": list(result.infeasibility_reasons or ()),
    }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
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
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
