"""Prepare four-route dated inputs without changing the verified 3-route source.

The Shibu24 API capture is joined to the existing fixed Shibu21-23 source in a
new, diagnostic-only candidate. This command duplicates the untouched parent
scenario for each week and materializes the seven-day timetable and
forecast-only PV input. The default mode writes candidate canonical inputs in
a separate namespace and never reports formal Prepare success. ``--validate``
uses the repository's complete ``get_or_build_run_preparation`` contract
sequentially and still never starts a solver.
"""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Sequence
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from bff.services.date_series_inputs import (
    _date_forecast_rows,
    _date_pv_rows,
    _persist_actual_profiles,
    _verified_holiday_manifest,
)
from bff.services.run_preparation import (
    RunPreparation,
    _build_canonical_input,
    _dataset_version,
    _load_optional_stops,
    _load_scope_frames,
    _persist_prepared_input_immutably,
    _prepared_input_dir,
    _prepared_input_id,
    _scenario_hash,
    _scope_cache_payload,
    _scope_hash,
    get_or_build_run_preparation,
)
from bff.store import output_paths, scenario_store
from scripts.audits.audit_shibu24_source import sha256
from scripts.benchmarks.monthly_week_contract import validate_balanced_week
from src.runtime_scope import resolve_scope
from src.value_normalization import normalize_for_python
from src.optimization.common.date_series import (
    DATE_SERIES_INPUT_MODE,
    consecutive_service_dates,
    content_hash,
    dated_capacity_factors,
    materialize_dated_timetable,
    offset_clock,
    validate_dated_timetable,
)


PARENT_SCENARIO_ID = "771d115b-75b0-49f7-a7f0-25f259a2cd21"
WEEKS = ("2025-02-03", "2025-05-12", "2025-08-04", "2025-11-03")
OLD_SOURCE_DIR = ROOT / "data/derived/timetables/tsurumaki_20260901"
SHIBU24_SOURCE_DIR = ROOT / "output/shibu21_24_seasonal_20260911/shibu24_source_audit"
SOURCE_CANDIDATE_DIR = ROOT / "output/shibu21_24_seasonal_20260911/four_route_source_candidate"
THREE_ROUTE_SOURCE_CANDIDATE_DIR = ROOT / "output/shibu21_23_exact_20260911/source_candidate"
SOURCE_ID = "tsurumaki_shibu21_24_20260911_diagnostic_candidate_v1"
THREE_ROUTE_SOURCE_ID = "tsurumaki_shibu21_23_exact_20260911_source_v1"
DEFAULT_ROUTE_CODES = ("渋21", "渋22", "渋23", "渋24")
THREE_ROUTE_CODES = ("渋21", "渋22", "渋23")
BESS_SOC_MIN_RATIO = 0.20
BESS_SOC_MAX_RATIO = 0.80


def apply_seasonal_bess_policy(asset: dict) -> dict:
    """Apply the declared seasonal BESS operating range without changing the asset.

    Capacity, initial SOC, power, efficiency, and price controls come from the
    untouched parent asset. Only the operating bounds and terminal policy are
    derived here: 20%/80% hard bounds and a 20% terminal floor with no target.
    This keeps day and weekend boundaries free of an initial-SOC restoration
    obligation while retaining physical SOC bounds.
    """
    configured = deepcopy(asset)
    capacity_kwh = float(configured.get("bess_energy_kwh") or 0.0)
    if capacity_kwh <= 0.0:
        raise ValueError("Seasonal BESS policy requires a positive bess_energy_kwh")
    soc_min_kwh = capacity_kwh * BESS_SOC_MIN_RATIO
    soc_max_kwh = capacity_kwh * BESS_SOC_MAX_RATIO
    initial_soc_kwh = float(configured.get("bess_initial_soc_kwh") or 0.0)
    if not soc_min_kwh <= initial_soc_kwh <= soc_max_kwh:
        raise ValueError(
            "Parent BESS initial SOC is outside the declared seasonal 20%-80% range"
        )
    configured.update(
        bess_soc_min_kwh=soc_min_kwh,
        bess_soc_max_kwh=soc_max_kwh,
        bess_terminal_soc_min_kwh=soc_min_kwh,
        bess_terminal_soc_policy="minimum_only",
        bess_terminal_soc_target_kwh=0.0,
        bess_initial_soc_percent=(initial_soc_kwh / capacity_kwh) * 100.0,
        bess_soc_min_percent=BESS_SOC_MIN_RATIO * 100.0,
        bess_soc_max_percent=BESS_SOC_MAX_RATIO * 100.0,
        bess_terminal_soc_min_percent=BESS_SOC_MIN_RATIO * 100.0,
        bess_initial_soc_ratio=initial_soc_kwh / capacity_kwh,
        bess_soc_min_ratio=BESS_SOC_MIN_RATIO,
        bess_soc_max_ratio=BESS_SOC_MAX_RATIO,
        bess_terminal_soc_min_ratio=BESS_SOC_MIN_RATIO,
        bess_terminal_soc_target_ratio=0.0,
        bess_terminal_soc_target_percent=0.0,
    )
    return configured


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parent_hash(document: dict) -> str:
    return hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _matches_route_code(row: dict, route_code: str) -> bool:
    """Match only an NFKC-normalized exact route-code field."""

    normalized = unicodedata.normalize("NFKC", str(route_code or "")).strip()
    return any(
        unicodedata.normalize("NFKC", str(row.get(field) or "")).strip()
        == normalized
        for field in ("routeCode", "route_code", "routeSeriesCode", "routeFamilyCode")
    )


