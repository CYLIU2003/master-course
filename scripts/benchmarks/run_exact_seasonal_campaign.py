"""Run a fresh-Prepare, sequential multi-week diagnostic campaign.

This entrypoint is deliberately diagnostic.  Each selected week gets a new
scenario and a new formal prepared input, followed by the existing combined
seasonal diagnostic (day-ahead solve plus 168 hourly rolling prefixes).  A
failed case stops automatic solver execution for later weeks; those weeks are
recorded as ``NOT_EXECUTED_AFTER_FAILURE``.

The campaign output must be a new directory under the repository root.  The
input-manifest path written into each case design is therefore ROOT-relative,
while prepared canonical inputs remain in ``output/prepared_inputs``.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.benchmarks.seasonal_design_contract import require_execution_enabled, seasonal_bess_controls


def canonical_design_hash(design: dict) -> str:
    """Hash the source design before campaign-only overrides are applied."""

    payload = json.dumps(
        design,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _root_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"Campaign output must be under repository root: {resolved}"
        ) from exc


def _declared_weeks(design: dict) -> tuple[str, ...]:
    weeks = tuple(str(value) for value in (design.get("evaluation_weeks") or ()))
    if not weeks or len(set(weeks)) != len(weeks):
        raise ValueError("design.evaluation_weeks must be a non-empty unique list")
    return weeks


def validate_carryover_weeks(weeks: tuple[str, ...], design: dict) -> None:
    """A stored monthly sample cannot establish consecutive-week operation."""
    if len(weeks) < 2 or design.get("diagnostic_stop_after_day_ahead") is True:
        raise ValueError("BESS carryover requires at least two fully executed weeks")
    if "bess_initial_soc_override_kwh" in design:
        raise ValueError("BESS carryover initial SOC must come from the previous executed plan")
    if any(date.fromisoformat(week).weekday() != 0 for week in weeks):
        raise ValueError("BESS carryover weeks must begin on Monday")
    for earlier, later in zip(weeks, weeks[1:]):
        if date.fromisoformat(later) != date.fromisoformat(earlier) + timedelta(days=7):
            raise ValueError("BESS carryover requires consecutive Monday-Sunday weeks")


def verified_bess_carryover(diagnostic: Path, result: dict, *, depot_id: str = "tsurumaki") -> dict:
    """Read the accepted rolling boundary, never a forecast or day-ahead state."""
    if (result.get("status") != "DIAGNOSTIC_EXECUTION_PASSED"
            or result.get("physical_accepted") is not True
            or result.get("accounting_eligible") is not True
            or int(result.get("hourly_steps_accepted") or 0) != 168):
        raise ValueError("Prior week lacks accepted 168-hour rolling execution")
    chain = diagnostic / "rolling_hourly_chain"
    plan_path = chain / "executed_plan.json"
    plan_bytes = plan_path.read_bytes()
    plan = json.loads(plan_bytes)
    physical_path = chain / "physical_validation.json"
    accounting_path = chain / "executed_day_accounting.json"
    physical_bytes = physical_path.read_bytes()
    accounting_bytes = accounting_path.read_bytes()
    physical = json.loads(physical_bytes)
    accounting = json.loads(accounting_bytes)
    if physical.get("accepted") is not True or accounting.get("eligible") is not True:
        raise ValueError("Prior week saved physical or accounting evidence is not accepted")
    trace = (plan.get("bess_soc_kwh_by_depot_slot") or {}).get(depot_id)
    if not isinstance(trace, dict) or set(trace) != {str(slot) for slot in range(672)}:
        raise ValueError("Prior week has no complete 672-slot BESS inventory trace")
    values = [float(trace[str(slot)]) for slot in range(672)]
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Prior week BESS inventory contains a non-finite value")
    if (accounting.get("executed_slot_count") != 672
            or accounting.get("missing_slots")
            or accounting.get("duplicate_slots")):
        raise ValueError("Prior week accounting does not cover exactly 672 executed slots")
    boundary = (accounting.get("bess_terminal_soc_by_depot") or {}).get(depot_id)
    if not isinstance(boundary, dict) or not math.isclose(
        values[-1], float(boundary["terminal_soc_kwh"]), rel_tol=0.0, abs_tol=1.0e-6
    ):
        raise ValueError("Prior week plan and accounting BESS terminal inventory disagree")
    return {
        "depot_id": depot_id,
        "terminal_soc_kwh": values[-1],
        "executed_plan_sha256": hashlib.sha256(plan_bytes).hexdigest(),
        "physical_validation_sha256": hashlib.sha256(physical_bytes).hexdigest(),
        "executed_day_accounting_sha256": hashlib.sha256(accounting_bytes).hexdigest(),
        "physical_validation_accepted": True,
        "accounting_eligible": True,
        "hourly_steps_accepted": 168,
    }


def campaign_source_design(design: dict, source_directory: Path) -> dict:
    """Use the same fresh source capture for Prepare and the later scope audit."""
    routes = _root_relative(source_directory / "selected_routes.json")
    return {
        **deepcopy(design),
        "route_source": routes,
        # A complete campaign capture must stand on its own; an unrelated
        # fallback catalog must not hide missing patterns in this capture.
        "route_source_fallback": routes,
        "route_timetable_audit_source": _root_relative(source_directory / "timetable_rows.json"),
    }


def campaign_case_design(
    design: dict,
    *,
    week: str,
    declared_weeks: tuple[str, ...],
    input_manifests_directory: str,
    source_design_sha256: str,
) -> dict:
    """Return an isolated one-week design with explicit campaign provenance."""

    case = deepcopy(design)
    case["evaluation_weeks"] = [week]
    case["campaign_declared_weeks"] = list(declared_weeks)
    case["input_manifests_directory"] = input_manifests_directory
    case["prepared_inputs_directory"] = "output/prepared_inputs"
    case["stage1_exact_depot_connection_factors"] = True
    case["campaign_source_design_sha256"] = source_design_sha256
    case["campaign_case_week"] = week
    case["campaign_research_status"] = "DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS"
    return case


def _empty_case_after_failure(
    week: str,
    *,
    reason: str,
    source_state_before: dict,
    source_state_after: dict,
) -> dict:
    return {
        "week": week,
        "status": "NOT_EXECUTED_AFTER_FAILURE",
        "research_status": "DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS",
        "solve_attempted": False,
        "formal_solve": False,
        "hourly_steps_accepted": 0,
        "physical_accepted": None,
        "accounting_eligible": False,
        "reasons": [reason],
        "source_state_before": source_state_before,
        "source_state_after": source_state_after,
    }


def _phase_summary(prepare: dict, diagnostic: dict | None) -> dict:
    """Keep Prepare, solve, rolling, physical, and accounting evidence distinct."""

    result = diagnostic or {}
    return {
        "prepare": {
            "status": (
                "PREPARED"
                if prepare.get("formal_prepared") and prepare.get("input_preparation_valid")
                else "BLOCKED"
            ),
            "formal_prepared": bool(prepare.get("formal_prepared")),
            "input_preparation_valid": bool(prepare.get("input_preparation_valid")),
            "prepared_input_id": prepare.get("prepared_input_id"),
            "prepared_input_path": prepare.get("prepared_input_path"),
            "error_code": prepare.get("error_code"),
            "error": prepare.get("error"),
            "warnings": list(prepare.get("warnings") or ()),
        },
        "solve": {
            "status": (
                "DAY_AHEAD_PASSED"
                if result.get("day_ahead_feasible")
                else "DAY_AHEAD_FAILED"
                if result.get("day_ahead_feasible") is False
                else "DAY_AHEAD_RESULT_UNAVAILABLE"
                if result.get("solve_attempted")
                else "NOT_ATTEMPTED"
            ),
            "attempted": bool(result.get("solve_attempted")),
            "feasible": result.get("day_ahead_feasible"),
            "solver_status": result.get("day_ahead_status"),
            "cost": result.get("day_ahead_cost") or {},
            "reasons": result.get("day_ahead_reasons") or [],
        },
        "rolling": {
            "status": (
                "168_PREFIXES_ACCEPTED"
                if int(result.get("hourly_steps_accepted") or 0) == 168
                else "ROLLING_FAILED"
                if result.get("day_ahead_physical_accepted")
                else "NOT_ATTEMPTED"
            ),
            "hourly_steps_accepted": int(result.get("hourly_steps_accepted") or 0),
            "reasons": result.get("hourly_reasons") or (
                result.get("reasons") if result.get("day_ahead_physical_accepted") else []
            ) or [],
        },
        "physical": {
            "day_ahead_accepted": result.get("day_ahead_physical_accepted"),
            "rolling_accepted": result.get("physical_accepted"),
            "violations": result.get("physical_violations") or [],
        },
        "accounting": {
            "eligible": result.get("accounting_eligible"),
            "cost": result.get("executed_cost") or {},
            "reasons": result.get("accounting_reasons") or [],
            "daily_cost_difference_jpy": result.get("daily_cost_difference_jpy"),
        },
    }


def run_campaign(
    design: dict,
    output: Path,
    *,
    selected_week: str | None = None,
    carry_bess: bool = False,
) -> dict:
    """Execute the sequential campaign without reusing prior week artifacts."""

    require_execution_enabled(design)
    seasonal_bess_controls(design)

    # Keep pure campaign-contract helpers importable in a lightweight test
    # environment.  These existing runners pull the full pandas/Gurobi stack;
    # loading them is required only when an actual campaign is authorized.
    from scripts.benchmarks.prepare_shibu21_24_seasonal_inputs import (
        build_source_candidate,
        prepare_week,
    )
    from scripts.benchmarks.run_shibu21_24_seasonal_diagnostic import (
        git_state,
        run_diagnostic,
        write_json,
    )

    output = output.resolve()
    if output.exists():
        raise FileExistsError(f"Campaign output already exists: {output}")
    output_relative = _root_relative(output)

    declared_weeks = _declared_weeks(design)
    if selected_week is not None and selected_week not in declared_weeks:
        raise ValueError(f"--week is not declared in evaluation_weeks: {selected_week}")
    weeks = (selected_week,) if selected_week is not None else declared_weeks
    if carry_bess:
        validate_carryover_weeks(weeks, design)
    source_design_sha256 = canonical_design_hash(design)
    campaign_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"

    source_state = git_state()
    if not source_state.get("sha"):
        raise RuntimeError("Cannot start campaign without a Git SHA")
    if source_state.get("status_porcelain"):
        raise RuntimeError("Campaign requires a clean Git worktree")
    if design.get("require_balanced_monthly_weeks"):
        from bff.services.date_series_inputs import _verified_holiday_manifest
        from scripts.benchmarks.monthly_week_contract import select_monthly_weeks

        year = int(design["evaluation_year"])
        calendar = _verified_holiday_manifest(ROOT, [f"{year}-01-01", f"{year}-12-31"])
        if (calendar["sha256"] != design["calendar_source_sha256"]
                or design["selection_holiday_dates"] != sorted(
                    day for day in calendar["holiday_dates"] if day.startswith(f"{year}-"))
                or list(declared_weeks) != select_monthly_weeks(year, list(calendar["holiday_dates"]))):
            raise ValueError("Monthly weeks differ from the declared holiday-free selection rule")

    output.mkdir(parents=True)
    inputs_root = output / "inputs"
    cases_root = output / "cases"
    input_manifests_directory = _root_relative(inputs_root)
    bound_design = campaign_source_design(design, output / "source_candidate")
    progress = {
        "schema_version": "exact_seasonal_campaign_progress_v1",
        "status": "BUILDING_SOURCE_CANDIDATE", "base_git_sha": source_state["sha"],
        "selected_weeks": list(weeks), "completed_weeks": [],
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_status": "DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS",
    }
    write_json(output / "progress.json", progress)
    write_json(
        output / "design.json",
        {
            **bound_design,
            "campaign_id": campaign_id,
            "campaign_source_design_sha256": source_design_sha256,
            "campaign_declared_weeks": list(declared_weeks),
            "selected_weeks": list(weeks),
            "stage1_exact_depot_connection_factors": True,
            "input_manifests_directory": input_manifests_directory,
            "prepared_inputs_directory": "output/prepared_inputs",
            "research_status": "DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS",
        },
    )

    # A second fresh campaign in the same checkout must not collide with or
    # overwrite the first campaign's immutable source capture.
    source = build_source_candidate(
        route_codes=design["route_codes"], output_directory=output / "source_candidate",
    )
    if git_state() != source_state:
        raise RuntimeError("Git SHA or dirty state changed while building source candidate")

    summaries: list[dict] = []
    stopped = False
    stop_reason = ""
    prior_bess_boundary: dict | None = None
    for week in weeks:
        week_before = git_state()
        case_root = cases_root / week
        prepare_output = inputs_root / week
        case_root.mkdir(parents=True)
        case_design = campaign_case_design(
            bound_design,
            week=week,
            declared_weeks=declared_weeks,
            input_manifests_directory=input_manifests_directory,
            source_design_sha256=source_design_sha256,
        )
        if carry_bess and prior_bess_boundary is not None:
            case_design["bess_initial_soc_override_kwh"] = prior_bess_boundary["terminal_soc_kwh"]
            case_design["bess_initial_soc_override_source"] = prior_bess_boundary
        write_json(case_root / "design.json", case_design)

        if stopped:
            skipped_after = git_state()
            summary = _empty_case_after_failure(
                week,
                reason=stop_reason,
                source_state_before=week_before,
                source_state_after=skipped_after,
            )
            summary.update(_phase_summary({}, None))
            summary["prepare"]["status"] = "NOT_ATTEMPTED"
            write_json(case_root / "summary.json", summary)
            summaries.append(summary)
            continue

        prepare_result: dict | None = None
        diagnostic_result: dict | None = None
        try:
            if week_before != source_state:
                raise RuntimeError("Git SHA or dirty state changed before Prepare")
            started_prepare = time.perf_counter()
            progress.update(status="PREPARING_WEEK", active_week=week,
                            phase_started_at_utc=datetime.now(timezone.utc).isoformat())
            write_json(output / "progress.json", progress)
            print(f"{week}: fresh complete Prepare begins", flush=True)
            prepare_result = prepare_week(
                week,
                prepare_output,
                source,
                existing=None,
                validation_mode=True,
                **({"design": case_design} if design.get("require_balanced_monthly_weeks") or carry_bess else {}),
            )
            after_prepare = git_state()
            if after_prepare != source_state or week_before != source_state:
                raise RuntimeError("Git SHA or dirty state changed during Prepare")
            prepare_result["prepare_seconds"] = time.perf_counter() - started_prepare

            diagnostic_output = case_root / "diagnostic"
            diagnostic_output.mkdir()
            write_json(diagnostic_output / "design.json", case_design)
            progress.update(status="RUNNING_WEEK", phase_started_at_utc=datetime.now(timezone.utc).isoformat())
            write_json(output / "progress.json", progress)
            diagnostic_summaries = run_diagnostic(case_design, diagnostic_output)
            diagnostic_result = diagnostic_summaries[0] if diagnostic_summaries else None
            if diagnostic_result is None:
                raise RuntimeError("Diagnostic returned no weekly summary")
            after_case = git_state()
            if after_case != source_state:
                raise RuntimeError("Git SHA or dirty state changed during diagnostic case")

            summary = {
                "week": week,
                "status": diagnostic_result.get("status"),
                "research_status": "DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS",
                "source_state_before": week_before,
                "source_state_after": after_case,
                "source_state_stable": True,
                "prepare_result": prepare_result,
                "diagnostic_result": diagnostic_result,
                **_phase_summary(prepare_result, diagnostic_result),
            }
            expected_status = (
                "DAY_AHEAD_ONLY_DIAGNOSIS_COMPLETE"
                if design.get("diagnostic_stop_after_day_ahead") is True
                else "DIAGNOSTIC_EXECUTION_PASSED"
            )
            failed = summary["status"] != expected_status
            if carry_bess and not failed:
                prior_bess_boundary = {
                    "week": week,
                    **verified_bess_carryover(diagnostic_output, diagnostic_result),
                }
                summary["bess_carryover_boundary"] = prior_bess_boundary
            if failed:
                stopped = True
                stop_reason = f"{week}: case failed with status {summary['status']}"
        except Exception as exc:
            after_case = git_state()
            summary = {
                "week": week,
                "status": "DIAGNOSTIC_CASE_FAILED",
                "research_status": "DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS",
                "source_state_before": week_before,
                "source_state_after": after_case,
                "source_state_stable": after_case == week_before == source_state,
                "prepare_result": prepare_result,
                "diagnostic_result": diagnostic_result,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "reasons": [f"{type(exc).__name__}: {exc}"],
                **_phase_summary(prepare_result or {}, diagnostic_result),
            }
            stopped = True
            stop_reason = f"{week}: case failed with {type(exc).__name__}: {exc}"

        write_json(case_root / "summary.json", summary)
        summaries.append(summary)
        progress.update(status="CASE_FINISHED", completed_weeks=[row["week"] for row in summaries],
                        last_case_status=summary["status"])
        write_json(output / "progress.json", progress)
        print(f"{week}: case ended with {summary['status']}", flush=True)

    final_state = git_state()
    campaign_status = "COMPLETED" if not stopped else "STOPPED_AFTER_FAILED_CASE"
    if not stopped and design.get("diagnostic_stop_after_day_ahead") is True:
        campaign_status = "DAY_AHEAD_ONLY_CAMPAIGN_COMPLETE"
    if final_state != source_state:
        campaign_status = "BLOCKED_SOURCE_STATE_DRIFT"
    campaign_summary = {
        "schema_version": "exact_seasonal_campaign_v1",
        "campaign_id": campaign_id,
        "status": campaign_status,
        "research_status": "DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS",
        "formal_solve_executed": False,
        "source_design_sha256": source_design_sha256,
        "campaign_declared_weeks": list(declared_weeks),
        "selected_weeks": list(weeks),
        "bess_carryover_enabled": carry_bess,
        "base_git_sha": source_state["sha"],
        "source_state_before": source_state,
        "source_state_after": final_state,
        "source_state_stable": final_state == source_state,
        "stage1_exact_depot_connection_factors": True,
        "input_manifests_directory": input_manifests_directory,
        "prepared_inputs_directory": "output/prepared_inputs",
        "summaries": summaries,
        "unexecuted_weeks": [
            row["week"]
            for row in summaries
            if row.get("status") == "NOT_EXECUTED_AFTER_FAILURE"
        ],
    }
    write_json(output / "summary.json", campaign_summary)
    progress.update(status=campaign_status, active_week=None)
    write_json(output / "progress.json", progress)
    return campaign_summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--week", type=str, default=None)
    parser.add_argument("--carry-bess", action="store_true", help="Carry accepted rolling BESS inventory into each adjacent week")
    args = parser.parse_args()
    config_path = args.config if args.config.is_absolute() else ROOT / args.config
    design = json.loads(config_path.read_text(encoding="utf-8"))
    run_campaign(design, args.output, selected_week=args.week, carry_bess=args.carry_bess)


if __name__ == "__main__":
    main()
