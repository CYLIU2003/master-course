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
from pathlib import Path
import subprocess
import sys
import traceback
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.benchmarks.run_shibu21_seasonal_diagnostic import solve_week, write_json


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
                else:
                    contract_status = "READY"
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
            "prepared_input_path": (
                str(prepared_path.relative_to(ROOT)) if prepared_path is not None else None
            ),
            "prepared_scope_audit_status": prepared_audit.get("status"),
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
                result = solve_week(week, week_output, config)
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
            failure = {
                "week": week,
                "status": "DIAGNOSTIC_CASE_FAILED",
                "research_status": "NOT_USED_FOR_RESEARCH_CONCLUSIONS",
                "formal_solve": False,
                "solve_attempted": not bool(blocked),
                "hourly_steps_accepted": 0,
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
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "design.json", config)
    if args.run:
        run_diagnostic(config, args.output)
    else:
        run_preflight(config, args.output)


if __name__ == "__main__":
    main()
