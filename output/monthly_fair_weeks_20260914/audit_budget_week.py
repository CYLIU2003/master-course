"""Independently audit one frozen monthly-budget campaign week.

This command reads saved evidence only.  It never prepares inputs, invokes a
solver, changes the frozen worktree, or reuses a result from another campaign.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
FROZEN_ROOT = Path(r"C:\master-course-worktrees\shibu21-23-monthly-budget-20260914")
EXPECTED_SHA = "fa0c22bfed6cf7bf0a09d24b82470d4f3570dfc8"
CAMPAIGN = FROZEN_ROOT / "output" / "monthly_budget_campaign_20260914"
FORECAST_DIR = FROZEN_ROOT / "output" / "monthly_fair_weeks_20260914" / "forecast_holdouts"
MONTHLY_INPUT_IMPORT = FROZEN_ROOT / "output" / "monthly_input_import.json"
TOLERANCE = 1.0e-6
NATIVE_COUNT = 169
EXPECTED_SEARCH_CONTROLS: dict[str, int] = {}

sys.path.insert(0, str(ROOT))
from scripts.benchmarks.monthly_week_contract import validate_balanced_week
from scripts.build_four_season_interpretation import (
    COST_KEYS,
    FLOW_FIELDS,
    aggregate_slots,
    require_close,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"Missing evidence file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def semantic_hash(value: Any) -> str:
    """Hash the canonical JSON model content, distinct from a file SHA."""
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def audit_forecast_execution_import(
    week: str,
    forecast_manifest_path: Path,
    training_model_path: Path,
    forecast_week_path: Path,
) -> dict[str, Any]:
    """Verify the three forecast files recorded before the frozen execution."""
    imported = read_json(MONTHLY_INPUT_IMPORT)
    require(imported.get("target_root") == str(FROZEN_ROOT),
            "monthly_input_import target_root does not match frozen root")
    require(imported.get("target_sha") == EXPECTED_SHA,
            "monthly_input_import target_sha does not match expected SHA")
    verified = {
        str(row.get("path", "")).replace("\\", "/"): row.get("sha256")
        for row in imported.get("verified_files", [])
        if isinstance(row, dict)
    }
    relative_paths = {
        "manifest": "output/monthly_fair_weeks_20260914/forecast_holdouts/manifest.json",
        "training_model": "output/monthly_fair_weeks_20260914/forecast_holdouts/training_model.json",
        "weekly_forecast": f"output/monthly_fair_weeks_20260914/forecast_holdouts/{week}_forecast.json",
    }
    current_paths = {
        "manifest": forecast_manifest_path,
        "training_model": training_model_path,
        "weekly_forecast": forecast_week_path,
    }
    checks: dict[str, Any] = {}
    for key, relative in relative_paths.items():
        expected = verified.get(relative)
        require(isinstance(expected, str) and len(expected) == 64,
                f"monthly_input_import is missing {relative}")
        actual = digest(current_paths[key])
        require(actual == expected, f"{relative}: execution-import SHA mismatch")
        checks[key] = {
            "relative_path": relative,
            "absolute_path": str(current_paths[key]),
            "imported_sha256": expected,
            "current_sha256": actual,
            "matches": True,
        }
    return {
        "source_path": str(MONTHLY_INPUT_IMPORT),
        "target_root": imported["target_root"],
        "target_sha": imported["target_sha"],
        "checks": checks,
        "all_three_match": True,
    }


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def git_state() -> dict[str, str]:
    sha = subprocess.run(
        ["git", "-C", str(FROZEN_ROOT), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "-C", str(FROZEN_ROOT), "status", "--porcelain"],
        check=True, capture_output=True, text=True,
    ).stdout
    return {"sha": sha, "status_porcelain": status}


def validate_trip_contract(prepared: dict[str, Any]) -> dict[str, int]:
    """Reject missing/UNKNOWN operators, invalid distance, or trip-count drift."""
    trips = prepared["trips"]
    require(len(trips) == prepared["trip_count"], "prepared trip list length differs from trip_count")
    operator_unknown_count = sum(
        not trip.get("operator_id") or str(trip.get("operator_id")).upper() == "UNKNOWN"
        for trip in trips
    )
    distance_invalid_count = sum(
        not finite(trip.get("distance_km")) or float(trip["distance_km"]) <= 0
        for trip in trips
    )
    require(operator_unknown_count == 0, "prepared trips contain missing/UNKNOWN operator_id")
    require(distance_invalid_count == 0, "prepared trips contain missing/non-positive distance_km")
    return {
        "trip_list_length": len(trips),
        "operator_unknown_count": operator_unknown_count,
        "distance_zero_or_missing_count": distance_invalid_count,
    }


def resolve_campaign_status(
    progress_status: str | None,
    weeks: dict[str, Any],
    declared_weeks: list[str],
) -> str:
    """Resolve campaign status without allowing audit evidence to imply execution completion."""
    declared = set(declared_weeks)
    observed = set(weeks)
    require(len(declared_weeks) == len(declared), "campaign declared weeks are not unique")
    require(observed <= declared, "audit contains a week outside campaign_declared_weeks")
    all_declared_audited = (
        len(weeks) == len(declared_weeks)
        and observed == declared
        and all(
            value.get("status") == "DIAGNOSTIC_EXECUTION_PASSED"
            and value.get("audit_status") == "INDEPENDENTLY_AUDITED"
            and value.get("fully_audited") is True
            for value in weeks.values()
        )
    )
    if progress_status == "STOPPED_AFTER_FAILED_CASE":
        return "STOPPED_AFTER_FAILED_CASE"
    if progress_status == "COMPLETED":
        return "COMPLETED" if all_declared_audited else "AWAITING_AUDIT"
    if all_declared_audited:
        return "AWAITING_CAMPAIGN_COMPLETION"
    return "RUNNING_CAMPAIGN"


def read_search_controls(document: dict[str, Any], expected: dict[str, int]) -> dict[str, int]:
    """Read serialized adapter metadata, never infer controls from source defaults.

    The engine's solver_metadata projection omits the two new search fields.
    The complete serialized plan metadata preserves their actual solve values.
    If a projection does contain either field, it must agree with that original.
    """
    original = document.get("metadata") or {}
    projected = document.get("solver_metadata") or {}
    observed = {}
    for key, value in expected.items():
        require(key in original and type(original[key]) is int and original[key] == value,
                f"Missing or changed original metadata.{key}")
        require(key not in projected or projected[key] == original[key],
                f"Conflicting solver_metadata.{key}")
        observed[key] = original[key]
    return observed


def audit_native_entries(
    nested: Path, chain: Path, trip_count: int, design: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    day_path = nested / "canonical_solver_result.json"
    day = read_json(day_path)
    entries = [("day_ahead", None, day_path, day)]
    for hour in range(168):
        path = chain / f"hour_{hour:03d}" / "forecast_result.json"
        entries.append(("hourly", hour, path, read_json(path)))
    require(len(entries) == NATIVE_COUNT, "native solver entry count is not 169")

    invalid: list[dict[str, Any]] = []
    quality: dict[str, list[float]] = {key: [] for key in (
        "maximum_constraint_violation", "maximum_bound_violation", "maximum_integrality_violation"
    )}
    arc_values: dict[str, set[Any]] = {key: set() for key in (
        "candidate_arc_count_before_successor_pruning", "arc_count_after_successor_pruning",
        "pruned_arc_count", "pruned_origin_count", "max_candidate_successors_per_origin"
    )}
    control_values: dict[str, list[Any]] = {key: [] for key in (
        "synthetic_pv_fallback_applied", "postsolve_repair_allowed",
        "postsolve_modified_solution", "derived_source_split", "successor_pruning_enabled"
    )}
    fallback_counts: list[Any] = []
    compact_entries: list[dict[str, Any]] = []
    for kind, hour, path, document in entries:
        metadata = document.get("solver_metadata")
        require(isinstance(metadata, dict), f"{path}: missing solver_metadata")
        search_controls = read_search_controls(document, EXPECTED_SEARCH_CONTROLS)
        effective = document.get("effective_limits") or {}
        required_metadata = (
            "stage2_gurobi_aggregate", "stage2_gurobi_presolve",
            "stage2_gurobi_feasibility_tol", "stage2_gurobi_integrality_tol",
            "stage2_has_feasible_incumbent", "synthetic_pv_fallback_applied",
            "postsolve_repair_allowed", "postsolve_modified_solution",
            "derived_source_split", "successor_pruning_enabled",
            "arc_pruning_summary", "search_profile", "stage2_numeric_diagnostics",
        )
        for key in required_metadata:
            require(key in metadata, f"{path}: missing raw solver_metadata.{key}")
        arc = metadata["arc_pruning_summary"]
        for key in arc_values:
            require(key in arc, f"{path}: missing raw solver_metadata.arc_pruning_summary.{key}")
            arc_values[key].add(arc[key])
        for key in control_values:
            control_values[key].append(metadata[key])
        search_profile = metadata["search_profile"]
        require("fallback_count" in search_profile, f"{path}: missing raw search_profile.fallback_count")
        fallback_counts.append(search_profile["fallback_count"])
        quality_data = metadata["stage2_numeric_diagnostics"]
        for key in quality:
            require(finite(quality_data.get(key)), f"{path}: missing/non-finite {key}")
            quality[key].append(float(quality_data[key]))

        effective_limit = effective.get("stage2_time_limit_sec")
        if kind == "day_ahead":
            effective_limit = effective_limit
            limit_ok = effective_limit == float(design["stage2_time_limit_sec"])
        else:
            effective_limit = metadata.get("stage2_time_limit_sec_effective", effective_limit)
            limit_ok = finite(effective_limit) and 0.0 < float(effective_limit) <= float(
                design["rolling_hour_time_limit_sec"]
            )
        reasons: list[str] = []
        expected = {
            "stage2_gurobi_aggregate": 0,
            "stage2_gurobi_presolve": 0,
            "stage2_gurobi_feasibility_tol": 1.0e-9,
            "stage2_gurobi_integrality_tol": 1.0e-9,
        }
        for key, value in expected.items():
            if metadata.get(key) != value:
                reasons.append(key)
        if metadata["stage2_has_feasible_incumbent"] is not True:
            reasons.append("stage2_has_feasible_incumbent")
        if document.get("feasible") is not True:
            reasons.append("feasible")
        if not limit_ok:
            reasons.append("stage2_time_limit_sec_effective")
        if kind == "hourly":
            if document.get("trip_count_served") != trip_count:
                reasons.append("trip_count_served")
            if document.get("trip_count_unserved") != 0:
                reasons.append("trip_count_unserved")
        if reasons:
            invalid.append({"kind": kind, "hour": hour, "reasons": reasons})
        compact_entries.append({
            "kind": kind, "hour": hour, "path": str(path),
            "stage2_time_limit_sec_effective": effective_limit,
            "stage2_gurobi_aggregate": metadata["stage2_gurobi_aggregate"],
            "stage2_gurobi_presolve": metadata["stage2_gurobi_presolve"],
            "stage2_gurobi_feasibility_tol": metadata["stage2_gurobi_feasibility_tol"],
            "stage2_gurobi_integrality_tol": metadata["stage2_gurobi_integrality_tol"],
            "feasible": document.get("feasible"),
            "quality": quality_data,
            "search_controls": search_controls,
            "search_controls_source": "metadata",
        })

    def one_value(key: str) -> Any:
        values = arc_values[key]
        require(len(values) == 1, f"native arc field {key} is inconsistent or missing")
        return next(iter(values))

    for key, values in control_values.items():
        require(len(values) == NATIVE_COUNT and all(value is not None for value in values),
                f"native control field {key} is incomplete")
    require(all(value is False for value in control_values["synthetic_pv_fallback_applied"]),
            "synthetic PV fallback was applied")
    require(all(value is False for value in control_values["postsolve_repair_allowed"]),
            "postsolve repair was allowed")
    require(all(value is False for value in control_values["postsolve_modified_solution"]),
            "postsolve modified the solution")
    require(all(value is False for value in control_values["derived_source_split"]),
            "derived source split was applied")
    require(all(value is False for value in control_values["successor_pruning_enabled"]),
            "successor pruning was enabled")
    require(len(fallback_counts) == NATIVE_COUNT and all(value == 0 for value in fallback_counts),
            "fallback_count is missing or nonzero")

    native = {
        "day_ahead": compact_entries[0],
        "hourly_observed_count": 168,
        "hourly_expected_count": 168,
        "hourly_invalid_count": len(invalid),
        "hourly_invalid": [item for item in invalid if item["kind"] == "hourly"],
        "native_entry_count": NATIVE_COUNT,
        "native_invalid_count": len(invalid),
        "native_invalid": invalid,
        "all_hourly_native_strict": not any(item["kind"] == "hourly" for item in invalid),
        "all_native_strict": not invalid,
        "required_aggregate": 0,
        "required_presolve": 0,
        "required_feasibility_tol": 1.0e-9,
        "required_integrality_tol": 1.0e-9,
        "day_ahead_stage2_time_limit_sec": compact_entries[0]["stage2_time_limit_sec_effective"],
        "hourly_effective_stage2_time_limit_sec_min": min(
            item["stage2_time_limit_sec_effective"] for item in compact_entries[1:]
        ),
        "hourly_effective_stage2_time_limit_sec_max": max(
            item["stage2_time_limit_sec_effective"] for item in compact_entries[1:]
        ),
        "quality_maximums": {key: max(values) for key, values in quality.items()},
    }
    controls = {
        "successor_pruning_enabled": False,
        "candidate_arc_count_before_successor_pruning": one_value(
            "candidate_arc_count_before_successor_pruning"
        ),
        "arc_count_after_successor_pruning": one_value("arc_count_after_successor_pruning"),
        "pruned_arc_count": one_value("pruned_arc_count"),
        "pruned_origin_count": one_value("pruned_origin_count"),
        "synthetic_pv_fallback_applied": False,
        "postsolve_modified_solution": False,
        "derived_source_split": False,
        "fallback_used": False,
        "allow_postsolve_repair": False,
        "raw_control_evidence": {
            "entry_count": NATIVE_COUNT,
            "source_files": "canonical_solver_result.json and rolling_hourly_chain/hour_*/forecast_result.json",
            "synthetic_pv_fallback_applied": Counter(map(str, control_values["synthetic_pv_fallback_applied"])),
            "postsolve_repair_allowed": Counter(map(str, control_values["postsolve_repair_allowed"])),
            "postsolve_modified_solution": Counter(map(str, control_values["postsolve_modified_solution"])),
            "derived_source_split": Counter(map(str, control_values["derived_source_split"])),
            "successor_pruning_enabled": Counter(map(str, control_values["successor_pruning_enabled"])),
            "fallback_count": Counter(map(str, fallback_counts)),
            "arc_values": {key: sorted(values, key=str) for key, values in arc_values.items()},
        },
    }
    return native, compact_entries, controls


def audit_week(week: str) -> dict[str, Any]:
    require(len(week) == 10 and week[4] == "-" and week[7] == "-", "week must be YYYY-MM-DD")
    case = CAMPAIGN / "cases" / week
    nested = case / "diagnostic" / week
    chain = nested / "rolling_hourly_chain"
    input_audit = read_json(nested / "input_audit.json")
    prepared_id = input_audit["prepared_input_id"]
    scenario_id = input_audit["scenario_id"]
    prepared_path = FROZEN_ROOT / "output" / "prepared_inputs" / scenario_id / f"{prepared_id}.json"
    files = {
        "case_summary": nested / "summary.json",
        "prepared_input": prepared_path,
        "executed_day_accounting": chain / "executed_day_accounting.json",
        "executed_plan": chain / "executed_plan.json",
        "physical_validation": chain / "physical_validation.json",
        "input_audit": nested / "input_audit.json",
        "prepared_input_audit": case / "diagnostic" / "prepared_input_audit.json",
        "fleet_audit": case / "diagnostic" / "parent_fleet_audit.json",
        "scope_audit": case / "diagnostic" / "scope_audit.json",
        "design": case / "design.json",
        "prepared_manifest": CAMPAIGN / "inputs" / week / "derived_scenarios.json",
        "canonical_solver_result": nested / "canonical_solver_result.json",
    }
    documents = {key: read_json(path) for key, path in files.items()}
    summary = documents["case_summary"]
    prepared = documents["prepared_input"]
    accounting = documents["executed_day_accounting"]
    plan = documents["executed_plan"]
    physical = documents["physical_validation"]
    design = documents["design"]
    config = input_audit["config"]
    require(summary["status"] == "DIAGNOSTIC_EXECUTION_PASSED", f"{week}: status gate")
    require(summary["hourly_steps_accepted"] == 168, f"{week}: hourly gate")
    require(summary["day_ahead_physical_accepted"] is True and summary["physical_accepted"] is True,
            f"{week}: physical summary gate")
    require(physical["accepted"] is True and physical["status"] == "VALID" and not physical["violations"],
            f"{week}: physical validation gate")
    require(accounting["eligible"] is True and accounting["expected_slot_count"] == 672
            and accounting["executed_slot_count"] == 672 and not accounting["missing_slots"]
            and not accounting["duplicate_slots"], f"{week}: accounting gate")
    require(prepared["trip_count"] == 1704 and len(prepared["vehicles"]) == 60, f"{week}: prepared counts")
    trip_contract = validate_trip_contract(prepared)
    fleet = Counter(vehicle["type"] for vehicle in prepared["vehicles"])
    require(dict(fleet) == {"BEV": 35, "ICE": 25}, f"{week}: fleet mix")
    balanced = validate_balanced_week(
        prepared["trips"], prepared["simulation_config"]["date_series_contract"], week=week
    )
    require(balanced["day_type_counts"] == {"weekday": 5, "saturday": 1, "sunday_or_holiday": 1},
            f"{week}: balanced-week gate")
    date_contract = prepared["simulation_config"]["date_series_contract"]
    require(date_contract["source_provenance"]["holiday_source_sha256"] == design["calendar_source_sha256"],
            f"{week}: holiday source drift")
    expected_config = {
        "phase": "phase3_two_stage", "time_limit_sec": 900,
        "stage1_time_limit_sec": 120, "stage2_time_limit_sec": 120,
        "random_seed": 42, "gurobi_threads": 12, "mip_gap": 0.1,
    }
    observed_config = {key: config.get(key) for key in expected_config}
    require(observed_config == expected_config, f"{week}: input config drift")
    require(design["phase"] == expected_config["phase"]
            and design["stage1_time_limit_sec"] == 120
            and design["stage2_time_limit_sec"] == 120
            and design["rolling_hour_time_limit_sec"] == 15
            and design["threads"] == 12 and design["seed"] == 42
            and design["mip_gap"] == 0.1 and design["successor_pruning"] == 0
            and design["postsolve_repair"] is False, f"{week}: design drift")
    require(config.get("allow_postsolve_repair") is False, f"{week}: input repair control drift")

    native, compact_entries, controls = audit_native_entries(
        nested, chain, prepared["trip_count"], design
    )
    require(native["all_native_strict"], f"{week}: native solver gate")
    controls.update({
        "fleet_count": len(prepared["vehicles"]),
        "expected_fleet": design["expected_fleet"],
        "diagnostic_only": design["diagnostic_only"],
        "research_status": design["research_status"],
    })
    require(controls["candidate_arc_count_before_successor_pruning"]
            == controls["arc_count_after_successor_pruning"]
            and controls["pruned_arc_count"] == 0 and controls["pruned_origin_count"] == 0,
            f"{week}: full-network gate")

    ledger_total = math.fsum(row["total_cost_jpy"] for row in plan["daily_cost_ledger"])
    cost = accounting["cost_breakdown"]
    require_close(ledger_total, cost["total_cost"], "daily ledger")
    require_close(math.fsum(cost[key] for key in (
        "vehicle_usage_cost", "electricity_cost", "fuel_cost", "co2_cost", "contract_overage_cost"
    )), cost["total_cost"], "cost components")
    slots = {key: aggregate_slots(plan, fields) for key, fields in FLOW_FIELDS.items()}
    for key, values in slots.items():
        require_close(math.fsum(values), cost[key], key)
    require_close(max(slots["grid_import_kwh"]) / 0.25, cost["peak_grid_kw"], "peak")
    require_close(cost["pv_used_total_kwh"] + cost["pv_curtailed_kwh"], cost["pv_generated_kwh"], "PV balance")
    require_close(math.fsum(max(value - 50.0, 0.0) for value in slots["grid_import_kwh"]),
                  cost["contract_over_limit_kwh"], "contractual excess")
    require_close(cost["contract_over_limit_kwh"] * 500.0, cost["contract_overage_cost"], "overage price")

    before = read_json(nested / "git_state_before.json")
    after = read_json(nested / "git_state_after.json")
    current = git_state()
    expected_state = {"sha": EXPECTED_SHA, "status_porcelain": ""}
    require(before == after == expected_state and current == expected_state,
            f"{week}: frozen source drift")

    forecast_dir = FORECAST_DIR
    forecast_manifest_path = forecast_dir / "manifest.json"
    forecast_week_path = forecast_dir / f"{week}_forecast.json"
    forecast_manifest = read_json(forecast_manifest_path)
    forecast_week = read_json(forecast_week_path)
    training_model_path = forecast_dir / "training_model.json"
    training_model = read_json(training_model_path)
    forecast_manifest_file_sha = digest(forecast_manifest_path)
    forecast_week_file_sha = digest(forecast_week_path)
    model_file_sha = digest(training_model_path)
    model_semantic_sha = semantic_hash(training_model)
    execution_import = audit_forecast_execution_import(
        week, forecast_manifest_path, training_model_path, forecast_week_path
    )
    forecast_hash_ok = (
        forecast_manifest["status"] == "TRAINING_AND_TEST_SEPARATED"
        and forecast_manifest["model_sha256"] == forecast_week["model_sha256"]
        and forecast_manifest["model_sha256"] == model_semantic_sha
        and forecast_manifest["artifacts"]["training_model.json"] == model_file_sha
    )
    require(forecast_hash_ok, f"{week}: forecast model/hash gate")

    prepared_forecast_audit = date_contract.get("forecast_audit")
    require(isinstance(prepared_forecast_audit, dict),
            f"{week}: missing date_series_contract.forecast_audit")
    require(prepared_forecast_audit.get("model_sha256") == model_file_sha,
            f"{week}: prepared forecast_audit model file SHA drift")
    require(prepared_forecast_audit.get("manifest_sha256") == forecast_manifest_file_sha,
            f"{week}: prepared forecast_audit manifest SHA drift")
    require(prepared_forecast_audit.get("weekly_profile_sha256") == forecast_week_file_sha,
            f"{week}: prepared forecast_audit weekly profile SHA drift")

    hashes = {key: digest(path) for key, path in files.items()}
    for key in ("case_summary", "prepared_input", "executed_day_accounting", "executed_plan", "physical_validation"):
        hashes[key] = hashes[key]
    terminal = accounting["bess_terminal_soc_by_depot"]["tsurumaki"]
    record = {
        "status": summary["status"], "audit_status": "INDEPENDENTLY_AUDITED",
        "fully_audited": True, "research_status": summary["research_status"],
        "case_root": str(nested), "case_root_relative": str(nested.relative_to(FROZEN_ROOT)).replace("\\", "/"),
        "prepared_input_path": str(prepared_path),
        "prepared_input_path_relative": str(prepared_path.relative_to(FROZEN_ROOT)).replace("\\", "/"),
        "prepared_manifest_path": str(files["prepared_manifest"]),
        "prepared_manifest_path_relative": str(files["prepared_manifest"].relative_to(FROZEN_ROOT)).replace("\\", "/"),
        "hashes": {**{f"{key}_sha256": value for key, value in hashes.items()},
                   **{key: hashes[key] for key in ("case_summary", "prepared_input", "executed_day_accounting", "executed_plan", "physical_validation")}},
        "prepared_contract": {
            "status": documents["prepared_input_audit"]["status"], "scenario_id": scenario_id,
            "prepared_input_id": prepared_id, "service_dates": prepared["service_dates"],
            "planning_days": prepared["planning_days"], "trip_count": prepared["trip_count"],
            "timetable_row_count": prepared["timetable_row_count"], "vehicle_count": len(prepared["vehicles"]),
            "fleet_counts": dict(fleet), **trip_contract,
            "balanced_week_audit": balanced, "forecast_holdout_status": forecast_manifest["status"],
            "forecast_model_sha256": forecast_manifest["model_sha256"],
            "forecast_model_semantic_sha256": model_semantic_sha,
            "forecast_model_file_sha256": model_file_sha,
            "forecast_training_end_exclusive": forecast_week["training_end_exclusive"],
            "future_weather_class_known": design["future_weather_class_known"], "valid": True,
        },
        "execution": {
            "case_status": summary["status"], "trip_count": summary["trip_count"],
            "hourly_steps_accepted": summary["hourly_steps_accepted"], "expected_hourly_steps": 168,
            "expected_slot_count": 672, "executed_slot_count": accounting["executed_slot_count"],
            "missing_slots": accounting["missing_slots"], "duplicate_slots": accounting["duplicate_slots"],
            "day_ahead_feasible": summary["day_ahead_feasible"], "day_ahead_status": summary["day_ahead_status"],
            "day_ahead_physical_accepted": summary["day_ahead_physical_accepted"],
            "physical_accepted": summary["physical_accepted"], "accounting_eligible": summary["accounting_eligible"],
            "formal_solve": summary["formal_solve"], "fully_accepted": True,
        },
        "accounting": {
            "executed_day_accounting_total_cost_jpy": cost["total_cost"],
            "executed_plan_daily_ledger_total_cost_jpy": ledger_total,
            "cost_difference_jpy": abs(float(cost["total_cost"]) - ledger_total),
            "within_1e-6_jpy": True, "daily_ledger_rows": len(plan["daily_cost_ledger"]),
            "accounting_basis": accounting["accounting_basis"],
            "objective_aggregation": accounting["objective_aggregation"],
            "terminal_energy_balanced": accounting["terminal_energy_balanced"],
            "bev_terminal_energy_balanced": accounting["bev_terminal_energy_balanced"],
            "bess_terminal_energy_balanced": accounting["bess_terminal_energy_balanced"],
            "bess_daily_energy_balanced": accounting["bess_daily_energy_balanced"],
            "cost_breakdown": {key: cost[key] for key in COST_KEYS if key in cost},
        },
        "controls": controls,
        "full_network": {
            "successor_pruning_enabled": False,
            "pruned_arc_count": controls["pruned_arc_count"],
            "pruned_origin_count": controls["pruned_origin_count"],
            "max_candidate_successors_per_origin": controls["raw_control_evidence"]["arc_values"]["max_candidate_successors_per_origin"][0],
            "full_candidate_network_preserved": True,
        },
        "physical_validation": {"accepted": physical["accepted"], "status": physical["status"],
                                "violations": physical["violations"], "metrics": physical["metrics"],
                                "all_metric_counts_zero": all(value == 0 for value in physical["metrics"].values())},
        "native_stage2_metadata": native,
        "config_audit": {"expected": expected_config, "observed": observed_config, "config_match": True},
        "source_state": {"expected_sha": EXPECTED_SHA, "campaign_before": before, "campaign_after": after,
                          "observed_sha": current["sha"], "observed_status_porcelain": current["status_porcelain"],
                          "clean_before_after": True, "stable": True},
        "forecast_audit": {"manifest_status": forecast_manifest["status"],
                            "manifest_declared_model_sha256": forecast_manifest["model_sha256"],
                            "week_declared_model_sha256": forecast_week["model_sha256"],
                            "semantic_model_sha256": model_semantic_sha,
                            "training_model_file_sha256": model_file_sha,
                            "manifest_file_sha256": forecast_manifest_file_sha,
                            "weekly_profile_file_sha256": forecast_week_file_sha,
                            "manifest_training_model_artifact_sha256": forecast_manifest["artifacts"]["training_model.json"],
                            "prepared_date_series_forecast_audit": prepared_forecast_audit,
                            "execution_import_contract": execution_import,
                            "semantic_model_hash_consistent": True,
                            "file_hash_consistent": True,
                            "model_hash_consistent": True},
        "bess_terminal": {"tsurumaki": terminal},
        "schema_contract": {"consumer_status": "DIAGNOSTIC_EXECUTION_PASSED", "audit_status_field": "audit_status",
                            "canonical_hash_keys": ["case_summary", "prepared_input", "executed_day_accounting", "executed_plan", "physical_validation"],
                            "canonical_hashes_are_sha256_of": "the exact files named by the corresponding path fields"},
    }
    return record


def write_audit(week: str, output: Path) -> dict[str, Any]:
    require(output.suffix.lower() == ".json", "--audit-output must be a JSON path")
    existing = read_json(output) if output.exists() else {}
    if existing:
        require(existing.get("expected_sha") == EXPECTED_SHA, "existing audit has a different source SHA")
        require(existing.get("frozen_root") == str(FROZEN_ROOT), "existing audit has a different frozen root")
        require(existing.get("campaign_output") == CAMPAIGN.relative_to(FROZEN_ROOT).as_posix(),
                "existing audit has a different campaign")
    campaign_design = read_json(CAMPAIGN / "design.json")
    declared_weeks = campaign_design.get("campaign_declared_weeks")
    require(isinstance(declared_weeks, list) and len(declared_weeks) == 12,
            "campaign design must declare exactly twelve weeks")
    require(week in declared_weeks, f"{week}: week is not in campaign_declared_weeks")
    record = audit_week(week)
    progress_path = CAMPAIGN / "progress.json"
    progress = read_json(progress_path) if progress_path.exists() else {}
    require(progress.get("base_git_sha", EXPECTED_SHA) == EXPECTED_SHA,
            "campaign progress has a different source SHA")
    weeks = dict(existing.get("weeks") or {})
    weeks[week] = record
    require(set(weeks) <= set(declared_weeks),
            "existing audit contains a week outside campaign_declared_weeks")
    audited_count = sum(value.get("fully_audited") is True for value in weeks.values())
    passed_count = sum(value.get("status") == "DIAGNOSTIC_EXECUTION_PASSED"
                       and value.get("audit_status") == "INDEPENDENTLY_AUDITED"
                       and value.get("fully_audited") is True for value in weeks.values())
    progress_status = progress.get("status")
    campaign_status = resolve_campaign_status(progress_status, weeks, declared_weeks)
    report = dict(existing)
    report.update({
        "schema_version": "monthly_budget_independent_audit_v1",
        "frozen_root": str(FROZEN_ROOT), "expected_sha": EXPECTED_SHA,
        "campaign_output": CAMPAIGN.relative_to(FROZEN_ROOT).as_posix(), "status": campaign_status,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(), "weeks": weeks,
        "expected_week_count": len(declared_weeks), "selected_weeks": declared_weeks,
        "campaign_progress": {
            "campaign_status": progress_status,
            "audited_week_count": audited_count,
            "passed_audited_week_count": passed_count,
            "declared_week_count": len(declared_weeks),
            "completed_weeks": progress.get("completed_weeks", []),
            "active_week": progress.get("active_week"),
        },
    })
    report.setdefault("required_contracts", {
        "hourly_steps": 168, "slots": 672, "native_solver_entries": 169,
        "accounting_tolerance_jpy": TOLERANCE, "source_clean_and_sha": EXPECTED_SHA,
    })
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=output.parent, prefix=f".{output.name}.",
        suffix=".tmp", delete=False
    ) as stream:
        temporary_path = Path(stream.name)
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary_path, output)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--week", required=True)
    parser.add_argument("--audit-output", required=True, type=Path)
    args = parser.parse_args()
    record = write_audit(args.week, args.audit_output)
    print(json.dumps({"week": args.week, "status": record["status"],
                      "fully_audited": record["fully_audited"],
                      "native_entries": record["native_stage2_metadata"]["native_entry_count"],
                      "all_native_strict": record["native_stage2_metadata"]["all_native_strict"],
                      "hash_count": len(record["hashes"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