def _validated_route_codes(route_codes: Sequence[str]) -> tuple[str, ...]:
    requested = tuple(str(value).strip() for value in route_codes)
    if requested == DEFAULT_ROUTE_CODES:
        return DEFAULT_ROUTE_CODES
    if set(requested) == set(THREE_ROUTE_CODES) and len(requested) == len(THREE_ROUTE_CODES):
        return THREE_ROUTE_CODES
    raise ValueError(
        "Only the declared four-route design or exact 渋21/渋22/渋23 scope is supported"
    )


def _source_directory_and_id(route_codes: tuple[str, ...]) -> tuple[Path, str]:
    if route_codes == DEFAULT_ROUTE_CODES:
        return SOURCE_CANDIDATE_DIR, SOURCE_ID
    return THREE_ROUTE_SOURCE_CANDIDATE_DIR, THREE_ROUTE_SOURCE_ID


def build_source_candidate(*, route_codes: Sequence[str] = DEFAULT_ROUTE_CODES) -> dict:
    """Build the declared route scope with immutable source provenance."""

    route_codes = _validated_route_codes(route_codes)
    source_directory, source_id = _source_directory_and_id(route_codes)
    old_manifest_path = OLD_SOURCE_DIR / "manifest.json"
    route24_manifest_path = SHIBU24_SOURCE_DIR / "manifest.json"
    old_routes_all = read_json(OLD_SOURCE_DIR / "selected_routes.json")
    old_rows_all = read_json(OLD_SOURCE_DIR / "timetable_rows.json")
    old_sequences_all = read_json(OLD_SOURCE_DIR / "stop_sequences.json")
    old_stops_all = read_json(OLD_SOURCE_DIR / "stops.json")
    if route_codes == DEFAULT_ROUTE_CODES:
        route24_routes_all = read_json(SHIBU24_SOURCE_DIR / "selected_routes.json")
        route24_rows_all = read_json(SHIBU24_SOURCE_DIR / "timetable_rows.json")
        route24_sequences_all = read_json(SHIBU24_SOURCE_DIR / "stop_sequences.json")
        route24_stops_all = read_json(SHIBU24_SOURCE_DIR / "stops.json")
    else:
        route24_routes_all = route24_rows_all = route24_sequences_all = route24_stops_all = []
    if route_codes == THREE_ROUTE_CODES:
        # The existing OLD source is already the exact three-route capture.
        # Preserve every original row and stop; only validate its scope.
        routes = old_routes_all
        rows = old_rows_all
        sequences = old_sequences_all
        stops = old_stops_all
        route24_routes = route24_rows = route24_sequences = route24_stops = []
    else:
        old_routes, old_rows, old_sequences, old_stops = (
            old_routes_all, old_rows_all, old_sequences_all, old_stops_all
        )
        route24_routes, route24_rows, route24_sequences, route24_stops = (
            route24_routes_all, route24_rows_all, route24_sequences_all, route24_stops_all
        )
        routes = old_routes + route24_routes
        rows = old_rows + route24_rows
        sequences = old_sequences + route24_sequences
        stops = old_stops + route24_stops
    route_ids = [row["id"] for row in routes]
    trip_ids = [row["trip_id"] for row in rows]
    present_codes = {
        code for code in route_codes
        if any(_matches_route_code(row, code) for row in routes)
    }
    if present_codes != set(route_codes):
        raise ValueError(f"Source does not contain exactly the requested route scope: {route_codes}")
    if any(
        not any(_matches_route_code(row, code) for code in route_codes)
        for row in routes
    ):
        raise ValueError("Source contains a route outside the requested exact scope")
    route_id_set = set(route_ids)
    unknown_route_ids = {
        str(row.get("route_id") or "") for row in rows
    } - route_id_set
    if unknown_route_ids:
        raise ValueError(
            f"Source rows reference unknown route IDs: {sorted(unknown_route_ids)}"
        )
    if any(
        not any(_matches_route_code(row, code) for code in route_codes)
        for row in rows
    ):
        raise ValueError("Source contains timetable rows outside the requested exact scope")
    if len(route_ids) != len(set(route_ids)):
        raise ValueError("Route candidate contains duplicate route IDs")
    if len(trip_ids) != len(set(trip_ids)):
        raise ValueError("Route candidate contains duplicate timetable IDs")
    if any(not row.get("operator_id") or str(row["operator_id"]).upper() == "UNKNOWN"
           for row in rows):
        raise ValueError("Route candidate contains UNKNOWN or missing operator IDs")
    if any(float(row.get("distance_km") or 0) <= 0 or not row.get("distance_source")
           for row in rows):
        raise ValueError("Route candidate contains nonpositive or unproven distances")
    stops_by_id = {}
    for row in stops:
        prior = stops_by_id.setdefault(row["id"], row)
        comparable = ("name", "lat", "lon", "operator_id")
        if any(prior.get(key) != row.get(key) for key in comparable):
            raise ValueError(f"Conflicting stop provenance for {row['id']}")
        if (route_codes == DEFAULT_ROUTE_CODES and row.get("source_provenance")
                and not prior.get("source_provenance")):
            prior["source_provenance"] = row["source_provenance"]
    if route_codes == THREE_ROUTE_CODES and source_directory.exists():
        raise FileExistsError(f"Three-route source output already exists: {source_directory}")
    source_directory.mkdir(parents=True, exist_ok=True)
    for name, payload in (("selected_routes.json", routes), ("timetable_rows.json", rows),
                          ("stop_sequences.json", sequences),
                          ("stops.json", stops if route_codes == THREE_ROUTE_CODES else
                           sorted(stops_by_id.values(), key=lambda row: row["id"]))):
        write_json(source_directory / name, payload)
    route_counts = defaultdict(int)
    for row in rows:
        route_counts[row["route_id"]] += 1
    manifest = {
        "schema_version": (
            "four_route_source_candidate_v1"
            if route_codes == DEFAULT_ROUTE_CODES
            else "three_route_source_candidate_v1"
        ),
        "status": "DIAGNOSTIC_SOURCE_CAPTURE_VALIDATED_DISTANCE_PROXY_DECLARED",
        "route_codes": list(route_codes),
        "source_id": source_id,
        "source_directory": source_directory.relative_to(ROOT).as_posix(),
        "route_count": len(routes), "trip_count": len(rows),
        "selected_route_ids": sorted(route_ids),
        "trip_count_by_route_id": dict(sorted(route_counts.items())),
        "operator_unknown_count": 0,
        "nonpositive_distance_count": 0,
        "distance_semantics": "Adjacent official stop-coordinate haversine sum; geographic proxy, not road-network distance.",
        "browser_comparison_policy": "Not required for this diagnostic because official API stop sequences and coordinates were validated; this remains a diagnostic source, not a research acceptance source.",
        "provenance": {
            "old_manifest": {"path": old_manifest_path.as_posix(), "sha256": sha256(old_manifest_path)},
            "route24_manifest": {"path": route24_manifest_path.as_posix(), "sha256": sha256(route24_manifest_path)} if route_codes == DEFAULT_ROUTE_CODES else None,
            "old_artifacts": {name: sha256(OLD_SOURCE_DIR / name) for name in
                               ("selected_routes.json", "timetable_rows.json", "stop_sequences.json", "stops.json")},
            "route24_artifacts": (
                {
                    name: sha256(SHIBU24_SOURCE_DIR / name)
                    for name in (
                        "selected_routes.json", "timetable_rows.json",
                        "stop_sequences.json", "stops.json"
                    )
                }
                if route_codes == DEFAULT_ROUTE_CODES
                else None
            ),
        },
        "input_source_sha256": {
            name: sha256(OLD_SOURCE_DIR / name)
            for name in ("selected_routes.json", "timetable_rows.json", "stop_sequences.json", "stops.json")
        },
        "artifacts": {},
    }
    for path in sorted(source_directory.iterdir()):
        if path.name != "manifest.json":
            manifest["artifacts"][path.name] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    write_json(source_directory / "manifest.json", manifest)
    return manifest


