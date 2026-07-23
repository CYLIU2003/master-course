"""Audit the final Phase 3 sunny/rain runs for advisor-facing reporting.

The audit rebuilds the immutable canonical inputs, but it never invokes the
solver.  It reconciles the persisted assignment and dispatch result against:

* stationary-battery state transitions and terminal SOC;
* PV, grid, battery, and bus-charging source balances;
* used BEV/ICE counts and time-of-day operation; and
* distance-based ICE fuel consumption and the reported provisional fuel cost.

The generated JSON/CSV files are evidence artifacts for the presentation.  In
particular, a zero fuel-cost residual proves consistency with the model's
distance accounting; it does not turn the result into a realized refuelling
ledger.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.optimization.common.bess_terminal_policy import (  # noqa: E402
    normalize_bess_terminal_policy,
    resolve_bess_terminal_soc_target_kwh,
)
from scripts.compare_research_phase3_weather import (  # noqa: E402
    _validate_manifest,
    build_weather_comparison,
)

DEFAULT_OUTPUTS_ROOT = Path(r"C:\master-course\output")
CASE_LABELS = {"sunny": "晴天", "rain": "雨天"}
BALANCE_TOLERANCE = 1.0e-6
FUEL_COST_TOLERANCE_JPY = 1.0e-6


def _number(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Required artifact is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_effective_scenario(
    run_dir: Path,
    input_audit: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Load the immutable run input and reject path/hash substitution."""

    artifact_name = str(input_audit.get("effective_scenario_artifact") or "").strip()
    if not artifact_name:
        return None
    run_root = run_dir.resolve()
    artifact_path = (run_root / artifact_name).resolve()
    if artifact_path.parent != run_root:
        raise ValueError(
            "effective_scenario_artifact must be a file directly inside the run directory"
        )
    scenario = _load_json(artifact_path)
    expected_hash = str(input_audit.get("effective_scenario_sha256") or "").strip()
    actual_hash = _canonical_hash(scenario)
    if not expected_hash or actual_hash != expected_hash:
        raise ValueError(
            "effective_scenario.json does not match input_audit.json"
        )
    return scenario


def _nested_slot_values(
    container: Mapping[str, Any],
    key: str,
    slot_count: int,
) -> list[float]:
    totals = [0.0] * slot_count
    by_depot = container.get(key)
    if not isinstance(by_depot, Mapping):
        return totals
    for raw_by_slot in by_depot.values():
        if not isinstance(raw_by_slot, Mapping):
            continue
        for raw_slot, raw_value in raw_by_slot.items():
            slot_index = int(raw_slot)
            if 0 <= slot_index < slot_count:
                totals[slot_index] += max(_number(raw_value), 0.0)
    return totals


def _single_depot_slot_values(
    container: Mapping[str, Any],
    key: str,
    depot_id: str,
    slot_count: int,
) -> list[float]:
    values = [0.0] * slot_count
    by_depot = container.get(key)
    if not isinstance(by_depot, Mapping):
        return values
    by_slot = by_depot.get(depot_id)
    if not isinstance(by_slot, Mapping):
        return values
    for raw_slot, raw_value in by_slot.items():
        slot_index = int(raw_slot)
        if 0 <= slot_index < slot_count:
            values[slot_index] = _number(raw_value)
    return values


def _clock_minute(text: str) -> int:
    hour, minute = str(text or "00:00").split(":", 1)
    return int(hour) * 60 + int(minute)


def _service_minute(value: int, horizon_start_min: int) -> int:
    minute = int(value)
    while minute < horizon_start_min:
        minute += 24 * 60
    return minute


