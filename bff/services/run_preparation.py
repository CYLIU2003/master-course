from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from bff.services.route_catalog_audit import audit_route_catalog_consistency
from src.optimization.common.pv_area import (
    DEFAULT_PERFORMANCE_RATIO,
    estimate_depot_pv_from_area,
)
from src.value_normalization import normalize_for_python


log = logging.getLogger("run_prep")


def _normalize_solver_mode(mode: Any) -> str:
    normalized = str(mode or "").strip().lower()
    alias_map = {
        "milp": "mode_milp_only",
        "exact": "mode_milp_only",
        "alns": "mode_alns_only",
        "heuristic": "mode_alns_only",
        "hybrid": "mode_alns_milp",
        "ga": "mode_ga_only",
        "abc": "mode_abc_only",
    }
    return alias_map.get(normalized, str(mode or "").strip() or "mode_milp_only")


def solver_prepare_profile(mode: Any) -> dict[str, Any]:
    solver_mode_effective = _normalize_solver_mode(mode)
    if solver_mode_effective == "mode_milp_only":
        return {
            "solver_mode_effective": solver_mode_effective,
            "profile": "milp_exact",
            "dispatch_rebuild_required": False,
            "preferred_execution": "optimization",
            "notes": [
                "prepared scope is used directly",
                "MILP exact solve consumes canonical ProblemData",
            ],
        }
    if solver_mode_effective == "mode_alns_only":
        return {
            "solver_mode_effective": solver_mode_effective,
            "profile": "metaheuristic_alns",
            "dispatch_rebuild_required": False,
            "preferred_execution": "optimization",
            "notes": [
                "prepared scope is used directly",
                "ALNS consumes canonical ProblemData without dispatch rebuild",
            ],
        }
    if solver_mode_effective == "mode_ga_only":
        return {
            "solver_mode_effective": solver_mode_effective,
            "profile": "metaheuristic_ga",
            "dispatch_rebuild_required": False,
            "preferred_execution": "optimization",
            "notes": [
                "prepared scope is used directly",
                "GA mode reuses canonical ProblemData preparation",
            ],
        }
    if solver_mode_effective == "mode_abc_only":
        return {
            "solver_mode_effective": solver_mode_effective,
            "profile": "metaheuristic_abc",
            "dispatch_rebuild_required": False,
            "preferred_execution": "optimization",
            "notes": [
                "prepared scope is used directly",
                "ABC mode reuses canonical ProblemData preparation",
            ],
        }
    return {
        "solver_mode_effective": solver_mode_effective,
        "profile": "hybrid_seeded",
        "dispatch_rebuild_required": False,
        "preferred_execution": "optimization",
        "notes": [
            "prepared scope is used directly",
            "hybrid mode consumes canonical ProblemData with ALNS+MILP pipeline",
        ],
    }


@dataclass
class RunPreparation:
    scenario_id: str
    dataset_version: str
    scenario_hash: str
    scope_hash: Optional[str]
    solver_input_path: Optional[Path]
    scope_summary: dict
    prepared_input_id: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    prepared_at: float = field(default_factory=time.time)
    error: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        return self.error is None and self.solver_input_path is not None


_prep_cache: dict[tuple[str, str, str], RunPreparation] = {}
_VOLATILE_HASH_KEYS = {
    "__unloaded_artifact_fields__",
    "updatedAt",
    "createdAt",
    "status",
    "meta",
    "stats",
    "refs",
    "timetable_rows",
    "stop_timetables",
    "trips",
    "graph",
    "blocks",
    "duties",
    "dispatch_plan",
    "simulation_result",
    "simulation_audit",
    "simulationAudit",
    "optimization_result",
    "optimization_audit",
    "optimizationAudit",
    "problemdata_build_audit",
    "problemdataBuildAudit",
    "datasetStatus",
    "dataset_status",
    "prepared_input_id",
    "preparedInputId",
    "prepared_at",
    "selectedDepotIds",
    "selectedRouteIds",
    "serviceIds",
}


