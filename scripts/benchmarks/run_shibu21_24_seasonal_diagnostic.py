"""Preflight and run the combined Shibu21/22/23/24 seasonal diagnostic.

The default command is a read-only scope preflight. It records exact route
matching, available timetable evidence, and blockers before any optimization.
Use ``--run`` only after the parent has frozen the source. Each dated case
must pass the repository Prepare contract and complete the strict transition
audit before its solve. A lightweight candidate with a deferred audit is retained
for diagnosis but blocks that case. This module reuses the
established Shibu21 solver helpers and never downgrades an incomplete route
scope to a smaller case.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import subprocess
import sys
import traceback
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.benchmarks.run_shibu21_seasonal_diagnostic import solve_week, write_json
from scripts.benchmarks.monthly_week_contract import validate_balanced_week
from scripts.benchmarks.seasonal_design_contract import require_execution_enabled, seasonal_bess_controls
from src.optimization.common.bess_terminal_policy import resolve_bess_terminal_soc_target_kwh
from src.optimization.common.date_series import content_hash
from src.optimization.common.soc_helpers import (
    effective_final_soc_target_kwh,
    is_electric_vehicle,
    vehicle_initial_soc_kwh,
)


def verify_evaluation_contract(problem, design: dict) -> dict:
    """Verify BEV and seasonal BESS terminal controls before a diagnostic solve."""
    controls = seasonal_bess_controls(design)
    metadata = problem.metadata
    if metadata.get("bev_terminal_soc_policy") != design["bev_evaluation_terminal_policy"]:
        raise ValueError("Prepared BEV terminal policy differs from the declared evaluation")
    if float(metadata.get("final_soc_target_tolerance_percent") or 0) != 0:
        raise ValueError("The evaluation forbids an inherited percentage terminal tolerance")
    if metadata.get("daily_return_depot_id") != design["daily_return_depot_id"]:
        raise ValueError("Prepared daily return depot differs from the declared evaluation")
    if metadata.get("rolling_window_terminal_policy") != design["rolling_window_terminal_policy"]:
        raise ValueError("The declared rolling boundary policy was not preserved")
    if metadata.get("rolling_bess_terminal_policy", "scenario") != design["rolling_bess_terminal_policy"]:
        raise ValueError("The declared rolling BESS terminal policy was not preserved")
    if metadata.get("bess_balance_period") != design["bess_balance_period"]:
        raise ValueError("Prepared BESS balance period differs from the declared evaluation")
    if metadata.get("bess_forecast_reserve_policy", "physical_floor_only") != controls["bess_forecast_reserve_policy"]:
        raise ValueError("Prepared BESS forecast reserve differs from the declared evaluation")
    if controls["bess_forecast_reserve_policy"] in ("evaluation_target_zero_pv", "evaluation_target_every_prefix"):
        from src.optimization.rolling.reoptimizer import RollingReoptimizer
        from src.optimization.common.bess_reserve_policy import bess_reserve_targets
        bess_reserve_targets(RollingReoptimizer._freeze_bess_terminal_soc_targets(problem))

    vehicle_targets = {}
    for vehicle in problem.vehicles:
        if not is_electric_vehicle(problem, vehicle):
            continue
        initial = vehicle_initial_soc_kwh(problem, vehicle)
        target = effective_final_soc_target_kwh(problem, vehicle)
        if target is None or abs(target - initial) > 1.0e-6:
            raise ValueError(
                f"Terminal target does not return {vehicle.vehicle_id} to its own initial state"
            )
        vehicle_targets[vehicle.vehicle_id] = {
            "initial_kwh": initial,
            "terminal_target_kwh": target,
        }

    bess_controls = {}
    expected_floor_ratio = float(design.get("bess_terminal_soc_floor_percent", 20.0)) / 100.0
    for depot_id, asset in (problem.depot_energy_assets or {}).items():
        if not asset.bess_enabled:
            continue
        capacity = float(asset.bess_energy_kwh or 0.0)
        expected_min = capacity * expected_floor_ratio
        expected_max = capacity * (1.0 - expected_floor_ratio)
        if abs(float(asset.bess_soc_min_kwh) - expected_min) > 1.0e-6:
            raise ValueError(f"BESS {depot_id} minimum SOC is not the declared 20% capacity floor")
        if abs(float(asset.bess_soc_max_kwh) - expected_max) > 1.0e-6:
            raise ValueError(f"BESS {depot_id} maximum SOC is not the declared 80% capacity ceiling")
        if abs(float(asset.bess_terminal_soc_min_kwh) - expected_min) > 1.0e-6:
            raise ValueError(f"BESS {depot_id} terminal floor is not the declared 20% capacity floor")
        if str(asset.bess_balance_period) != design["bess_balance_period"]:
            raise ValueError(f"BESS {depot_id} balance period differs from the declared evaluation")
        if str(asset.bess_terminal_soc_policy) != design["bess_terminal_soc_policy"]:
            raise ValueError(f"BESS {depot_id} terminal policy differs from the declared evaluation")
        target = resolve_bess_terminal_soc_target_kwh(
            policy=asset.bess_terminal_soc_policy,
            initial_soc_kwh=asset.bess_initial_soc_kwh,
            configured_target_kwh=asset.bess_terminal_soc_target_kwh,
            terminal_soc_floor_kwh=asset.bess_terminal_soc_min_kwh,
            maximum_soc_kwh=asset.bess_soc_max_kwh,
        )
        expected_target = (
            float(asset.bess_initial_soc_kwh)
            if controls["bess_terminal_soc_policy"] == "return_to_initial"
            else None
        )
        if (target is None) != (expected_target is None) or (
            target is not None and abs(target - expected_target) > 1.0e-6
        ):
            raise ValueError(f"BESS {depot_id} terminal SOC target differs from the declared evaluation")
        bess_controls[str(depot_id)] = {
            "capacity_kwh": capacity,
            "initial_soc_kwh": float(asset.bess_initial_soc_kwh),
            "soc_min_kwh": float(asset.bess_soc_min_kwh),
            "soc_max_kwh": float(asset.bess_soc_max_kwh),
            "terminal_soc_floor_kwh": float(asset.bess_terminal_soc_min_kwh),
            "terminal_soc_policy": str(asset.bess_terminal_soc_policy),
            "terminal_soc_target_kwh": target,
        }
    return {
        "status": "DECLARED_TERMINAL_CONTROLS_VERIFIED",
        "vehicle_targets": vehicle_targets,
        "bess_controls": bess_controls,
        "bess_balance_period": design["bess_balance_period"],
        "rolling_bess_terminal_policy": design["rolling_bess_terminal_policy"],
        "bess_forecast_reserve_policy": controls["bess_forecast_reserve_policy"],
    }


def git_state() -> dict:
    """Capture the source revision and dirty state for the formal run gate."""
    return {
        "sha": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "status_porcelain": subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ),
    }


_SEASONAL_HOURS = 168


def _verified_persisted_progress(output: Path, week: str) -> dict:
    """Read only the safe progress fields written by ``solve_week``.

    A failed solve must not inherit cost or acceptance fields from a partially
    written JSON file.  The accepted-hour count is trusted only when its type,
    week, and completed-prefix artifacts agree with the runner's write order.
    """

    path = output / "progress.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict) or payload.get("week") != week:
        return {}

    accepted = payload.get("hourly_steps_accepted")
    if isinstance(accepted, bool) or not isinstance(accepted, int):
        return {}
    if not 0 <= accepted <= _SEASONAL_HOURS:
        return {}

    physical = payload.get("day_ahead_physical_accepted")
    if physical is not None and not isinstance(physical, bool):
        return {}

    # A positive prefix is meaningful only after the day-ahead physical gate
    # passed.  Keep that gate as an independent diagnostic field, but never
    # let an unverified prefix count escape from the exception path.
    if accepted > 0 and physical is not True:
        return {
            "hourly_steps_accepted": 0,
            **({"day_ahead_physical_accepted": physical} if physical is not None else {}),
        }

    verified = {"hourly_steps_accepted": accepted}
    if physical is not None:
        verified["day_ahead_physical_accepted"] = physical
    if accepted == 0:
        return verified

    # ``solve_week`` writes progress only after the complete execution state,
    # PV audit, and accepted prefix have been persisted.  Parse and validate
    # those files before inferring the next failed hour; file existence alone
    # would allow truncated or placeholder JSON to overstate progress.
    for hour in range(accepted):
        folder = output / "rolling_hourly_chain" / f"hour_{hour:03d}"
        try:
            forecast = json.loads(
                (folder / "forecast_result.json").read_text(encoding="utf-8")
            )
            execution_state = json.loads(
                (folder / "execution_state.json").read_text(encoding="utf-8")
            )
            pv_audit = json.loads(
                (folder / "pv_execution_audit.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {
                "hourly_steps_accepted": 0,
                "day_ahead_physical_accepted": physical,
            }
        if (
            not isinstance(forecast, dict)
            or forecast.get("feasible") is not True
            or not isinstance(execution_state, dict)
            or isinstance(execution_state.get("current_min"), bool)
            or not isinstance(execution_state.get("current_min"), int)
            or execution_state.get("current_min") != (hour + 1) * 60
            or not isinstance(pv_audit, dict)
            or not isinstance(pv_audit.get("policy"), str)
            or not pv_audit["policy"]
            or isinstance(pv_audit.get("start_slot"), bool)
            or not isinstance(pv_audit.get("start_slot"), int)
            or isinstance(pv_audit.get("stop_slot"), bool)
            or not isinstance(pv_audit.get("stop_slot"), int)
            or pv_audit["start_slot"] != hour * 4
            or pv_audit["stop_slot"] != (hour + 1) * 4
            or pv_audit.get("bus_charging_commands_unchanged") is not True
            or not isinstance(pv_audit.get("rows"), list)
            or pv_audit.get("future_observations_used") is not False
            or not isinstance(pv_audit.get("provenance"), str)
            or not pv_audit["provenance"]
        ):
            return {
                "hourly_steps_accepted": 0,
                "day_ahead_physical_accepted": physical,
            }
    if accepted < _SEASONAL_HOURS:
        verified["failed_hour"] = accepted
    return verified


def normalize_route_code(value: object) -> str:
    """Normalize route labels for exact equality, preserving route semantics."""
    return "".join(unicodedata.normalize("NFKC", str(value or "")).split())


def _route_code(row: dict) -> str:
    for key in ("routeCode", "route_code", "routeFamilyCode", "route_family", "routeSeriesCode"):
        value = normalize_route_code(row.get(key))
        if value:
            return value
    return ""


def _load_rows(path: Path, key: str | None = None) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if key is None:
        return payload if isinstance(payload, list) else []
    rows = payload.get(key, []) if isinstance(payload, dict) else []
    return rows if isinstance(rows, list) else []


def discover_route_scope(config: dict) -> dict:
    """Audit route patterns and timetable evidence without mutating scenarios."""
    requested = [normalize_route_code(value) for value in config["route_codes"]]
    source_paths = [ROOT / config["route_source"], ROOT / config["route_source_fallback"]]
    matches: dict[str, list[dict]] = {code: [] for code in requested}
    source_counts: dict[str, int] = {}
    for path in source_paths:
        if not path.is_file():
            source_counts[str(path.relative_to(ROOT))] = -1
            continue
        key = None if path.name == "selected_routes.json" else "routes"
        rows = _load_rows(path, key)
        source_counts[str(path.relative_to(ROOT))] = len(rows)
        for row in rows:
            code = _route_code(row)
            if code in matches:
                matches[code].append({
                    "id": row.get("id"),
                    "route_code": code,
                    "routeCode": row.get("routeCode"),
                    "routeFamilyCode": row.get("routeFamilyCode"),
                    "source": str(path.relative_to(ROOT)),
                })

    deduped: dict[str, list[dict]] = {}
    for code, rows in matches.items():
        seen: set[str] = set()
        deduped[code] = []
        for row in rows:
            identity = str(row.get("id") or "")
            if not identity:
                identity = f"{row.get('source')}::{len(deduped[code])}"
            if identity not in seen:
                seen.add(identity)
                deduped[code].append(row)

    audit_path = ROOT / config["route_timetable_audit_source"]
    timetable_summary: dict[str, dict] = {code: {"dataset_items": 0, "trip_count": 0} for code in requested}
    if audit_path.is_file():
        rows = _load_rows(audit_path)
        if not rows:
            rows = _load_rows(audit_path, "items")
        for row in rows:
            code = normalize_route_code(row.get("route_code") or row.get("routeCode"))
            if code in timetable_summary:
                timetable_summary[code]["dataset_items"] += 1
                timetable_summary[code]["trip_count"] += int(row.get("trip_count") or 1)

    blockers = []
    for code in requested:
        if not deduped[code]:
            blockers.append(f"{code}: no exact NFKC route-pattern match in the verified sources")
        if timetable_summary[code]["trip_count"] <= 0:
            blockers.append(f"{code}: verified timetable dataset has zero trips")

    return {
        "status": "BLOCKED_ROUTE_SCOPE" if blockers else "ROUTE_SCOPE_READY",
        "requested_route_codes": requested,
        "matching_rule": "NFKC(value).strip-equivalent exact equality",
        "route_pattern_matches": deduped,
        "route_pattern_match_counts": {code: len(rows) for code, rows in deduped.items()},
        "timetable_evidence": timetable_summary,
        "source_row_counts": source_counts,
        "blockers": blockers,
        "route_scope_complete": not blockers,
    }


def _route_metadata_provenance_verified(prepared_payload: dict, case: dict) -> bool:
    routes = prepared_payload.get("routes")
    if not isinstance(routes, list) or not routes:
        return False
    if any(not isinstance(route, dict) or not str(route.get("id") or "").strip() for route in routes):
        return False
    if len({route["id"] for route in routes}) != len(routes):
        return False
    distances = [route.get("distanceKm") for route in routes]
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not math.isfinite(value) or value <= 0 for value in distances
    ):
        return False
    catalog_audit = (case.get("scope_summary") or {}).get("route_catalog_audit") or {}
    declared_hash = case.get("declared_route_metadata_sha256")
    return bool(
        declared_hash and case.get("route_metadata_preserved") is True
        and content_hash({route["id"]: route for route in routes}) == declared_hash
        and catalog_audit.get("issueCount") == 0
        and catalog_audit.get("checkedRouteCount") == len(routes)
    )


def audit_prepared_inputs(config: dict) -> dict:
    root = ROOT / config["input_manifests_directory"]
    prepared_root = ROOT / config.get("prepared_inputs_directory", "output/prepared_inputs")
    cases = {}
    blockers = []
    for week in config["evaluation_weeks"]:
        path = root / week / "derived_scenarios.json"
        if not path.is_file():
            cases[week] = {"status": "MISSING", "path": str(path.relative_to(ROOT))}
            blockers.append(f"{week}: missing prepared-input manifest")
            continue
        manifest = json.loads(path.read_text(encoding="utf-8"))
        rows = manifest.get("cases") or []
        case = rows[0] if rows else {}
        valid = bool(case.get("input_preparation_valid"))
        prepared_input_id = str(case.get("prepared_input_id") or "")
        scenario_id = str(case.get("scenario_id") or "")
        prepared_namespace = str(case.get("prepared_input_namespace") or "formal_prepared_inputs")
        candidate_path = None
        if case.get("prepared_input_path"):
            candidate_path = ROOT / str(case["prepared_input_path"])
        prepared_path = (
            prepared_root / scenario_id / f"{prepared_input_id}.json"
            if scenario_id and prepared_input_id and prepared_namespace == "formal_prepared_inputs"
            else candidate_path if prepared_namespace == "candidate_prepared_inputs" else None
        )
        prepared_payload = None
        prepared_audit = {}
        contract_status = "INVALID"
        contract_blocker = None
        if prepared_namespace == "candidate_prepared_inputs" and prepared_path and prepared_path.is_file():
            prepared_payload = json.loads(prepared_path.read_text(encoding="utf-8"))
            prepared_audit = dict(prepared_payload.get("prepared_scope_audit") or {})
        if prepared_namespace == "candidate_prepared_inputs":
            contract_status = "BLOCKED_CANDIDATE_NAMESPACE"
            contract_blocker = (
                f"{week}: candidate prepared input is outside the formal prepared_inputs namespace"
            )
        elif valid and prepared_path is None:
            contract_status = "BLOCKED_PREPARED_ID_MISSING"
            contract_blocker = f"{week}: prepared scenario/input identity is missing"
        elif valid and not prepared_path.is_file():
            contract_status = "BLOCKED_PREPARED_FILE_MISSING"
            contract_blocker = f"{week}: canonical prepared input file is missing"
        elif valid:
            prepared_payload = json.loads(prepared_path.read_text(encoding="utf-8"))
            prepared_audit = dict(prepared_payload.get("prepared_scope_audit") or {})
            audit_status = str(prepared_audit.get("status") or "")
            strict_executed = prepared_audit.get("strict_transition_audit_executed")
            if audit_status == "CANONICAL_INPUT_PREPARED_STRICT_TRANSITION_AUDIT_DEFERRED" or strict_executed is False:
                contract_status = "BLOCKED_STRICT_TRANSITION_AUDIT_DEFERRED"
                contract_blocker = (
                    f"{week}: lightweight canonical candidate has deferred strict transition audit"
                )
            elif not prepared_audit:
                contract_status = "BLOCKED_PREPARED_AUDIT_MISSING"
                contract_blocker = f"{week}: prepared input has no prepared_scope_audit"
            else:
                required_checks = (
                    "formal_transition_network_ready",
                    "formal_turnaround_sensitivity_ready",
                    "formal_vehicle_trip_compatibility_ready",
                )
                failed_checks = [key for key in required_checks if prepared_audit.get(key) is not True]
                strict_coverage = dict(prepared_audit.get("strict_coverage_precheck") or {})
                if strict_coverage.get("checked") is not True:
                    failed_checks.append("strict_coverage_precheck_not_checked")
                if strict_coverage.get("infeasible") is True:
                    failed_checks.append("strict_coverage_precheck_infeasible")
                if failed_checks:
                    contract_status = "BLOCKED_PREPARED_SCOPE_CONTRACT"
                    contract_blocker = f"{week}: " + ", ".join(failed_checks)
                elif not _route_metadata_provenance_verified(prepared_payload, case):
                    contract_status = "BLOCKED_ROUTE_METADATA_PROVENANCE"
                    contract_blocker = f"{week}: captured route metadata, distance, or catalog audit is unverified"
                else:
                    contract_status = "READY"
        balanced_week_audit = None
        if contract_status == "READY" and config.get("require_balanced_monthly_weeks"):
            try:
                date_contract = prepared_payload["simulation_config"]["date_series_contract"]
                balanced_week_audit = validate_balanced_week(
                    prepared_payload["trips"], date_contract, week=week,
                )
                forecast_audit = date_contract.get("forecast_audit") or {}
                if (balanced_week_audit != case.get("balanced_week_audit")
                        or date_contract["source_provenance"].get("holiday_source_sha256") != config["calendar_source_sha256"]
                        or forecast_audit != case.get("forecast_audit")
                        or forecast_audit.get("weekly_profile_verified") is not True
                        or forecast_audit.get("training_end_exclusive") != config["training_end_exclusive"]):
                    raise ValueError("Prepared monthly calendar/forecast evidence differs from its manifest")
            except (KeyError, TypeError, ValueError) as exc:
                contract_status = "BLOCKED_MONTHLY_WEEK_CONTRACT"
                contract_blocker = f"{week}: {exc}"
        if not valid and prepared_namespace != "candidate_prepared_inputs":
            contract_status = "INVALID"
            contract_blocker = f"{week}: prepared input is not valid"
        cases[week] = {
            "status": contract_status,
            "input_candidate_status": manifest.get("status"),
            "prepared_input_namespace": prepared_namespace,
            "scenario_id": scenario_id or case.get("scenario_id"),
            "prepared_input_id": prepared_input_id or case.get("prepared_input_id"),
            "vehicle_count": case.get("vehicle_count"),
            "timetable_row_count": case.get("timetable_row_count"),
            "selected_route_codes": case.get("selected_route_codes"),
            "declared_route_metadata_sha256": case.get("declared_route_metadata_sha256"),
            "route_metadata_preserved": case.get("route_metadata_preserved"),
            "prepared_input_path": (
                str(prepared_path.relative_to(ROOT)) if prepared_path is not None else None
            ),
            "prepared_scope_audit_status": prepared_audit.get("status"),
            "balanced_week_audit": balanced_week_audit,
            "strict_transition_audit_executed": prepared_audit.get("strict_transition_audit_executed"),
            "path": str(path.relative_to(ROOT)),
        }
        if contract_blocker:
            blockers.append(contract_blocker)
    return {"status": "BLOCKED_PREPARED_INPUTS" if blockers else "PREPARED_INPUTS_READY",
            "cases": cases, "blockers": blockers}


def audit_parent_fleet(config: dict) -> dict:
    """Read the untouched parent fleet contract before any child preparation."""
    from bff.store import scenario_store

    parent = scenario_store._load(config["parent_scenario_id"], skip_graph_arcs=True)
    vehicles = list(parent.get("vehicles") or [])
    counts = Counter(str(row.get("type") or row.get("vehicle_type") or "").upper() for row in vehicles)
    expected = {str(key).upper(): int(value) for key, value in config["expected_fleet"].items() if key != "count"}
    blockers = []
    if len(vehicles) != int(config["expected_fleet"]["count"]):
        blockers.append(f"parent fleet count changed: expected {config['expected_fleet']['count']}, got {len(vehicles)}")
    if counts != expected:
        blockers.append(f"parent fleet powertrain counts changed: expected {expected}, got {dict(counts)}")
    non_tsurumaki = [str(row.get("id")) for row in vehicles if str(row.get("depotId") or "") != config["daily_return_depot_id"]]
    if non_tsurumaki:
        blockers.append(f"parent fleet contains vehicles outside {config['daily_return_depot_id']}: {len(non_tsurumaki)}")
    return {"status": "BLOCKED_PARENT_FLEET" if blockers else "PARENT_FLEET_READY",
            "parent_scenario_id": config["parent_scenario_id"], "vehicle_count": len(vehicles),
            "powertrain_counts": dict(counts), "vehicle_ids": sorted(str(row.get("id")) for row in vehicles),
            "blockers": blockers}


def build_public_evaluation(config: dict, preflight: dict, summaries: list[dict] | None = None) -> dict:
    """Build the small stable JSON contract consumed by the frontend/reporting layer."""
    by_week = {str(row.get("week")): row for row in (summaries or [])}
    route_blockers = list(preflight["route_scope"]["blockers"])
    prepared = preflight["prepared_inputs"]["cases"]
    rows = []
    for week in config["evaluation_weeks"]:
        result = by_week.get(week)
        if result is None:
            case = prepared.get(week, {})
            reasons = list(route_blockers)
            if case.get("status") == "MISSING":
                reasons.append(f"{week}: missing prepared-input manifest")
            elif case.get("status") != "READY":
                reasons.extend(
                    blocker for blocker in preflight["prepared_inputs"]["blockers"]
                    if blocker.startswith(f"{week}:")
                )
            rows.append({"week": week, "status": "BLOCKED_ROUTE_SCOPE" if route_blockers else "BLOCKED_PREPARED_INPUTS",
                         "trip_count": None, "accepted_hourly_prefixes": 0,
                         "physical_accepted": None, "accounting_eligible": None,
                         "final_week_cost_jpy": None, "stage1_certified_gap": None,
                         "reasons": reasons, "prepared_input_status": case.get("status")})
            continue
        rows.append({"week": week, "status": result.get("status"),
                     "trip_count": result.get("trip_count"),
                     "accepted_hourly_prefixes": result.get("hourly_steps_accepted", 0),
                     "physical_accepted": result.get("physical_accepted"),
                     "accounting_eligible": result.get("accounting_eligible"),
                     "final_week_cost_jpy": (result.get("executed_cost") or {}).get("total_cost"),
                     "stage1_certified_gap": result.get("stage1_certified_gap"),
                     "reasons": (result.get("reasons") or result.get("accounting_reasons")
                                 or result.get("hourly_reasons") or result.get("day_ahead_reasons")
                                 or result.get("physical_violations") or [])})
    return {"schema_version": "seasonal_evaluation_public_v1",
            "status": ("DIAGNOSTIC_EVALUATION_COMPLETE"
                       if len(summaries or []) == len(config["evaluation_weeks"])
                       else "DIAGNOSTIC_EVALUATION_IN_PROGRESS" if summaries else preflight["status"]),
            "research_status": config["research_status"],
            "formal_solve_executed": False,
            "diagnostic_cases_attempted": sum(bool(row.get("solve_attempted")) for row in (summaries or [])),
            "route_codes": list(config["route_codes"]),
            "evaluation_weeks": list(config["evaluation_weeks"]),
            "rows": rows,
            "blockers": list(preflight["blockers"])}


def run_preflight(config: dict, output: Path) -> dict:
    scope = discover_route_scope(config)
    prepared = audit_prepared_inputs(config)
    fleet = audit_parent_fleet(config)
    source_state_before = git_state()
    worktree_dirty = bool(source_state_before["status_porcelain"])
    blockers = list(scope["blockers"]) + list(prepared["blockers"]) + list(fleet["blockers"])
    if worktree_dirty:
        blockers.append("working tree is dirty; freeze and commit before any diagnostic solve")
    summary = {
        "status": "BLOCKED" if blockers else "READY_FOR_FROZEN_RUN",
        "research_status": "DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS",
        "formal_solve_executed": False,
        "base_git_sha": source_state_before["sha"],
        "source_state_before": source_state_before,
        "worktree_dirty": worktree_dirty,
        "route_scope": scope,
        "prepared_inputs": prepared,
        "parent_fleet": fleet,
        "blockers": blockers,
    }
    write_json(output / "scope_audit.json", scope)
    write_json(output / "prepared_input_audit.json", prepared)
    write_json(output / "parent_fleet_audit.json", fleet)
    write_json(output / "seasonal_evaluation.json", build_public_evaluation(config, summary))
    write_json(output / "summary.json", summary)
    return summary


def run_diagnostic(config: dict, output: Path) -> list[dict]:
    require_execution_enabled(config)
    preflight = run_preflight(config, output)
    if preflight["worktree_dirty"]:
        raise RuntimeError("Diagnostic run requires the parent to freeze and commit the source first")
    source_state_before = git_state()
    if source_state_before["status_porcelain"]:
        raise RuntimeError("Source became dirty after preflight")
    source_sha = source_state_before["sha"]
    summaries = []
    for week in config["evaluation_weeks"]:
        week_output = output / week
        week_output.mkdir(parents=True, exist_ok=False)
        week_state_before = git_state()
        write_json(week_output / "git_state_before.json", week_state_before)
        shared_blockers = list(preflight["route_scope"]["blockers"])
        shared_blockers += list(preflight.get("parent_fleet", {}).get("blockers", []))
        case_blockers = [reason for reason in preflight["prepared_inputs"].get("blockers", [])
                         if reason.startswith(f"{week}:")]
        if preflight["prepared_inputs"]["cases"].get(week, {}).get("status") != "READY" and not case_blockers:
            case_blockers.append(f"{week}: prepared input did not pass the complete Prepare contract")
        if week_state_before != source_state_before:
            shared_blockers.append("Git SHA or dirty state changed before the case")
        blocked = shared_blockers + case_blockers
        try:
            if blocked:
                result = {
                    "week": week, "status": "BLOCKED_CASE_PREFLIGHT",
                    "research_status": config["research_status"],
                    "solve_attempted": False, "hourly_steps_accepted": 0,
                    "physical_accepted": None, "accounting_eligible": None,
                    "executed_cost": {}, "reasons": blocked,
                }
            else:
                print(f"{week}: complete Prepare passed; diagnostic starts", flush=True)
                result = solve_week(
                    week,
                    week_output,
                    config,
                    contract_validator=verify_evaluation_contract,
                )
                result["solve_attempted"] = True
            result["git_state_before"] = week_state_before
            result["git_state_after"] = git_state()
            result["source_state_stable"] = (
                result["git_state_before"] == result["git_state_after"]
                and result["git_state_before"] == source_state_before
            )
            write_json(week_output / "git_state_after.json", result["git_state_after"])
            if not result["source_state_stable"]:
                result["status"] = "BLOCKED_SOURCE_STATE_DRIFT"
                result["research_status"] = "NOT_USED_FOR_RESEARCH_CONCLUSIONS"
                result["accounting_eligible"] = False
                result["source_state_drift_reason"] = "Git SHA or dirty state changed during the case"
                result.setdefault("reasons", []).append(result["source_state_drift_reason"])
            summaries.append(result)
        except Exception as exc:
            after = git_state()
            persisted_progress = _verified_persisted_progress(week_output, week)
            failure = {
                "week": week,
                "status": "DIAGNOSTIC_CASE_FAILED",
                "research_status": "NOT_USED_FOR_RESEARCH_CONCLUSIONS",
                "formal_solve": False,
                "solve_attempted": not bool(blocked),
                "hourly_steps_accepted": persisted_progress.get(
                    "hourly_steps_accepted", 0
                ),
                "physical_accepted": None,
                "accounting_eligible": False,
                "final_week_cost_jpy": None,
                "executed_cost": {},
                "day_ahead_cost": {},
                "reasons": [f"{type(exc).__name__}: {exc}"],
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": traceback.format_exc(),
                "git_state_before": week_state_before,
                "git_state_after": after,
                "source_state_stable": week_state_before == after == source_state_before,
            }
            if "day_ahead_physical_accepted" in persisted_progress:
                failure["day_ahead_physical_accepted"] = persisted_progress[
                    "day_ahead_physical_accepted"
                ]
            if "failed_hour" in persisted_progress:
                failure["failed_hour"] = persisted_progress["failed_hour"]
            write_json(week_output / "failure.json", failure)
            summaries.append(failure)
        write_json(week_output / "summary.json", summaries[-1])
        write_json(output / "seasonal_evaluation.json", build_public_evaluation(config, preflight, summaries))
        print(json.dumps({"week": week, "status": summaries[-1]["status"],
                          "hours": summaries[-1].get("hourly_steps_accepted")}, ensure_ascii=False), flush=True)
        write_json(output / "summary.json", {
            "base_git_sha": source_sha,
            "source_state_before": source_state_before,
            "summaries": summaries,
            "completed_weeks": [row.get("week") for row in summaries],
            "research_status": config["research_status"],
            "formal_solve_executed": False,
        })
    source_state_after = git_state()
    source_state_stable = source_state_after == source_state_before
    write_json(output / "summary.json", {"base_git_sha": source_sha,
                                         "source_state_before": source_state_before,
                                         "source_state_after": source_state_after,
                                         "source_state_stable": source_state_stable,
                                         "summaries": summaries,
                                         "completed_weeks": [row.get("week") for row in summaries],
                                         "research_status": config["research_status"],
                                         "formal_solve_executed": False})
    write_json(output / "seasonal_evaluation.json", build_public_evaluation(config, preflight, summaries))
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/shibu21_24_2025_seasonal_test.json")
    parser.add_argument("--output", type=Path, default=ROOT / "output/shibu21_24_seasonal_diagnostics_20260911")
    parser.add_argument("--run", action="store_true", help="run only after an unblocked preflight")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.run:
        require_execution_enabled(config)
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "design.json", config)
    if args.run:
        run_diagnostic(config, args.output)
    else:
        run_preflight(config, args.output)


if __name__ == "__main__":
    main()
