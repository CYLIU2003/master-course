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
from src.preprocess.weather.operation_policy import apply_weather_policy_to_problem


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


def _git_state() -> dict[str, Any]:
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True
    ).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=REPO_ROOT, text=True
        ).strip()
    )
    return {"git_sha": sha, "git_dirty": dirty}


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


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
            "bess_terminal_soc_target_kwh": float(asset.bess_terminal_soc_target_kwh),
            "bess_terminal_soc_deviation_penalty_yen_per_kwh": float(
                asset.bess_terminal_soc_deviation_penalty_yen_per_kwh
            ),
        }
        for depot_id, asset in sorted(problem.depot_energy_assets.items())
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
    return _canonical_hash(
        [
            {
                "trip_id": trip.trip_id,
                "departure_min": trip.departure_min,
                "arrival_min": trip.arrival_min,
                "distance_km": trip.distance_km,
                "energy_kwh": trip.energy_kwh,
                "fuel_l": trip.fuel_l,
            }
            for trip in sorted(problem.trips, key=lambda item: str(item.trip_id))
        ]
    )


def _vehicle_input_hash(problem: Any) -> str:
    return _canonical_hash(
        [
            {
                "vehicle_id": vehicle.vehicle_id,
                "vehicle_type": vehicle.vehicle_type,
                "home_depot_id": vehicle.home_depot_id,
                "available": vehicle.available,
                "battery_capacity_kwh": vehicle.battery_capacity_kwh,
                "initial_soc": vehicle.initial_soc,
                "reserve_soc": vehicle.reserve_soc,
                "fuel_tank_capacity_l": vehicle.fuel_tank_capacity_l,
                "initial_fuel_l": vehicle.initial_fuel_l,
                "fuel_reserve_l": vehicle.fuel_reserve_l,
            }
            for vehicle in sorted(problem.vehicles, key=lambda item: str(item.vehicle_id))
        ]
    )


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
    if int(problem.scenario.timestep_min) != 60 or len(problem.price_slots) != 24:
        raise ValueError(
            "Frontend weather comparison must retain its 60-minute, 24-slot setting"
        )
    if not any(asset.pv_enabled for asset in problem.depot_energy_assets.values()):
        raise ValueError("Frontend weather comparison requires an enabled PV asset")
    if not any(asset.bess_enabled for asset in problem.depot_energy_assets.values()):
        raise ValueError("Frontend weather comparison requires an enabled BESS asset")
    simulation_config = dict(scenario.get("simulation_config") or {})
    if not bool(simulation_config.get("enable_weather_operation_policy", False)):
        raise ValueError("Frontend weather operation policy must remain enabled")


def run(args: argparse.Namespace) -> int:
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
    scenario, weather_forecast, weather_profile = _prepare_weather_policy_for_scenario(
        scenario,
        enable_weather_operation_policy=None,
        weather_proxy_forecast_path=None,
    )
    initial_soc_policy = _resolve_initial_soc_policy(scenario)
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        time_limit_sec=int(args.time_limit_sec),
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
    weather_configuration = _weather_configuration(scenario)
    terminal_soc_policy = {
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
            "charger_configuration": charger_configuration,
            "timestep_min": int(problem.scenario.timestep_min),
            "depot_energy_assets": depot_energy_assets,
            "weather_configuration": weather_configuration,
            "phase": "phase3_two_stage",
            "research_run": True,
            "time_limit_sec": int(args.time_limit_sec),
            "mip_gap": float(args.mip_gap),
            "random_seed": int(args.random_seed),
            "git_sha": git_state["git_sha"],
        }
    )
    input_audit = {
        "case_name": args.case_name,
        "scenario_id": args.scenario_id,
        "prepared_input_id": args.prepared_input_id,
        "prepared_input_sha256": _sha256(prepared_path),
        "service_date": str(problem.metadata.get("service_date") or "")[:10],
        "phase": "phase3_two_stage",
        "time_limit_sec": int(args.time_limit_sec),
        "mip_gap": float(args.mip_gap),
        "random_seed": int(args.random_seed),
        "postsolve_repair_enabled": False,
        "vehicle_soc_semantics": "slot_start",
        "weather_operation_policy_enabled": True,
        "weather_configuration": weather_configuration,
        "trip_count": len(problem.trips),
        "fleet": {
            "BEV": sum(1 for item in problem.vehicles if str(item.vehicle_type).upper() == "BEV"),
            "ICE": sum(1 for item in problem.vehicles if str(item.vehicle_type).upper() == "ICE"),
        },
        "timestep_min": int(problem.scenario.timestep_min),
        "price_slot_count": len(problem.price_slots),
        "clock_hour_grid_price_yen_per_kwh": _clock_hour_prices(problem),
        "demand_charge_monthly_yen_per_kw": float(problem.scenario.demand_charge_on_peak_yen_per_kw),
        "demand_charge_horizon_yen_per_kw": float(
            problem.scenario.demand_charge_on_peak_horizon_yen_per_kw
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
        "charger_configuration": charger_configuration,
        "charger_configuration_hash": _canonical_hash(charger_configuration),
        "depot_energy_assets": depot_energy_assets,
        "vehicle_input_hash": vehicle_input_hash,
        "trip_input_hash": trip_input_hash,
        "experiment_hash": experiment_hash,
        **git_state,
    }
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
    print("[3/4] Solving Phase 3 (no fallback, no postsolve repair)", flush=True)
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
            "vehicle_usage_cost",
        )
    }
    summary = {
        **input_audit,
        "solver_status": str(result.solver_status or ""),
        "feasible": bool(result.feasible),
        "elapsed_seconds": elapsed,
        "trip_count_served": len(result.plan.served_trip_ids),
        "trip_count_unserved": len(result.plan.unserved_trip_ids),
        "used_vehicle_count": len(result.plan.vehicle_paths()),
        "max_fragments_observed": int(result.plan.max_fragments_observed()),
        "stage1_solver_status": metadata.get("stage1_solver_status"),
        "stage2_solver_status": metadata.get("stage2_solver_status"),
        "stage1_objective": _finite(metadata.get("stage1_objective")),
        "stage2_objective": _finite(metadata.get("stage2_objective")),
        "stage1_best_bound": _finite(metadata.get("stage1_best_bound")),
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
        "stage2_runtime_seconds": _finite(metadata.get("stage2_runtime_seconds")),
        "research_run_accepted": bool(metadata.get("research_run_accepted", False)),
        "research_feasibility_eligible": bool(
            metadata.get("research_feasibility_eligible", False)
        ),
        "research_cost_kpi_eligible": bool(
            metadata.get("research_cost_kpi_eligible", False)
        ),
        "solver_objective_matches_accounting_total": bool(
            metadata.get("solver_objective_matches_accounting_total", False)
        ),
        "objective_semantics": metadata.get("objective_semantics"),
        "accounting_total_cost_jpy": _finite(breakdown.get("total_cost")),
        "cost_comparison_scope": (
            "feasible_schedule_accounting_not_global_total_cost_optimum"
            if result.feasible
            else "not_available_for_infeasible_result"
        ),
        "validation_metrics": dict(metadata.get("validation_metrics") or {}),
        "flows_kwh_or_kw": flows,
        "costs_jpy": costs,
        "warnings": list(result.warnings or ()),
        "infeasibility_reasons": list(result.infeasibility_reasons or ()),
    }
    print("[4/4] Writing reproducibility artifacts", flush=True)
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
    parser.add_argument("--mip-gap", type=float, default=0.1)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument("--build-only", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