def _canonicalize_for_hash(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonicalize_for_hash(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _VOLATILE_HASH_KEYS
        }
    if isinstance(value, list):
        return [_canonicalize_for_hash(item) for item in value]
    return value


def _scenario_hash(scenario_dict: dict) -> str:
    canonical = json.dumps(
        _canonicalize_for_hash(scenario_dict),
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _prepared_input_id(scenario_hash: str) -> str:
    return f"prepared-{scenario_hash}"


def _scope_hash(scope_payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        _canonicalize_for_hash(scope_payload),
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _as_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame.empty:
        return []
    return [
        {str(key): normalize_for_python(value) for key, value in record.items()}
        for record in frame.to_dict(orient="records")
    ]


def _rows_to_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def _scenario_value(scenario: dict, *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in scenario and scenario[key] is not None:
            return scenario[key]
    return default


def _scenario_id(scenario: dict) -> str:
    meta = scenario.get("meta") or {}
    return str(
        scenario.get("id")
        or scenario.get("scenario_id")
        or meta.get("id")
        or "unknown"
    )


def _dataset_version(scenario: dict) -> str:
    meta = scenario.get("meta") or {}
    overlay = _scenario_value(scenario, "scenario_overlay", "scenarioOverlay", default={}) or {}
    feed_context = _scenario_value(scenario, "feed_context", "feedContext", default={}) or {}
    return str(
        scenario.get("datasetVersion")
        or scenario.get("dataset_version")
        or meta.get("datasetVersion")
        or overlay.get("dataset_version")
        or overlay.get("datasetVersion")
        or feed_context.get("snapshotId")
        or "unknown"
    )


def _dataset_id(scenario: dict) -> str:
    meta = scenario.get("meta") or {}
    overlay = _scenario_value(scenario, "scenario_overlay", "scenarioOverlay", default={}) or {}
    feed_context = _scenario_value(scenario, "feed_context", "feedContext", default={}) or {}
    return str(
        scenario.get("datasetId")
        or scenario.get("dataset_id")
        or meta.get("datasetId")
        or overlay.get("dataset_id")
        or overlay.get("datasetId")
        or feed_context.get("datasetId")
        or "tokyu_core"
    )


def _random_seed(scenario: dict) -> int:
    meta = scenario.get("meta") or {}
    overlay = _scenario_value(scenario, "scenario_overlay", "scenarioOverlay", default={}) or {}
    simulation_config = _scenario_value(
        scenario,
        "simulation_config",
        "simulationConfig",
        default={},
    ) or {}
    raw = (
        scenario.get("randomSeed")
        or scenario.get("random_seed")
        or meta.get("randomSeed")
        or overlay.get("random_seed")
        or overlay.get("randomSeed")
        or simulation_config.get("random_seed")
        or simulation_config.get("randomSeed")
        or 42
    )
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 42


def _id_aliases(value: Any) -> set[str]:
    raw = str(value or "").strip()
    if not raw:
        return set()
    return {raw, raw.split(":")[-1]}


def _select_items_by_ids(items: list[dict[str, Any]], ids: list[str]) -> list[dict[str, Any]]:
    if not items:
        return []
    if not ids:
        return [dict(item) for item in items]
    selected_ids: set[str] = set()
    for item in ids:
        selected_ids.update(_id_aliases(item))
    return [
        dict(item)
        for item in items
        if _id_aliases(item.get("id") or item.get("routeId") or item.get("depotId") or "") & selected_ids
    ]


def _collect_referenced_stop_ids(
    trips_df: pd.DataFrame,
    timetables_df: pd.DataFrame,
) -> set[str]:
    referenced_stop_ids: set[str] = set()
    frame_columns = (
        (trips_df, ("origin_stop_id", "destination_stop_id", "originStopId", "destinationStopId")),
        (timetables_df, ("stop_id", "stopId", "origin_stop_id", "destination_stop_id", "originStopId", "destinationStopId")),
    )
    for frame, columns in frame_columns:
        if frame.empty:
            continue
        for column in columns:
            if column not in frame.columns:
                continue
            referenced_stop_ids.update(
                str(value)
                for value in frame[column].dropna().astype(str).tolist()
                if str(value).strip()
            )
    return referenced_stop_ids


def _filter_stop_records(
    stops: list[dict[str, Any]],
    referenced_stop_ids: set[str],
) -> list[dict[str, Any]]:
    if not stops:
        return []
    if not referenced_stop_ids:
        return [dict(item) for item in stops if isinstance(item, dict)]
    filtered: list[dict[str, Any]] = []
    for item in stops:
        if not isinstance(item, dict):
            continue
        stop_id = str(item.get("id") or item.get("stop_id") or item.get("stopId") or "").strip()
        if stop_id and stop_id in referenced_stop_ids:
            filtered.append(dict(item))
    return filtered


def _load_catalog_stops(
    scenario: dict,
    referenced_stop_ids: set[str],
) -> list[dict[str, Any]]:
    try:
        from src import tokyu_bus_data

        dataset_id = _dataset_id(scenario)
        if not tokyu_bus_data.tokyu_bus_data_ready(dataset_id):
            return []
        return _filter_stop_records(
            tokyu_bus_data.load_stops(dataset_id=dataset_id),
            referenced_stop_ids,
        )
    except Exception as exc:
        log.warning("Catalog stop load failed; falling back to inferred stops: %s", exc)
        return []


def _merge_stop_records(
    primary_rows: list[dict[str, Any]],
    fallback_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    ordered_ids: list[str] = []
    for rows in (primary_rows, fallback_rows):
        for item in rows:
            if not isinstance(item, dict):
                continue
            stop_id = str(item.get("id") or item.get("stop_id") or item.get("stopId") or "").strip()
            if not stop_id:
                continue
            normalized = dict(item)
            if stop_id in merged:
                existing = merged[stop_id]
                for key, value in normalized.items():
                    if existing.get(key) in (None, "", 0.0) and value not in (None, ""):
                        existing[key] = value
                continue
            merged[stop_id] = normalized
            ordered_ids.append(stop_id)
    return [merged[stop_id] for stop_id in ordered_ids]


def _load_optional_stops(
    built_dir: Path,
    scenario: dict,
    trips_df: pd.DataFrame,
    timetables_df: pd.DataFrame,
) -> list[dict[str, Any]]:
    referenced_stop_ids = _collect_referenced_stop_ids(trips_df, timetables_df)
    stops_path = built_dir / "stops.parquet"
    if not stops_path.exists():
        catalog_rows = _load_catalog_stops(scenario, referenced_stop_ids)
        return _merge_stop_records(
            catalog_rows,
            _derived_stops_from_frames(trips_df, timetables_df),
        )
    frame = pd.read_parquet(stops_path)
    if frame.empty:
        catalog_rows = _load_catalog_stops(scenario, referenced_stop_ids)
        return _merge_stop_records(
            catalog_rows,
            _derived_stops_from_frames(trips_df, timetables_df),
        )
    frame_rows = _as_records(frame)
    filtered_frame_rows = _filter_stop_records(frame_rows, referenced_stop_ids)
    if filtered_frame_rows:
        catalog_rows = _load_catalog_stops(scenario, referenced_stop_ids)
        return _merge_stop_records(
            filtered_frame_rows,
            _merge_stop_records(
                catalog_rows,
                _derived_stops_from_frames(trips_df, timetables_df),
            ),
        )
    catalog_rows = _load_catalog_stops(scenario, referenced_stop_ids)
    return _merge_stop_records(
        catalog_rows or frame_rows,
        _derived_stops_from_frames(trips_df, timetables_df),
    )


def _derived_stops_from_frames(
    trips_df: pd.DataFrame,
    timetables_df: pd.DataFrame,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    frames = (
        (
            timetables_df,
            (
                ("stop_id", "stop_name"),
                ("stopId", "stopName"),
                ("origin_stop_id", "origin"),
                ("destination_stop_id", "destination"),
                ("originStopId", "origin"),
                ("destinationStopId", "destination"),
            ),
        ),
        (
            trips_df,
            (
                ("origin_stop_id", "origin"),
                ("destination_stop_id", "destination"),
                ("originStopId", "origin"),
                ("destinationStopId", "destination"),
            ),
        ),
    )
    for frame, column_pairs in frames:
        if frame.empty:
            continue
        for row in frame.to_dict(orient="records"):
            for column, name_column in column_pairs:
                if column not in row:
                    continue
                stop_id = str(row.get(column) or "").strip()
                if not stop_id or stop_id in seen_ids:
                    continue
                seen_ids.add(stop_id)
                items.append(
                    {
                        "id": stop_id,
                        "name": str(row.get(name_column) or stop_id),
                        "source": "prepared_input_inferred",
                    }
                )
    return items


def _load_scope_frames(
    scenario: dict,
    *,
    built_dir: Path,
    scope,
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    try:
        from src import tokyu_bus_data, tokyu_shard_loader

        dataset_id = _dataset_id(scenario)
        if tokyu_shard_loader.shard_runtime_ready(dataset_id):
            trip_rows = tokyu_shard_loader.load_trip_rows_for_scope(
                dataset_id=dataset_id,
                route_ids=scope.route_ids,
                depot_ids=scope.depot_ids,
                service_ids=scope.service_ids,
            )
            stop_time_rows = tokyu_shard_loader.load_stop_time_rows_for_scope(
                dataset_id=dataset_id,
                route_ids=scope.route_ids,
                depot_ids=scope.depot_ids,
                service_ids=scope.service_ids,
            )
            return (
                _rows_to_frame(trip_rows),
                _rows_to_frame(stop_time_rows),
                "tokyu_shard",
            )
        if tokyu_bus_data.tokyu_bus_data_ready(dataset_id):
            trip_rows = tokyu_bus_data.load_trip_rows_for_scope(
                dataset_id=dataset_id,
                route_ids=scope.route_ids,
                depot_ids=scope.depot_ids,
                service_ids=scope.service_ids,
            )
            stop_time_rows = tokyu_bus_data.load_stop_time_rows_for_scope(
                dataset_id=dataset_id,
                route_ids=scope.route_ids,
                depot_ids=scope.depot_ids,
                service_ids=scope.service_ids,
            )
            return (
                _rows_to_frame(trip_rows),
                _rows_to_frame(stop_time_rows),
                "tokyu_bus_data",
            )
    except Exception as exc:
        log.warning("Shard runtime load failed; falling back to built parquet: %s", exc)

    from src.runtime_scope import load_scoped_timetables, load_scoped_trips

    try:
        trips_df = load_scoped_trips(built_dir, scope)
        timetables_df = load_scoped_timetables(built_dir, scope)
        if not trips_df.empty:
            return (trips_df, timetables_df, "built_parquet")
    except Exception as exc:
        log.warning("Built parquet load failed; falling back to timetable_rows: %s", exc)

    timetable_rows = list(scenario.get("timetable_rows") or [])
    if timetable_rows:
        route_id_set = set(scope.route_ids) if scope.route_ids else None
        service_id_set = set(scope.service_ids) if scope.service_ids else None
        _vn_pattern = re.compile(r"__v\d+$")
        scoped_rows = [
            row for row in timetable_rows
            if (route_id_set is None or str(row.get("route_id") or "").strip() in route_id_set)
            and (service_id_set is None or str(row.get("service_id") or "").strip() in service_id_set)
            and not _vn_pattern.search(str(row.get("trip_id") or ""))
        ]
        return (
            _rows_to_frame(scoped_rows),
            _rows_to_frame([]),
            "timetable_rows_fallback",
        )

    return (_rows_to_frame([]), _rows_to_frame([]), "built_parquet")


_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")


def _validate_path_segment(raw: str) -> str:
    """Reject path-traversal payloads in user-supplied IDs."""
    text = str(raw or "").strip()
    if not text or not _SAFE_ID_RE.match(text):
        raise ValueError(f"Invalid ID (path traversal blocked): {raw!r}")
    return text


def _prepared_input_dir(scenarios_dir: Path, scenario_id: str) -> Path:
    sid = _validate_path_segment(scenario_id)
    if scenarios_dir.name == "prepared_inputs":
        return scenarios_dir / sid
    return scenarios_dir / sid / "prepared_inputs"


def _route_catalog_audit_warnings(audit: dict[str, Any]) -> list[str]:
    checked_count = int(audit.get("checkedRouteCount") or 0)
    if checked_count <= 0:
        return []
    issue_count = int(audit.get("issueCount") or 0)
    family_issue_count = int(audit.get("familyIssueCount") or 0)
    trip_count_mismatch_count = int(audit.get("tripCountMismatchCount") or 0)
    source = str(audit.get("actualCountsSource") or "unavailable")
    if issue_count <= 0:
        return [
            "Route catalog audit passed: "
            f"checked={checked_count}, family_issues=0, trip_count_mismatches=0, source={source}"
        ]

    summary = (
        "Route catalog audit found inconsistencies: "
        f"checked={checked_count}, family_issues={family_issue_count}, "
        f"trip_count_mismatches={trip_count_mismatch_count}, source={source}"
    )
    details: list[str] = []
    for issue in list(audit.get("issues") or [])[:3]:
        kind = str(issue.get("kind") or "unknown")
        route_id = str(issue.get("routeId") or "").strip()
        route_code = str(issue.get("routeCode") or "").strip()
        label = route_code or route_id or "unknown-route"
        details.append(f"audit detail: {kind} ({label})")
    return [summary, *details]


def _depot_area_value(depot: dict[str, Any]) -> Any:
    return depot.get("depotAreaM2", depot.get("depot_area_m2"))


def _compose_generation_from_capacity_factor_rows(
    capacity_kw: float,
    rows: list[Any],
) -> tuple[list[float], list[dict[str, Any]]]:
    combined: list[float] = []
    generation_rows: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        try:
            slot_minutes = max(int(item.get("slot_minutes") or item.get("slotMinutes") or 60), 1)
        except (TypeError, ValueError):
            slot_minutes = 60
        duration_h = max(slot_minutes / 60.0, 1.0e-9)
        factors = []
        for value in item.get("capacity_factor_by_slot") or item.get("capacityFactorBySlot") or []:
            try:
                factors.append(max(0.0, min(float(value or 0.0), 1.0)))
            except (TypeError, ValueError):
                factors.append(0.0)
        daily = [round(max(capacity_kw, 0.0) * factor * duration_h, 6) for factor in factors]
        generation_rows.append(
            {
                "date": str(item.get("date") or ""),
                "slot_minutes": slot_minutes,
                "pv_generation_kwh_by_slot": daily,
            }
        )
        combined.extend(daily)
    return combined, generation_rows


def _capacity_factor_from_generation_series(
    generation_kwh_by_slot: list[Any],
    *,
    legacy_capacity_kw: Any,
    slot_minutes: Any = 60,
) -> list[float]:
    try:
        capacity_kw = max(float(legacy_capacity_kw or 0.0), 0.0)
    except (TypeError, ValueError):
        capacity_kw = 0.0
    try:
        duration_h = max(int(slot_minutes or 60), 1) / 60.0
    except (TypeError, ValueError):
        duration_h = 1.0
    values: list[float] = []
    for value in generation_kwh_by_slot:
        try:
            values.append(max(float(value or 0.0), 0.0))
        except (TypeError, ValueError):
            values.append(0.0)
    if not values:
        return []
    if capacity_kw <= 0.0:
        capacity_kw = max(value / max(duration_h, 1.0e-9) for value in values)
    if capacity_kw <= 0.0:
        return [0.0 for _value in values]
    denominator = capacity_kw * max(duration_h, 1.0e-9)
    return [max(0.0, min(value / denominator, 1.0)) for value in values]


def _prepare_depot_energy_assets(
    simulation_config: dict[str, Any],
    depots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    existing_by_depot: dict[str, dict[str, Any]] = {}
    ordered_ids: list[str] = []
    for item in simulation_config.get("depot_energy_assets") or []:
        if not isinstance(item, dict):
            continue
        depot_id = str(item.get("depot_id") or item.get("depotId") or "").strip()
        if not depot_id:
            continue
        existing_by_depot[depot_id] = dict(item)
        ordered_ids.append(depot_id)

    depot_area_by_id = {
        str(depot.get("id") or depot.get("depot_id") or depot.get("depotId") or "").strip(): _depot_area_value(depot)
        for depot in depots
        if str(depot.get("id") or depot.get("depot_id") or depot.get("depotId") or "").strip()
    }
    for depot_id in depot_area_by_id:
        if depot_id not in ordered_ids:
            ordered_ids.append(depot_id)

    prepared_rows: list[dict[str, Any]] = []
    for depot_id in ordered_ids:
        row = dict(existing_by_depot.get(depot_id) or {"depot_id": depot_id})
        row["depot_id"] = depot_id
        legacy_capacity_kw = row.get("pv_capacity_kw", row.get("pvCapacityKw"))
        area_value = row.get("depot_area_m2", row.get("depotAreaM2"))
        if area_value is None:
            area_value = depot_area_by_id.get(depot_id)
        estimate = estimate_depot_pv_from_area(
            area_value,
            usable_area_ratio=row.get("usable_area_ratio", row.get("usableAreaRatio")),
            panel_power_density_kw_m2=row.get(
                "panel_power_density_kw_m2",
                row.get("panelPowerDensityKwM2"),
            ),
        )
        row["depot_area_m2"] = estimate.depot_area_m2
        row["usable_area_ratio"] = estimate.usable_area_ratio
        row["panel_power_density_kw_m2"] = estimate.panel_power_density_kw_m2
        try:
            performance_ratio = float(row.get("performance_ratio") or DEFAULT_PERFORMANCE_RATIO)
        except (TypeError, ValueError):
            performance_ratio = DEFAULT_PERFORMANCE_RATIO
        row["performance_ratio"] = performance_ratio if performance_ratio > 0.0 else DEFAULT_PERFORMANCE_RATIO
        row["estimated_installable_area_m2"] = round(estimate.installable_area_m2, 6)
        row["pv_capacity_kw"] = round(estimate.capacity_kw, 6) if estimate.depot_area_m2 is not None else 0.0
        row["derived_pv_capacity_kw"] = row["pv_capacity_kw"]
        row["pv_enabled"] = estimate.depot_area_m2 is not None and estimate.capacity_kw > 0.0

        factor_rows = list(row.get("pv_capacity_factor_by_date") or [])
        if (
            row["pv_enabled"]
            and not factor_rows
            and not row.get("capacity_factor_by_slot")
            and row.get("pv_generation_kwh_by_slot")
        ):
            try:
                direct_slot_minutes = max(int(row.get("pv_slot_minutes", row.get("pvSlotMinutes", 60)) or 60), 1)
            except (TypeError, ValueError):
                direct_slot_minutes = 60
            direct_duration_h = direct_slot_minutes / 60.0
            row["legacy_pv_capacity_kw"] = legacy_capacity_kw
            row["capacity_factor_by_slot"] = _capacity_factor_from_generation_series(
                list(row.get("pv_generation_kwh_by_slot") or []),
                legacy_capacity_kw=legacy_capacity_kw,
                slot_minutes=direct_slot_minutes,
            )
            row["pv_generation_kwh_by_slot"] = [
                round(float(row["pv_capacity_kw"]) * factor * direct_duration_h, 6)
                for factor in row["capacity_factor_by_slot"]
            ]
        if row["pv_enabled"] and factor_rows:
            combined, generation_rows = _compose_generation_from_capacity_factor_rows(
                float(row["pv_capacity_kw"]),
                factor_rows,
            )
            row["pv_generation_kwh_by_slot"] = combined
            row["pv_generation_kwh_by_date"] = generation_rows
        elif not row["pv_enabled"]:
            row["pv_generation_kwh_by_slot"] = []
            row["pv_generation_kwh_by_date"] = []
        prepared_rows.append(row)
    return prepared_rows


def _build_canonical_input(
    *,
    scenario: dict,
    prepared_input_id: str,
    scenario_id: str,
    dataset_version: str,
    scenario_hash: str,
    scope,
    trips_df: pd.DataFrame,
    timetables_df: pd.DataFrame,
    stops: list[dict[str, Any]],
) -> dict[str, Any]:
    scenario_overlay = dict(
        _scenario_value(scenario, "scenario_overlay", "scenarioOverlay", default={}) or {}
    )
    dispatch_scope = dict(
        _scenario_value(scenario, "dispatch_scope", "dispatchScope", default={}) or {}
    )
    simulation_config = dict(_scenario_value(scenario, "simulation_config", "simulationConfig", default={}) or {})
    service_dates = list(simulation_config.get("service_dates") or [])
    planning_days = max(int(simulation_config.get("planning_days") or 1), 1)
    dataset_id = _dataset_id(scenario)
    random_seed = _random_seed(scenario)
    vehicles = [dict(item) for item in list(scenario.get("vehicles") or [])]
    chargers = [dict(item) for item in list(scenario.get("chargers") or [])]
    solver_mode_requested = str(
        simulation_config.get("solver_mode")
        or (scenario_overlay.get("solver_config") or {}).get("mode")
        or "mode_milp_only"
    ).strip() or "mode_milp_only"
    solver_mode_effective = _normalize_solver_mode(solver_mode_requested)
    prepare_profile = solver_prepare_profile(solver_mode_effective)
    depots = _select_items_by_ids(
        [dict(item) for item in list(scenario.get("depots") or [])],
        list(scope.depot_ids),
    )
    simulation_config["depot_energy_assets"] = _prepare_depot_energy_assets(
        simulation_config,
        depots,
    )
    routes = _select_items_by_ids(
        [dict(item) for item in list(scenario.get("routes") or [])],
        list(scope.route_ids),
    )
    trip_records = _as_records(trips_df)
    stop_time_records = _as_records(timetables_df)
    route_index = {
        str(route.get("id") or ""): idx
        for idx, route in enumerate(routes)
        if route.get("id") is not None
    }
    trip_index = {
        str(item.get("trip_id") or ""): idx
        for idx, item in enumerate(trip_records)
        if item.get("trip_id") is not None
    }
    depot_index = {
        str(depot.get("id") or depot.get("depotId") or ""): idx
        for idx, depot in enumerate(depots)
        if depot.get("id") is not None or depot.get("depotId") is not None
    }
    vehicle_index = {
        str(vehicle.get("id") or ""): idx
        for idx, vehicle in enumerate(vehicles)
        if vehicle.get("id") is not None
    }
    charger_index = {
        str(charger.get("id") or charger.get("charger_id") or ""): idx
        for idx, charger in enumerate(chargers)
        if charger.get("id") is not None or charger.get("charger_id") is not None
    }
    scope_payload = {
        "depot_ids": list(scope.depot_ids),
        "route_ids": list(scope.route_ids),
        "service_ids": list(scope.service_ids),
        "service_date": scope.service_date,
        "service_dates": service_dates,
        "planning_days": planning_days,
        "primary_depot_id": scope.depot_ids[0] if scope.depot_ids else None,
    }
    scope_hash = _scope_hash(scope_payload)

    return {
        "prepared_input_id": prepared_input_id,
        "scenario_id": scenario_id,
        "dataset_id": dataset_id,
        "dataset_version": dataset_version,
        "random_seed": random_seed,
        "scenario_hash": scenario_hash,
        "scope_hash": scope_hash,
        "prepared_at": time.time(),
        "solver_mode_requested": solver_mode_requested,
        "solver_mode_effective": solver_mode_effective,
        "prepare_profile": prepare_profile,
        "depot_ids": list(scope.depot_ids),
        "route_ids": list(scope.route_ids),
        "service_ids": list(scope.service_ids),
        "service_date": scope.service_date,
        "service_dates": service_dates,
        "planning_days": planning_days,
        "primary_depot_id": scope.depot_ids[0] if scope.depot_ids else None,
        "trip_count": len(trip_records),
        "timetable_row_count": len(stop_time_records),
        "scope": scope_payload,
        "counts": {
            "depot_count": len(scope.depot_ids),
            "route_count": len(scope.route_ids),
            "trip_count": len(trips_df),
            "timetable_row_count": len(timetables_df),
            "stop_count": len(stops),
            "vehicle_count": len(vehicles),
            "charger_count": len(chargers),
        },
        "dispatch_scope": dispatch_scope,
        "scenario_overlay": scenario_overlay,
        "simulation_config": simulation_config,
        "depots": depots,
        "routes": routes,
        "vehicles": vehicles,
        "chargers": chargers,
        "trips": trip_records,
        "stop_time_sequences": stop_time_records,
        "stops": stops,
        "solver_ready_ids": {
            "depot_index": depot_index,
            "route_index": route_index,
            "trip_index": trip_index,
            "vehicle_index": vehicle_index,
            "charger_index": charger_index,
        },
    }


def _distance_audit(
    rows: list[dict[str, Any]],
    *,
    keys: tuple[str, ...] = ("distance_km", "distanceKm", "distance"),
) -> dict[str, Any]:
    total_count = len(rows)
    zero_or_missing_count = 0
    missing_count = 0
    for row in rows:
        raw_value: Any = None
        for key in keys:
            if key in row and row.get(key) is not None:
                raw_value = row.get(key)
                break
        if raw_value is None:
            missing_count += 1
            zero_or_missing_count += 1
            continue
        try:
            numeric_value = float(raw_value)
        except (TypeError, ValueError):
            missing_count += 1
            zero_or_missing_count += 1
            continue
        if numeric_value <= 0.0:
            zero_or_missing_count += 1
    return {
        "total_count": total_count,
        "zero_or_missing_count": zero_or_missing_count,
        "missing_count": missing_count,
        "zero_or_missing_ratio": (
            float(zero_or_missing_count) / float(total_count) if total_count > 0 else 0.0
        ),
    }


def _prepared_scope_audit_warnings(audit: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    trip_distance = dict(audit.get("trip_distance_audit") or {})
    route_distance = dict(audit.get("route_distance_audit") or {})
    strict_precheck = dict(audit.get("strict_coverage_precheck") or {})

    trip_zero_or_missing = int(trip_distance.get("zero_or_missing_count") or 0)
    trip_total = int(trip_distance.get("total_count") or 0)
    if trip_total > 0 and trip_zero_or_missing > 0:
        warnings.append(
            "Prepared scope audit: "
            f"{trip_zero_or_missing}/{trip_total} trips have zero or missing distance_km. "
            "This does not explain strict coverage infeasibility by itself, but it invalidates energy/cost interpretation."
        )

    route_zero_or_missing = int(route_distance.get("zero_or_missing_count") or 0)
    route_total = int(route_distance.get("total_count") or 0)
    if route_total > 0 and route_zero_or_missing > 0:
        warnings.append(
            "Prepared scope audit: "
            f"{route_zero_or_missing}/{route_total} scoped routes have zero or missing route distance."
        )

    diagnostic_message = str(strict_precheck.get("diagnostic_message") or "").strip()
    if diagnostic_message:
        warnings.append(f"Prepared scope audit: {diagnostic_message}")

    blocked_reason_counts = dict(strict_precheck.get("blocked_transition_reason_counts") or {})
    dominant_reason = str(strict_precheck.get("dominant_blocked_transition_reason") or "").strip()
    dominant_count = int(blocked_reason_counts.get(dominant_reason) or 0)
    interval_pair_count = int(strict_precheck.get("interval_feasible_pair_count") or 0)
    if dominant_reason and dominant_count > 0:
        warnings.append(
            "Prepared scope audit: blocked interval-feasible transitions are dominated by "
            f"`{dominant_reason}` ({dominant_count}/{interval_pair_count})."
        )
    return warnings


def _build_prepared_scope_audit(prepared_input: dict[str, Any]) -> dict[str, Any]:
    trip_rows = [
        dict(item)
        for item in list(prepared_input.get("trips") or [])
        if isinstance(item, dict)
    ]
    route_rows = [
        dict(item)
        for item in list(prepared_input.get("routes") or [])
        if isinstance(item, dict)
    ]
    audit: dict[str, Any] = {
        "trip_distance_audit": _distance_audit(trip_rows),
        "route_distance_audit": _distance_audit(route_rows),
        "strict_coverage_precheck": {},
        "warning_codes": [],
        "warnings": [],
    }
    try:
        from src.optimization.common.builder import ProblemBuilder
        from src.optimization.common.problem import OptimizationConfig, OptimizationMode
        from src.optimization.common.strict_precheck import evaluate_strict_coverage_precheck

        service_ids = list(prepared_input.get("service_ids") or [])
        primary_depot_id = str(prepared_input.get("primary_depot_id") or "").strip()
        planning_days = max(int(prepared_input.get("planning_days") or 1), 1)
        if primary_depot_id and service_ids:
            problem = ProblemBuilder().build_from_scenario(
                prepared_input,
                depot_id=primary_depot_id,
                service_id=str(service_ids[0]),
                config=OptimizationConfig(mode=OptimizationMode.MILP),
                planning_days=planning_days,
            )
            audit["strict_coverage_precheck"] = evaluate_strict_coverage_precheck(problem).to_metadata()
    except Exception as exc:
        audit["strict_coverage_precheck"] = {
            "checked": False,
            "infeasible": False,
            "reason": "prepared_scope_audit_failed",
            "diagnostic_message": f"prepared scope audit failed: {exc}",
        }
        audit["warning_codes"].append("prepared_scope_audit_failed")

    trip_zero_or_missing = int((audit.get("trip_distance_audit") or {}).get("zero_or_missing_count") or 0)
    if trip_zero_or_missing > 0:
        audit["warning_codes"].append("trip_distance_zero_or_missing")

    route_zero_or_missing = int((audit.get("route_distance_audit") or {}).get("zero_or_missing_count") or 0)
    if route_zero_or_missing > 0:
        audit["warning_codes"].append("route_distance_zero_or_missing")

    strict_precheck = dict(audit.get("strict_coverage_precheck") or {})
    if bool(strict_precheck.get("infeasible")):
        audit["warning_codes"].append("strict_coverage_precheck_infeasible")
    dominant_reason = str(strict_precheck.get("dominant_blocked_transition_reason") or "").strip()
    if dominant_reason == "deadhead_missing":
        audit["warning_codes"].append("deadhead_missing_dominates_relaxed_connectivity")

    audit["warning_codes"] = sorted(set(audit.get("warning_codes") or []))
    audit["warnings"] = _prepared_scope_audit_warnings(audit)
    return audit


def materialize_scenario_from_prepared_input(
    scenario: dict[str, Any],
    prepared_input: dict[str, Any],
) -> dict[str, Any]:
    hydrated = dict(scenario)
    meta = dict(hydrated.get("meta") or {})
    meta["selectedDepotIds"] = list(prepared_input.get("depot_ids") or [])
    meta["selectedRouteIds"] = list(prepared_input.get("route_ids") or [])
    meta["serviceIds"] = list(prepared_input.get("service_ids") or [])
    hydrated["meta"] = meta

    for key in ("scenario_overlay", "dispatch_scope", "simulation_config"):
        value = prepared_input.get(key)
        if isinstance(value, dict):
            hydrated[key] = dict(value)

    current_scope = dict(scenario.get("dispatch_scope") or {})
    hydrated_scope = dict(hydrated.get("dispatch_scope") or {})
    for key in (
        "fixedRouteBandMode",
        "allowIntraDepotRouteSwap",
        "allowInterDepotSwap",
    ):
        if key in current_scope:
            hydrated_scope[key] = current_scope.get(key)
    hydrated["dispatch_scope"] = hydrated_scope

    current_simulation_cfg = dict(scenario.get("simulation_config") or {})
    hydrated_simulation_cfg = dict(hydrated.get("simulation_config") or {})
    for key in (
        "fixed_route_band_mode",
        "enable_vehicle_diagram_output",
        "output_vehicle_diagram",
        "objective_mode",
        "objective_preset",
        "deadhead_speed_kmh",
        "service_coverage_mode",
        "allow_partial_service",
        "unserved_penalty",
        "cost_component_flags",
        "disable_vehicle_acquisition_cost",
        "enable_vehicle_cost",
        "enable_driver_cost",
        "enable_other_cost",
    ):
        if key in current_simulation_cfg:
            hydrated_simulation_cfg[key] = current_simulation_cfg.get(key)
    hydrated["simulation_config"] = hydrated_simulation_cfg

    current_overlay = dict(scenario.get("scenario_overlay") or {})
    hydrated_overlay = dict(hydrated.get("scenario_overlay") or {})
    current_solver_cfg = dict(current_overlay.get("solver_config") or {})
    hydrated_solver_cfg = dict(hydrated_overlay.get("solver_config") or {})
    for key in (
        "fixed_route_band_mode",
        "enable_vehicle_diagram_output",
        "output_vehicle_diagram",
        "objective_mode",
        "objective_preset",
        "service_coverage_mode",
        "allow_partial_service",
        "unserved_penalty",
        "milp_max_successors_per_trip",
    ):
        if key in current_solver_cfg:
            hydrated_solver_cfg[key] = current_solver_cfg.get(key)
    if hydrated_solver_cfg:
        hydrated_overlay["solver_config"] = hydrated_solver_cfg
    for key in ("charging_constraints", "cost_coefficients"):
        value = current_overlay.get(key)
        if isinstance(value, dict):
            hydrated_overlay[key] = dict(value)
    hydrated["scenario_overlay"] = hydrated_overlay

    for key in ("depots", "routes", "vehicles", "chargers", "stops", "trips"):
        value = prepared_input.get(key)
        if isinstance(value, list):
            hydrated[key] = [
                dict(item)
                for item in value
                if isinstance(item, dict)
            ]

    stop_time_sequences = prepared_input.get("stop_time_sequences")
    if isinstance(stop_time_sequences, list):
        hydrated["stop_timetables"] = [
            dict(item)
            for item in stop_time_sequences
            if isinstance(item, dict)
        ]

    if isinstance(prepared_input.get("trips"), list):
        # Treat the prepared scoped trips as the canonical timetable rows for
        # optimization/simulation paths that previously depended on persisted
        # dispatch artifacts.
        hydrated["timetable_rows"] = [
            dict(item)
            for item in prepared_input.get("trips") or []
            if isinstance(item, dict)
        ]

    referenced_stop_ids: set[str] = set()
    for stop in hydrated.get("stops") or []:
        if not isinstance(stop, dict):
            continue
        stop_id = str(stop.get("id") or stop.get("stop_id") or stop.get("stopId") or "").strip()
        if stop_id:
            referenced_stop_ids.add(stop_id)
    for row in hydrated.get("timetable_rows") or []:
        if not isinstance(row, dict):
            continue
        for key in ("origin_stop_id", "destination_stop_id", "originStopId", "destinationStopId", "stop_id", "stopId"):
            stop_id = str(row.get(key) or "").strip()
            if stop_id:
                referenced_stop_ids.add(stop_id)
    for row in hydrated.get("stop_timetables") or []:
        if not isinstance(row, dict):
            continue
        for key in ("stop_id", "stopId"):
            stop_id = str(row.get(key) or "").strip()
            if stop_id:
                referenced_stop_ids.add(stop_id)

    if referenced_stop_ids:
        catalog_stops = _load_catalog_stops(hydrated, referenced_stop_ids)
        if catalog_stops:
            hydrated["stops"] = _merge_stop_records(
                list(hydrated.get("stops") or []),
                catalog_stops,
            )

    hydrated["prepared_input_id"] = str(prepared_input.get("prepared_input_id") or "")
    hydrated["prepared_scope_summary"] = dict(prepared_input.get("scope") or {})
    hydrated["prepared_scope_summary"]["scope_hash"] = str(prepared_input.get("scope_hash") or "")
    hydrated["prepare_profile"] = dict(prepared_input.get("prepare_profile") or {})
    hydrated["scope_hash"] = str(prepared_input.get("scope_hash") or "")
    return hydrated


def get_or_build_run_preparation(
    scenario: dict,
    built_dir: Path,
    scenarios_dir: Path,
    routes_df,
    *,
    force_rebuild: bool = False,
) -> RunPreparation:
    scenario_id = _scenario_id(scenario)
    dataset_version = _dataset_version(scenario)
    scenario_hash = _scenario_hash(scenario)
    cache_key = (scenario_id, dataset_version, scenario_hash)

    if cache_key in _prep_cache and not force_rebuild:
        cached = _prep_cache[cache_key]
        if cached.is_valid:
            log.debug("run_prep cache HIT: %s %s", scenario_id, scenario_hash)
            return cached
        log.debug("run_prep cache INVALID: %s", scenario_id)

    log.info("Building run preparation for scenario %s (hash=%s)", scenario_id, scenario_hash)
    prep = _build_run_preparation(scenario, built_dir, scenarios_dir, routes_df, scenario_hash)
    _prep_cache[cache_key] = prep
    return prep


def _build_run_preparation(
    scenario: dict,
    built_dir: Path,
    scenarios_dir: Path,
    routes_df,
    scenario_hash: str,
) -> RunPreparation:
    scenario_id = _scenario_id(scenario)
    dataset_version = _dataset_version(scenario)
    try:
        from src.runtime_scope import resolve_scope

        scope = resolve_scope(scenario, routes_df if routes_df is not None else pd.DataFrame())
        trips_df, timetables_df, load_source = _load_scope_frames(
            scenario,
            built_dir=built_dir,
            scope=scope,
        )
        stops = _load_optional_stops(
            built_dir,
            scenario,
            trips_df,
            timetables_df,
        )
        warnings: list[str] = []
        if not scope.depot_ids:
            warnings.append("No depot is selected in the current builder scope.")
        if not scope.route_ids:
            warnings.append("No routes are selected in the current builder scope.")
        if trips_df.empty:
            warnings.append("Scoped built dataset returned zero trips for the current selection.")
        if load_source == "tokyu_shard":
            warnings.append("Prepared input was assembled from Tokyu shard runtime artifacts.")
        route_catalog_audit = audit_route_catalog_consistency(scenario)
        warnings.extend(_route_catalog_audit_warnings(route_catalog_audit))

        prepared_input_id = _prepared_input_id(scenario_hash)
        simulation_config = dict(
            _scenario_value(scenario, "simulation_config", "simulationConfig", default={}) or {}
        )
        service_dates = list(simulation_config.get("service_dates") or [])
        planning_days = max(int(simulation_config.get("planning_days") or 1), 1)
        solver_input = normalize_for_python(_build_canonical_input(
            scenario=scenario,
            prepared_input_id=prepared_input_id,
            scenario_id=scenario_id,
            dataset_version=dataset_version,
            scenario_hash=scenario_hash,
            scope=scope,
            trips_df=trips_df,
            timetables_df=timetables_df,
            stops=stops,
        ))
        prepared_scope_audit = normalize_for_python(_build_prepared_scope_audit(solver_input))
        solver_input["prepared_scope_audit"] = prepared_scope_audit
        scope_payload = dict(solver_input.get("scope") or {})
        scope_payload["prepared_scope_audit"] = prepared_scope_audit
        solver_input["scope"] = scope_payload
        warnings.extend(list(prepared_scope_audit.get("warnings") or []))
        scenario_dir = _prepared_input_dir(scenarios_dir, scenario_id)
        scenario_dir.mkdir(parents=True, exist_ok=True)
        solver_input_path = scenario_dir / f"{prepared_input_id}.json"
        solver_input_path.write_text(
            json.dumps(solver_input, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return RunPreparation(
            scenario_id=scenario_id,
            dataset_version=dataset_version,
            scenario_hash=scenario_hash,
            scope_hash=str(solver_input.get("scope_hash") or ""),
            solver_input_path=solver_input_path,
            prepared_input_id=prepared_input_id,
            warnings=warnings,
            scope_summary={
                "depot_ids": scope.depot_ids,
                "route_ids": scope.route_ids,
                "service_ids": scope.service_ids,
                "service_date": scope.service_date,
                "service_dates": service_dates,
                "planning_days": planning_days,
                "prepared_input_id": prepared_input_id,
                "scenario_hash": scenario_hash,
                "scope_hash": str(solver_input.get("scope_hash") or ""),
                "primary_depot_id": scope.depot_ids[0] if scope.depot_ids else None,
                "trip_count": len(trips_df),
                "timetable_row_count": len(timetables_df),
                "load_source": load_source,
                "route_catalog_audit": route_catalog_audit,
                "prepared_scope_audit": prepared_scope_audit,
            },
        )
    except Exception as exc:
        log.error("run_preparation failed for %s: %s", scenario_id, exc)
        return RunPreparation(
            scenario_id=scenario_id,
            dataset_version=dataset_version,
            scenario_hash=scenario_hash,
            scope_hash=None,
            solver_input_path=None,
            scope_summary={},
            error=str(exc),
        )


def load_prepared_input(
    *,
    scenario_id: str,
    prepared_input_id: str,
    scenarios_dir: Path,
) -> dict[str, Any]:
    path = _prepared_input_dir(scenarios_dir, scenario_id) / f"{_validate_path_segment(prepared_input_id)}.json"
    if not path.exists():
        raise FileNotFoundError(str(path))
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def invalidate_scenario(scenario_id: str) -> None:
    keys = [key for key in _prep_cache if key[0] == scenario_id]
    for key in keys:
        del _prep_cache[key]
    if keys:
        log.info("Invalidated %s run_prep cache entries for %s", len(keys), scenario_id)
