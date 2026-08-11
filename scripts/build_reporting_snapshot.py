"""Build a presentation-only release from an accepted controlled PV pair.

This postprocessor never invokes an optimizer and never mutates either source
run.  It freezes one deterministic reporting snapshot from the final trip
assignment, accepted hourly Rolling execution, physical validation, effective
solver settings, and the immutable pair-control evidence.  Every public
artifact is then generated from that snapshot and carries the same snapshot
digest.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Iterable, Mapping, Sequence
import uuid
import zipfile

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKBOOK_BUILDER = REPO_ROOT / "scripts" / "build_reporting_snapshot_workbook.mjs"
WORKBOOK_SHEET_NAMES = (
    "Summary",
    "Vehicle Assignment",
    "Energy Balance",
    "Cost Breakdown",
    "Validation",
    "Hourly Energy",
    "Hourly SOC",
    "Provenance",
)

CASE_ORDER = ("sunny", "rain")
CASE_DISPLAY_NAMES = {"sunny": "High PV", "rain": "Low PV"}
CASE_ROLES = {"sunny": "baseline", "rain": "counterfactual"}
ELECTRIC_POWERTRAINS = {"BEV", "PHEV", "FCEV"}
COST_TOLERANCE_JPY = 0.01
ENERGY_TOLERANCE_KWH = 1.0e-6
SOC_TOLERANCE_KWH = 1.0e-6
STALE_RELEASE_MARKERS = (
    b"vehicle-soc-violation",
    b"OUT_OF_SCOPE_REMAINS",
    b"Remains because this run was not re-optimized.",
)

PUBLIC_CASE_SOURCES = {
    "trip_assignment": "graph/trip_assignment.csv",
    "executed_day_accounting": (
        "rolling_hourly_chain/executed_day_accounting.json"
    ),
    "hourly_rolling_energy": (
        "rolling_hourly_chain/hourly_energy_flow_chart.csv"
    ),
    "rolling_chain_summary": (
        "rolling_hourly_chain/rolling_chain_summary.json"
    ),
    "physical_schedule_validation": "graph/physical_schedule_validation.json",
    "solver_settings": "solver_settings.json",
    "optimization_parameters": "optimization_parameters.json",
    "comparison_case_manifest": "comparison_case_manifest.json",
    "case_execution_metadata": "case_execution_metadata.json",
    "frontend_job_terminal_response": "frontend_job_terminal_response.json",
    "frontend_depot_energy_asset_request": (
        "frontend_depot_energy_asset_request.json"
    ),
}
PAIR_SOURCES = {
    "canonical_pair_manifest": "pair/pair_manifest.json",
    "tariff_condition": "tariff_condition.json",
}

FIGURE_NAMES = (
    "cost_comparison.png",
    "dispatch_comparison.png",
    "energy_flow_baseline.png",
    "energy_flow_low_pv.png",
    "soc_baseline.png",
    "soc_low_pv.png",
)


class ReportingSnapshotError(RuntimeError):
    """Raised when canonicalization or a fail-closed release gate fails."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReportingSnapshotError(f"Cannot read JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise ReportingSnapshotError(f"Expected JSON object: {path}")
    return dict(value)


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = list(reader.fieldnames or ())
            rows = [dict(row) for row in reader]
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ReportingSnapshotError(f"Cannot read CSV relation: {path}") from exc
    if not fields:
        raise ReportingSnapshotError(f"CSV has no schema: {path}")
    return fields, rows


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_csv(
    path: Path,
    fields: Sequence[str],
    rows: Iterable[Mapping[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fields), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _number(value: Any, *, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ReportingSnapshotError(f"Expected finite number for {field}: {value!r}") from exc
    if not math.isfinite(result):
        raise ReportingSnapshotError(f"Expected finite number for {field}: {value!r}")
    return result


def _integer(value: Any, *, field: str) -> int:
    number = _number(value, field=field)
    rounded = round(number)
    if abs(number - rounded) > 1.0e-9:
        raise ReportingSnapshotError(f"Expected integer for {field}: {value!r}")
    return int(rounded)


def _optional_number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "ok"}


def _source_record(pair_dir: Path, path: Path, role: str) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise ReportingSnapshotError(f"Missing or empty required source: {path}")
    return {
        "role": role,
        "path": path.relative_to(pair_dir).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _source_paths(pair_dir: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for case in CASE_ORDER:
        case_dir = pair_dir / case
        for role, relative in PUBLIC_CASE_SOURCES.items():
            paths[f"{case}.{role}"] = case_dir / relative
    for role, relative in PAIR_SOURCES.items():
        paths[f"pair.{role}"] = pair_dir / relative
    return paths


def _hash_sources(paths: Mapping[str, Path]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for role, path in paths.items():
        if not path.is_file() or path.stat().st_size <= 0:
            raise ReportingSnapshotError(f"Missing or empty required source: {path}")
        hashes[role] = _sha256(path)
    return hashes


def _normal_powertrain(value: Any) -> str:
    token = str(value or "").strip().upper()
    if token in ELECTRIC_POWERTRAINS:
        return "BEV"
    if token in {"ICE", "DIESEL", "COMBUSTION"}:
        return "ICE"
    return token


def _assignment_summary(
    case: str,
    case_label: str,
    fields: Sequence[str],
    rows: Sequence[Mapping[str, str]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    required = {
        "trip_id",
        "assigned_vehicle_id",
        "assigned_vehicle_type",
        "served_flag",
    }
    missing = sorted(required.difference(fields))
    if missing:
        raise ReportingSnapshotError(
            f"{case} trip_assignment.csv missing columns: {missing}"
        )
    if not rows:
        raise ReportingSnapshotError(f"{case} trip_assignment.csv has no rows")

    trip_ids: set[str] = set()
    used_by_type: dict[str, set[str]] = {"BEV": set(), "ICE": set()}
    trips_by_type = {"BEV": 0, "ICE": 0}
    public_rows: list[dict[str, Any]] = []
    unserved = 0
    for source in rows:
        trip_id = str(source.get("trip_id") or "").strip()
        if not trip_id:
            raise ReportingSnapshotError(f"{case} assignment contains blank trip_id")
        if trip_id in trip_ids:
            raise ReportingSnapshotError(f"{case} duplicate trip assignment: {trip_id}")
        trip_ids.add(trip_id)
        served = _as_bool(source.get("served_flag"))
        vehicle_id = str(source.get("assigned_vehicle_id") or "").strip()
        powertrain = _normal_powertrain(source.get("assigned_vehicle_type"))
        if served:
            if not vehicle_id or powertrain not in {"BEV", "ICE"}:
                raise ReportingSnapshotError(
                    f"{case} served trip lacks supported assignment: {trip_id}"
                )
            trips_by_type[powertrain] += 1
            used_by_type[powertrain].add(vehicle_id)
        else:
            unserved += 1
        public_rows.append(
            {
                "case": case,
                "case_label": case_label,
                **dict(source),
            }
        )

    ambiguous_vehicle_ids = used_by_type["BEV"] & used_by_type["ICE"]
    if ambiguous_vehicle_ids:
        raise ReportingSnapshotError(
            f"{case} vehicle IDs assigned to multiple powertrains: "
            + ", ".join(sorted(ambiguous_vehicle_ids))
        )
    used_all = used_by_type["BEV"] | used_by_type["ICE"]
    return (
        {
            "total_trip_count": len(rows),
            "served_trip_count": len(rows) - unserved,
            "unserved_trip_count": unserved,
            "bev_trip_count": trips_by_type["BEV"],
            "ice_trip_count": trips_by_type["ICE"],
            "used_vehicle_count": len(used_all),
            "used_bev_count": len(used_by_type["BEV"]),
            "used_ice_count": len(used_by_type["ICE"]),
            "used_vehicle_ids": sorted(used_all),
            "used_bev_ids": sorted(used_by_type["BEV"]),
            "used_ice_ids": sorted(used_by_type["ICE"]),
        },
        public_rows,
    )


def _required_cost_component(cost: Mapping[str, Any], *keys: str) -> float:
    for key in keys:
        if cost.get(key) is not None:
            return _number(cost.get(key), field=f"cost_breakdown.{key}")
    raise ReportingSnapshotError(
        "Missing required executed-day accounting field: " + " or ".join(keys)
    )


def _accounting_summary(accounting: Mapping[str, Any]) -> dict[str, Any]:
    if not _as_bool(accounting.get("eligible")):
        raise ReportingSnapshotError("executed_day_accounting is not eligible")
    raw_cost = accounting.get("cost_breakdown")
    if not isinstance(raw_cost, Mapping):
        raise ReportingSnapshotError("executed_day_accounting lacks cost_breakdown")
    cost = dict(raw_cost)

    components = {
        "electricity_cost_jpy": _required_cost_component(cost, "electricity_cost"),
        "demand_cost_jpy": _required_cost_component(cost, "demand_cost"),
        "fuel_cost_jpy": _required_cost_component(cost, "fuel_cost"),
        "vehicle_usage_cost_jpy": _required_cost_component(
            cost, "vehicle_usage_cost_jpy", "vehicle_usage_cost"
        ),
        "co2_cost_jpy": _required_cost_component(cost, "co2_cost"),
        "battery_degradation_cost_jpy": _required_cost_component(
            cost, "battery_degradation_cost", "degradation_cost"
        ),
        "contract_overage_cost_jpy": _required_cost_component(
            cost, "contract_overage_cost"
        ),
    }
    reported_total = _required_cost_component(cost, "total_cost")
    component_total = sum(components.values())

    terminal_by_depot = accounting.get("bess_terminal_soc_by_depot")
    if not isinstance(terminal_by_depot, Mapping) or not terminal_by_depot:
        raise ReportingSnapshotError("Missing BESS terminal SOC evidence")
    bess_by_depot: dict[str, dict[str, Any]] = {}
    for depot, raw in terminal_by_depot.items():
        if not isinstance(raw, Mapping):
            raise ReportingSnapshotError(f"Invalid BESS terminal SOC: {depot}")
        bess_by_depot[str(depot)] = {
            "policy": str(raw.get("policy") or ""),
            "initial_soc_kwh": _number(
                raw.get("initial_soc_kwh"), field=f"{depot}.initial_soc_kwh"
            ),
            "target_soc_kwh": _number(
                raw.get("target_soc_kwh"), field=f"{depot}.target_soc_kwh"
            ),
            "terminal_soc_kwh": _number(
                raw.get("terminal_soc_kwh"), field=f"{depot}.terminal_soc_kwh"
            ),
            "absolute_deviation_kwh": _number(
                raw.get("absolute_deviation_kwh"),
                field=f"{depot}.absolute_deviation_kwh",
            ),
            "balanced": _as_bool(raw.get("balanced")),
        }

    energy = {
        "pv_generated_kwh": _required_cost_component(cost, "pv_generated_kwh"),
        "pv_to_bus_kwh": _required_cost_component(cost, "pv_to_bus_kwh"),
        "pv_to_bess_kwh": _required_cost_component(cost, "pv_to_bess_kwh"),
        "bess_to_bus_kwh": _required_cost_component(cost, "bess_to_bus_kwh"),
        "grid_import_kwh": _required_cost_component(cost, "grid_import_kwh"),
        "grid_to_bus_kwh": _required_cost_component(cost, "grid_to_bus_kwh"),
        "grid_to_bess_kwh": _required_cost_component(cost, "grid_to_bess_kwh"),
        "pv_curtailed_kwh": _required_cost_component(
            cost, "pv_curtailed_kwh", "pv_curtail_kwh"
        ),
        "peak_grid_kw": _required_cost_component(cost, "peak_grid_kw"),
    }
    energy["pv_balance_residual_kwh"] = energy["pv_generated_kwh"] - (
        energy["pv_to_bus_kwh"]
        + energy["pv_to_bess_kwh"]
        + energy["pv_curtailed_kwh"]
    )
    energy["grid_balance_residual_kwh"] = energy["grid_import_kwh"] - (
        energy["grid_to_bus_kwh"] + energy["grid_to_bess_kwh"]
    )

    return {
        "accounting_basis": str(accounting.get("accounting_basis") or ""),
        "eligible": True,
        "published_cost_basis": "accepted_24_hour_rolling_executed_day_accounting",
        "internal_search_objective_excluded": True,
        "cost": {
            **components,
            "accounting_component_sum_jpy": component_total,
            "accounting_total_cost_jpy": reported_total,
            "accounting_residual_jpy": reported_total - component_total,
            "vehicle_usage_cost_jpy_per_used_bus": _required_cost_component(
                cost, "vehicle_usage_cost_jpy_per_used_bus"
            ),
            "used_vehicle_day_count": _integer(
                _required_cost_component(cost, "used_vehicle_day_count"),
                field="cost_breakdown.used_vehicle_day_count",
            ),
        },
        "energy": energy,
        "emissions": {
            "total_co2_kg": _required_cost_component(cost, "total_co2_kg"),
            "grid_electricity_co2_kg": _required_cost_component(
                cost, "grid_electricity_co2_kg"
            ),
            "ice_co2_kg": _required_cost_component(cost, "ice_co2_kg"),
        },
        "bess_terminal_soc_by_depot": bess_by_depot,
        "bev_terminal_energy_balanced": _as_bool(
            accounting.get("bev_terminal_energy_balanced")
        ),
        "bess_terminal_energy_balanced": _as_bool(
            accounting.get("bess_terminal_energy_balanced")
        ),
        "terminal_energy_balanced": _as_bool(
            accounting.get("terminal_energy_balanced")
        ),
    }


def _hourly_summary(rows: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    if len(rows) != 24:
        raise ReportingSnapshotError(
            f"Expected 24 Rolling energy rows, observed {len(rows)}"
        )
    parsed: list[dict[str, Any]] = []
    observed_steps: set[int] = set()
    for raw in rows:
        step = _integer(raw.get("step_index"), field="hourly.step_index")
        if step in observed_steps:
            raise ReportingSnapshotError(f"Duplicate Rolling step: {step}")
        observed_steps.add(step)
        try:
            bess_by_depot = json.loads(str(raw.get("bess_end_soc_kwh_by_depot") or "{}"))
        except json.JSONDecodeError as exc:
            raise ReportingSnapshotError("Invalid hourly BESS SOC JSON") from exc
        if not isinstance(bess_by_depot, Mapping):
            raise ReportingSnapshotError("Hourly BESS SOC must be an object")
        parsed.append(
            {
                "step_index": step,
                "time": str(raw.get("current_time") or ""),
                "execution_minutes": _integer(
                    raw.get("execution_minutes"), field="execution_minutes"
                ),
                "pv_generated_kwh": _number(
                    raw.get("pv_generated_kwh"), field="hourly.pv_generated_kwh"
                ),
                "pv_to_bus_kwh": _number(
                    raw.get("pv_to_bus_kwh"), field="hourly.pv_to_bus_kwh"
                ),
                "pv_to_bess_kwh": _number(
                    raw.get("pv_to_bess_kwh"), field="hourly.pv_to_bess_kwh"
                ),
                "pv_curtailed_kwh": _number(
                    raw.get("pv_curtailed_kwh"), field="hourly.pv_curtailed_kwh"
                ),
                "bess_to_bus_kwh": _number(
                    raw.get("bess_to_bus_kwh"), field="hourly.bess_to_bus_kwh"
                ),
                "grid_to_bus_kwh": _number(
                    raw.get("grid_to_bus_kwh"), field="hourly.grid_to_bus_kwh"
                ),
                "grid_to_bess_kwh": _number(
                    raw.get("grid_to_bess_kwh"), field="hourly.grid_to_bess_kwh"
                ),
                "bess_end_soc_kwh": sum(
                    _number(value, field=f"hourly.bess.{depot}")
                    for depot, value in bess_by_depot.items()
                ),
                "bev_soc_min_kwh": _optional_number(raw.get("bev_soc_min_kwh")),
                "bev_soc_mean_kwh": _optional_number(raw.get("bev_soc_mean_kwh")),
                "charging_kw_max": _number(
                    raw.get("charging_kw_max"), field="hourly.charging_kw_max"
                ),
                "grid_kw_max": _number(
                    raw.get("on_peak_kw_max"), field="hourly.on_peak_kw_max"
                )
                + _number(
                    raw.get("off_peak_kw_max"), field="hourly.off_peak_kw_max"
                ),
            }
        )
    parsed.sort(key=lambda row: row["step_index"])
    if [row["step_index"] for row in parsed] != list(range(24)):
        raise ReportingSnapshotError("Rolling steps must be exactly 0..23")
    return parsed


def _solution_quality(
    raw_status: str,
    solver: Mapping[str, Any],
) -> dict[str, Any]:
    time_limit_requested = _integer(
        solver.get("time_limit_seconds_requested"),
        field="time_limit_seconds_requested",
    )
    time_limit_effective = _integer(
        solver.get("time_limit_seconds_effective"),
        field="time_limit_seconds_effective",
    )
    requested_gap_ratio = _number(
        solver.get("mip_gap_requested_ratio"), field="mip_gap_requested_ratio"
    )
    requested_gap = _number(
        solver.get("mip_gap_requested_percent"), field="mip_gap_requested_percent"
    )
    certified_gap = _number(
        solver.get("certified_mip_gap_percent"), field="certified_mip_gap_percent"
    )
    raw_gap_ratio = _number(
        solver.get("gurobi_raw_mip_gap_ratio"), field="gurobi_raw_mip_gap_ratio"
    )
    feasible = _as_bool(solver.get("has_feasible_incumbent"))
    target_met = _as_bool(solver.get("mip_gap_target_met"))
    normalized_status = raw_status.strip().lower()
    if normalized_status == "optimal" and feasible and target_met:
        label = "SOLVED_WITHIN_DECLARED_GAP"
        display = (
            f"Solved within {requested_gap:.3g}% tolerance "
            f"(certified gap {certified_gap:.3f}%)"
        )
    elif feasible and target_met:
        label = "CERTIFIED_NEAR_OPTIMAL"
        display = f"Certified near-optimal (gap upper bound {certified_gap:.3f}%)"
    elif feasible:
        label = "FEASIBLE_GAP_NOT_MET"
        display = f"Feasible incumbent; certified gap {certified_gap:.3f}%"
    else:
        label = "NO_FEASIBLE_INCUMBENT"
        display = "No feasible incumbent"
    return {
        "raw_solver_status": normalized_status,
        "solution_quality_label": label,
        "solution_quality_display": display,
        "has_feasible_incumbent": feasible,
        "time_limit_seconds_requested": time_limit_requested,
        "time_limit_seconds_effective": time_limit_effective,
        "requested_gap_ratio": requested_gap_ratio,
        "requested_gap_percent": requested_gap,
        "gurobi_raw_gap_percent": raw_gap_ratio * 100.0,
        "certified_gap_percent": certified_gap,
        "certified_gap_semantics": str(
            solver.get("certified_mip_gap_semantics") or ""
        ),
        "requested_gap_certificate_met": target_met,
        "solve_time_sec": _number(solver.get("solve_time_sec"), field="solve_time_sec"),
    }


def _effective_controls(
    optimization: Mapping[str, Any],
    rolling: Mapping[str, Any],
) -> dict[str, Any]:
    config = optimization.get("effective_optimization_config")
    problem = optimization.get("effective_problem_scenario")
    metadata = optimization.get("effective_model_metadata")
    if not isinstance(config, Mapping) or not isinstance(problem, Mapping):
        raise ReportingSnapshotError("optimization_parameters lacks effective values")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    return {
        "executed_phase": str(config.get("phase") or ""),
        "day_ahead_time_limit_sec": _integer(
            config.get("time_limit_sec"), field="effective.time_limit_sec"
        ),
        "day_ahead_mip_gap_ratio": _number(
            config.get("mip_gap"), field="effective.mip_gap"
        ),
        "gurobi_threads": _integer(
            config.get("gurobi_threads"), field="effective.gurobi_threads"
        ),
        "random_seed": _integer(
            config.get("random_seed"), field="effective.random_seed"
        ),
        "timestep_min": _integer(
            problem.get("timestep_min"), field="effective.timestep_min"
        ),
        "service_coverage_mode": str(problem.get("service_coverage_mode") or ""),
        "vehicle_usage_cost_jpy_per_used_bus": _number(
            metadata.get("vehicle_usage_cost_jpy_per_used_bus"),
            field="effective.vehicle_usage_cost_jpy_per_used_bus",
        ),
        "rolling_step_count": _integer(
            rolling.get("step_count"), field="rolling.step_count"
        ),
        "rolling_expected_step_count": _integer(
            rolling.get("expected_step_count"),
            field="rolling.expected_step_count",
        ),
        "rolling_time_limit_sec_per_step": _number(
            rolling.get("time_limit_sec"), field="rolling.time_limit_sec"
        ),
        "rolling_mip_gap_ratio": _number(
            rolling.get("mip_gap"), field="rolling.mip_gap"
        ),
        "rolling_chain_accepted": _as_bool(rolling.get("chain_accepted")),
    }


def _asset_summary(asset: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "depot_id": str(asset.get("depot_id") or ""),
        "pv_rated_output_kw": _number(
            asset.get("pv_capacity_kw"), field="asset.pv_capacity_kw"
        ),
        "pv_capacity_input_mode": str(asset.get("pv_capacity_input_mode") or ""),
        "pv_capacity_manual_override": _as_bool(
            asset.get("pv_capacity_kw_manual_override")
        ),
        "estimated_pv_panel_area_from_rated_output_m2": _number(
            asset.get("estimated_installable_area_m2"),
            field="asset.estimated_installable_area_m2",
        ),
        "estimated_required_depot_area_from_rated_output_m2": _number(
            asset.get("estimated_depot_area_from_pv_capacity_m2"),
            field="asset.estimated_depot_area_from_pv_capacity_m2",
        ),
        "area_inferred_pv_capacity_kw": _number(
            asset.get("derived_pv_capacity_kw"),
            field="asset.derived_pv_capacity_kw",
        ),
        "panel_power_density_kw_per_m2": _number(
            asset.get("panel_power_density_kw_m2"),
            field="asset.panel_power_density_kw_m2",
        ),
        "usable_area_ratio": _number(
            asset.get("usable_area_ratio"), field="asset.usable_area_ratio"
        ),
        "observed_depot_area_m2": _number(
            asset.get("depot_area_m2"), field="asset.depot_area_m2"
        ),
        "bess_energy_capacity_kwh": _number(
            asset.get("bess_energy_kwh"), field="asset.bess_energy_kwh"
        ),
        "bess_power_capacity_kw": _number(
            asset.get("bess_power_kw"), field="asset.bess_power_kw"
        ),
        "bess_initial_soc_kwh": _number(
            asset.get("bess_initial_soc_kwh"), field="asset.bess_initial_soc_kwh"
        ),
        "bess_terminal_soc_target_kwh": _number(
            asset.get("bess_terminal_soc_target_kwh"),
            field="asset.bess_terminal_soc_target_kwh",
        ),
        "pv_source_date": str(asset.get("pv_source_date") or ""),
        "pv_profile_case_id": str(asset.get("pv_case_id") or ""),
    }


def _case_gate(
    name: str,
    passed: bool,
    observed: Any,
    expected: Any,
    source: str,
) -> dict[str, Any]:
    return {
        "gate": name,
        "status": "OK" if passed else "FAIL",
        "passed": bool(passed),
        "observed": observed,
        "expected": expected,
        "source": source,
    }


def _build_case(pair_dir: Path, case: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    case_dir = pair_dir / case
    paths = {role: case_dir / relative for role, relative in PUBLIC_CASE_SOURCES.items()}
    comparison = _read_json(paths["comparison_case_manifest"])
    pv_reference_date = str(comparison.get("pv_source_date") or "").strip()
    case_label = CASE_DISPLAY_NAMES[case]
    if pv_reference_date:
        case_label = f"{case_label} ({pv_reference_date} curve)"
    assignment_fields, assignment_rows = _read_csv(paths["trip_assignment"])
    assignment, public_assignment_rows = _assignment_summary(
        case, case_label, assignment_fields, assignment_rows
    )
    accounting = _accounting_summary(_read_json(paths["executed_day_accounting"]))
    _, hourly_rows = _read_csv(paths["hourly_rolling_energy"])
    hourly = _hourly_summary(hourly_rows)
    physical = _read_json(paths["physical_schedule_validation"])
    solver = _read_json(paths["solver_settings"])
    optimization = _read_json(paths["optimization_parameters"])
    execution = _read_json(paths["case_execution_metadata"])
    terminal = _read_json(paths["frontend_job_terminal_response"])
    rolling = _read_json(paths["rolling_chain_summary"])
    asset = _asset_summary(_read_json(paths["frontend_depot_energy_asset_request"]))

    raw_solver_status = str(
        (terminal.get("metadata") or {}).get("solver_status") or ""
    )
    quality = _solution_quality(raw_solver_status, solver)
    controls = _effective_controls(optimization, rolling)

    cost = accounting["cost"]
    energy = accounting["energy"]
    hourly_totals = {
        key: sum(row[key] for row in hourly)
        for key in (
            "pv_generated_kwh",
            "pv_to_bus_kwh",
            "pv_to_bess_kwh",
            "pv_curtailed_kwh",
            "bess_to_bus_kwh",
            "grid_to_bus_kwh",
            "grid_to_bess_kwh",
        )
    }
    hourly_totals["grid_import_kwh"] = (
        hourly_totals["grid_to_bus_kwh"] + hourly_totals["grid_to_bess_kwh"]
    )

    metrics = physical.get("validation_metrics")
    if not isinstance(metrics, Mapping):
        raise ReportingSnapshotError(f"{case} missing physical validation metrics")
    zero_metric_values = {
        str(key): _number(value, field=f"physical.{key}")
        for key, value in metrics.items()
        if str(key).endswith("_count")
    }
    initial_soc = sum(
        depot["initial_soc_kwh"]
        for depot in accounting["bess_terminal_soc_by_depot"].values()
    )
    target_soc = sum(
        depot["target_soc_kwh"]
        for depot in accounting["bess_terminal_soc_by_depot"].values()
    )
    terminal_soc = sum(
        depot["terminal_soc_kwh"]
        for depot in accounting["bess_terminal_soc_by_depot"].values()
    )
    pv_reverse_inputs_valid = (
        asset["pv_rated_output_kw"] > 0.0
        and asset["panel_power_density_kw_per_m2"] > 0.0
        and 0.0 < asset["usable_area_ratio"] <= 1.0
    )
    pv_reverse_residuals: dict[str, float | None] = {
        "panel_area_m2": None,
        "required_depot_area_m2": None,
        "area_inferred_capacity_kw": None,
    }
    if pv_reverse_inputs_valid:
        expected_panel_area = (
            asset["pv_rated_output_kw"]
            / asset["panel_power_density_kw_per_m2"]
        )
        expected_depot_area = expected_panel_area / asset["usable_area_ratio"]
        pv_reverse_residuals = {
            "panel_area_m2": (
                asset["estimated_pv_panel_area_from_rated_output_m2"]
                - expected_panel_area
            ),
            "required_depot_area_m2": (
                asset["estimated_required_depot_area_from_rated_output_m2"]
                - expected_depot_area
            ),
            "area_inferred_capacity_kw": (
                asset["area_inferred_pv_capacity_kw"]
                - asset["pv_rated_output_kw"]
            ),
        }
    accounting_asset_depot = accounting["bess_terminal_soc_by_depot"].get(
        asset["depot_id"]
    )

    gates = [
        _case_gate(
            "assignment_trip_count_complete",
            assignment["served_trip_count"] == assignment["total_trip_count"],
            assignment["served_trip_count"],
            assignment["total_trip_count"],
            "graph/trip_assignment.csv",
        ),
        _case_gate(
            "unserved_trip_count_zero",
            assignment["unserved_trip_count"] == 0,
            assignment["unserved_trip_count"],
            0,
            "graph/trip_assignment.csv",
        ),
        _case_gate(
            "used_vehicle_count_matches_accounting",
            assignment["used_vehicle_count"] == cost["used_vehicle_day_count"],
            assignment["used_vehicle_count"],
            cost["used_vehicle_day_count"],
            "graph/trip_assignment.csv + executed_day_accounting.json",
        ),
        _case_gate(
            "vehicle_usage_cost_reconciles",
            abs(
                cost["vehicle_usage_cost_jpy"]
                - assignment["used_vehicle_count"]
                * cost["vehicle_usage_cost_jpy_per_used_bus"]
            )
            <= COST_TOLERANCE_JPY,
            cost["vehicle_usage_cost_jpy"],
            assignment["used_vehicle_count"]
            * cost["vehicle_usage_cost_jpy_per_used_bus"],
            "executed_day_accounting.json",
        ),
        _case_gate(
            "accounting_cost_components_reconcile",
            abs(cost["accounting_residual_jpy"]) <= COST_TOLERANCE_JPY,
            cost["accounting_residual_jpy"],
            f"abs <= {COST_TOLERANCE_JPY}",
            "executed_day_accounting.json",
        ),
        _case_gate(
            "pv_energy_balance_reconciles",
            abs(energy["pv_balance_residual_kwh"]) <= ENERGY_TOLERANCE_KWH,
            energy["pv_balance_residual_kwh"],
            f"abs <= {ENERGY_TOLERANCE_KWH}",
            "executed_day_accounting.json",
        ),
        _case_gate(
            "grid_energy_balance_reconciles",
            abs(energy["grid_balance_residual_kwh"]) <= ENERGY_TOLERANCE_KWH,
            energy["grid_balance_residual_kwh"],
            f"abs <= {ENERGY_TOLERANCE_KWH}",
            "executed_day_accounting.json",
        ),
        _case_gate(
            "hourly_rolling_totals_match_accounting",
            all(
                abs(hourly_totals[key] - energy[key]) <= ENERGY_TOLERANCE_KWH
                for key in hourly_totals
            ),
            {
                key: hourly_totals[key] - energy[key]
                for key in hourly_totals
            },
            f"all abs residuals <= {ENERGY_TOLERANCE_KWH}",
            "hourly_energy_flow_chart.csv + executed_day_accounting.json",
        ),
        _case_gate(
            "bess_initial_terminal_soc_balanced",
            abs(initial_soc - terminal_soc) <= SOC_TOLERANCE_KWH
            and abs(target_soc - terminal_soc) <= SOC_TOLERANCE_KWH
            and accounting["bess_terminal_energy_balanced"],
            {
                "terminal_minus_initial_kwh": terminal_soc - initial_soc,
                "terminal_minus_target_kwh": terminal_soc - target_soc,
            },
            f"both abs residuals <= {SOC_TOLERANCE_KWH}",
            "executed_day_accounting.json",
        ),
        _case_gate(
            "pv_rated_output_reverse_calculation_reconciles",
            asset["pv_capacity_manual_override"]
            and asset["pv_capacity_input_mode"] == "rated_output_manual"
            and pv_reverse_inputs_valid
            and all(
                residual is not None
                and abs(residual) <= ENERGY_TOLERANCE_KWH
                for residual in pv_reverse_residuals.values()
            ),
            {
                "input_mode": asset["pv_capacity_input_mode"],
                "manual_override": asset["pv_capacity_manual_override"],
                "residuals": pv_reverse_residuals,
            },
            {
                "input_mode": "rated_output_manual",
                "manual_override": True,
                "all_abs_residuals": f"<= {ENERGY_TOLERANCE_KWH}",
            },
            "frontend_depot_energy_asset_request.json",
        ),
        _case_gate(
            "bess_asset_soc_matches_executed_accounting",
            accounting_asset_depot is not None
            and abs(
                asset["bess_initial_soc_kwh"]
                - accounting_asset_depot["initial_soc_kwh"]
            )
            <= SOC_TOLERANCE_KWH
            and abs(
                asset["bess_terminal_soc_target_kwh"]
                - accounting_asset_depot["target_soc_kwh"]
            )
            <= SOC_TOLERANCE_KWH
            and asset["bess_energy_capacity_kwh"]
            + SOC_TOLERANCE_KWH
            >= max(asset["bess_initial_soc_kwh"], asset["bess_terminal_soc_target_kwh"]),
            {
                "asset_initial_soc_kwh": asset["bess_initial_soc_kwh"],
                "asset_terminal_target_kwh": asset[
                    "bess_terminal_soc_target_kwh"
                ],
                "accounting_initial_soc_kwh": (
                    accounting_asset_depot["initial_soc_kwh"]
                    if accounting_asset_depot
                    else None
                ),
                "accounting_target_soc_kwh": (
                    accounting_asset_depot["target_soc_kwh"]
                    if accounting_asset_depot
                    else None
                ),
                "bess_capacity_kwh": asset["bess_energy_capacity_kwh"],
            },
            "asset initial/target equal executed accounting and fit capacity",
            "frontend_depot_energy_asset_request.json + executed_day_accounting.json",
        ),
        _case_gate(
            "physical_schedule_valid",
            _as_bool(physical.get("accepted"))
            and not physical.get("failed_checks")
            and all(abs(value) <= 0.0 for value in zero_metric_values.values()),
            {
                "accepted": physical.get("accepted"),
                "failed_checks": physical.get("failed_checks") or [],
                "nonzero_metrics": {
                    key: value for key, value in zero_metric_values.items() if value
                },
            },
            "accepted=true, no failures, zero violation counts",
            "graph/physical_schedule_validation.json",
        ),
        _case_gate(
            "rolling_24_of_24_accepted",
            controls["rolling_chain_accepted"]
            and controls["rolling_step_count"]
            == controls["rolling_expected_step_count"]
            == 24,
            {
                "accepted": controls["rolling_chain_accepted"],
                "steps": controls["rolling_step_count"],
            },
            {"accepted": True, "steps": 24},
            "rolling_chain_summary.json",
        ),
        _case_gate(
            "solver_settings_match_effective_inputs",
            quality["time_limit_seconds_requested"]
            == quality["time_limit_seconds_effective"]
            == controls["day_ahead_time_limit_sec"]
            and abs(
                quality["requested_gap_ratio"]
                - controls["day_ahead_mip_gap_ratio"]
            )
            <= 1.0e-12
            and abs(
                quality["requested_gap_percent"]
                - 100.0 * quality["requested_gap_ratio"]
            )
            <= 1.0e-12,
            {
                "solver_requested_time_limit_sec": quality[
                    "time_limit_seconds_requested"
                ],
                "solver_effective_time_limit_sec": quality[
                    "time_limit_seconds_effective"
                ],
                "input_time_limit_sec": controls["day_ahead_time_limit_sec"],
                "solver_requested_gap_ratio": quality["requested_gap_ratio"],
                "input_gap_ratio": controls["day_ahead_mip_gap_ratio"],
            },
            "equal time limits and MIP-gap requests",
            "solver_settings.json + optimization_parameters.json",
        ),
        _case_gate(
            "certified_gap_meets_declared_target",
            quality["has_feasible_incumbent"]
            and quality["requested_gap_certificate_met"]
            and quality["certified_gap_percent"]
            <= quality["requested_gap_percent"] + 1.0e-12,
            quality["certified_gap_percent"],
            f"<= {quality['requested_gap_percent']} percent",
            "solver_settings.json",
        ),
    ]

    run_dir = str(execution.get("run_dir") or "")
    run_id = Path(run_dir).name if run_dir else ""
    return (
        {
            "case": case,
            "case_label": case_label,
            "comparison_role": CASE_ROLES[case],
            "run_id": run_id,
            "scenario_id": str(execution.get("scenario_id") or ""),
            "prepared_input_id": str(execution.get("prepared_input_id") or ""),
            "job_id": str(execution.get("job_id") or ""),
            "service_date": str(
                (comparison.get("comparison_control_payload") or {}).get(
                    "service_date"
                )
                or ""
            ),
            "pv_reference_date": pv_reference_date,
            "comparison_control_hash": str(
                comparison.get("comparison_control_hash") or ""
            ),
            "pv_profile_hash": str(comparison.get("pv_profile_hash") or ""),
            "assignment_hash": str(comparison.get("assignment_hash") or ""),
            "assignment": assignment,
            "accounting": accounting,
            "hourly_rolling": hourly,
            "hourly_totals": hourly_totals,
            "solver_quality": quality,
            "effective_controls": controls,
            "depot_energy_asset": asset,
            "physical_validation": {
                "status": str(physical.get("status") or ""),
                "accepted": _as_bool(physical.get("accepted")),
                "failed_checks": list(physical.get("failed_checks") or ()),
                "validation_metrics": dict(zero_metric_values),
            },
            "gates": gates,
            "source_lineage": [
                _source_record(pair_dir, path, f"{case}.{role}")
                for role, path in paths.items()
            ],
        },
        public_assignment_rows,
    )


def _pair_gate(
    name: str,
    passed: bool,
    observed: Any,
    expected: Any,
    source: str,
) -> dict[str, Any]:
    return _case_gate(name, passed, observed, expected, source)


def _build_snapshot_payload(pair_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cases: dict[str, dict[str, Any]] = {}
    assignments: list[dict[str, Any]] = []
    for case in CASE_ORDER:
        case_payload, case_assignments = _build_case(pair_dir, case)
        cases[case] = case_payload
        assignments.extend(case_assignments)

    pair_manifest = _read_json(pair_dir / PAIR_SOURCES["canonical_pair_manifest"])
    tariff = _read_json(pair_dir / PAIR_SOURCES["tariff_condition"])
    sunny = cases["sunny"]
    rain = cases["rain"]
    numeric_asset_controls = (
        "pv_rated_output_kw",
        "estimated_pv_panel_area_from_rated_output_m2",
        "estimated_required_depot_area_from_rated_output_m2",
        "area_inferred_pv_capacity_kw",
        "panel_power_density_kw_per_m2",
        "usable_area_ratio",
        "bess_energy_capacity_kwh",
        "bess_power_capacity_kw",
        "bess_initial_soc_kwh",
        "bess_terminal_soc_target_kwh",
    )
    sunny_asset = sunny["depot_energy_asset"]
    rain_asset = rain["depot_energy_asset"]
    asset_controls_match = (
        sunny_asset["depot_id"] == rain_asset["depot_id"]
        and sunny_asset["pv_capacity_input_mode"]
        == rain_asset["pv_capacity_input_mode"]
        and sunny_asset["pv_capacity_manual_override"]
        == rain_asset["pv_capacity_manual_override"]
        and all(
            abs(sunny_asset[key] - rain_asset[key]) <= ENERGY_TOLERANCE_KWH
            for key in numeric_asset_controls
        )
    )
    pair_gates = [
        _pair_gate(
            "same_service_date",
            bool(sunny["service_date"])
            and sunny["service_date"] == rain["service_date"],
            [sunny["service_date"], rain["service_date"]],
            "equal non-empty values",
            "comparison_case_manifest.json",
        ),
        _pair_gate(
            "same_trip_population",
            sunny["assignment"]["total_trip_count"]
            == rain["assignment"]["total_trip_count"],
            [
                sunny["assignment"]["total_trip_count"],
                rain["assignment"]["total_trip_count"],
            ],
            "equal values",
            "graph/trip_assignment.csv",
        ),
        _pair_gate(
            "comparison_control_hash_match",
            bool(sunny["comparison_control_hash"])
            and sunny["comparison_control_hash"]
            == rain["comparison_control_hash"],
            [sunny["comparison_control_hash"], rain["comparison_control_hash"]],
            "equal non-empty hashes",
            "comparison_case_manifest.json",
        ),
        _pair_gate(
            "pv_profile_hash_different",
            bool(sunny["pv_profile_hash"])
            and bool(rain["pv_profile_hash"])
            and sunny["pv_profile_hash"] != rain["pv_profile_hash"],
            [sunny["pv_profile_hash"], rain["pv_profile_hash"]],
            "different non-empty hashes",
            "comparison_case_manifest.json",
        ),
        _pair_gate(
            "canonical_pair_manifest_verified",
            _as_bool(
                pair_manifest.get("accepted_for_controlled_pv_sensitivity_comparison")
            )
            and not pair_manifest.get("failed_checks"),
            {
                "accepted": pair_manifest.get(
                    "accepted_for_controlled_pv_sensitivity_comparison"
                ),
                "failed_checks": pair_manifest.get("failed_checks") or [],
            },
            {"accepted": True, "failed_checks": []},
            "pair/pair_manifest.json",
        ),
        _pair_gate(
            "tariff_is_flat_30_no_demand",
            abs(
                _number(
                    tariff.get("grid_energy_price_yen_per_kwh"),
                    field="tariff.grid_energy_price_yen_per_kwh",
                )
                - 30.0
            )
            <= 1.0e-12
            and abs(
                _number(
                    tariff.get("demand_charge_yen_per_kw"),
                    field="tariff.demand_charge_yen_per_kw",
                )
            )
            <= 1.0e-12,
            {
                "energy_jpy_per_kwh": tariff.get(
                    "grid_energy_price_yen_per_kwh"
                ),
                "demand_jpy_per_kw": tariff.get("demand_charge_yen_per_kw"),
            },
            {"energy_jpy_per_kwh": 30.0, "demand_jpy_per_kw": 0.0},
            "tariff_condition.json",
        ),
        _pair_gate(
            "depot_energy_asset_controls_match",
            asset_controls_match,
            {
                "sunny": {
                    key: sunny_asset[key]
                    for key in (
                        "depot_id",
                        "pv_rated_output_kw",
                        "bess_energy_capacity_kwh",
                        "bess_power_capacity_kw",
                        "bess_initial_soc_kwh",
                        "bess_terminal_soc_target_kwh",
                    )
                },
                "rain": {
                    key: rain_asset[key]
                    for key in (
                        "depot_id",
                        "pv_rated_output_kw",
                        "bess_energy_capacity_kwh",
                        "bess_power_capacity_kw",
                        "bess_initial_soc_kwh",
                        "bess_terminal_soc_target_kwh",
                    )
                },
            },
            "identical controlled depot-energy assets",
            "frontend_depot_energy_asset_request.json",
        ),
        _pair_gate(
            "effective_solver_and_rolling_controls_match",
            sunny["effective_controls"] == rain["effective_controls"],
            {
                "sunny": sunny["effective_controls"],
                "rain": rain["effective_controls"],
            },
            "identical effective controls",
            "optimization_parameters.json + rolling_chain_summary.json",
        ),
    ]

    all_case_gates = [gate for case in cases.values() for gate in case["gates"]]
    presentation_ready = all(gate["passed"] for gate in all_case_gates + pair_gates)
    comparison = {
        "schema_version": "comparison_pair_manifest_v1",
        "comparison_type": "same_service_date_pv_counterfactual",
        "baseline_run_id": sunny["run_id"],
        "counterfactual_run_id": rain["run_id"],
        "control_hash_match": pair_gates[2]["passed"],
        "control_hash": sunny["comparison_control_hash"],
        "baseline_pv_hash": sunny["pv_profile_hash"],
        "counterfactual_pv_hash": rain["pv_profile_hash"],
        "pv_hash_different": pair_gates[3]["passed"],
        "both_physical_valid": all(
            case["physical_validation"]["accepted"] for case in cases.values()
        ),
        "both_rolling_accepted": all(
            case["effective_controls"]["rolling_chain_accepted"]
            for case in cases.values()
        ),
        "both_accounting_eligible": all(
            case["accounting"]["eligible"] for case in cases.values()
        ),
        "pair_verification_status": "VERIFIED" if presentation_ready else "BLOCKED",
        "comparison_pair_verified": presentation_ready,
        "progress_presentation_ready": presentation_ready,
        "research_submission_ready": False,
        "input_realism_assessed": False,
        "canonical_pair_formal_research_submission_ready": _as_bool(
            pair_manifest.get("formal_research_submission_ready")
        ),
        "release_scope": "progress_presentation_only",
        "research_submission_note": (
            "This derived presentation bundle does not assess input realism and "
            "does not replace the immutable canonical pair manifest."
        ),
    }

    source_lineage = [
        _source_record(pair_dir, pair_dir / relative, f"pair.{role}")
        for role, relative in PAIR_SOURCES.items()
    ]
    for case in CASE_ORDER:
        source_lineage.extend(cases[case]["source_lineage"])

    payload = {
        "schema_version": "reporting_snapshot_v1",
        "source_pair_directory_name": pair_dir.name,
        "canonical_source_policy": {
            "assignment": "graph/trip_assignment.csv",
            "energy_cost_and_co2": (
                "rolling_hourly_chain/executed_day_accounting.json"
            ),
            "hourly_energy_and_soc": (
                "rolling_hourly_chain/hourly_energy_flow_chart.csv"
            ),
            "physical_validation": "graph/physical_schedule_validation.json",
            "day_ahead_solver_quality": "solver_settings.json",
            "effective_solver_inputs": "optimization_parameters.json",
            "pair_controls": "comparison_case_manifest.json + pair/pair_manifest.json",
            "day_ahead_plan_excluded_from_final_kpis": True,
            "internal_search_objective_excluded_from_public_costs": True,
        },
        "claim_scope": {
            "progress_presentation_ready": presentation_ready,
            "research_submission_ready": False,
            "input_realism_assessed": False,
            "canonical_pair_formal_research_submission_ready": comparison[
                "canonical_pair_formal_research_submission_ready"
            ],
            "note": comparison["research_submission_note"],
        },
        "tariff": {
            "grid_energy_price_jpy_per_kwh": _number(
                tariff.get("grid_energy_price_yen_per_kwh"),
                field="tariff.grid_energy_price_yen_per_kwh",
            ),
            "demand_charge_jpy_per_kw": _number(
                tariff.get("demand_charge_yen_per_kw"),
                field="tariff.demand_charge_yen_per_kw",
            ),
        },
        "comparison_pair": comparison,
        "cases": cases,
        "pair_gates": pair_gates,
        "source_lineage": sorted(source_lineage, key=lambda row: row["role"]),
        "tolerances": {
            "cost_jpy": COST_TOLERANCE_JPY,
            "energy_kwh": ENERGY_TOLERANCE_KWH,
            "soc_kwh": SOC_TOLERANCE_KWH,
        },
    }
    if not presentation_ready:
        failures = [
            gate["gate"]
            for gate in all_case_gates + pair_gates
            if not gate["passed"]
        ]
        raise ReportingSnapshotError(
            "Progress presentation release gates failed: " + ", ".join(failures)
        )
    return payload, assignments


def _summary_rows(payload: Mapping[str, Any], digest: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in CASE_ORDER:
        value = payload["cases"][case]
        assignment = value["assignment"]
        accounting = value["accounting"]
        energy = accounting["energy"]
        cost = accounting["cost"]
        asset = value["depot_energy_asset"]
        quality = value["solver_quality"]
        controls = value["effective_controls"]
        rows.append(
            {
                "reporting_snapshot_sha256": digest,
                "case": case,
                "case_label": value["case_label"],
                "service_date": value["service_date"],
                "pv_reference_date": value["pv_reference_date"],
                "served_trip_count": assignment["served_trip_count"],
                "unserved_trip_count": assignment["unserved_trip_count"],
                "bev_trip_count": assignment["bev_trip_count"],
                "ice_trip_count": assignment["ice_trip_count"],
                "used_bev_count": assignment["used_bev_count"],
                "used_ice_count": assignment["used_ice_count"],
                "pv_rated_output_kw": asset["pv_rated_output_kw"],
                "estimated_pv_panel_area_m2": asset[
                    "estimated_pv_panel_area_from_rated_output_m2"
                ],
                "estimated_required_depot_area_m2": asset[
                    "estimated_required_depot_area_from_rated_output_m2"
                ],
                "bess_capacity_kwh": asset["bess_energy_capacity_kwh"],
                "pv_generated_kwh": energy["pv_generated_kwh"],
                "grid_import_kwh": energy["grid_import_kwh"],
                "peak_grid_kw": energy["peak_grid_kw"],
                "electricity_cost_jpy": cost["electricity_cost_jpy"],
                "fuel_cost_jpy": cost["fuel_cost_jpy"],
                "accounting_total_cost_jpy": cost["accounting_total_cost_jpy"],
                "total_co2_kg": accounting["emissions"]["total_co2_kg"],
                "raw_solver_status": quality["raw_solver_status"],
                "solution_quality_label": quality["solution_quality_label"],
                "day_ahead_time_limit_sec": quality[
                    "time_limit_seconds_effective"
                ],
                "day_ahead_requested_gap_percent": quality[
                    "requested_gap_percent"
                ],
                "gurobi_raw_gap_percent": quality["gurobi_raw_gap_percent"],
                "certified_gap_percent": quality["certified_gap_percent"],
                "rolling_step_count": controls["rolling_step_count"],
                "rolling_time_limit_sec_per_step": controls[
                    "rolling_time_limit_sec_per_step"
                ],
                "rolling_requested_gap_percent": (
                    100.0 * controls["rolling_mip_gap_ratio"]
                ),
            }
        )
    return rows


def _energy_rows(payload: Mapping[str, Any], digest: str) -> list[dict[str, Any]]:
    rows = []
    for case in CASE_ORDER:
        energy = payload["cases"][case]["accounting"]["energy"]
        rows.append(
            {
                "reporting_snapshot_sha256": digest,
                "case": case,
                "case_label": payload["cases"][case]["case_label"],
                **energy,
            }
        )
    return rows


def _cost_rows(payload: Mapping[str, Any], digest: str) -> list[dict[str, Any]]:
    rows = []
    for case in CASE_ORDER:
        cost = payload["cases"][case]["accounting"]["cost"]
        rows.append(
            {
                "reporting_snapshot_sha256": digest,
                "case": case,
                "case_label": payload["cases"][case]["case_label"],
                **cost,
                "published_cost_basis": (
                    "accepted_24_hour_rolling_executed_day_accounting"
                ),
                "internal_search_objective_excluded": True,
            }
        )
    return rows


def _validation_rows(payload: Mapping[str, Any], digest: str) -> list[dict[str, Any]]:
    rows = []
    for case in CASE_ORDER:
        for gate in payload["cases"][case]["gates"]:
            rows.append(
                {
                    "reporting_snapshot_sha256": digest,
                    "scope": case,
                    **gate,
                }
            )
    for gate in payload["pair_gates"]:
        rows.append(
            {
                "reporting_snapshot_sha256": digest,
                "scope": "pair",
                **gate,
            }
        )
    return rows


def _hourly_rows(payload: Mapping[str, Any], digest: str) -> list[dict[str, Any]]:
    rows = []
    for case in CASE_ORDER:
        for row in payload["cases"][case]["hourly_rolling"]:
            rows.append(
                {
                    "reporting_snapshot_sha256": digest,
                    "case": case,
                    "case_label": payload["cases"][case]["case_label"],
                    **row,
                }
            )
    return rows


def _figure_footer(fig: Any, digest: str) -> None:
    fig.text(
        0.99,
        0.006,
        f"Rolling execution | snapshot {digest}",
        ha="right",
        va="bottom",
        fontsize=6,
        color="#5F6B73",
    )


def _save_figure(fig: Any, path: Path, digest: str) -> None:
    _figure_footer(fig, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(
        path,
        dpi=180,
        bbox_inches="tight",
        facecolor="white",
        metadata={
            "Title": path.stem,
            "reporting_snapshot_sha256": digest,
            "Source": "accepted 24-hour Rolling execution",
        },
    )
    plt.close(fig)


def _plot_cost(payload: Mapping[str, Any], path: Path, digest: str) -> None:
    labels = [payload["cases"][case]["case_label"] for case in CASE_ORDER]
    components = [
        ("Electricity", "electricity_cost_jpy", "#7B2CBF"),
        ("Fuel", "fuel_cost_jpy", "#6C757D"),
        ("Vehicle-day", "vehicle_usage_cost_jpy", "#2A9D8F"),
        ("CO2", "co2_cost_jpy", "#E76F51"),
    ]
    fig, ax = plt.subplots(figsize=(8.4, 5.0))
    bottom = [0.0, 0.0]
    for name, key, color in components:
        values = [
            payload["cases"][case]["accounting"]["cost"][key]
            for case in CASE_ORDER
        ]
        ax.bar(labels, values, bottom=bottom, label=name, color=color, width=0.58)
        bottom = [left + right for left, right in zip(bottom, values)]
    for index, total in enumerate(bottom):
        ax.text(index, total + max(bottom) * 0.012, f"JPY {total:,.1f}", ha="center")
    ax.set_ylabel("JPY/day")
    ax.set_ylim(0.0, max(bottom) * 1.10)
    fig.suptitle("Executed accounting cost comparison", y=0.98)
    ax.legend(
        ncol=4,
        frameon=False,
        loc="lower center",
        bbox_to_anchor=(0.5, 1.01),
    )
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.18)
    fig.subplots_adjust(top=0.78)
    _save_figure(fig, path, digest)


def _plot_dispatch(payload: Mapping[str, Any], path: Path, digest: str) -> None:
    labels = [payload["cases"][case]["case_label"] for case in CASE_ORDER]
    bev_used = [payload["cases"][case]["assignment"]["used_bev_count"] for case in CASE_ORDER]
    ice_used = [payload["cases"][case]["assignment"]["used_ice_count"] for case in CASE_ORDER]
    bev_trips = [payload["cases"][case]["assignment"]["bev_trip_count"] for case in CASE_ORDER]
    ice_trips = [payload["cases"][case]["assignment"]["ice_trip_count"] for case in CASE_ORDER]
    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.8))
    for ax, bev, ice, title, ylabel in (
        (axes[0], bev_used, ice_used, "Used vehicles", "vehicles"),
        (axes[1], bev_trips, ice_trips, "Assigned service trips", "trips"),
    ):
        ax.bar(labels, bev, label="BEV", color="#2A9D8F", width=0.58)
        ax.bar(labels, ice, bottom=bev, label="ICE", color="#6C757D", width=0.58)
        for index, (bev_value, ice_value) in enumerate(zip(bev, ice)):
            ax.text(
                index,
                bev_value / 2,
                str(bev_value),
                ha="center",
                va="center",
                color="white",
                fontweight="bold",
            )
            if ice_value:
                ax.text(
                    index,
                    bev_value + ice_value / 2,
                    str(ice_value),
                    ha="center",
                    va="center",
                    color="white",
                    fontweight="bold",
                )
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.18)
    axes[0].legend(frameon=False, loc="upper right")
    fig.suptitle("Final assignment from graph/trip_assignment.csv", fontsize=13)
    fig.tight_layout()
    _save_figure(fig, path, digest)


def _plot_energy_case(
    payload: Mapping[str, Any],
    case: str,
    path: Path,
    digest: str,
) -> None:
    rows = payload["cases"][case]["hourly_rolling"]
    hours = [row["step_index"] for row in rows]
    pv_bus = [row["pv_to_bus_kwh"] for row in rows]
    pv_bess = [row["pv_to_bess_kwh"] for row in rows]
    curtailed = [row["pv_curtailed_kwh"] for row in rows]
    pv_generation = [row["pv_generated_kwh"] for row in rows]
    grid = [row["grid_to_bus_kwh"] + row["grid_to_bess_kwh"] for row in rows]
    bess_bus = [row["bess_to_bus_kwh"] for row in rows]
    fig, ax = plt.subplots(figsize=(10.5, 5.0))
    ax.bar(hours, pv_bus, label="PV to bus", color="#F4B400")
    ax.bar(hours, pv_bess, bottom=pv_bus, label="PV to BESS", color="#FFD166")
    pv_used = [left + right for left, right in zip(pv_bus, pv_bess)]
    ax.bar(hours, curtailed, bottom=pv_used, label="PV curtailed", color="#D9D9D9")
    ax.plot(hours, pv_generation, color="#B26A00", linewidth=1.8, label="PV generated")
    ax.plot(hours, bess_bus, color="#00A6A6", marker="o", markersize=3, label="BESS to bus")
    ax.plot(hours, grid, color="#7B2CBF", marker="s", markersize=3, label="Grid import")
    ax.set_xticks(range(0, 24, 2))
    ax.set_xlabel("hour")
    ax.set_ylabel("executed energy per hour (kWh)")
    ax.set_title(
        f"{payload['cases'][case]['case_label']}: executed hourly energy flows"
    )
    ax.legend(ncol=3, frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.18)
    _save_figure(fig, path, digest)


def _plot_soc_case(
    payload: Mapping[str, Any],
    case: str,
    path: Path,
    digest: str,
) -> None:
    value = payload["cases"][case]
    rows = value["hourly_rolling"]
    asset = value["depot_energy_asset"]
    bess_hours = list(range(25))
    bess_soc = [asset["bess_initial_soc_kwh"]] + [
        row["bess_end_soc_kwh"] for row in rows
    ]
    bev_min = [row["bev_soc_min_kwh"] for row in rows]
    bev_mean = [row["bev_soc_mean_kwh"] for row in rows]
    fig, axes = plt.subplots(2, 1, figsize=(10.5, 6.5), sharex=False)
    axes[0].plot(bess_hours, bess_soc, color="#00A6A6", marker="o", markersize=3)
    axes[0].axhline(
        asset["bess_terminal_soc_target_kwh"],
        color="#546E7A",
        linestyle="--",
        label="terminal target",
    )
    axes[0].set_ylabel("BESS SOC (kWh)")
    axes[0].set_title(
        f"{payload['cases'][case]['case_label']}: Rolling SOC evidence"
    )
    axes[0].legend(frameon=False)
    axes[0].grid(alpha=0.18)
    axes[0].spines[["top", "right"]].set_visible(False)
    axes[1].plot(
        range(24),
        bev_mean,
        color="#2A9D8F",
        marker="o",
        markersize=3,
        label="BEV mean SOC",
    )
    axes[1].plot(
        range(24),
        bev_min,
        color="#E76F51",
        marker="s",
        markersize=3,
        label="BEV minimum SOC",
    )
    axes[1].set_xticks(range(0, 24, 2))
    axes[1].set_xlabel("Rolling step hour")
    axes[1].set_ylabel("vehicle energy (kWh)")
    axes[1].legend(frameon=False, ncol=2)
    axes[1].grid(alpha=0.18)
    axes[1].spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    _save_figure(fig, path, digest)


def _write_figures(payload: Mapping[str, Any], output_dir: Path, digest: str) -> None:
    figures = output_dir / "figures"
    _plot_cost(payload, figures / "cost_comparison.png", digest)
    _plot_dispatch(payload, figures / "dispatch_comparison.png", digest)
    _plot_energy_case(payload, "sunny", figures / "energy_flow_baseline.png", digest)
    _plot_energy_case(payload, "rain", figures / "energy_flow_low_pv.png", digest)
    _plot_soc_case(payload, "sunny", figures / "soc_baseline.png", digest)
    _plot_soc_case(payload, "rain", figures / "soc_low_pv.png", digest)


def _create_node_modules_link(link: Path, target: Path) -> None:
    if link.exists() or link.is_symlink():
        raise ReportingSnapshotError(f"Temporary node_modules already exists: {link}")
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except OSError:
        if os.name != "nt":
            raise
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ReportingSnapshotError(
            "Cannot create temporary node_modules junction: "
            + (completed.stderr or completed.stdout).strip()
        )


def _run_workbook_builder(
    workbook_payload: Mapping[str, Any],
    output_path: Path,
    node_executable: Path,
    node_modules_dir: Path,
    preview_dir: Path,
) -> dict[str, Any]:
    if not node_executable.is_file():
        raise ReportingSnapshotError(f"Node executable not found: {node_executable}")
    if not node_modules_dir.is_dir():
        raise ReportingSnapshotError(f"Bundled node_modules not found: {node_modules_dir}")
    if not WORKBOOK_BUILDER.is_file():
        raise ReportingSnapshotError(f"Workbook builder not found: {WORKBOOK_BUILDER}")
    preview_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="reporting-workbook-") as raw_temp:
        temp_dir = Path(raw_temp)
        builder_copy = temp_dir / WORKBOOK_BUILDER.name
        shutil.copy2(WORKBOOK_BUILDER, builder_copy)
        link = temp_dir / "node_modules"
        _create_node_modules_link(link, node_modules_dir)
        payload_path = temp_dir / "workbook_payload.json"
        verification_path = temp_dir / "workbook_verification.json"
        _write_json(payload_path, workbook_payload)
        completed = subprocess.run(
            [
                str(node_executable),
                str(builder_copy),
                str(payload_path),
                str(output_path),
                str(preview_dir),
                str(verification_path),
            ],
            cwd=temp_dir,
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        try:
            link.rmdir()
        except OSError:
            pass
        if completed.returncode != 0:
            raise ReportingSnapshotError(
                "Workbook builder failed: "
                + (completed.stderr or completed.stdout).strip()
            )
        # artifact-tool may emit an inspection sidecar beside the workbook.
        # It is useful during authoring but is not part of the public release.
        inspection_sidecar = output_path.with_name(
            output_path.name + ".inspect.ndjson"
        )
        if inspection_sidecar.exists():
            inspection_sidecar.unlink()
        verification = _read_json(verification_path)
        if verification.get("status") != "OK":
            raise ReportingSnapshotError(
                f"Workbook verification failed: {verification}"
            )
        if verification.get("formula_error_count") != 0:
            raise ReportingSnapshotError(
                "Workbook formula-error scan did not certify zero errors"
            )
        if verification.get("sheet_names") != list(WORKBOOK_SHEET_NAMES):
            raise ReportingSnapshotError("Workbook sheet contract mismatch")
        if verification.get("sheet_count") != len(WORKBOOK_SHEET_NAMES):
            raise ReportingSnapshotError("Workbook sheet count mismatch")
        previews = verification.get("previews")
        if not isinstance(previews, list) or len(previews) != len(
            WORKBOOK_SHEET_NAMES
        ):
            raise ReportingSnapshotError("Workbook preview count mismatch")
        normalized_previews: list[dict[str, str]] = []
        preview_root = preview_dir.resolve()
        for expected_sheet, record in zip(WORKBOOK_SHEET_NAMES, previews):
            if not isinstance(record, Mapping) or record.get("sheet") != expected_sheet:
                raise ReportingSnapshotError("Workbook preview sheet mismatch")
            preview_path = Path(str(record.get("path") or "")).resolve()
            if (
                preview_path.parent != preview_root
                or not preview_path.is_file()
                or preview_path.stat().st_size <= 0
            ):
                raise ReportingSnapshotError(
                    f"Workbook preview missing or outside preview directory: {preview_path}"
                )
            normalized_previews.append(
                {"sheet": expected_sheet, "file": preview_path.name}
            )
        verification["previews"] = normalized_previews
        verification["preview_count"] = len(normalized_previews)
        return verification


def _workbook_payload(
    payload: Mapping[str, Any],
    digest: str,
    assignments: Sequence[Mapping[str, Any]],
    summary_rows: Sequence[Mapping[str, Any]],
    energy_rows: Sequence[Mapping[str, Any]],
    cost_rows: Sequence[Mapping[str, Any]],
    validation_rows: Sequence[Mapping[str, Any]],
    hourly_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    provenance_rows = [
        {
            "role": row["role"],
            "path": row["path"],
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
            "reporting_snapshot_sha256": digest,
        }
        for row in payload["generator_lineage"] + payload["source_lineage"]
    ]
    return {
        "reporting_snapshot_sha256": digest,
        "release_scope": payload["comparison_pair"]["release_scope"],
        "progress_presentation_ready": True,
        "research_submission_ready": False,
        "summary_rows": list(summary_rows),
        "assignment_rows": list(assignments),
        "energy_rows": list(energy_rows),
        "cost_rows": list(cost_rows),
        "validation_rows": list(validation_rows),
        "hourly_rows": list(hourly_rows),
        "provenance_rows": provenance_rows,
        "tariff": payload["tariff"],
        "comparison_pair": payload["comparison_pair"],
    }


def _record_generated(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _xlsx_contains_digest(path: Path, digest: str) -> bool:
    needle = digest.encode("utf-8")
    try:
        with zipfile.ZipFile(path) as archive:
            return any(
                needle in archive.read(name)
                for name in archive.namelist()
                if name.endswith(".xml")
            )
    except (OSError, zipfile.BadZipFile) as exc:
        raise ReportingSnapshotError(f"Invalid workbook: {path}") from exc


def _verify_public_digest(path: Path, digest: str) -> bool:
    if path.suffix.lower() == ".xlsx":
        return _xlsx_contains_digest(path, digest)
    return digest.encode("utf-8") in path.read_bytes()


def _scan_stale_markers(output_dir: Path) -> list[str]:
    findings: list[str] = []
    for path in output_dir.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() == ".xlsx":
            try:
                with zipfile.ZipFile(path) as archive:
                    data = b"\n".join(
                        archive.read(name)
                        for name in archive.namelist()
                        if name.endswith(".xml")
                    )
            except zipfile.BadZipFile as exc:
                raise ReportingSnapshotError(f"Invalid workbook: {path}") from exc
        else:
            data = path.read_bytes()
        for marker in STALE_RELEASE_MARKERS:
            if marker in data:
                findings.append(f"{path.relative_to(output_dir)}:{marker!r}")
    return findings


def _zip_release(output_dir: Path, zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(output_dir.parent))
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise ReportingSnapshotError(f"ZIP CRC failure: {bad}")


def _safe_output_dir(pair_dir: Path, output_dir: Path) -> None:
    pair = pair_dir.resolve()
    output = output_dir.resolve()
    if output == pair or output.parent != pair:
        raise ReportingSnapshotError(
            "Release output must be an immediate child of the pair directory"
        )
    if output.name.startswith(".") or output.name in {"sunny", "rain", "pair"}:
        raise ReportingSnapshotError(f"Unsafe release directory name: {output.name}")
    if output.suffix.lower() == ".zip":
        raise ReportingSnapshotError("Release directory must not use a .zip suffix")


def _safe_zip_path(pair_dir: Path, output_dir: Path, zip_path: Path) -> None:
    pair = pair_dir.resolve()
    output = output_dir.resolve()
    archive = zip_path.resolve()
    if archive.parent != pair:
        raise ReportingSnapshotError(
            "Release ZIP must be an immediate child of the pair directory"
        )
    if archive == output or archive.name.startswith("."):
        raise ReportingSnapshotError(f"Unsafe release ZIP path: {archive}")
    if archive.suffix.lower() != ".zip":
        raise ReportingSnapshotError("Release ZIP must use a .zip suffix")


def build_reporting_release(
    *,
    pair_dir: Path,
    output_dir: Path,
    zip_path: Path,
    node_executable: Path,
    node_modules_dir: Path,
    workbook_preview_dir: Path,
    overwrite: bool = False,
) -> dict[str, Any]:
    pair_dir = pair_dir.resolve()
    output_dir = output_dir.resolve()
    zip_path = zip_path.resolve()
    _safe_output_dir(pair_dir, output_dir)
    _safe_zip_path(pair_dir, output_dir, zip_path)
    if not pair_dir.is_dir():
        raise ReportingSnapshotError(f"Pair directory not found: {pair_dir}")
    if output_dir.exists() and not overwrite:
        raise ReportingSnapshotError(f"Release output already exists: {output_dir}")
    if zip_path.exists() and not overwrite:
        raise ReportingSnapshotError(f"Release ZIP already exists: {zip_path}")

    source_paths = _source_paths(pair_dir)
    source_hashes_before = _hash_sources(source_paths)
    generator_paths = {
        "reporting.python_builder": Path(__file__).resolve(),
        "reporting.workbook_builder": WORKBOOK_BUILDER.resolve(),
    }
    generator_hashes_before = _hash_sources(generator_paths)
    payload, assignments = _build_snapshot_payload(pair_dir)
    payload["generator_lineage"] = [
        _source_record(REPO_ROOT, path, role)
        for role, path in sorted(generator_paths.items())
    ]
    digest = _canonical_digest(payload)
    snapshot = {
        "schema_version": "reporting_snapshot_envelope_v1",
        "generated_at_utc": _utc_now(),
        "reporting_snapshot_sha256": digest,
        "reporting_snapshot_sha256_semantics": (
            "sha256 of canonical JSON for snapshot_payload"
        ),
        "snapshot_payload": payload,
    }

    staging = output_dir.parent / f".{output_dir.name}.staging-{uuid.uuid4().hex}"
    if staging.exists():
        raise ReportingSnapshotError(f"Unexpected staging path exists: {staging}")
    staging.mkdir(parents=True)
    try:
        _write_json(staging / "reporting_snapshot.json", snapshot)

        summary_rows = _summary_rows(payload, digest)
        energy_rows = _energy_rows(payload, digest)
        cost_rows = _cost_rows(payload, digest)
        validation_rows = _validation_rows(payload, digest)
        hourly_rows = _hourly_rows(payload, digest)

        comparison_manifest = {
            "reporting_snapshot_sha256": digest,
            **payload["comparison_pair"],
        }
        _write_json(staging / "comparison_pair_manifest.json", comparison_manifest)
        _write_json(
            staging / "result_summary.json",
            {
                "schema_version": "reporting_result_summary_v1",
                "reporting_snapshot_sha256": digest,
                "progress_presentation_ready": True,
                "research_submission_ready": False,
                "comparison_pair_verified": True,
                "cost_reporting_policy": (
                    "accepted Rolling executed-day accounting only; internal "
                    "search objective excluded"
                ),
                "cases": summary_rows,
            },
        )
        _write_csv(
            staging / "comparison_summary.csv",
            list(summary_rows[0].keys()),
            summary_rows,
        )
        assignment_fields = [
            "reporting_snapshot_sha256",
            "case",
            "case_label",
        ] + [
            field
            for field in assignments[0].keys()
            if field not in {"case", "case_label"}
        ]
        assignment_rows = [
            {"reporting_snapshot_sha256": digest, **row} for row in assignments
        ]
        _write_csv(
            staging / "vehicle_assignment.csv",
            assignment_fields,
            assignment_rows,
        )
        _write_csv(staging / "energy_balance.csv", list(energy_rows[0].keys()), energy_rows)
        _write_csv(staging / "cost_breakdown.csv", list(cost_rows[0].keys()), cost_rows)

        _write_figures(payload, staging, digest)
        workbook_verification = _run_workbook_builder(
            _workbook_payload(
                payload,
                digest,
                assignment_rows,
                summary_rows,
                energy_rows,
                cost_rows,
                validation_rows,
                hourly_rows,
            ),
            staging / "results.xlsx",
            node_executable,
            node_modules_dir,
            workbook_preview_dir,
        )

        expected_before_validation = {
            "result_summary.json",
            "comparison_summary.csv",
            "vehicle_assignment.csv",
            "energy_balance.csv",
            "cost_breakdown.csv",
            "reporting_snapshot.json",
            "comparison_pair_manifest.json",
            "results.xlsx",
            *(f"figures/{name}" for name in FIGURE_NAMES),
        }
        actual_before_validation = {
            path.relative_to(staging).as_posix()
            for path in staging.rglob("*")
            if path.is_file()
        }
        if actual_before_validation != expected_before_validation:
            raise ReportingSnapshotError(
                "Unexpected release files before validation: "
                f"expected={sorted(expected_before_validation)}, "
                f"actual={sorted(actual_before_validation)}"
            )
        missing_digest = [
            relative
            for relative in sorted(expected_before_validation)
            if not _verify_public_digest(staging / relative, digest)
        ]
        if missing_digest:
            raise ReportingSnapshotError(
                "Public artifacts missing snapshot digest: " + ", ".join(missing_digest)
            )
        stale_findings = _scan_stale_markers(staging)
        if stale_findings:
            raise ReportingSnapshotError(
                "Stale warning text found in release: " + ", ".join(stale_findings)
            )

        artifact_records = [
            _record_generated(staging, staging / relative)
            for relative in sorted(expected_before_validation)
        ]
        validation_summary = {
            "schema_version": "reporting_validation_summary_v1",
            "reporting_snapshot_sha256": digest,
            "status": "READY_FOR_PROGRESS_PRESENTATION",
            "progress_presentation_ready": True,
            "research_submission_ready": False,
            "case_and_pair_gates": validation_rows,
            "workbook_verification": workbook_verification,
            "stale_warning_scan": {
                "status": "OK",
                "policy": "legacy_superseded_warning_marker_scan_v1",
                "forbidden_marker_count": len(STALE_RELEASE_MARKERS),
                "findings": [],
            },
            "generated_artifacts_excluding_this_file": artifact_records,
        }
        _write_json(staging / "validation_summary.json", validation_summary)
        if not _verify_public_digest(staging / "validation_summary.json", digest):
            raise ReportingSnapshotError("validation_summary.json lacks snapshot digest")
        final_stale_findings = _scan_stale_markers(staging)
        if final_stale_findings:
            raise ReportingSnapshotError(
                "Stale warning text found after final validation: "
                + ", ".join(final_stale_findings)
            )

        source_hashes_after = _hash_sources(source_paths)
        if source_hashes_after != source_hashes_before:
            changed = sorted(
                role
                for role in source_hashes_before
                if source_hashes_before[role] != source_hashes_after.get(role)
            )
            raise ReportingSnapshotError(
                "Source artifacts changed during reporting: " + ", ".join(changed)
            )
        generator_hashes_after = _hash_sources(generator_paths)
        if generator_hashes_after != generator_hashes_before:
            changed = sorted(
                role
                for role in generator_hashes_before
                if generator_hashes_before[role] != generator_hashes_after.get(role)
            )
            raise ReportingSnapshotError(
                "Reporting generators changed during reporting: "
                + ", ".join(changed)
            )

        if output_dir.exists():
            shutil.rmtree(output_dir)
        staging.replace(output_dir)
        if zip_path.exists():
            zip_path.unlink()
        _zip_release(output_dir, zip_path)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise

    return {
        "status": "READY_FOR_PROGRESS_PRESENTATION",
        "reporting_snapshot_sha256": digest,
        "release_dir": str(output_dir),
        "release_zip": str(zip_path),
        "release_file_count": sum(1 for path in output_dir.rglob("*") if path.is_file()),
        "source_artifacts_unchanged": True,
        "research_submission_ready": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pair_dir", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--zip-path", type=Path)
    parser.add_argument("--node-executable", required=True, type=Path)
    parser.add_argument("--node-modules-dir", required=True, type=Path)
    parser.add_argument("--workbook-preview-dir", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    pair_dir = args.pair_dir.resolve()
    output_dir = (args.output_dir or (pair_dir / "release")).resolve()
    zip_path = (args.zip_path or (pair_dir / "release.zip")).resolve()
    result = build_reporting_release(
        pair_dir=pair_dir,
        output_dir=output_dir,
        zip_path=zip_path,
        node_executable=args.node_executable.resolve(),
        node_modules_dir=args.node_modules_dir.resolve(),
        workbook_preview_dir=args.workbook_preview_dir.resolve(),
        overwrite=args.overwrite,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
