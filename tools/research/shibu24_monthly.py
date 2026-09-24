"""Audit and prepare twelve real Shibu24 weeks with paid final overnight slots.

This command never starts an optimizer. ``check`` is read-only; ``prepare``
duplicates the saved parent into a fresh, resumable scenario per week and uses
the repository Prepare path. All results remain diagnostic until an independent
research review and a frozen solve pass the applicable acceptance gates.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import sys
import re

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bff.services.date_series_inputs import _date_forecast_rows, _date_pv_rows, _verified_holiday_manifest
from bff.services.cluster.contracts import git_state
from bff.services.run_preparation import get_or_build_run_preparation
from bff.store import output_paths, scenario_store
from scripts.benchmarks.monthly_week_contract import select_monthly_weeks, validate_balanced_week
from scripts.benchmarks.prepare_shibu21_24_seasonal_inputs import configure_doc, parent_hash
from scripts.benchmarks.shibu24_optimization_store import DATABASE_DIR, load_database
from src.optimization.common.date_series import content_hash, materialize_dated_timetable, timetable_hash
from src.optimization.common.next_morning import PRICE_POLICY, SCHEMA, resolve_next_morning_contract

SELECTION = ROOT / "output/monthly_fair_weeks_20260914/week_selection.json"
FORECAST = ROOT / "output/monthly_fair_weeks_20260914/forecast_holdouts"
PARENT_ID = "771d115b-75b0-49f7-a7f0-25f259a2cd21"


def _read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _source_and_design() -> tuple[dict, dict, list[str]]:
    database_manifest, _ = load_database(DATABASE_DIR)
    if database_manifest.get("source_status") != "SOURCE_CAPTURE_VALIDATED_BROWSER_COMPARISON_PENDING":
        raise ValueError("Unexpected Shibu24 source audit status")
    forecast_manifest = _read(FORECAST / "manifest.json")
    design = deepcopy(forecast_manifest["design"])
    selection = _read(SELECTION)
    if design["calendar_source_sha256"] != selection["official_holiday_source_sha256"]:
        raise ValueError("Monthly holiday provenance differs from forecast design")
    weeks = select_monthly_weeks(2025, design["selection_holiday_dates"])
    if weeks != [row["start"] for row in selection["weeks"]] or weeks != design["evaluation_weeks"]:
        raise ValueError("Monthly week selection changed after forecast freeze")
    if design["parent_scenario_id"] != PARENT_ID:
        raise ValueError("Forecast design parent scenario changed")
    source = {
        "optimization_database": DATABASE_DIR.relative_to(ROOT).as_posix(),
        "optimization_database_sha256": database_manifest["database_sha256"],
        "optimization_manifest_sha256": _sha(DATABASE_DIR / "manifest.json"),
        "source_manifest_sha256": database_manifest["source_manifest_sha256"],
        "source_id": "tsurumaki_shibu24_odpt_20260911_diagnostic_v1",
        "route_codes": ["渋24"],
        "distance_semantics": database_manifest["distance_semantics"],
    }
    return source, design, weeks


def _clock_minutes(value: str) -> int:
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def _overnight_contract(doc: dict, templates: list[dict]) -> dict:
    config = doc["simulation_config"]
    dates = list(config["service_dates"])
    day_count = len(dates)
    next_date = (date.fromisoformat(dates[-1]) + timedelta(days=1)).isoformat()
    extended_dates = dates + [next_date]
    holiday = _verified_holiday_manifest(ROOT, extended_dates, config.get("holiday_source_id"))
    extended_rows, _ = materialize_dated_timetable(
        templates, service_dates=extended_dates,
        holiday_dates=list(holiday["holiday_dates"]),
        source_provenance=config["date_series_contract"]["source_provenance"],
    )
    if timetable_hash(extended_rows[:len(doc["timetable_rows"])]) != timetable_hash(doc["timetable_rows"]):
        raise ValueError("Service days changed while deriving the following morning")
    next_rows = [row for row in extended_rows if row["service_date"] == next_date]
    first_departures = [
        min(_clock_minutes(row["source_departure"]) for row in extended_rows
            if row["service_date"] == day)
        for day in extended_dates[1:]
    ]
    asset = next(row for row in config["depot_energy_assets"] if row["depot_id"] == "tsurumaki")
    step = int(config["timestep_min"])
    performance_ratio = float(asset.get("performance_ratio") or .85)
    predicted, forecast_audit = _date_forecast_rows(
        ROOT, extended_dates, step, performance_ratio
    )
    if predicted[:day_count] != asset["pv_capacity_factor_by_date"]:
        raise ValueError("Next-morning model differs from the frozen service-day forecast")
    actual, actual_sources = _date_pv_rows(
        ROOT / "data/external/solcast_raw/tsurumaki_2025_2026",
        extended_dates, step, performance_ratio,
    )
    if not actual_sources or len(actual) != day_count + 1:
        raise ValueError("The final next morning has no verified Solcast source")
    contract = {
        "schema_version": SCHEMA,
        "service_dates": dates,
        "next_service_date": next_date,
        "next_day_timetable_rows": next_rows,
        "next_day_timetable_rows_sha256": timetable_hash(next_rows),
        "first_departure_minute_by_next_day": first_departures,
        "next_day_pv_capacity_factor": predicted[day_count],
        "next_day_pv_sha256": content_hash(predicted[day_count]),
        "next_day_actual_pv_capacity_factor": actual[day_count],
        "next_day_actual_pv_sha256": content_hash(actual[day_count]),
        "price_calendar_policy": PRICE_POLICY,
        "next_day_actual_pv_source_sha256": [row["sha256"] for row in actual_sources],
        "weather_claim": "training_only_climatology_proxy_for_planning",
        "timetable_claim": "fixed_current_schedule_applied_to_2025_weather_not_2025_actual_operations",
        "distance_claim": "geographic_proxy_not_road_distance",
        "research_status": "DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS",
    }
    config.update(
        bev_soc_deadline_mode="next_morning_operational_max",
        final_overnight_mode="include",
        bev_terminal_soc_policy="fixed_target",
        final_soc_target_percent=float(config["soc_max"]) * 100.0,
        final_soc_target_tolerance_percent=0.0,
        terminal_overnight_contract=contract,
    )
    doc["scenario_overlay"]["charging_constraints"].update(
        bev_terminal_soc_policy="fixed_target",
        final_soc_target_percent=config["final_soc_target_percent"],
        final_soc_target_tolerance_percent=0.0,
    )
    config["date_series_contract"].update(
        bev_terminal_soc_policy="fixed_target",
        final_soc_target_percent=config["final_soc_target_percent"],
        terminal_overnight_contract_sha256=content_hash(contract),
    )
    resolve_next_morning_contract(config, timestep_min=step, timetable_rows=doc["timetable_rows"])
    if day_count == 7:
        validate_balanced_week(doc["timetable_rows"], config["date_series_contract"], week=dates[0])
    return {"next_service_date": next_date, "extra_slots": first_departures[-1] // step,
            "forecast_model_sha256": forecast_audit.get("model_sha256"),
            "next_day_pv_sha256": contract["next_day_pv_sha256"],
            "next_day_timetable_rows_sha256": contract["next_day_timetable_rows_sha256"]}


def check() -> dict:
    source, design, weeks = _source_and_design()
    _, tables = load_database(DATABASE_DIR)
    templates = tables["timetable_rows"]
    results = []
    for week in weeks:
        dates = [(date.fromisoformat(week) + timedelta(days=index)).isoformat() for index in range(8)]
        holiday = _verified_holiday_manifest(ROOT, dates, None)
        rows, contract = materialize_dated_timetable(
            templates, service_dates=dates, holiday_dates=list(holiday["holiday_dates"]),
            source_provenance={"source_id": source["source_id"]},
        )
        step = int(design["timestep_minutes"])
        actual, actual_sources = _date_pv_rows(
            ROOT / "data/external/solcast_raw/tsurumaki_2025_2026", dates, step, .85
        )
        forecast, _ = _date_forecast_rows(ROOT, dates, step, .85)
        first = min(_clock_minutes(row["source_departure"]) for row in rows
                    if row["service_date"] == dates[-1])
        results.append({"week": week, "service_trip_count": sum(
            day["trip_count"] for day in contract["days"][:7]),
            "next_day_first_departure_min": first,
            "overnight_slots": first // step,
            "actual_pv_days": len(actual), "forecast_pv_days": len(forecast),
            "actual_source_count": len(actual_sources)})
    return {"schema_version": "shibu24_monthly_preflight_v1", "status": "INPUTS_AVAILABLE_DIAGNOSTIC",
            "year": 2025, "source_manifest_sha256": source["source_manifest_sha256"],
            "optimization_database_sha256": source["optimization_database_sha256"],
            "optimization_manifest_sha256": source["optimization_manifest_sha256"],
            "forecast_manifest_sha256": _sha(FORECAST / "manifest.json"),
            "week_selection_sha256": _sha(SELECTION), "weeks": results,
            "source_limit": "browser comparison pending; geographic distance proxy",
            "formal_solve_executed": False}


def prepare(output: Path, *, limit: int) -> dict:
    preflight = check()
    source, design, weeks = _source_and_design()
    _, source_tables = load_database(DATABASE_DIR)
    templates = source_tables["timetable_rows"]
    state = git_state(ROOT)
    if state["dirty"]:
        raise ValueError("Monthly Prepare requires a clean frozen Git worktree")
    output.mkdir(parents=True, exist_ok=True)
    binding = {"git_sha": state["sha"],
               "preflight_hash": content_hash(preflight), "weeks": weeks}
    binding_path = output / "binding.json"
    if binding_path.exists() and _read(binding_path) != binding:
        raise ValueError("Campaign source or code changed; use a new output directory")
    _write(binding_path, binding)
    parent = scenario_store._load(PARENT_ID, skip_graph_arcs=True)
    original_parent_hash = parent_hash(parent)
    cases = []
    for week in weeks[:limit]:
        path = output / week / "state.json"
        state = _read(path) if path.exists() else {}
        if state.get("status") == "PREPARED":
            prepared_path = (output_paths.outputs_root() / "prepared_inputs" /
                             str(state["scenario_id"]) /
                             f"{state['prepared_input_id']}.json")
            if (not prepared_path.is_file() or
                    _sha(prepared_path) != state.get("prepared_input_sha256")):
                raise ValueError(f"Prepared input changed or is missing for {week}")
            cases.append(state)
            continue
        if not state.get("scenario_id"):
            scenario_id = scenario_store.duplicate_scenario(
                PARENT_ID, name=f"渋24 2025年{int(week[5:7])}月代表週 {week} 翌朝SOC診断"
            )["id"]
            state = {"week": week, "scenario_id": scenario_id, "status": "DUPLICATED"}
            _write(path, state)
        doc = scenario_store._load(state["scenario_id"], skip_graph_arcs=True)
        doc = configure_doc(doc, week, source, design=design)
        extension = _overnight_contract(doc, templates)
        scenario_store._invalidate_dispatch_artifacts(doc)
        scenario_store._normalize_dispatch_scope(doc)
        scenario_store._save(doc)
        if parent_hash(scenario_store._load(PARENT_ID, skip_graph_arcs=True)) != original_parent_hash:
            raise ValueError("Parent scenario changed during monthly preparation")
        prepared = get_or_build_run_preparation(
            scenario=scenario_store._load(state["scenario_id"], skip_graph_arcs=True),
            built_dir=ROOT / "data/built/tokyu_full", routes_df=None,
            scenarios_dir=output_paths.outputs_root() / "prepared_inputs",
        )
        audit = dict((prepared.scope_summary or {}).get("prepared_scope_audit") or {})
        strict = dict(audit.get("strict_coverage_precheck") or {})
        audit_passed = bool(
            strict.get("checked")
            and not strict.get("infeasible")
            and audit.get("formal_transition_network_ready")
            and audit.get("formal_turnaround_sensitivity_ready")
            and audit.get("formal_vehicle_trip_compatibility_ready")
        )
        prepared_path = prepared.solver_input_path
        prepared_sha = (_sha(prepared_path) if prepared_path and prepared_path.is_file() else None)
        audit_passed = audit_passed and prepared_sha is not None
        state.update(status="PREPARED" if prepared.is_valid and audit_passed else "BLOCKED_PREPARE",
                     prepared_input_id=prepared.prepared_input_id,
                     prepared_input_sha256=prepared_sha,
                     input_preparation_valid=prepared.is_valid,
                     strict_scope_audit_passed=audit_passed,
                     strict_scope_warning_codes=list(audit.get("warning_codes") or []),
                     error_code=(prepared.error_code if not prepared.is_valid else
                                 None if audit_passed else "PREPARED_SCOPE_AUDIT_FAILED"),
                     error=(prepared.error if not prepared.is_valid else
                            None if audit_passed else "Full transition and turnaround audit must pass"),
                     overnight=extension)
        _write(path, state)
        cases.append(state)
        print(json.dumps({"week": week, "status": state["status"],
                          "prepared_input_id": prepared.prepared_input_id}, ensure_ascii=False), flush=True)
        if state["status"] != "PREPARED":
            break
    return {"schema_version": "shibu24_monthly_prepare_v1", "binding": binding,
            "cases": cases, "all_prepared": len(cases) == len(weeks) and all(
                row["status"] == "PREPARED" for row in cases),
            "formal_solve_executed": False}


def create_batch(output: Path, settings_path: Path, batch_id: str,
                 *, minimum_ram_gb: float) -> dict:
    """Freeze a diagnostic batch only after all twelve exact Prepared files pass."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", batch_id):
        raise ValueError("Invalid batch identity")
    settings = _read(settings_path)
    git = git_state(ROOT)
    if git["dirty"] or git["sha"] != settings.get("git_sha"):
        raise ValueError("Batch requires the controller release's clean frozen SHA")
    if git_state(Path(settings["release"])) != git:
        raise ValueError("Controller release differs from the campaign SHA")
    summary = _read(output / "summary.json")
    binding = _read(output / "binding.json")
    if (not summary.get("all_prepared") or
            summary.get("binding") != binding or
            binding.get("git_sha") != git["sha"] or
            binding.get("preflight_hash") != content_hash(check())):
        raise ValueError("All twelve input audits must pass on the same frozen source")
    _, _, weeks = _source_and_design()
    if binding.get("weeks") != weeks or len(summary.get("cases", [])) != 12:
        raise ValueError("The monthly campaign does not contain exactly twelve weeks")
    prepared_root = Path(settings["outputs"]) / "prepared_inputs"
    tasks = []
    for week in weeks:
        state = _read(output / week / "state.json")
        if (state.get("status") != "PREPARED" or
                state.get("week") != week or
                not state.get("strict_scope_audit_passed")):
            raise ValueError(f"Week {week} is not strictly Prepared")
        path = prepared_root / state["scenario_id"] / f"{state['prepared_input_id']}.json"
        if not path.is_file() or _sha(path) != state.get("prepared_input_sha256"):
            raise ValueError(f"Prepared input changed for {week}")
        request = {
            "execution_profile": "existing_solver_v1", "mode": "mode_milp_only",
            "prepared_input_id": state["prepared_input_id"],
            "rebuild_dispatch": False, "use_existing_duties": False,
            "research_run": False, "random_seed": 42, "gurobi_threads": 4,
            "run_profile": "day_ahead_and_hourly_rolling",
            "run_hourly_rolling": True, "rolling_execution_minutes": 60,
            "time_limit_seconds": 120,
            "stage1_time_limit_seconds": 1800,
            "stage2_time_limit_seconds": 120,
            "mip_gap": 0.01, "timestep_min": 15,
        }
        tasks.append({"task_id": f"month-{week[:7]}", "submission": {
            "scenario_id": state["scenario_id"],
            "minimum_ram_gb": minimum_ram_gb, "request": request,
        }})
    manifest = {"schema_version": 1, "batch_id": batch_id,
                "controller_url": f"http://127.0.0.1:{settings['port']}",
                "git_sha": git["sha"], "tasks": tasks}
    from tools.cluster.batch import validate_batch
    validate_batch(manifest)
    path = output / "batch.json"
    if path.exists() and _read(path) != manifest:
        raise ValueError("Batch controls changed; create a new campaign directory")
    _write(path, manifest)
    return {"status": "BATCH_READY_DIAGNOSTIC", "batch_id": batch_id,
            "tasks": len(tasks), "manifest_sha256": _sha(path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "prepare", "batch"))
    parser.add_argument("--output", type=Path,
                        default=ROOT / "output/shibu24_monthly_20260923")
    parser.add_argument("--limit", type=int, default=12,
                        help="Prepare at most this many weeks; useful for a first-week gate")
    parser.add_argument("--settings", type=Path,
                        help="Frozen controller settings, required for batch")
    parser.add_argument("--batch-id", default="shibu24-monthly-overnight-v1")
    parser.add_argument("--minimum-ram-gb", type=float, default=18.0)
    args = parser.parse_args()
    if not 1 <= args.limit <= 12:
        parser.error("--limit must be in [1, 12]")
    if args.command == "batch":
        if args.settings is None:
            parser.error("batch requires --settings")
        result = create_batch(args.output.resolve(), args.settings.resolve(),
                              args.batch_id, minimum_ram_gb=args.minimum_ram_gb)
    else:
        result = check() if args.command == "check" else prepare(args.output.resolve(), limit=args.limit)
    if args.command == "prepare":
        _write(args.output.resolve() / "summary.json", result)
    summary = {"status": result.get("status", "PREPARE_COMPLETE")}
    if args.command == "batch":
        summary.update(tasks=result["tasks"], manifest_sha256=result["manifest_sha256"])
    elif args.command == "prepare":
        summary.update(weeks=len(result.get("cases", [])), all_prepared=result.get("all_prepared"))
    else:
        summary["weeks"] = len(result.get("weeks", []))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