def _slot_index_for_minute(
    minute: int,
    *,
    horizon_start_min: int,
    timestep_min: int,
    slot_count: int,
) -> int:
    service_minute = _service_minute(minute, horizon_start_min)
    return min(max((service_minute - horizon_start_min) // timestep_min, 0), slot_count - 1)


def _interval_overlaps_slot(
    departure_min: int,
    arrival_min: int,
    *,
    slot_index: int,
    horizon_start_min: int,
    timestep_min: int,
) -> bool:
    departure = _service_minute(departure_min, horizon_start_min)
    arrival = int(arrival_min)
    while arrival <= departure:
        arrival += 24 * 60
    slot_start = horizon_start_min + slot_index * timestep_min
    slot_end = slot_start + timestep_min
    return departure < slot_end and arrival > slot_start


def _slot_label(slot_index: int, *, horizon_start_min: int, timestep_min: int) -> str:
    start = horizon_start_min + slot_index * timestep_min
    end = start + timestep_min
    return (
        f"{(start // 60) % 24:02d}:{start % 60:02d}–"
        f"{(end // 60) % 24:02d}:{end % 60:02d}"
    )


def _build_problem(
    *,
    run_dir: Path,
    outputs_root: Path,
    input_audit: Mapping[str, Any],
) -> Any:
    """Rebuild the exact canonical input path without solving."""

    os.environ["MC_OUTPUTS_DIR"] = str(outputs_root)
    from scripts import run_research_phase3_frontend_weather as runner
    from src.optimization import OptimizationConfig, OptimizationMode, ProblemBuilder
    from src.preprocess.weather.operation_policy import apply_weather_policy_to_problem

    scenario_id = str(input_audit["scenario_id"])
    prepared_input_id = str(input_audit["prepared_input_id"])
    scenario = _load_effective_scenario(run_dir, input_audit)
    if scenario is None:
        prepared_payload = runner.load_prepared_input(
            scenario_id=scenario_id,
            prepared_input_id=prepared_input_id,
            scenarios_dir=runner._prepared_inputs_root(),
        )
        scenario = deepcopy(
            runner.materialize_scenario_from_prepared_input(
                runner.store.get_scenario_document_shallow(scenario_id),
                prepared_payload,
            )
        )
        runner._configure_research_discretization(
            scenario,
            timestep_min=int(input_audit["timestep_min"]),
        )
    else:
        scenario = deepcopy(scenario)
    scenario, weather_forecast, weather_profile = runner._prepare_weather_policy_for_scenario(
        scenario,
        enable_weather_operation_policy=None,
        weather_proxy_forecast_path=None,
    )
    terminal_policy = dict(input_audit.get("terminal_soc_policy") or {})
    simulation_config = dict(scenario.get("simulation_config") or {})
    simulation_config["bev_terminal_soc_policy"] = str(
        terminal_policy.get("bev_terminal_soc_policy") or "return_to_initial"
    )
    scenario["simulation_config"] = simulation_config
    runner.enforce_research_phase3_single_continuous_duty(scenario)
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        time_limit_sec=int(input_audit["time_limit_sec"]),
        mip_gap=float(input_audit["mip_gap"]),
        random_seed=int(input_audit["random_seed"]),
        warm_start=True,
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
        depot_id="tsurumaki",
        service_id=str(input_audit.get("service_id") or "WEEKDAY"),
        config=config,
        planning_days=1,
    )
    if weather_forecast is not None and weather_profile is not None:
        problem = apply_weather_policy_to_problem(
            problem,
            weather_forecast,
            weather_profile,
            random_seed=int(input_audit["random_seed"]),
        )
    if runner._trip_input_hash(problem) != input_audit["trip_input_hash"]:
        raise ValueError("Rebuilt trip input hash does not match the recorded run")
    if runner._vehicle_input_hash(problem) != input_audit["vehicle_input_hash"]:
        raise ValueError("Rebuilt vehicle input hash does not match the recorded run")
    return problem


def _fuel_rate_by_vehicle_type(problem: Any, vehicle_type: str) -> float:
    for item in problem.vehicle_types:
        if str(item.vehicle_type_id) == str(vehicle_type):
            return max(_number(item.fuel_consumption_l_per_km), 0.0)
    return 0.0


def _pv_generation_by_slot(problem: Any, slot_count: int) -> list[float]:
    totals = [0.0] * slot_count
    for asset in problem.depot_energy_assets.values():
        for slot_index, value in enumerate(asset.pv_generation_kwh_by_slot):
            if slot_index < slot_count:
                totals[slot_index] += max(_number(value), 0.0)
    return totals


def _charging_input_by_slot(
    result: Mapping[str, Any],
    *,
    timestep_h: float,
    slot_count: int,
) -> list[float]:
    totals = [0.0] * slot_count
    for row in result.get("charging_schedule") or []:
        slot_index = int(row["slot_index"])
        if 0 <= slot_index < slot_count:
            net_kw = max(_number(row.get("charge_kw")) - _number(row.get("discharge_kw")), 0.0)
            totals[slot_index] += net_kw * timestep_h
    return totals


def _operation_and_fuel(
    problem: Any,
    result: Mapping[str, Any],
    *,
    horizon_start_min: int,
    timestep_min: int,
    slot_count: int,
) -> dict[str, Any]:
    trip_by_id = problem.trip_by_id()
    duty_vehicle_map = dict((result.get("metadata") or {}).get("duty_vehicle_map") or {})
    active_vehicle_ids: dict[str, list[set[str]]] = {
        "BEV": [set() for _ in range(slot_count)],
        "ICE": [set() for _ in range(slot_count)],
    }
    departure_trip_count: dict[str, list[int]] = {
        "BEV": [0] * slot_count,
        "ICE": [0] * slot_count,
    }
    fuel_service_l = [0.0] * slot_count
    fuel_deadhead_l = [0.0] * slot_count
    used_vehicle_ids: dict[str, set[str]] = {"BEV": set(), "ICE": set()}
    assigned_trip_count = {"BEV": 0, "ICE": 0}
    service_distance_km = {"BEV": 0.0, "ICE": 0.0}
    deadhead_distance_km = {"BEV": 0.0, "ICE": 0.0}
    service_fuel_l = 0.0
    deadhead_fuel_l = 0.0
    deadhead_speed_kmh = max(_number(problem.metadata.get("deadhead_speed_kmh"), 18.0), 0.0)

    for duty in result.get("duties") or []:
        vehicle_type = str(duty.get("vehicle_type") or "").upper()
        if vehicle_type not in {"BEV", "ICE"}:
            continue
        duty_id = str(duty["duty_id"])
        vehicle_id = str(duty_vehicle_map.get(duty_id) or duty_id)
        used_vehicle_ids[vehicle_type].add(vehicle_id)
        # Match the accounting evaluator, which prices duty fuel by canonical
        # vehicle-type rate rather than by a vehicle-specific override.
        fuel_rate = _fuel_rate_by_vehicle_type(problem, vehicle_type)
        for leg in duty.get("legs") or []:
            trip_id = str(leg["trip_id"])
            trip = trip_by_id.get(trip_id)
            if trip is None:
                raise ValueError(f"Persisted duty references unknown trip: {trip_id}")
            assigned_trip_count[vehicle_type] += 1
            service_distance_km[vehicle_type] += max(_number(trip.distance_km), 0.0)
            departure_slot = _slot_index_for_minute(
                trip.departure_min,
                horizon_start_min=horizon_start_min,
                timestep_min=timestep_min,
                slot_count=slot_count,
            )
            departure_trip_count[vehicle_type][departure_slot] += 1
            for slot_index in range(slot_count):
                if _interval_overlaps_slot(
                    trip.departure_min,
                    trip.arrival_min,
                    slot_index=slot_index,
                    horizon_start_min=horizon_start_min,
                    timestep_min=timestep_min,
                ):
                    active_vehicle_ids[vehicle_type][slot_index].add(vehicle_id)

            if vehicle_type == "ICE":
                trip_fuel_l = max(_number(trip.fuel_l), 0.0)
                if trip_fuel_l <= 0.0:
                    trip_fuel_l = max(_number(trip.distance_km), 0.0) * fuel_rate
                service_fuel_l += trip_fuel_l
                fuel_service_l[departure_slot] += trip_fuel_l

            deadhead_min = max(int(leg.get("deadhead_from_prev_min") or 0), 0)
            deadhead_km = deadhead_min * deadhead_speed_kmh / 60.0
            deadhead_distance_km[vehicle_type] += deadhead_km
            if vehicle_type == "ICE" and deadhead_km > 0.0:
                leg_deadhead_fuel_l = deadhead_km * fuel_rate
                deadhead_fuel_l += leg_deadhead_fuel_l
                fuel_deadhead_l[departure_slot] += leg_deadhead_fuel_l

    return {
        "used_vehicle_ids": {
            key: sorted(values) for key, values in used_vehicle_ids.items()
        },
        "used_vehicle_count": {
            key: len(values) for key, values in used_vehicle_ids.items()
        },
        "assigned_trip_count": assigned_trip_count,
        "service_distance_km": service_distance_km,
        "intertrip_deadhead_distance_km": deadhead_distance_km,
        "active_vehicle_count_by_slot": {
            key: [len(values) for values in slots]
            for key, slots in active_vehicle_ids.items()
        },
        "departure_trip_count_by_slot": departure_trip_count,
        "fuel_service_l_by_slot": fuel_service_l,
        "fuel_deadhead_l_by_slot": fuel_deadhead_l,
        "fuel_service_l": service_fuel_l,
        "fuel_intertrip_deadhead_l": deadhead_fuel_l,
        "fuel_total_l": service_fuel_l + deadhead_fuel_l,
        "deadhead_speed_kmh": deadhead_speed_kmh,
    }


def _audit_case(
    *,
    case_key: str,
    run_dir: Path,
    outputs_root: Path,
) -> dict[str, Any]:
    input_audit = _load_json(run_dir / "input_audit.json")
    result = _load_json(run_dir / "solver_result.json")
    summary = _load_json(run_dir / "summary.json")
    problem = _build_problem(
        run_dir=run_dir,
        outputs_root=outputs_root,
        input_audit=input_audit,
    )

    timestep_min = int(input_audit["timestep_min"])
    timestep_h = timestep_min / 60.0
    slot_count = int(input_audit["price_slot_count"])
    horizon_start_min = _clock_minute(str(result.get("metadata", {}).get("horizon_start") or "00:00"))
    if len(input_audit["depot_energy_assets"]) != 1:
        raise ValueError("This advisor audit requires exactly one depot energy asset")
    depot_id = next(iter(input_audit["depot_energy_assets"]))
    asset = input_audit["depot_energy_assets"][depot_id]
    canonical_asset = problem.depot_energy_assets[depot_id]
    terminal_policy = normalize_bess_terminal_policy(
        getattr(canonical_asset, "bess_terminal_soc_policy", ""),
        has_explicit_target=(
            _number(canonical_asset.bess_terminal_soc_target_kwh) > 0.0
        ),
    )
    terminal_target_kwh = resolve_bess_terminal_soc_target_kwh(
        policy=terminal_policy,
        initial_soc_kwh=_number(canonical_asset.bess_initial_soc_kwh),
        configured_target_kwh=_number(
            canonical_asset.bess_terminal_soc_target_kwh
        ),
        terminal_soc_floor_kwh=max(
            _number(canonical_asset.bess_terminal_soc_min_kwh),
            _number(canonical_asset.bess_soc_min_kwh),
        ),
        maximum_soc_kwh=_number(canonical_asset.bess_soc_max_kwh),
    )
    pv_generation = _pv_generation_by_slot(problem, slot_count)
    grid_to_bus = _nested_slot_values(result, "grid_to_bus_kwh_by_depot_slot", slot_count)
    pv_to_bus = _nested_slot_values(result, "pv_to_bus_kwh_by_depot_slot", slot_count)
    bess_to_bus = _nested_slot_values(result, "bess_to_bus_kwh_by_depot_slot", slot_count)
    pv_to_bess = _nested_slot_values(result, "pv_to_bess_kwh_by_depot_slot", slot_count)
    grid_to_bess = _nested_slot_values(result, "grid_to_bess_kwh_by_depot_slot", slot_count)
    pv_curtail = _nested_slot_values(result, "pv_curtail_kwh_by_depot_slot", slot_count)
    bess_soc_start = _single_depot_slot_values(
        result.get("metadata") or {},
        "bess_soc_start_kwh_by_depot_slot",
        depot_id,
        slot_count,
    )
    bess_soc_end = _single_depot_slot_values(
        result.get("metadata") or {},
        "bess_soc_end_kwh_by_depot_slot",
        depot_id,
        slot_count,
    )
    charging_input = _charging_input_by_slot(
        result,
        timestep_h=timestep_h,
        slot_count=slot_count,
    )
    operation = _operation_and_fuel(
        problem,
        result,
        horizon_start_min=horizon_start_min,
        timestep_min=timestep_min,
        slot_count=slot_count,
    )

    charge_efficiency = _number(asset["bess_charge_efficiency"])
    discharge_efficiency = _number(asset["bess_discharge_efficiency"])
    rows: list[dict[str, Any]] = []
    for slot_index in range(slot_count):
        bus_source_total = grid_to_bus[slot_index] + pv_to_bus[slot_index] + bess_to_bus[slot_index]
        grid_import = grid_to_bus[slot_index] + grid_to_bess[slot_index]
        pv_balance_residual = (
            pv_generation[slot_index]
            - pv_to_bus[slot_index]
            - pv_to_bess[slot_index]
            - pv_curtail[slot_index]
        )
        bus_source_residual = charging_input[slot_index] - bus_source_total
        bess_balance_residual = (
            bess_soc_end[slot_index]
            - bess_soc_start[slot_index]
            - charge_efficiency * (pv_to_bess[slot_index] + grid_to_bess[slot_index])
            + bess_to_bus[slot_index] / discharge_efficiency
        )
        rows.append(
            {
                "slot_index": slot_index,
                "slot_label": _slot_label(
                    slot_index,
                    horizon_start_min=horizon_start_min,
                    timestep_min=timestep_min,
                ),
                "pv_generated_kwh": pv_generation[slot_index],
                "grid_to_bus_kwh": grid_to_bus[slot_index],
                "pv_to_bus_kwh": pv_to_bus[slot_index],
                "bess_to_bus_kwh": bess_to_bus[slot_index],
                "pv_to_bess_kwh": pv_to_bess[slot_index],
                "grid_to_bess_kwh": grid_to_bess[slot_index],
                "pv_curtail_kwh": pv_curtail[slot_index],
                "bus_charging_input_kwh": charging_input[slot_index],
                "grid_import_kwh": grid_import,
                "grid_import_average_kw": grid_import / timestep_h,
                "bess_soc_start_kwh": bess_soc_start[slot_index],
                "bess_soc_end_kwh": bess_soc_end[slot_index],
                "pv_balance_residual_kwh": pv_balance_residual,
                "bus_source_balance_residual_kwh": bus_source_residual,
                "bess_balance_residual_kwh": bess_balance_residual,
                "active_bev_count": operation["active_vehicle_count_by_slot"]["BEV"][slot_index],
                "active_ice_count": operation["active_vehicle_count_by_slot"]["ICE"][slot_index],
                "departing_bev_trip_count": operation["departure_trip_count_by_slot"]["BEV"][slot_index],
                "departing_ice_trip_count": operation["departure_trip_count_by_slot"]["ICE"][slot_index],
                "fuel_service_l": operation["fuel_service_l_by_slot"][slot_index],
                "fuel_intertrip_deadhead_l": operation["fuel_deadhead_l_by_slot"][slot_index],
            }
        )

    reported_fuel_cost = _number(result.get("cost_breakdown", {}).get("fuel_cost_final"))
    fuel_price = _number(input_audit["diesel_price_yen_per_l"])
    expected_fuel_cost = operation["fuel_total_l"] * fuel_price
    daily = {
        "pv_generated_kwh": sum(pv_generation),
        "pv_to_bus_kwh": sum(pv_to_bus),
        "pv_to_bess_kwh": sum(pv_to_bess),
        "pv_curtailed_kwh": sum(pv_curtail),
        "grid_to_bus_kwh": sum(grid_to_bus),
        "grid_to_bess_kwh": sum(grid_to_bess),
        "grid_import_kwh": sum(row["grid_import_kwh"] for row in rows),
        "bess_to_bus_kwh": sum(bess_to_bus),
        "bus_charging_input_kwh": sum(charging_input),
        "peak_grid_import_kw": max(row["grid_import_average_kw"] for row in rows),
        "bess_charge_input_kwh": sum(pv_to_bess) + sum(grid_to_bess),
        "bess_discharge_delivered_kwh": sum(bess_to_bus),
        "bess_charge_loss_kwh": (sum(pv_to_bess) + sum(grid_to_bess)) * (1.0 - charge_efficiency),
        "bess_discharge_loss_kwh": sum(bess_to_bus) / discharge_efficiency - sum(bess_to_bus),
    }
    max_residuals = {
        "pv_balance_kwh": max(abs(row["pv_balance_residual_kwh"]) for row in rows),
        "bus_source_balance_kwh": max(abs(row["bus_source_balance_residual_kwh"]) for row in rows),
        "bess_balance_kwh": max(abs(row["bess_balance_residual_kwh"]) for row in rows),
    }
    balance_passed = all(value <= BALANCE_TOLERANCE for value in max_residuals.values())
    validation_metrics = dict(summary.get("validation_metrics") or {})

    return {
        "case_key": case_key,
        "case_label": CASE_LABELS[case_key],
        "run_dir": str(run_dir),
        "scenario_id": input_audit["scenario_id"],
        "service_date": input_audit["service_date"],
        "prepared_input_id": input_audit["prepared_input_id"],
        "trip_input_hash": input_audit["trip_input_hash"],
        "vehicle_input_hash": input_audit["vehicle_input_hash"],
        "solver_result_sha256": hashlib.sha256(
            (run_dir / "solver_result.json").read_bytes()
        ).hexdigest(),
        "experiment_hash": input_audit["experiment_hash"],
        "git_sha": input_audit["git_sha"],
        "git_dirty": bool(input_audit["git_dirty"]),
        "solver": {
            "solver_mode": result["solver_mode"],
            "solver_status": result["solver_status"],
            "stage1_status": result["metadata"]["stage1_solver_status"],
            "stage1_mip_gap_ratio": _number(result["metadata"]["stage1_mip_gap_ratio"]),
            "stage1_runtime_seconds": _number(result["metadata"]["stage1_runtime_seconds"]),
            "stage2_status": result["metadata"]["stage2_solver_status"],
            "stage2_runtime_seconds": _number(result["metadata"]["stage2_runtime_seconds"]),
            "research_cost_kpi_eligible": bool(result["metadata"]["research_cost_kpi_eligible"]),
            "research_run": bool(result["metadata"].get("research_run")),
            "research_run_accepted": bool(
                result["metadata"].get("research_run_accepted")
            ),
            "vehicle_source_provenance_exact": bool(
                result["metadata"].get("vehicle_source_provenance_exact")
            ),
            "vehicle_source_allocation_policy": result["metadata"].get(
                "vehicle_source_allocation_policy"
            ),
            "objective_semantics": result["metadata"]["objective_semantics"],
            "bev_terminal_soc_balance_satisfied": bool(
                result["metadata"].get("bev_terminal_soc_balance_satisfied")
            ),
            "bev_terminal_soc_total_target_shortfall_kwh": _number(
                result["metadata"].get(
                    "bev_terminal_soc_total_target_shortfall_kwh"
                )
            ),
            "bev_terminal_soc_total_target_surplus_kwh": _number(
                result["metadata"].get(
                    "bev_terminal_soc_total_target_surplus_kwh"
                )
            ),
            "bev_terminal_soc_max_abs_target_deviation_kwh": _number(
                result["metadata"].get(
                    "bev_terminal_soc_max_abs_target_deviation_kwh"
                )
            ),
            "physical_charger_assignment_semantics": result["metadata"].get(
                "physical_charger_assignment_semantics"
            ),
        },
        "scenario_parameters": {
            "phase": input_audit["phase"],
            "solver_backend": result["metadata"].get("backend", "gurobi_two_stage"),
            "time_limit_sec": int(input_audit["time_limit_sec"]),
            "stage_time_limit_sec": int(max(int(input_audit["time_limit_sec"]), 2) / 2),
            "mip_gap": _number(input_audit["mip_gap"]),
            "random_seed": int(input_audit["random_seed"]),
            "postsolve_repair_enabled": bool(input_audit["postsolve_repair_enabled"]),
            "timestep_min": int(input_audit["timestep_min"]),
            "price_slot_count": int(input_audit["price_slot_count"]),
            "horizon_start": result["metadata"]["horizon_start"],
            "trip_count": int(input_audit["trip_count"]),
            "fleet": dict(input_audit["fleet"]),
            "expected_fleet": dict(input_audit.get("expected_fleet") or {}),
            "fleet_available": dict(input_audit["fleet_available"]),
            "research_fragment_policy": dict(input_audit["research_fragment_policy"]),
            "charger_configuration": list(input_audit["charger_configuration"]),
            "depot_import_limit_kw_by_depot": dict(input_audit["depot_import_limit_kw_by_depot"]),
            "contract_overage_penalty_yen_per_kwh": _number(
                input_audit["contract_overage_penalty_yen_per_kwh"]
            ),
            "clock_hour_grid_price_yen_per_kwh": dict(
                input_audit["clock_hour_grid_price_yen_per_kwh"]
            ),
            "demand_charge_monthly_yen_per_kw": _number(
                input_audit["demand_charge_monthly_yen_per_kw"]
            ),
            "demand_charge_horizon_yen_per_kw": _number(
                input_audit["demand_charge_horizon_yen_per_kw"]
            ),
            "diesel_price_yen_per_l": _number(input_audit["diesel_price_yen_per_l"]),
            "co2_price_yen_per_kg": _number(input_audit["co2_price_yen_per_kg"]),
            "vehicle_usage_cost_jpy_per_used_bus": _number(
                input_audit["vehicle_usage_cost_jpy_per_used_bus"]
            ),
            "minimum_used_bev_count": int(
                input_audit.get("minimum_used_bev_count") or 0
            ),
            "grid_co2_kg_per_kwh": dict(input_audit["grid_co2_kg_per_kwh"]),
            "pv_marginal_charge_cost_yen_per_kwh": _number(
                input_audit["pv_marginal_charge_cost_yen_per_kwh"]
            ),
            "pv_curtail_penalty_yen_per_kwh": _number(
                input_audit["pv_curtail_penalty_yen_per_kwh"]
            ),
            "cost_component_flags": dict(input_audit["cost_component_flags"]),
            "objective_weights": dict(input_audit["objective_weights"]),
            "initial_soc_policy": input_audit["initial_soc_policy"],
            "initial_soc_source": input_audit["initial_soc_source"],
            "terminal_soc_policy": dict(input_audit["terminal_soc_policy"]),
            "depot_energy_assets": dict(input_audit["depot_energy_assets"]),
            "weather_configuration": dict(input_audit["weather_configuration"]),
            "weather_operation_profile": dict(input_audit["weather_operation_profile"]),
            "weather_pv_forecast_applied": bool(
                input_audit.get("weather_pv_forecast_applied")
            ),
            "weather_pv_forecast_skip_reason": input_audit.get(
                "weather_pv_forecast_skip_reason"
            ),
            "calendar_service_contract": dict(
                input_audit.get("calendar_service_contract") or {}
            ),
        },
        "fleet_input": dict(input_audit["fleet"]),
        "operation": operation,
        "bess": {
            "capacity_kwh": _number(asset["bess_energy_kwh"]),
            "power_kw": _number(asset["bess_power_kw"]),
            "soc_min_kwh": _number(asset["bess_soc_min_kwh"]),
            "soc_max_kwh": _number(asset["bess_soc_max_kwh"]),
            "initial_soc_kwh": bess_soc_start[0],
            "terminal_soc_kwh": bess_soc_end[-1],
            "terminal_policy": terminal_policy,
            "terminal_target_kwh": terminal_target_kwh,
            "terminal_delta_kwh": bess_soc_end[-1] - bess_soc_start[0],
            "terminal_target_deviation_kwh": (
                bess_soc_end[-1] - terminal_target_kwh
                if terminal_target_kwh is not None
                else None
            ),
            "observed_min_soc_kwh": min(min(bess_soc_start), min(bess_soc_end)),
            "observed_max_soc_kwh": max(max(bess_soc_start), max(bess_soc_end)),
            "charge_efficiency": charge_efficiency,
            "discharge_efficiency": discharge_efficiency,
            "terminal_validation_deviation_kwh": _number(
                validation_metrics.get("bess_terminal_soc_deviation_kwh")
            ),
        },
        "daily_energy": daily,
        "fuel": {
            "service_distance_km": operation["service_distance_km"]["ICE"],
            "intertrip_deadhead_distance_km": operation["intertrip_deadhead_distance_km"]["ICE"],
            "service_fuel_l": operation["fuel_service_l"],
            "intertrip_deadhead_fuel_l": operation["fuel_intertrip_deadhead_l"],
            "total_fuel_l": operation["fuel_total_l"],
            "diesel_price_yen_per_l": fuel_price,
            "expected_distance_based_cost_jpy": expected_fuel_cost,
            "reported_fuel_cost_final_jpy": reported_fuel_cost,
            "cost_residual_jpy": reported_fuel_cost - expected_fuel_cost,
            "reported_source": result.get("cost_breakdown", {}).get("fuel_cost_final_source"),
            "realized_refuel_cost_jpy": _number(result.get("fuel_cost_realized_jpy")),
            "refueling_event_count": len(result.get("refueling_schedule") or []),
            "interpretation": (
                "assigned service and inter-trip deadhead distance accounting; "
                "not a realized tank/refuelling ledger"
            ),
        },
        "costs_jpy": dict(summary.get("costs_jpy") or result.get("cost_breakdown") or {}),
        "balances": {
            "tolerance_kwh": BALANCE_TOLERANCE,
            "max_absolute_residuals": max_residuals,
            "all_balances_passed": balance_passed,
        },
        "validation_metrics": validation_metrics,
        "slot_rows": rows,
    }


def _advisor_case_acceptance(case: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate the supervisor-facing representative-day evidence contract."""

    parameters = dict(case.get("scenario_parameters") or {})
    solver = dict(case.get("solver") or {})
    operation = dict(case.get("operation") or {})
    balances = dict(case.get("balances") or {})
    bess = dict(case.get("bess") or {})
    fuel = dict(case.get("fuel") or {})
    validation = dict(case.get("validation_metrics") or {})
    rolling = dict(case.get("rolling") or {})
    assigned_counts = dict(operation.get("assigned_trip_count") or {})
    charger_ports_by_power_kw: dict[float, int] = {}
    for charger in parameters.get("charger_configuration") or []:
        if not isinstance(charger, Mapping):
            continue
        power_kw = float(charger.get("power_kw") or 0.0)
        charger_ports_by_power_kw[power_kw] = (
            charger_ports_by_power_kw.get(power_kw, 0)
            + int(charger.get("simultaneous_ports") or 0)
        )
    checks = {
        "git_clean": case.get("git_dirty") is False,
        "formal_research_run_accepted": (
            solver.get("research_run") is True
            and solver.get("research_run_accepted") is True
        ),
        "calendar_matches_service_table": dict(
            parameters.get("calendar_service_contract") or {}
        ).get("matches")
        is True,
        "weather_pv_curve_applied": (
            parameters.get("weather_pv_forecast_applied") is True
            and not parameters.get("weather_pv_forecast_skip_reason")
        ),
        "formal_fleet_bev35_ice26": parameters.get("fleet")
        == {"BEV": 35, "ICE": 26},
        "fleet_matches_declared_expectation": parameters.get("fleet")
        == parameters.get("expected_fleet"),
        "minimum_used_bev_policy_satisfied": int(
            operation.get("used_vehicle_count", {}).get("BEV") or 0
        )
        >= int(parameters.get("minimum_used_bev_count") or 0),
        "hourly_rolling_chain_accepted": (
            not rolling.get("required")
            or (
                rolling.get("chain_accepted") is True
                and int(rolling.get("execution_minutes") or 0) == 60
                and rolling.get("all_steps_feasible") is True
                and rolling.get("scenario_id") == case.get("scenario_id")
                and rolling.get("prepared_input_id")
                == case.get("prepared_input_id")
                and rolling.get("service_date") == case.get("service_date")
                and rolling.get("trip_input_hash") == case.get("trip_input_hash")
                and rolling.get("vehicle_input_hash")
                == case.get("vehicle_input_hash")
                and rolling.get("day_ahead_git_sha") == case.get("git_sha")
                and rolling.get("day_ahead_result_sha256")
                == case.get("solver_result_sha256")
            )
        ),
        "all_trips_assigned": sum(int(value) for value in assigned_counts.values())
        == int(parameters.get("trip_count") or 0),
        "all_hard_validations_passed": validation.get(
            "all_required_validation_checks_passed"
        )
        is True,
        "all_energy_balances_passed": balances.get("all_balances_passed") is True,
        "bev_terminal_soc_balanced": solver.get(
            "bev_terminal_soc_balance_satisfied"
        )
        is True,
        "bess_terminal_target_declared": bess.get("terminal_target_kwh") is not None,
        "bess_terminal_soc_balanced": (
            bess.get("terminal_target_deviation_kwh") is not None
            and abs(float(bess["terminal_target_deviation_kwh"]))
            <= BALANCE_TOLERANCE
        ),
        "physical_charger_assignment_enforced": solver.get(
            "physical_charger_assignment_semantics"
        )
        == (
            "one_physical_charger_definition_per_active_vehicle_slot; "
            "simultaneous_ports_are_identical_ports"
        ),
        "charger_inventory_90kw5_50kw5": charger_ports_by_power_kw
        == {90.0: 5, 50.0: 5},
        "fuel_cost_reconciled": (
            fuel.get("cost_residual_jpy") is not None
            and math.isfinite(float(fuel["cost_residual_jpy"]))
            and abs(float(fuel["cost_residual_jpy"]))
            <= FUEL_COST_TOLERANCE_JPY
        ),
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    return {
        "accepted": not failed,
        "checks": checks,
        "failed_checks": failed,
        "scope": (
            "representative_day_feasibility_and_accounting_evidence; "
            "not_global_total_cost_optimality"
        ),
        "charger_ports_by_power_kw": {
            str(power_kw): count
            for power_kw, count in sorted(charger_ports_by_power_kw.items())
        },
    }


def _rolling_evidence(path: str | Path | None, *, required: bool) -> dict[str, Any]:
    if not path:
        return {
            "required": required,
            "provided": False,
            "chain_accepted": False,
            "all_steps_feasible": False,
            "execution_minutes": None,
            "step_count": 0,
        }
    summary_path = Path(path).resolve()
    payload = _load_json(summary_path)
    return {
        "required": required,
        "provided": True,
        "path": str(summary_path),
        "chain_accepted": payload.get("chain_accepted") is True,
        "all_steps_feasible": payload.get("all_steps_feasible") is True,
        "execution_minutes": payload.get("execution_minutes"),
        "step_count": int(payload.get("step_count") or 0),
        "scenario_id": payload.get("scenario_id"),
        "prepared_input_id": payload.get("prepared_input_id"),
        "service_date": payload.get("service_date"),
        "trip_input_hash": payload.get("trip_input_hash"),
        "vehicle_input_hash": payload.get("vehicle_input_hash"),
        "day_ahead_git_sha": payload.get("day_ahead_git_sha"),
        "day_ahead_result_sha256": payload.get("day_ahead_result_sha256"),
        "acceptance_checks": dict(payload.get("acceptance_checks") or {}),
    }


def _write_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"Cannot write empty CSV: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def run(args: argparse.Namespace) -> int:
    outputs_root = Path(args.outputs_root).resolve()
    audit_dir = Path(args.audit_dir).resolve()
    audit_dir.mkdir(parents=True, exist_ok=True)
    sunny_run = Path(args.sunny_run).resolve()
    rain_run = Path(args.rain_run).resolve()
    sunny_summary_path = sunny_run / "summary.json"
    rain_summary_path = rain_run / "summary.json"
    sunny_summary = _load_json(sunny_summary_path)
    rain_summary = _load_json(rain_summary_path)
    _validate_manifest("sunny", sunny_summary_path, sunny_summary)
    _validate_manifest("rain", rain_summary_path, rain_summary)
    build_weather_comparison(sunny_summary, rain_summary)
    cases = {
        "sunny": _audit_case(
            case_key="sunny",
            run_dir=sunny_run,
            outputs_root=outputs_root,
        ),
        "rain": _audit_case(
            case_key="rain",
            run_dir=rain_run,
            outputs_root=outputs_root,
        ),
    }
    require_rolling = bool(getattr(args, "require_rolling", False))
    cases["sunny"]["rolling"] = _rolling_evidence(
        getattr(args, "sunny_rolling_summary", None),
        required=require_rolling,
    )
    cases["rain"]["rolling"] = _rolling_evidence(
        getattr(args, "rain_rolling_summary", None),
        required=require_rolling,
    )
    advisor_acceptance = {
        case_key: _advisor_case_acceptance(case)
        for case_key, case in cases.items()
    }
    advisor_acceptance["all_cases_accepted"] = all(
        item["accepted"]
        for item in advisor_acceptance.values()
        if isinstance(item, Mapping)
    )
    fleet_discrepancy = {
        "requested_text_ice_count": 26,
        "recorded_model_input_ice_count": int(cases["sunny"]["fleet_input"]["ICE"]),
        "matches": int(cases["sunny"]["fleet_input"]["ICE"]) == 26,
        "handling": (
            "The formal evidence requires BEV 35 / ICE 26. A different input "
            "is rejected unless it is run and labelled as a separate sensitivity."
        ),
    }
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology": {
            "solver_rerun": False,
            "canonical_input_rebuilt_for_lookup": True,
            "trip_and_vehicle_hashes_verified": True,
            "fuel_semantics": "provisional_distance_based",
            "balance_tolerance_kwh": BALANCE_TOLERANCE,
        },
        "known_input_discrepancy": fleet_discrepancy,
        "advisor_acceptance": advisor_acceptance,
        "cases": cases,
        "comparison": {
            "used_bev_delta_rain_minus_sunny": (
                cases["rain"]["operation"]["used_vehicle_count"]["BEV"]
                - cases["sunny"]["operation"]["used_vehicle_count"]["BEV"]
            ),
            "used_ice_delta_rain_minus_sunny": (
                cases["rain"]["operation"]["used_vehicle_count"]["ICE"]
                - cases["sunny"]["operation"]["used_vehicle_count"]["ICE"]
            ),
            "fuel_l_delta_rain_minus_sunny": (
                cases["rain"]["fuel"]["total_fuel_l"]
                - cases["sunny"]["fuel"]["total_fuel_l"]
            ),
            "pv_generated_delta_rain_minus_sunny_kwh": (
                cases["rain"]["daily_energy"]["pv_generated_kwh"]
                - cases["sunny"]["daily_energy"]["pv_generated_kwh"]
            ),
            "grid_import_delta_rain_minus_sunny_kwh": (
                cases["rain"]["daily_energy"]["grid_import_kwh"]
                - cases["sunny"]["daily_energy"]["grid_import_kwh"]
            ),
        },
    }
    audit_path = audit_dir / "weather_energy_balance_audit.json"
    audit_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    hourly_rows: list[dict[str, Any]] = []
    for case_key, case in cases.items():
        for row in case["slot_rows"]:
            hourly_rows.append(
                {
                    "case_key": case_key,
                    "case_label": case["case_label"],
                    "service_date": case["service_date"],
                    **row,
                }
            )
    _write_csv(audit_dir / "weather_energy_hourly.csv", hourly_rows)
    daily_rows: list[dict[str, Any]] = []
    for case_key, case in cases.items():
        daily_rows.append(
            {
                "case_key": case_key,
                "case_label": case["case_label"],
                "service_date": case["service_date"],
                "fleet_bev": case["fleet_input"]["BEV"],
                "fleet_ice": case["fleet_input"]["ICE"],
                "used_bev": case["operation"]["used_vehicle_count"]["BEV"],
                "used_ice": case["operation"]["used_vehicle_count"]["ICE"],
                "bev_trips": case["operation"]["assigned_trip_count"]["BEV"],
                "ice_trips": case["operation"]["assigned_trip_count"]["ICE"],
                "pv_generated_kwh": case["daily_energy"]["pv_generated_kwh"],
                "pv_to_bus_kwh": case["daily_energy"]["pv_to_bus_kwh"],
                "pv_to_bess_kwh": case["daily_energy"]["pv_to_bess_kwh"],
                "pv_curtailed_kwh": case["daily_energy"]["pv_curtailed_kwh"],
                "grid_import_kwh": case["daily_energy"]["grid_import_kwh"],
                "peak_grid_import_kw": case["daily_energy"]["peak_grid_import_kw"],
                "bess_initial_soc_kwh": case["bess"]["initial_soc_kwh"],
                "bess_terminal_soc_kwh": case["bess"]["terminal_soc_kwh"],
                "bess_terminal_delta_kwh": case["bess"]["terminal_delta_kwh"],
                "ice_service_distance_km": case["fuel"]["service_distance_km"],
                "ice_intertrip_deadhead_distance_km": case["fuel"]["intertrip_deadhead_distance_km"],
                "fuel_total_l": case["fuel"]["total_fuel_l"],
                "fuel_cost_jpy": case["fuel"]["reported_fuel_cost_final_jpy"],
                "fuel_cost_residual_jpy": case["fuel"]["cost_residual_jpy"],
                "all_energy_balances_passed": case["balances"]["all_balances_passed"],
            }
        )
    _write_csv(audit_dir / "weather_energy_daily_summary.csv", daily_rows)
    print(audit_path)
    print(audit_dir / "weather_energy_hourly.csv")
    print(audit_dir / "weather_energy_daily_summary.csv")
    return 0 if advisor_acceptance["all_cases_accepted"] else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs-root", default=str(DEFAULT_OUTPUTS_ROOT))
    parser.add_argument("--sunny-run", required=True)
    parser.add_argument("--rain-run", required=True)
    parser.add_argument("--audit-dir", required=True)
    parser.add_argument(
        "--require-rolling",
        action="store_true",
        help="Require accepted 60-minute rolling chains for both cases.",
    )
    parser.add_argument("--sunny-rolling-summary")
    parser.add_argument("--rain-rolling-summary")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
