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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bff.services.date_series_inputs import _date_forecast_rows, _date_pv_rows, _verified_holiday_manifest
from bff.services.cluster.contracts import git_state
from bff.services.run_preparation import get_or_build_run_preparation
from bff.store import output_paths, scenario_store
from scripts.benchmarks.monthly_week_contract import select_monthly_weeks, validate_balanced_week
from scripts.benchmarks.prepare_shibu21_24_seasonal_inputs import configure_doc, parent_hash
from src.optimization.common.date_series import content_hash, materialize_dated_timetable, timetable_hash
from src.optimization.common.next_morning import PRICE_POLICY, SCHEMA, resolve_next_morning_contract

SOURCE = ROOT / "output/shibu21_24_seasonal_20260911/shibu24_source_audit"
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
    source_manifest = _read(SOURCE / "manifest.json")
    if source_manifest.get("status") != "SOURCE_CAPTURE_VALIDATED_BROWSER_COMPARISON_PENDING":
        raise ValueError("Unexpected Shibu24 source audit status")
    for name in ("selected_routes.json", "timetable_rows.json", "stop_sequences.json", "stops.json"):
        if _sha(SOURCE / name) != source_manifest["artifacts"][name]["sha256"]:
            raise ValueError(f"Shibu24 source hash changed: {name}")
    for source in source_manifest["capture_manifest"]["sources"]:
        original = Path(source["path"])
        if not original.is_file() or _sha(original) != source["sha256"]:
            raise ValueError("Original Shibu24 ODPT capture changed or is missing")
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
        "source_directory": SOURCE.relative_to(ROOT).as_posix(),
        "source_id": "tsurumaki_shibu24_odpt_20260911_diagnostic_v1",
        "route_codes": ["渋24"],
        "distance_semantics": source_manifest["source_validation"]["distance_semantics"],
    }
    return source, design, weeks


def _clock_minutes(value: str) -> int:
    hour, minute = map(int, value.split(":"))
    return hour * 60 + minute


def _overnight_contract(doc: dict, templates: list[dict]) -> dict:
    config = doc["simulation_config"]
    dates = list(config["service_dates"])
    next_date = (date.fromisoformat(dates[-1]) + timedelta(days=1)).isoformat()
    eight_dates = dates + [next_date]
    holiday = _verified_holiday_manifest(ROOT, eight_dates, config.get("holiday_source_id"))
    eight_rows, _ = materialize_dated_timetable(
        templates, service_dates=eight_dates,
        holiday_dates=list(holiday["holiday_dates"]),
        source_provenance=config["date_series_contract"]["source_provenance"],
    )
    if timetable_hash(eight_rows[:len(doc["timetable_rows"])]) != timetable_hash(doc["timetable_rows"]):
        raise ValueError("Seven service days changed while deriving the following morning")
    next_rows = [row for row in eight_rows if row["service_date"] == next_date]
    first_departures = [
        min(_clock_minutes(row["source_departure"]) for row in eight_rows
            if row["service_date"] == day)
        for day in eight_dates[1:]
    ]
    asset = next(row for row in config["depot_energy_assets"] if row["depot_id"] == "tsurumaki")
    step = int(config["timestep_min"])
    performance_ratio = float(asset.get("performance_ratio") or .85)
    predicted, forecast_audit = _date_forecast_rows(
        ROOT, eight_dates, step, performance_ratio
    )
    if predicted[:7] != asset["pv_capacity_factor_by_date"]:
        raise ValueError("Next-morning model differs from the frozen seven-day forecast")
    actual, actual_sources = _date_pv_rows(
        ROOT / "data/external/solcast_raw/tsurumaki_2025_2026",
        eight_dates, step, performance_ratio,
    )
    if not actual_sources or len(actual) != 8:
        raise ValueError("The final next morning has no verified Solcast source")
    contract = {
        "schema_version": SCHEMA,
        "service_dates": dates,
        "next_service_date": next_date,
        "next_day_timetable_rows": next_rows,
        "next_day_timetable_rows_sha256": timetable_hash(next_rows),
        "first_departure_minute_by_next_day": first_departures,
        "next_day_pv_capacity_factor": predicted[7],
        "next_day_pv_sha256": content_hash(predicted[7]),
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
    validate_balanced_week(doc["timetable_rows"], config["date_series_contract"], week=dates[0])
    return {"next_service_date": next_date, "extra_slots": first_departures[-1] // step,
            "forecast_model_sha256": forecast_audit.get("model_sha256"),
            "next_day_pv_sha256": contract["next_day_pv_sha256"],
            "next_day_timetable_rows_sha256": contract["next_day_timetable_rows_sha256"]}


def check() -> dict:
    source, design, weeks = _source_and_design()
    templates = _read(SOURCE / "timetable_rows.json")
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
            "year": 2025, "source_manifest_sha256": _sha(SOURCE / "manifest.json"),
            "forecast_manifest_sha256": _sha(FORECAST / "manifest.json"),
            "week_selection_sha256": _sha(SELECTION), "weeks": results,
            "source_limit": "browser comparison pending; geographic distance proxy",
            "formal_solve_executed": False}


def prepare(output: Path, *, limit: int) -> dict:
    preflight = check()
    source, design, weeks = _source_and_design()
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
        extension = _overnight_contract(doc, _read(SOURCE / "timetable_rows.json"))
        scenario_store._invalidate_dispatch_artifacts(doc)
        scenario_store._normalize_dispatch_scope(doc)
        scenario_store._save(doc)
        if parent_hash(scenario_store._load(PARENT_ID, skip_graph_arcs=True)) != original_parent_hash:
            raise ValueError("Parent scenario changed during monthly preparation")
        prepared = get_or_build_run_preparation(
            scenario=scenario_store._load(state["scenario_id"], skip_graph_arcs=True),
            built_dir=ROOT / "data/built/tokyu_core", routes_df=None,
            scenarios_dir=output_paths.outputs_root() / "prepared_inputs",
        )
        state.update(status="PREPARED" if prepared.is_valid else "BLOCKED_PREPARE",
                     prepared_input_id=prepared.prepared_input_id,
                     input_preparation_valid=prepared.is_valid,
                     error_code=prepared.error_code, error=prepared.error,
                     overnight=extension)
        _write(path, state)
        cases.append(state)
        print(json.dumps({"week": week, "status": state["status"],
                          "prepared_input_id": prepared.prepared_input_id}, ensure_ascii=False), flush=True)
        if not prepared.is_valid:
            break
    return {"schema_version": "shibu24_monthly_prepare_v1", "binding": binding,
            "cases": cases, "all_prepared": len(cases) == len(weeks) and all(
                row["status"] == "PREPARED" for row in cases),
            "formal_solve_executed": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "prepare"))
    parser.add_argument("--output", type=Path,
                        default=ROOT / "output/shibu24_monthly_20260923")
    parser.add_argument("--limit", type=int, default=12,
                        help="Prepare at most this many weeks; useful for a first-week gate")
    args = parser.parse_args()
    if not 1 <= args.limit <= 12:
        parser.error("--limit must be in [1, 12]")
    result = check() if args.command == "check" else prepare(args.output.resolve(), limit=args.limit)
    if args.command == "prepare":
        _write(args.output.resolve() / "summary.json", result)
    print(json.dumps({"status": result.get("status", "PREPARE_COMPLETE"),
                      "weeks": len(result.get("weeks", result.get("cases", []))),
                      "all_prepared": result.get("all_prepared")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