def configure_doc(doc: dict, start_date: str, source: dict, *, design: dict | None = None) -> dict:
    """Materialize one seven-day case from the immutable candidate source."""
    source_directory = ROOT / str(
        source.get("source_directory") or SOURCE_CANDIDATE_DIR.relative_to(ROOT)
    )
    source_id = str(source.get("source_id") or SOURCE_ID)
    source_route_codes = list(source.get("route_codes") or DEFAULT_ROUTE_CODES)
    cfg = doc["simulation_config"]
    cfg.update(multi_day_input_mode=DATE_SERIES_INPUT_MODE, service_date=start_date,
               service_dates=[], planning_days=7, planning_horizon_hours=168,
               time_step_min=15, timestep_min=15, start_time="00:00", end_time="23:59",
               operation_time_window_enabled=False, rolling_lookahead_hours=24,
               bess_balance_period="evaluation_period", bess_terminal_soc_policy="minimum_only",
               rolling_bess_terminal_policy="minimum_only",
               bess_terminal_soc_floor_percent=20.0, pv_information_mode="training_only_forecast_proxy",
               daily_return_depot_id="tsurumaki", rolling_window_terminal_policy="day_ahead_boundary_state")
    cfg.pop("calendar_policy", None)
    cfg["allow_fixed_weekday_timetable_pv_counterfactual"] = False
    terminal = {"bev_terminal_soc_policy": "return_to_initial",
                "final_soc_target_percent": None, "final_soc_target_tolerance_percent": 0.0}
    cfg.update(terminal)
    doc.setdefault("scenario_overlay", {}).setdefault("charging_constraints", {}).update(terminal)
    selected_routes = read_json(source_directory / "selected_routes.json")
    selected_ids = [row["id"] for row in selected_routes]
    doc["dispatch_scope"]["routeSelection"].update(includeRouteIds=selected_ids, excludeRouteIds=[])
    doc["dispatch_scope"]["serviceSelection"] = {"serviceIds": ["WEEKDAY", "SAT", "SUN_HOL"]}
    dates = consecutive_service_dates(start_date, 7, [])
    holiday_manifest = _verified_holiday_manifest(ROOT, dates, cfg.get("holiday_source_id"))
    templates = [row for row in read_json(source_directory / "timetable_rows.json")
                 if row["route_id"] in set(selected_ids)]
    rows, contract = materialize_dated_timetable(
        templates, service_dates=dates, holiday_dates=list(holiday_manifest["holiday_dates"]),
        source_provenance={"source_id": source_id,
                           "source_candidate_manifest_sha256": sha256(source_directory / "manifest.json"),
                           "holiday_source_sha256": holiday_manifest["sha256"],
                           "distance_semantics": source["distance_semantics"]},
    )
    doc["timetable_rows"] = rows
    doc["routes"] = [deepcopy(row) for row in selected_routes]
    for route in doc["routes"]:
        route_templates = [row for row in templates if row["route_id"] == route["id"]]
        distances = {float(row["distance_km"]) for row in route_templates}
        if len(distances) != 1:
            raise ValueError(f"Route {route['id']} has inconsistent distances")
        route["distanceKm"] = distances.pop()
        route["distanceSource"] = "trip_stop_sequence_polyline_haversine"
        route["operator_id"] = "tokyu"
        route["tripCount"] = len(route_templates)
        route["tripCountsByDayType"] = {day: sum(row["service_id"] == day for row in route_templates)
                                         for day in ("WEEKDAY", "SAT", "SUN_HOL")}
    template_sequences = defaultdict(list)
    for row in read_json(source_directory / "stop_sequences.json"):
        template_sequences[row["trip_id"]].append(row)
    doc["stop_timetables"] = []
    for trip in rows:
        for original in template_sequences[trip["template_trip_id"]]:
            stop_row = {**deepcopy(original), "trip_id": trip["trip_id"],
                        "service_date": trip["service_date"], "service_id": trip["service_id"],
                        "route_id": trip["route_id"]}
            for key in ("departure_time", "arrival_time"):
                if stop_row.get(key) is not None:
                    stop_row[key] = offset_clock(stop_row[key], trip["day_index"] * 1440)
            doc["stop_timetables"].append(stop_row)
    used_stops = {row["stop_id"] for row in doc["stop_timetables"]}
    all_stops = {row["id"]: row for row in read_json(source_directory / "stops.json")}
    doc["stops"] = [deepcopy(all_stops[stop_id]) for stop_id in sorted(used_stops)]
    assets = cfg.get("depot_energy_assets") or []
    if isinstance(assets, dict):
        assets = [dict(value, depot_id=key) for key, value in assets.items()]
    asset = next((deepcopy(row) for row in assets if row.get("depot_id") == "tsurumaki"), {"depot_id": "tsurumaki"})
    step = int(cfg.get("timestep_min") or cfg.get("time_step_min") or 30)
    profiles, actual_sources = _date_pv_rows(ROOT / "data/external/solcast_raw/tsurumaki_2025_2026",
                                               dates, step, float(asset.get("performance_ratio") or .85))
    execution_input = _persist_actual_profiles(ROOT, profiles, actual_sources, dates, step)
    forecast_directory = None
    if design and design.get("require_balanced_monthly_weeks"):
        forecast_directory = ROOT / design["forecast_holdouts_directory"]
    profiles, forecast_audit = _date_forecast_rows(
        ROOT, dates, step, float(asset.get("performance_ratio") or .85),
        forecast_directory=forecast_directory,
    )
    for key in ("capacity_factor_by_slot", "pv_generation_kwh_by_slot", "pv_generation_kwh_by_date",
                "pv_case_id", "pv_source_date"):
        asset.pop(key, None)
    asset.update(pv_capacity_factor_by_date=profiles, pv_profile_source="training_only_climatology_proxy",
                 pv_profile_dates=dates, pv_slot_minutes=step,
                 pv_input_semantics="gross_generation_before_depot_load",
                 depot_load_model="explicit_zero_nontraction_load",
                 depot_load_kwh_by_slot=[0.0] * (1440 // step * len(dates)),
                 bess_balance_period="evaluation_period")
    asset = apply_seasonal_bess_policy(asset)
    dated_capacity_factors(asset, dates, step)
    cfg["depot_energy_assets"] = [asset]
    doc.setdefault("scenario_overlay", {})["depot_energy_assets"] = {"tsurumaki": deepcopy(asset)}
    doc["scenario_overlay"].setdefault("cost_coefficients", {}).update(
        pv_profile_id=None, pv_input_semantics="gross_generation_before_depot_load", pv_resolution_minutes=step)
    doc["pv_profiles"] = []
    contract.update(pv_source_sha256=[source["sha256"] for source in actual_sources],
                    daily_return_depot_id="tsurumaki", rolling_window_terminal_policy="day_ahead_boundary_state",
                    rolling_bess_terminal_policy="minimum_only",
                    selected_route_ids=selected_ids, depot_load_model="explicit_zero_nontraction_load",
                    bess_balance_period="evaluation_period", bess_terminal_soc_policy="minimum_only",
                    bess_terminal_soc_floor_percent=20.0,
                    rolling_lookahead_hours=cfg.get("rolling_lookahead_hours"),
                    pv_capacity_factor_rows_sha256=content_hash(profiles),
                    pv_information_mode="training_only_forecast_proxy", forecast_audit=forecast_audit,
                    pv_execution_input=execution_input,
                    bev_terminal_soc_policy="return_to_initial", final_soc_target_tolerance_percent=0.0,
                    solar_semantics="training_only_forecast_for_planning_separate_actuals_for_execution")
    cfg.update(service_dates=dates, service_date=dates[0], date_series_contract=contract,
               date_series_source_id=source_id, holiday_dates=list(holiday_manifest["holiday_dates"]),
               pv_input_semantics="gross_generation_before_depot_load", weather_observation_date=dates[0],
               weather_profile_source=source_id, comparison_type="fixed_timetable_with_date_specific_historical_pv",
               comparison_role=None, counterfactual_pv_source_date=None, pv_profile_id=None,
               planning_horizon_hours=168, start_time="00:00", end_time="23:59")
    cfg["pv_information_mode"] = "training_only_forecast_proxy"
    doc["dispatch_scope"]["serviceSelection"] = {"serviceIds": sorted({row["service_id"] for row in rows}),
                                                    "serviceDates": dates}
    doc["dispatch_scope"]["serviceDates"] = dates
    doc["dispatch_scope"]["serviceId"] = rows[0]["service_id"]
    cfg["day_type"] = rows[0]["service_id"]
    source_metadata = {
        "source_id": source_id, "source_manifest_sha256": sha256(source_directory / "manifest.json"),
        "route_codes": source_route_codes,
        "distance_semantics": source["distance_semantics"],
        "diagnostic_only": True,
    }
    doc["meta"]["route_scope_source_candidate"] = source_metadata
    if tuple(source_route_codes) == DEFAULT_ROUTE_CODES:
        doc["meta"]["four_route_source_candidate"] = deepcopy(source_metadata)
    validate_dated_timetable(rows, contract)
    if design and design.get("require_balanced_monthly_weeks"):
        if holiday_manifest["sha256"] != design["calendar_source_sha256"]:
            raise ValueError("Monthly selection and materialized calendar source hashes differ")
        contract["balanced_week_audit"] = validate_balanced_week(rows, contract, week=start_date)
    return doc


def _prepare_lightweight_candidate(
    doc: dict,
    scenario_id: str,
    output: Path,
) -> tuple[RunPreparation, Path]:
    """Materialize a candidate without representing it as formal Prepare success."""
    built_dir = ROOT / "data/built/tokyu_core"
    # ``output`` is the per-week directory; keep all candidate inputs in one
    # namespace beside the week manifests, never under authoritative
    # ``output/prepared_inputs``.
    scenarios_dir = output.parent / "candidate_prepared_inputs"
    scenario_hash = _scenario_hash(doc)
    scope = resolve_scope(doc, __import__("pandas").DataFrame())
    scope_payload = _scope_cache_payload(doc, scope)
    scope_hash = _scope_hash(scope_payload)
    prepared_input_id = _prepared_input_id(scenario_hash, scope_hash)
    trips_df, timetables_df, load_source = _load_scope_frames(
        doc, built_dir=built_dir, scope=scope
    )
    stops = _load_optional_stops(built_dir, doc, trips_df, timetables_df)
    canonical = normalize_for_python(_build_canonical_input(
        scenario=doc,
        prepared_input_id=prepared_input_id,
        scenario_id=scenario_id,
        dataset_version=_dataset_version(doc),
        scenario_hash=scenario_hash,
        scope_hash=scope_hash,
        scope_payload=scope_payload,
        scope=scope,
        trips_df=trips_df,
        timetables_df=timetables_df,
        stops=stops,
        stop_sequences=list(doc.get("stop_timetables") or []),
    ))
    prepared_scope_audit = {
        "status": "CANONICAL_INPUT_PREPARED_STRICT_TRANSITION_AUDIT_DEFERRED",
        "diagnostic_only": True,
        "strict_transition_audit_executed": False,
        "strict_transition_audit_reason": (
            "Deferred until root freezes the candidate; this preparation command "
            "must not execute a formal ProblemBuilder audit or solver."
        ),
        "load_source": load_source,
        "route_count": len(scope.route_ids),
        "trip_count": len(trips_df),
        "stop_time_row_count": len(timetables_df),
        "stop_count": len(stops),
        "vehicle_count": len(canonical.get("vehicles") or []),
        "operator_unknown_count": sum(
            not row.get("operator_id") or str(row.get("operator_id")).upper() == "UNKNOWN"
            for row in list(canonical.get("trips") or [])
        ),
        "warnings": ["STRICT_TRANSITION_AUDIT_DEFERRED"],
    }
    canonical["prepared_scope_audit"] = prepared_scope_audit
    canonical["scope"] = {
        **dict(canonical.get("scope") or {}),
        "prepared_scope_audit": prepared_scope_audit,
    }
    prepared_path = scenarios_dir / scenario_id
    prepared_path.mkdir(parents=True, exist_ok=True)
    solver_input_path = prepared_path / f"{prepared_input_id}.json"
    _persist_prepared_input_immutably(solver_input_path, canonical)
    # A candidate deliberately carries an error so RunPreparation.is_valid is
    # false.  The canonical file remains useful for inspection, but cannot be
    # mistaken for the formal Prepare contract by callers.
    prepared = RunPreparation(
        scenario_id=scenario_id,
        dataset_version=_dataset_version(doc),
        scenario_hash=scenario_hash,
        scope_hash=scope_hash,
        solver_input_path=solver_input_path,
        prepared_input_id=prepared_input_id,
        warnings=["STRICT_TRANSITION_AUDIT_DEFERRED"],
        error_code="CANDIDATE_STRICT_TRANSITION_AUDIT_DEFERRED",
        error="Candidate input is not formal Prepare success.",
        scope_summary={
            **dict(canonical.get("scope") or {}),
            "load_source": load_source,
            "prepared_scope_audit": prepared_scope_audit,
        },
    )
    return prepared, solver_input_path


def prepare_week(
    start_date: str,
    output: Path,
    source: dict,
    existing: dict | None = None,
    *,
    validation_mode: bool = False,
    design: dict | None = None,
) -> dict:
    parent = scenario_store._load(PARENT_SCENARIO_ID, skip_graph_arcs=True)
    before_hash = parent_hash(parent)
    record = existing or {}
    if record.get("scenario_id"):
        scenario_id = record["scenario_id"]
    else:
        route_scope_label = "-".join(source.get("route_codes") or DEFAULT_ROUTE_CODES)
        scenario_id = scenario_store.duplicate_scenario(
            PARENT_SCENARIO_ID, name=f"{route_scope_label} 7日入力候補 {start_date} diagnostic"
        )["id"]
    doc = scenario_store._load(scenario_id, skip_graph_arcs=True)
    doc = configure_doc(doc, start_date, source, design=design)
    scenario_store._invalidate_dispatch_artifacts(doc)
    scenario_store._normalize_dispatch_scope(doc)
    route_metadata_hash = content_hash({route["id"]: route for route in doc["routes"]})
    scenario_store._save(doc)
    doc = scenario_store._load(scenario_id, skip_graph_arcs=True)
    if content_hash({route["id"]: route for route in doc["routes"]}) != route_metadata_hash:
        raise ValueError("Captured route metadata changed during scenario save/reload")
    scenario_id = str(doc.get("id") or scenario_id)
    if validation_mode:
        prepared = get_or_build_run_preparation(
            scenario=doc,
            built_dir=ROOT / "data/built/tokyu_core",
            routes_df=None,
            scenarios_dir=output_paths.outputs_root() / "prepared_inputs",
        )
        prepared_path = prepared.solver_input_path
        prepared_namespace = "formal_prepared_inputs"
    else:
        prepared, prepared_path = _prepare_lightweight_candidate(doc, scenario_id, output)
        prepared_namespace = "candidate_prepared_inputs"
    canonical_route_metadata_hash = None
    if prepared_path is not None:
        canonical_routes = read_json(prepared_path).get("routes") or []
        canonical_route_metadata_hash = content_hash({route["id"]: route for route in canonical_routes})
        if canonical_route_metadata_hash != route_metadata_hash:
            raise ValueError("Captured route metadata changed during canonical Prepare")
    after_hash = parent_hash(scenario_store._load(PARENT_SCENARIO_ID, skip_graph_arcs=True))
    if before_hash != after_hash:
        raise ValueError("Parent scenario changed during four-route preparation")
    contract = doc["simulation_config"]["date_series_contract"]
    result = {
        "parent_scenario_id": PARENT_SCENARIO_ID, "scenario_id": scenario_id,
        "parent_document_sha256_before": before_hash, "parent_document_sha256_after": after_hash,
        "parent_unchanged": True, "prepared_input_id": prepared.prepared_input_id,
        "declared_route_metadata_sha256": route_metadata_hash,
        "canonical_route_metadata_sha256": canonical_route_metadata_hash,
        "route_metadata_preserved": canonical_route_metadata_hash == route_metadata_hash,
        "input_preparation_valid": bool(validation_mode and prepared.is_valid),
        "formal_prepared": bool(validation_mode and prepared.is_valid),
        "prepared_input_namespace": prepared_namespace,
        "prepared_input_path": (
            prepared_path.relative_to(ROOT).as_posix() if prepared_path else None
        ),
        "error_code": prepared.error_code,
        "error": prepared.error, "warnings": list(prepared.warnings),
        "vehicle_count": len(doc.get("vehicles") or []), "timetable_row_count": len(doc["timetable_rows"]),
        "selected_route_ids": contract["selected_route_ids"],
        "selected_route_codes": sorted({row.get("routeCode") for row in doc["routes"]}),
        "operator_unknown_count": sum(not row.get("operator_id") or str(row["operator_id"]).upper() == "UNKNOWN"
                                       for row in doc["timetable_rows"]),
        "nonpositive_distance_count": sum(float(row.get("distance_km") or 0) <= 0
                                           for row in doc["timetable_rows"]),
        "service_dates": contract["service_dates"],
        "days": [{key: day[key] for key in ("service_date", "day_type", "trip_count")}
                 for day in contract["days"]],
        "balanced_week_audit": contract.get("balanced_week_audit"),
        "forecast_audit": contract.get("forecast_audit"),
        "scope_summary": prepared.scope_summary,
        "source_candidate_manifest_sha256": sha256(
            ROOT / str(
                source.get("source_directory")
                or SOURCE_CANDIDATE_DIR.relative_to(ROOT)
            ) / "manifest.json"
        ),
        "research_status": "DIAGNOSTIC_NOT_USED_FOR_RESEARCH_CONCLUSIONS",
    }
    manifest_status = (
        "INPUTS_PREPARED_STRICT_AUDITED"
        if validation_mode and prepared.is_valid
        else "INPUTS_PREPARED_DIAGNOSTIC_CANDIDATE"
        if not validation_mode and prepared.solver_input_path
        else "INPUT_PREPARATION_BLOCKED"
    )
    write_json(output / "derived_scenarios.json", {"schema_version": "shibu21_24_prepared_inputs_v1",
                                                   "status": manifest_status,
                                                   "start_date": start_date, "source_candidate": source,
                                                   "cases": [result], "formal_solve_executed": False,
                                                   "research_status": result["research_status"]})
    return result


def main() -> None:
    parser = __import__("argparse").ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "output/shibu21_24_seasonal_inputs_20260911")
    parser.add_argument(
        "--validate",
        action="store_true",
        help=(
            "Run the repository's complete get_or_build_run_preparation path "
            "sequentially; this may take a long time and never starts a solver."
        ),
    )
    args = parser.parse_args()
    args.output = args.output.resolve()
    source = build_source_candidate()
    args.output.mkdir(parents=True, exist_ok=True)
    summary = {"status": "INPUT_PREPARATION_IN_PROGRESS", "mode": "formal_prepare_validation" if args.validate else "diagnostic_candidate",
               "validation_mode": bool(args.validate), "cases": [], "failures": [], "formal_solve_executed": False,
               "source_candidate_manifest_sha256": sha256(SOURCE_CANDIDATE_DIR / "manifest.json")}
    write_json(args.output / "summary.json", summary)
    for week in WEEKS:
        week_output = args.output / week
        week_output.mkdir(parents=True, exist_ok=True)
        started_at = time.time()
        write_json(week_output / "prepare_progress.json", {
            "schema_version": "shibu21_24_prepare_progress_v1",
            "week": week,
            "mode": summary["mode"],
            "validation_mode": bool(args.validate),
            "status": "PREPARATION_IN_PROGRESS",
            "started_at_utc": datetime.fromtimestamp(started_at, tz=timezone.utc).isoformat(),
            "started_at_unix": started_at,
            "completed": False,
            "failed": False,
            "formal_solve_executed": False,
        })
        print(json.dumps({"week": week, "status": "PREPARATION_IN_PROGRESS",
                          "mode": summary["mode"]}, ensure_ascii=False), flush=True)
        summary["active_week"] = week
        summary["active_started_at_unix"] = started_at
        write_json(args.output / "summary.json", summary)
        record = None
        manifest_path = week_output / "derived_scenarios.json"
        if manifest_path.exists():
            prior = read_json(manifest_path).get("cases") or []
            record = prior[0] if prior else None
        try:
            result = prepare_week(
                week, week_output, source, record, validation_mode=args.validate
            )
            case_summary = {"week": week, **{key: result[key] for key in
                                             ("scenario_id", "prepared_input_id", "input_preparation_valid",
                                              "formal_prepared", "prepared_input_namespace", "prepared_input_path",
                                              "vehicle_count", "timetable_row_count", "operator_unknown_count",
                                              "nonpositive_distance_count", "days")}}
        except Exception as exc:
            case_summary = {
                "week": week,
                "status": "INPUT_PREPARATION_FAILED",
                "input_preparation_valid": False,
                "formal_prepared": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            summary["failures"].append(case_summary)
            write_json(
                week_output / "prepare_failure.json",
                {"schema_version": "shibu21_24_prepare_failure_v1", **case_summary},
            )
        progress = {
            "schema_version": "shibu21_24_prepare_progress_v1",
            "week": week,
            "mode": summary["mode"],
            "validation_mode": bool(args.validate),
            "status": "PREPARATION_FAILED" if case_summary.get("status") == "INPUT_PREPARATION_FAILED" else "PREPARATION_COMPLETE",
            "started_at_utc": datetime.fromtimestamp(started_at, tz=timezone.utc).isoformat(),
            "started_at_unix": started_at,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": time.time() - started_at,
            "completed": case_summary.get("status") != "INPUT_PREPARATION_FAILED",
            "failed": case_summary.get("status") == "INPUT_PREPARATION_FAILED",
            "formal_solve_executed": False,
            "case": case_summary,
        }
        write_json(week_output / "prepare_progress.json", progress)
        summary["cases"].append(case_summary)
        summary.pop("active_week", None)
        summary.pop("active_started_at_unix", None)
        write_json(args.output / "summary.json", summary)
        print(json.dumps(summary["cases"][-1], ensure_ascii=False), flush=True)
    if args.validate:
        summary["status"] = (
            "INPUTS_PREPARED_STRICT_AUDITED"
            if summary["cases"] and all(row.get("formal_prepared") for row in summary["cases"])
            else "INPUT_PREPARATION_BLOCKED"
        )
    else:
        summary["status"] = (
            "INPUTS_PREPARED_DIAGNOSTIC_CANDIDATE"
            if summary["cases"] and all(row.get("prepared_input_namespace") == "candidate_prepared_inputs" for row in summary["cases"])
            else "INPUT_PREPARATION_BLOCKED"
        )
    write_json(args.output / "summary.json", summary)
    print(json.dumps({"status": summary["status"], "case_count": len(summary["cases"]),
                      "failure_count": len(summary["failures"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
