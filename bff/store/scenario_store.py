"""
bff/store/scenario_store.py

JSON-file-backed scenario store.
One file per scenario: output/scenarios/{scenario_id}.json

Each file stores the complete scenario document:
{
    "meta":    { id, name, description, mode, createdAt, updatedAt, status },
    "depots":  [ Depot ... ],
    "vehicles": [ Vehicle ... ],
    "routes":  [ Route ... ],
    "stops":   [ Stop ... ],
    "depot_route_permissions":   [ {depotId, routeId, allowed} ... ],
    "vehicle_route_permissions": [ {vehicleId, routeId, allowed} ... ],
    "route_import_meta": { "seed": { ... } },
    "stop_import_meta": { "seed": { ... } },
    "timetable_import_meta": { "seed": { ... } },
    "stop_timetable_import_meta": { "seed": { ... } },
    "timetable_rows": [ TimetableRow ... ],   # service_id field included
    "stop_timetables": [ StopTimetable ... ],
    "calendar": [ ServiceCalendar ... ],      # WEEKDAY/SAT/SUN_HOL definitions
    "calendar_dates": [ CalendarDate ... ],   # exception overrides
    "dispatch_scope": {
        "scopeId": str | null,
        "operatorId": str | null,
        "datasetVersion": str | null,
        "depotSelection": {
            "mode": "include",
            "depotIds": [str, ...],
            "primaryDepotId": str | null,
        },
        "routeSelection": {
            "mode": "refine",
            "includeRouteIds": [str, ...],
            "excludeRouteIds": [str, ...],
        },
        "serviceSelection": { "serviceIds": [str, ...] },
        "tripSelection": {
            "includeShortTurn": bool,
            "includeDepotMoves": bool,
            "includeDeadhead": bool,
        },
        # legacy aliases kept for compatibility
        "depotId": str | null,
        "serviceId": str,
    },
    "simulation_config": { ... } | null,
    "trips":   [ Trip ... ] | null,
    "graph":   { ... } | null,
    "duties":  [ VehicleDuty ... ] | null,
    "simulation_result":  { ... } | null,
    "optimization_result": { ... } | null,
}
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, RLock
from typing import Any, Dict, List, Optional

from bff.services.service_ids import canonical_service_id
from bff.store import master_data_store, output_paths, scenario_meta_store, trip_store
from src.value_normalization import coerce_list

_STORE_DIR = output_paths.scenarios_root()
_APP_CONTEXT_PATH = output_paths.outputs_root() / "app_context.json"
_VALID_OPERATOR_IDS = {"tokyu", "toei"}
_MASTER_DATA_KEYS = (
    "depots",
    "vehicles",
    "vehicle_templates",
    "routes",
    "stops",
    "route_depot_assignments",
    "depot_route_permissions",
    "vehicle_route_permissions",
    "route_import_meta",
    "stop_import_meta",
    "timetable_import_meta",
    "stop_timetable_import_meta",
    "calendar",
    "calendar_dates",
    "dispatch_scope",
    "public_data",
    "feed_context",
    "scenario_overlay",
    "simulation_config",
    "deadhead_rules",
    "turnaround_rules",
    "charger_sites",
    "chargers",
    "pv_profiles",
    "energy_price_profiles",
    "experiment_case_type",
    "problemdata_build_audit",
    "optimization_audit",
    "simulation_audit",
    "source_snapshot",
    "runtime_features",
)
_ARTIFACT_REF_KEYS = {
    "timetable_rows": "timetableRows",
    "stop_timetables": "stopTimetables",
    "trips": "tripSet",
    "graph": "graph",
    "blocks": "blocks",
    "duties": "duties",
    "dispatch_plan": "dispatchPlan",
    "simulation_result": "simulationResult",
    "optimization_result": "optimizationResult",
}
_SQLITE_ROW_ARTIFACT_FIELDS = {"timetable_rows", "stop_timetables"}
_SQLITE_SCALAR_ARTIFACT_FIELDS = {"dispatch_plan", "simulation_result", "optimization_result"}
_SUMMARY_SCALAR_NAMES = {
    "timetable_rows": "timetable_summary",
    "trips": "trips_summary",
    "duties": "duties_summary",
}
_PARQUET_ROW_ARTIFACT_FIELDS = {"trips", "blocks", "duties"}
_UNLOADED_ARTIFACT_FIELDS_KEY = "__unloaded_artifact_fields__"
_SCENARIO_LOCKS: dict[str, RLock] = {}
_SCENARIO_LOCKS_GUARD = Lock()


def _scenario_lock(scenario_id: str) -> RLock:
    with _SCENARIO_LOCKS_GUARD:
        lock = _SCENARIO_LOCKS.get(scenario_id)
        if lock is None:
            lock = RLock()
            _SCENARIO_LOCKS[scenario_id] = lock
        return lock


def _release_scenario_lock(scenario_id: str) -> None:
    """Remove a scenario's lock entry to prevent unbounded memory growth."""
    with _SCENARIO_LOCKS_GUARD:
        _SCENARIO_LOCKS.pop(scenario_id, None)


def _default_dispatch_scope() -> Dict[str, Any]:
    return {
        "scopeId": None,
        "operatorId": None,
        "datasetVersion": None,
        "depotSelection": {
            "mode": "include",
            "depotIds": [],
            "primaryDepotId": None,
        },
        "routeSelection": {
            "mode": "refine",
            "includeRouteIds": [],
            "excludeRouteIds": [],
            "includeRouteFamilyCodes": [],
            "excludeRouteFamilyCodes": [],
        },
        "serviceSelection": {
            "serviceIds": ["WEEKDAY"],
        },
        "tripSelection": {
            "includeShortTurn": True,
            "includeDepotMoves": True,
            "includeDeadhead": True,
        },
        # Swap permissions control whether vehicles may serve trips from other
        # routes (intra-depot) or across depots (inter-depot).
        "allowIntraDepotRouteSwap": False,
        "allowInterDepotSwap": False,
        "fixedRouteBandMode": False,
        "depotId": None,
        "serviceId": "WEEKDAY",
    }


def _default_v1_2_fields() -> Dict[str, Any]:
    return {
        "deadhead_rules": [],
        "turnaround_rules": [],
        "charger_sites": [],
        "chargers": [],
        "pv_profiles": [],
        "energy_price_profiles": [],
        "experiment_case_type": None,
        "problemdata_build_audit": None,
        "optimization_audit": None,
        "simulation_audit": None,
        "source_snapshot": None,
        "feed_context": None,
        "runtime_features": None,
    }


def _default_public_data_state() -> Dict[str, Any]:
    return {
        "raw_snapshots": [],
        "normalized_snapshots": [],
        "diff_sessions": [],
        "sync_histories": [],
        "change_logs": [],
        "warnings": [],
    }


def _default_app_context() -> Dict[str, Any]:
    return {
        "contextKey": "local-default",
        "activeScenarioId": None,
        "selectedOperatorId": None,
        "lastOpenedPage": None,
        "updatedAt": _now_iso(),
    }


def _ensure_dir() -> None:
    _STORE_DIR.mkdir(parents=True, exist_ok=True)


def _quarantine_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.delete-me-{int(time.time() * 1000)}")


def _quarantine_tree(path: Path) -> bool:
    if not path.exists():
        return True
    try:
        quarantine = _quarantine_path(path)
        if quarantine.exists():
            _remove_tree_with_retries(quarantine, ignore_errors=True)
        _rename_with_retries(path, quarantine)
        return True
    except FileNotFoundError:
        return True
    except PermissionError:
        return False


def _remove_tree_with_retries(path: Path, *, ignore_errors: bool = False) -> None:
    if not path.exists():
        return
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            shutil.rmtree(path, ignore_errors=False)
            return
        except FileNotFoundError:
            return
        except PermissionError as exc:
            last_error = exc
            # Windows may keep SQLite staging files briefly after close.
            time.sleep(0.1 * (attempt + 1))
    if _quarantine_tree(path):
        return
    if ignore_errors:
        shutil.rmtree(path, ignore_errors=True)
        return
    if last_error is not None:
        raise last_error


def _unlink_with_retries(path: Path, *, missing_ok: bool = False) -> None:
    if missing_ok and not path.exists():
        return
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            path.unlink(missing_ok=missing_ok)
            return
        except FileNotFoundError:
            if missing_ok:
                return
            raise
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.1 * (attempt + 1))
    if missing_ok:
        try:
            path.unlink(missing_ok=True)
            return
        except Exception:
            return
    if last_error is not None:
        raise last_error


def _rename_with_retries(source: Path, target: Path) -> None:
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            source.rename(target)
            return
        except FileNotFoundError:
            raise
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.1 * (attempt + 1))
    if last_error is not None:
        raise last_error


def _sync_tree_non_atomic(source: Path, target: Path) -> None:
    """Best-effort directory sync used when atomic rename is blocked on Windows.

    This fallback prefers availability over strict atomicity and is used only
    after rename retries fail with PermissionError.
    """
    target.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        dst = target / child.name
        if child.is_dir():
            shutil.copytree(child, dst, dirs_exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(child, dst)


def _path(scenario_id: str) -> Path:
    return scenario_meta_store.scenario_path(_STORE_DIR, scenario_id)


def _master_data_path(scenario_id: str, meta: Optional[Dict[str, Any]] = None) -> Path:
    refs = _refs_for_scenario(scenario_id, meta)
    return Path(refs["masterData"])


def _timetable_path(scenario_id: str) -> Path:
    return scenario_meta_store.artifact_dir(_STORE_DIR, scenario_id) / "timetable_rows.json"


def _stop_timetables_path(scenario_id: str) -> Path:
    return scenario_meta_store.artifact_dir(_STORE_DIR, scenario_id) / "stop_timetables.json"


def _legacy_timetable_path(scenario_id: str) -> Path:
    return _STORE_DIR / f"{scenario_id}_timetable.json"


def _legacy_stop_timetables_path(scenario_id: str) -> Path:
    return _STORE_DIR / f"{scenario_id}_stop_timetables.json"


def _refs_for_scenario(scenario_id: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    refs = scenario_meta_store.default_refs(_STORE_DIR, scenario_id)
    if isinstance(payload, dict):
        candidate_refs = payload.get("refs") or {}
        safe_refs: Dict[str, str] = {}
        for key, value in candidate_refs.items():
            if not value:
                continue
            text = str(value)
            # Prevent stale refs from other scenarios (e.g., duplicated docs carrying old refs).
            try:
                if Path(text).parent.name != scenario_id:
                    continue
            except Exception:
                continue
            safe_refs[str(key)] = text
        refs.update(safe_refs)
    return refs


def _artifact_store_path(refs: Dict[str, str]) -> Path:
    return Path(refs["artifactStore"])


def _artifact_dir_for_scenario(scenario_id: str) -> Path:
    return scenario_meta_store.artifact_dir(_STORE_DIR, scenario_id)


def _complete_marker_path(scenario_id: str) -> Path:
    return _artifact_dir_for_scenario(scenario_id) / "_COMPLETE"


def _incomplete_marker_path(scenario_id: str) -> Path:
    return _artifact_dir_for_scenario(scenario_id) / "_INCOMPLETE"


def _is_auxiliary_path(path: Path) -> bool:
    name = path.name
    return name.endswith("_timetable.json") or name.endswith("_stop_timetables.json")


def _load_json_list(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    payload = trip_store.load_json(path, [])
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, dict)]


def _save_json_list(path: Path, items: List[Dict[str, Any]]) -> None:
    trip_store.save_json(path, items)


def _load_split_or_inline(path: Path, inline_value: Any) -> List[Dict[str, Any]]:
    if path.exists():
        return _load_json_list(path)
    return [dict(item) for item in list(inline_value or []) if isinstance(item, dict)]


def _artifact_default(key: str) -> Any:
    return [] if key in {"timetable_rows", "stop_timetables"} else None


def _artifact_fields_unloaded(doc: Dict[str, Any]) -> set[str]:
    return {
        str(field).strip()
        for field in list(doc.get(_UNLOADED_ARTIFACT_FIELDS_KEY) or [])
        if str(field).strip() in _ARTIFACT_REF_KEYS
    }


def _mark_artifact_fields_unloaded(
    doc: Dict[str, Any],
    fields: set[str],
) -> None:
    if fields:
        doc[_UNLOADED_ARTIFACT_FIELDS_KEY] = sorted(fields)
        return
    doc.pop(_UNLOADED_ARTIFACT_FIELDS_KEY, None)


def _graph_meta_name() -> str:
    return "graph_meta"


def _load_graph_artifact(artifact_db_path: Path, fallback_path: Path) -> Any:
    graph_meta = trip_store.load_scalar(artifact_db_path, _graph_meta_name(), None)
    if graph_meta is not None:
        graph = dict(graph_meta)
        graph["arcs"] = trip_store.load_graph_arcs(artifact_db_path)
        return graph
    if fallback_path.exists():
        return trip_store.load_json(fallback_path, None)
    return None


def _save_graph_artifact(artifact_db_path: Path, graph: Any) -> None:
    if graph is None:
        trip_store.save_scalar(artifact_db_path, _graph_meta_name(), None)
        trip_store.save_graph_arcs(artifact_db_path, [])
        return
    graph_dict = dict(graph)
    arcs = list(graph_dict.pop("arcs", []) or [])
    trip_store.save_scalar(artifact_db_path, _graph_meta_name(), graph_dict)
    trip_store.save_graph_arcs(artifact_db_path, arcs)


def _scenario_stats(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "routeCount": len(list(doc.get("routes") or [])),
        "stopCount": len(list(doc.get("stops") or [])),
        "timetableRowCount": len(list(doc.get("timetable_rows") or [])),
        "tripCount": len(list(doc.get("trips") or [])) if doc.get("trips") is not None else 0,
        "dutyCount": len(list(doc.get("duties") or [])) if doc.get("duties") is not None else 0,
    }


def _scenario_stats_for_save(
    doc: Dict[str, Any],
    *,
    fallback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    unloaded_fields = _artifact_fields_unloaded(doc)
    stats = dict(fallback or {})
    stats["routeCount"] = len(list(doc.get("routes") or []))
    stats["stopCount"] = len(list(doc.get("stops") or []))
    if "timetable_rows" not in unloaded_fields:
        stats["timetableRowCount"] = len(_drop_vn_duplicate_rows(list(doc.get("timetable_rows") or [])))
    else:
        stats.setdefault("timetableRowCount", 0)
    if "trips" not in unloaded_fields:
        stats["tripCount"] = len(list(doc.get("trips") or [])) if doc.get("trips") is not None else 0
    else:
        stats.setdefault("tripCount", 0)
    if "duties" not in unloaded_fields:
        stats["dutyCount"] = len(list(doc.get("duties") or [])) if doc.get("duties") is not None else 0
    else:
        stats.setdefault("dutyCount", 0)
    return stats


def _normalize_stats_payload(
    doc: Dict[str, Any],
    *,
    fallback: Optional[Dict[str, Any]] = None,
    dispatch_invalidated: bool = False,
) -> Dict[str, Any]:
    stats = dict(fallback or doc.get("stats") or {})
    if "routes" in doc:
        stats["routeCount"] = len(list(doc.get("routes") or []))
    else:
        stats.setdefault("routeCount", 0)
    if "stops" in doc:
        stats["stopCount"] = len(list(doc.get("stops") or []))
    else:
        stats.setdefault("stopCount", 0)
    stats.setdefault("timetableRowCount", 0)
    if dispatch_invalidated:
        stats["tripCount"] = 0
        stats["dutyCount"] = 0
    else:
        stats.setdefault("tripCount", 0)
        stats.setdefault("dutyCount", 0)
    return stats


def _clear_dispatch_artifacts(refs: Dict[str, str]) -> None:
    artifact_db_path = _artifact_store_path(refs)

    trip_store.save_scalar(artifact_db_path, _graph_meta_name(), None)
    trip_store.save_graph_arcs(artifact_db_path, [])

    for field in _PARQUET_ROW_ARTIFACT_FIELDS:
        trip_store.save_rows(artifact_db_path, field, [])
        summary_name = _SUMMARY_SCALAR_NAMES.get(field)
        if summary_name:
            trip_store.save_scalar(artifact_db_path, summary_name, None)

    for field in _SQLITE_SCALAR_ARTIFACT_FIELDS:
        trip_store.save_scalar(artifact_db_path, field, None)

    for field in ("graph", "trips", "blocks", "duties", "dispatch_plan", "simulation_result", "optimization_result"):
        artifact_path = Path(refs[_ARTIFACT_REF_KEYS[field]])
        if artifact_path.exists():
            _unlink_with_retries(artifact_path, missing_ok=True)


def _save_master_only(
    doc: Dict[str, Any],
    *,
    invalidate_dispatch: bool,
) -> None:
    _ensure_dir()
    scenario_id = str((doc.get("meta") or {}).get("id") or "")
    if not scenario_id:
        raise ValueError("scenario id is required for _save_master_only")

    with _scenario_lock(scenario_id):
        refs = _refs_for_scenario(scenario_id, doc)
        doc["refs"] = refs

        in_memory_artifacts = {
            field: doc.get(field)
            for field in _ARTIFACT_REF_KEYS
            if field in doc
        }

        master_payload = {key: doc.get(key) for key in _MASTER_DATA_KEYS}
        master_data_store.save_master_data(Path(refs["masterData"]), master_payload)

        if invalidate_dispatch:
            _clear_dispatch_artifacts(refs)

        existing_meta = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
        existing_stats = dict(existing_meta.get("stats") or {})
        stats = _normalize_stats_payload(
            doc,
            fallback=existing_stats,
            dispatch_invalidated=invalidate_dispatch,
        )

        slim_doc = {
            "scenarioId": scenario_id,
            "name": doc.get("meta", {}).get("name"),
            "meta": {
                **dict(doc.get("meta") or {}),
                **_scope_summary(doc.get("dispatch_scope")),
            },
            "feed_context": doc.get("feed_context"),
            "refs": refs,
            "stats": stats,
        }
        scenario_meta_store.save_meta(_STORE_DIR, scenario_id, slim_doc)
        doc["stats"] = stats
        for field, value in in_memory_artifacts.items():
            doc[field] = value


def _save_master_subset(
    scenario_id: str,
    *,
    updates: Dict[str, Any],
    invalidate_dispatch: bool,
) -> None:
    if not updates:
        return

    _ensure_dir()
    with _scenario_lock(scenario_id):
        meta_doc = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
        refs = _refs_for_scenario(scenario_id, meta_doc)
        master_db_path = Path(refs["masterData"])

        master_data_store.save_master_collections(master_db_path, updates)

        if invalidate_dispatch:
            _clear_dispatch_artifacts(refs)

        now = _now_iso()
        meta_payload = dict(meta_doc.get("meta") or {})
        meta_payload["updatedAt"] = now

        scope_source = updates.get("dispatch_scope")
        if not isinstance(scope_source, dict):
            scope_source = _load_shallow(scenario_id).get("dispatch_scope") or {}

        merged_doc = {
            "meta": meta_payload,
            "dispatch_scope": scope_source,
            **updates,
        }
        existing_stats = dict(meta_doc.get("stats") or {})
        stats = _normalize_stats_payload(
            merged_doc,
            fallback=existing_stats,
            dispatch_invalidated=invalidate_dispatch,
        )

        slim_doc = {
            "scenarioId": scenario_id,
            "name": meta_doc.get("name") or meta_payload.get("name"),
            "meta": {
                **meta_payload,
                **_scope_summary(updates.get("dispatch_scope")),
            },
            "feed_context": meta_doc.get("feed_context"),
            "refs": refs,
            "stats": stats,
        }
        if "feed_context" in updates:
            slim_doc["feed_context"] = updates.get("feed_context")

        scenario_meta_store.save_meta(_STORE_DIR, scenario_id, slim_doc)

        return


def _scope_summary(scope: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    normalized = scope if isinstance(scope, dict) else _default_dispatch_scope()
    depot_selection = dict(normalized.get("depotSelection") or {})
    route_selection = dict(normalized.get("routeSelection") or {})
    service_selection = dict(normalized.get("serviceSelection") or {})
    return {
        "selectedDepotIds": list(depot_selection.get("depotIds") or []),
        "selectedRouteIds": list(route_selection.get("includeRouteIds") or []),
        "serviceIds": list(service_selection.get("serviceIds") or []),
    }


def _updated_at_from_imports(imports: Dict[str, Any]) -> Optional[str]:
    timestamps = [
        str(item.get("generatedAt") or "")
        for item in dict(imports or {}).values()
        if isinstance(item, dict) and item.get("generatedAt")
    ]
    if not timestamps:
        return None
    return max(timestamps)


_VN_TRIP_PATTERN = re.compile(r"__v\d+$")


def _drop_vn_duplicate_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove GTFS-reconciliation duplicate rows whose trip_id ends with __vN."""
    return [
        row for row in rows
        if not _VN_TRIP_PATTERN.search(str(row.get("trip_id") or ""))
    ]


def _build_timetable_summary_artifact(rows: List[Dict[str, Any]], imports: Dict[str, Any]) -> Dict[str, Any]:
    # Exclude __vN GTFS reconciliation duplicates before counting
    rows = _drop_vn_duplicate_rows(rows)
    total_distance_km = 0.0
    first_departure: Optional[str] = None
    last_arrival: Optional[str] = None
    by_service: Dict[str, Dict[str, Any]] = {}
    by_route: Dict[str, int] = {}
    for row in rows:
        service_id = str(row.get("service_id") or "WEEKDAY")
        route_id = str(row.get("route_id") or "")
        departure = row.get("departure")
        arrival = row.get("arrival")
        total_distance_km += float(row.get("distance_km") or 0.0)
        if isinstance(departure, str) and departure:
            first_departure = departure if first_departure is None or departure < first_departure else first_departure
        if isinstance(arrival, str) and arrival:
            last_arrival = arrival if last_arrival is None or arrival > last_arrival else last_arrival
        if route_id:
            by_route[route_id] = by_route.get(route_id, 0) + 1
        bucket = by_service.setdefault(
            service_id,
            {
                "serviceId": service_id,
                "rowCount": 0,
                "routeIds": set(),
                "firstDeparture": None,
                "lastArrival": None,
            },
        )
        bucket["rowCount"] += 1
        if route_id:
            bucket["routeIds"].add(route_id)
        if isinstance(departure, str) and departure:
            bucket["firstDeparture"] = departure if bucket["firstDeparture"] is None or departure < bucket["firstDeparture"] else bucket["firstDeparture"]
        if isinstance(arrival, str) and arrival:
            bucket["lastArrival"] = arrival if bucket["lastArrival"] is None or arrival > bucket["lastArrival"] else bucket["lastArrival"]
    return {
        "totalRows": len(rows),
        "routeCount": len(by_route),
        "totalDistanceKm": round(total_distance_km, 3),
        "firstDeparture": first_departure,
        "lastArrival": last_arrival,
        "updatedAt": _updated_at_from_imports(imports),
        "byService": [
            {
                "serviceId": item["serviceId"],
                "rowCount": item["rowCount"],
                "routeCount": len(item["routeIds"]),
                "firstDeparture": item["firstDeparture"],
                "lastArrival": item["lastArrival"],
            }
            for item in sorted(by_service.values(), key=lambda value: value["serviceId"])
        ],
        "imports": imports,
    }


def _build_trips_summary_artifact(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    route_counts: Dict[str, int] = {}
    earliest_departure: Optional[str] = None
    latest_arrival: Optional[str] = None
    for item in items:
        route_id = str(item.get("route_id") or "")
        if route_id:
            route_counts[route_id] = route_counts.get(route_id, 0) + 1
        departure = item.get("departure")
        arrival = item.get("arrival")
        if isinstance(departure, str) and departure:
            earliest_departure = departure if earliest_departure is None or departure < earliest_departure else earliest_departure
        if isinstance(arrival, str) and arrival:
            latest_arrival = arrival if latest_arrival is None or arrival > latest_arrival else latest_arrival
    return {
        "totalTrips": len(items),
        "routeCount": len(route_counts),
        "firstDeparture": earliest_departure,
        "lastArrival": latest_arrival,
        "byRoute": [
            {"route_id": route_id, "trip_count": count}
            for route_id, count in sorted(route_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:50]
        ],
    }


def _build_duties_summary_artifact(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    vehicle_type_counts: Dict[str, int] = {}
    total_legs = 0
    total_distance_km = 0.0
    for item in items:
        vehicle_type = str(item.get("vehicle_type") or "unknown")
        vehicle_type_counts[vehicle_type] = vehicle_type_counts.get(vehicle_type, 0) + 1
        total_legs += len(item.get("legs") or [])
        total_distance_km += float(item.get("total_distance_km") or 0.0)
    return {
        "totalDuties": len(items),
        "totalLegs": total_legs,
        "averageLegsPerDuty": round(total_legs / len(items), 2) if items else 0.0,
        "totalDistanceKm": round(total_distance_km, 3),
        "vehicleTypeCounts": vehicle_type_counts,
    }


def _master_repair_dataset_id(doc: Dict[str, Any]) -> Optional[str]:
    overlay = doc.get("scenario_overlay") or {}
    feed_context = doc.get("feed_context") or {}
    for value in (
        overlay.get("dataset_id"),
        overlay.get("datasetId"),
        feed_context.get("datasetId"),
        feed_context.get("dataset_id"),
    ):
        normalized = str(value or "").strip()
        if normalized:
            return normalized
    return None


def _scenario_route_ids(doc: Dict[str, Any]) -> List[str]:
    return [
        str(route.get("id") or "").strip()
        for route in doc.get("routes") or []
        if str(route.get("id") or "").strip()
    ]


def _tokyu_bus_timetable_summary_for_doc(
    doc: Dict[str, Any],
    *,
    service_ids: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    dataset_id = _master_repair_dataset_id(doc)
    route_ids = _scenario_route_ids(doc)
    if not dataset_id or not route_ids:
        return None
    from src.tokyu_bus_data import build_timetable_summary_for_scope, tokyu_bus_data_ready

    if not tokyu_bus_data_ready(dataset_id):
        return None
    summary = build_timetable_summary_for_scope(
        dataset_id=dataset_id,
        route_ids=route_ids,
        depot_ids=None,
        service_ids=service_ids,
    )
    return dict(summary) if isinstance(summary, dict) else None


def _tokyu_bus_timetable_rows_for_doc(
    doc: Dict[str, Any],
    *,
    service_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    dataset_id = _master_repair_dataset_id(doc)
    route_ids = _scenario_route_ids(doc)
    if not dataset_id or not route_ids:
        return []
    from src.tokyu_bus_data import load_trip_rows_for_scope, tokyu_bus_data_ready

    if not tokyu_bus_data_ready(dataset_id):
        return []
    return [
        dict(item)
        for item in load_trip_rows_for_scope(
            dataset_id=dataset_id,
            route_ids=route_ids,
            depot_ids=None,
            service_ids=service_ids,
        )
    ]


def _tokyu_bus_route_service_count_rows_for_doc(
    doc: Dict[str, Any],
) -> List[Dict[str, Any]]:
    dataset_id = _master_repair_dataset_id(doc)
    route_ids = _scenario_route_ids(doc)
    if not dataset_id or not route_ids:
        return []
    from src.tokyu_bus_data import route_trip_counts_by_day_type, tokyu_bus_data_ready

    if not tokyu_bus_data_ready(dataset_id):
        return []
    counts_by_route = route_trip_counts_by_day_type(
        dataset_id=dataset_id,
        route_ids=route_ids,
        depot_ids=None,
    )
    rows: List[Dict[str, Any]] = []
    for route_id, counts in sorted(counts_by_route.items()):
        for service_id, trip_count in sorted(dict(counts or {}).items()):
            normalized_trip_count = int(trip_count or 0)
            if normalized_trip_count <= 0:
                continue
            rows.append(
                {
                    "route_id": str(route_id or "").strip(),
                    "service_id": str(service_id or "WEEKDAY"),
                    "trip_count": normalized_trip_count,
                }
            )
    return rows


def _repair_route_metadata_from_preload(doc: Dict[str, Any]) -> bool:
    dataset_id = _master_repair_dataset_id(doc)
    current_routes = [dict(route) for route in doc.get("routes") or [] if isinstance(route, dict)]
    if not dataset_id or not current_routes:
        return False

    from bff.services import master_defaults
    from bff.services.runtime_route_family import reclassify_routes_for_runtime

    payload = master_defaults.get_preloaded_master_data(dataset_id)
    fresh_routes = [dict(route) for route in payload.get("routes") or [] if isinstance(route, dict)]
    fresh_by_id = {
        str(route.get("id") or "").strip(): route
        for route in fresh_routes
        if str(route.get("id") or "").strip()
    }
    if not fresh_by_id:
        return False

    preserve_keys = {
        "enabled",
        "color",
        "routeVariantTypeManual",
        "canonicalDirectionManual",
        "classificationSource",
        "manualClassificationLocked",
        "classificationEditedByUser",
        "manualOverrideSource",
    }
    changed = False
    repaired_routes: List[Dict[str, Any]] = []
    for current_route in current_routes:
        route_id = str(current_route.get("id") or "").strip()
        fresh_route = fresh_by_id.get(route_id)
        if not route_id or fresh_route is None:
            repaired_routes.append(dict(current_route))
            continue
        merged_route = {**dict(current_route), **dict(fresh_route)}
        for key in preserve_keys:
            if key in current_route and current_route.get(key) is not None:
                merged_route[key] = current_route.get(key)
        if merged_route != current_route:
            changed = True
        repaired_routes.append(merged_route)

    repaired_routes = reclassify_routes_for_runtime(repaired_routes)
    if repaired_routes != current_routes:
        changed = True
    if changed:
        doc["routes"] = repaired_routes
    return changed


def _repair_missing_master_defaults(
    doc: Dict[str, Any],
    *,
    touch_updated_at: bool = False,
) -> bool:
    dataset_id = _master_repair_dataset_id(doc)
    if not dataset_id:
        return False
    from bff.services import master_defaults

    repaired = master_defaults.repair_missing_master_data(doc, dataset_id=dataset_id)
    if repaired and touch_updated_at:
        _normalize_dispatch_scope(doc)
        doc["meta"]["updatedAt"] = _now_iso()
    return repaired


def _needs_master_repair(doc: Dict[str, Any]) -> bool:
    return not all(
        bool(doc.get(key))
        for key in (
            "depots",
            "routes",
            "vehicle_templates",
            "route_depot_assignments",
        )
    )


def _needs_runtime_master_alignment(doc: Dict[str, Any]) -> bool:
    dataset_id = _master_repair_dataset_id(doc)
    if not dataset_id:
        return False
    from bff.services import master_defaults

    payload = master_defaults.get_preloaded_master_data(dataset_id)
    effective_dataset_id = str(payload.get("datasetId") or "").strip()
    if effective_dataset_id and effective_dataset_id != dataset_id:
        return True

    current_route_ids = {
        str(item.get("id") or "").strip()
        for item in doc.get("routes") or []
        if str(item.get("id") or "").strip()
    }
    runtime_route_ids = {
        str(item.get("id") or "").strip()
        for item in payload.get("routes") or []
        if str(item.get("id") or "").strip()
    }
    runtime_depot_ids = {
        str(item.get("id") or item.get("depotId") or "").strip()
        for item in payload.get("depots") or []
        if str(item.get("id") or item.get("depotId") or "").strip()
    }
    current_depot_ids = {
        str(item.get("id") or item.get("depotId") or "").strip()
        for item in doc.get("depots") or []
        if str(item.get("id") or item.get("depotId") or "").strip()
    }
    if current_route_ids and runtime_route_ids and not current_route_ids.intersection(runtime_route_ids):
        return True
    if (
        current_route_ids
        and runtime_route_ids
        and current_route_ids.issubset(runtime_route_ids)
        and len(current_route_ids) < len(runtime_route_ids)
    ):
        return True
    if (
        current_depot_ids
        and runtime_depot_ids
        and current_depot_ids.issubset(runtime_depot_ids)
        and len(current_depot_ids) < len(runtime_depot_ids)
    ):
        return True
    return False


# Fields that are heavy and should NOT be loaded for lightweight operations
# like editor-bootstrap.  These are populated on-demand by specific endpoints.
_HEAVY_ARTIFACT_FIELDS = frozenset({
    "timetable_rows",
    "stop_timetables",
    "trips",
    "graph",
    "blocks",
    "duties",
    "dispatch_plan",
    "simulation_result",
    "optimization_result",
})


def _load_shallow(
    scenario_id: str,
    *,
    repair_route_metadata: bool = True,
) -> Dict[str, Any]:
    """Load only meta + master data (depots, vehicles, routes, etc.).

    Does NOT load any heavy artifacts (timetable_rows, trips, graph, …).
    Use this for editor-bootstrap and other lightweight reads.
    """
    if _incomplete_marker_path(scenario_id).exists() and not _complete_marker_path(scenario_id).exists():
        raise RuntimeError(
            f"Scenario '{scenario_id}' artifacts are incomplete. The previous save may have been interrupted."
        )
    doc = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
    refs = _refs_for_scenario(scenario_id, doc)
    doc["refs"] = refs

    has_inline_master = any(
        key in doc
        for key in (
            "depots",
            "vehicles",
            "routes",
            "stops",
            "dispatch_scope",
            "public_data",
            "calendar",
        )
    )
    if not has_inline_master:
        master_payload = master_data_store.load_master_data(Path(refs["masterData"]))
        doc.update(master_payload)

    doc.setdefault("meta", {})
    doc["meta"].setdefault("operatorId", "tokyu")
    doc.setdefault("depots", [])
    doc.setdefault("vehicles", [])
    doc.setdefault("vehicle_templates", [])
    doc.setdefault("routes", [])
    doc.setdefault("route_depot_assignments", [])
    doc.setdefault("depot_route_permissions", [])
    doc.setdefault("vehicle_route_permissions", [])
    doc.setdefault("route_import_meta", {})
    doc.setdefault("stop_import_meta", {})
    doc.setdefault("timetable_import_meta", {})
    doc.setdefault("stop_timetable_import_meta", {})
    doc.setdefault("stops", [])

    # Heavy artifacts are left empty — callers must use get_field() to load them.
    for field in _HEAVY_ARTIFACT_FIELDS:
        doc.setdefault(field, _artifact_default(field))
    _mark_artifact_fields_unloaded(doc, set(_HEAVY_ARTIFACT_FIELDS))

    doc.setdefault("calendar", _default_calendar())
    doc.setdefault("calendar_dates", [])
    doc.setdefault("simulation_config", None)
    doc.setdefault("scenario_overlay", None)
    doc.setdefault("dispatch_scope", _default_dispatch_scope())
    doc.setdefault("public_data", _default_public_data_state())
    if _needs_master_repair(doc):
        _repair_missing_master_defaults(doc)
    if repair_route_metadata:
        _repair_route_metadata_from_preload(doc)
    doc.setdefault("stats", _scenario_stats(doc))
    for key, value in _default_v1_2_fields().items():
        doc.setdefault(key, value)
    return doc


def _load(
    scenario_id: str,
    *,
    repair_missing_master: bool = True,
    skip_graph_arcs: bool = False,
    repair_route_metadata: bool = True,
) -> Dict[str, Any]:
    if _incomplete_marker_path(scenario_id).exists() and not _complete_marker_path(scenario_id).exists():
        raise RuntimeError(
            f"Scenario '{scenario_id}' artifacts are incomplete. The previous save may have been interrupted."
        )
    doc = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
    refs = _refs_for_scenario(scenario_id, doc)
    if "refs" not in doc:
        doc["refs"] = refs
    else:
        doc["refs"] = refs

    has_inline_master = any(
        key in doc
        for key in (
            "depots",
            "vehicles",
            "routes",
            "stops",
            "dispatch_scope",
            "public_data",
            "calendar",
        )
    )
    if not has_inline_master:
        master_payload = master_data_store.load_master_data(Path(refs["masterData"]))
        doc.update(master_payload)

    doc.setdefault("meta", {})
    doc["meta"].setdefault("operatorId", "tokyu")
    doc.setdefault("depots", [])
    doc.setdefault("vehicles", [])
    doc.setdefault("vehicle_templates", [])
    doc.setdefault("routes", [])
    doc.setdefault("route_depot_assignments", [])
    doc.setdefault("depot_route_permissions", [])
    doc.setdefault("vehicle_route_permissions", [])
    doc.setdefault("route_import_meta", {})
    doc.setdefault("stop_import_meta", {})
    doc.setdefault("timetable_import_meta", {})
    doc.setdefault("stop_timetable_import_meta", {})
    doc.setdefault("stops", [])

    for field, ref_key in _ARTIFACT_REF_KEYS.items():
        artifact_path = Path(refs[ref_key])
        artifact_db_path = _artifact_store_path(refs)
        if field == "graph":
            if skip_graph_arcs:
                # Load only graph metadata (arc counts), not the full arc list.
                # Callers that need arcs must call get_field(scenario_id, "graph").
                graph_meta = trip_store.load_scalar(artifact_db_path, _graph_meta_name(), None)
                if graph_meta is not None:
                    doc[field] = dict(graph_meta)
                    doc[field]["arcs"] = []  # placeholder — not loaded
                else:
                    doc[field] = None
            else:
                graph_value = _load_graph_artifact(artifact_db_path, artifact_path)
                doc[field] = graph_value
            continue
        if field == "timetable_rows":
            if trip_store.count_timetable_rows(artifact_db_path) > 0:
                # page_timetable_rows already excludes __vN GTFS duplicates
                doc[field] = trip_store.page_timetable_rows(artifact_db_path, offset=0, limit=None)
            elif trip_store.count_rows(artifact_db_path, field) > 0:
                # row_artifacts fallback: filter __vN duplicates manually
                doc[field] = _drop_vn_duplicate_rows(trip_store.load_rows(artifact_db_path, field))
            elif artifact_path.exists():
                doc[field] = _drop_vn_duplicate_rows(_load_json_list(artifact_path))
            elif _legacy_timetable_path(scenario_id).exists():
                doc[field] = _drop_vn_duplicate_rows(_load_json_list(_legacy_timetable_path(scenario_id)))
            else:
                doc[field] = _load_split_or_inline(artifact_path, doc.get(field))
            continue
        if field in _PARQUET_ROW_ARTIFACT_FIELDS:
            if artifact_path.exists():
                doc[field] = trip_store.load_parquet_rows(artifact_path)
            elif trip_store.count_rows(artifact_db_path, field) > 0:
                doc[field] = trip_store.load_rows(artifact_db_path, field)
            else:
                doc.setdefault(field, _artifact_default(field))
            continue
        if field == "stop_timetables":
            if trip_store.count_rows(artifact_db_path, field) > 0:
                doc[field] = trip_store.load_rows(artifact_db_path, field)
            elif artifact_path.exists():
                doc[field] = _load_json_list(artifact_path)
            elif _legacy_stop_timetables_path(scenario_id).exists():
                doc[field] = _load_json_list(_legacy_stop_timetables_path(scenario_id))
            else:
                doc[field] = _load_split_or_inline(artifact_path, doc.get(field))
            continue
        if field in _SQLITE_ROW_ARTIFACT_FIELDS and trip_store.count_rows(artifact_db_path, field) > 0:
            doc[field] = trip_store.load_rows(artifact_db_path, field)
        elif field in _SQLITE_SCALAR_ARTIFACT_FIELDS and artifact_db_path.exists():
            doc[field] = trip_store.load_scalar(artifact_db_path, field, _artifact_default(field))
        elif artifact_path.exists():
            doc[field] = trip_store.load_json(artifact_path, _artifact_default(field))
        else:
            doc.setdefault(field, _artifact_default(field))

    _mark_artifact_fields_unloaded(doc, set())
    doc.setdefault("calendar", _default_calendar())
    doc.setdefault("calendar_dates", [])
    doc.setdefault("simulation_config", None)
    doc.setdefault("scenario_overlay", None)
    doc.setdefault("dispatch_scope", _default_dispatch_scope())
    doc.setdefault("public_data", _default_public_data_state())
    if repair_missing_master and _needs_master_repair(doc):
        _repair_missing_master_defaults(doc)
    if repair_route_metadata:
        _repair_route_metadata_from_preload(doc)
    doc.setdefault("stats", _scenario_stats(doc))
    for key, value in _default_v1_2_fields().items():
        doc.setdefault(key, value)
    return doc


def _save(doc: Dict[str, Any]) -> None:
    _ensure_dir()
    scenario_id = doc["meta"]["id"]
    with _scenario_lock(scenario_id):
        refs = _refs_for_scenario(scenario_id, doc)
        try:
            existing_meta = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
        except KeyError:
            existing_meta = {}
        existing_refs = _refs_for_scenario(scenario_id, existing_meta)
        unloaded_fields = _artifact_fields_unloaded(doc)

        staging_dir = _STORE_DIR / f"{scenario_id}.staging"
        if staging_dir.exists():
            _remove_tree_with_retries(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)

        staging_refs = {}
        for k, v in refs.items():
            staging_refs[k] = str(staging_dir / Path(v).name)

        artifact_db_path = Path(staging_refs["artifactStore"])

        complete_marker = staging_dir / "_COMPLETE"
        incomplete_marker = staging_dir / "_INCOMPLETE"
        incomplete_marker.write_text(_now_iso(), encoding="utf-8")

        staging_json = _STORE_DIR / f"{scenario_id}.json.staging"

        try:
            master_payload = {key: doc.get(key) for key in _MASTER_DATA_KEYS}
            master_data_store.save_master_data(Path(staging_refs["masterData"]), master_payload)

            preserved_artifacts: Dict[str, Any] = {}
            for field, ref_key in _ARTIFACT_REF_KEYS.items():
                preserved_artifacts[field] = doc.get(field)
                target_path = Path(staging_refs[ref_key])
                existing_target_path = Path(existing_refs[ref_key])
                if field in unloaded_fields:
                    if field == "graph" or field in _SQLITE_ROW_ARTIFACT_FIELDS or field in _SQLITE_SCALAR_ARTIFACT_FIELDS:
                        if Path(existing_refs["artifactStore"]).exists() and not artifact_db_path.exists():
                            shutil.copy2(existing_refs["artifactStore"], artifact_db_path)
                        continue
                    if existing_target_path.exists():
                        shutil.copy2(existing_target_path, target_path)
                    continue
                if field == "graph":
                    _save_graph_artifact(artifact_db_path, doc.get(field))
                elif field == "timetable_rows":
                    rows = list(doc.get(field) or [])
                    trip_store.save_timetable_rows(artifact_db_path, rows)
                    trip_store.save_rows(artifact_db_path, field, rows)
                    trip_store.save_scalar(
                        artifact_db_path,
                        _SUMMARY_SCALAR_NAMES[field],
                        _build_timetable_summary_artifact(rows, doc.get("timetable_import_meta") or {}),
                    )
                elif field in _PARQUET_ROW_ARTIFACT_FIELDS:
                    value = doc.get(field)
                    if value is None:
                        if target_path.exists():
                            _unlink_with_retries(target_path)
                        if field in _SUMMARY_SCALAR_NAMES:
                            trip_store.save_scalar(
                                artifact_db_path,
                                _SUMMARY_SCALAR_NAMES[field],
                                None,
                            )
                    else:
                        rows = list(value or [])
                        trip_store.save_parquet_rows(target_path, rows)
                        if field in _SUMMARY_SCALAR_NAMES:
                            summary_builder = (
                                _build_trips_summary_artifact if field == "trips" else _build_duties_summary_artifact
                            )
                            trip_store.save_scalar(
                                artifact_db_path,
                                _SUMMARY_SCALAR_NAMES[field],
                                summary_builder(rows),
                            )
                elif field in _SQLITE_ROW_ARTIFACT_FIELDS:
                    rows = list(doc.get(field) or [])
                    trip_store.save_rows(artifact_db_path, field, rows)
                    if field in _SUMMARY_SCALAR_NAMES:
                        summary_builder = (
                            _build_trips_summary_artifact if field == "trips" else _build_duties_summary_artifact
                        )
                        trip_store.save_scalar(
                            artifact_db_path,
                            _SUMMARY_SCALAR_NAMES[field],
                            summary_builder(rows),
                        )
                elif field in _SQLITE_SCALAR_ARTIFACT_FIELDS:
                    trip_store.save_scalar(artifact_db_path, field, doc.get(field))
                if field not in _PARQUET_ROW_ARTIFACT_FIELDS and target_path.exists():
                    _unlink_with_retries(target_path)

            slim_doc = {
                "scenarioId": scenario_id,
                "name": doc.get("meta", {}).get("name"),
                "meta": {
                    **dict(doc.get("meta") or {}),
                    **_scope_summary(doc.get("dispatch_scope")),
                },
                "feed_context": doc.get("feed_context"),
                "refs": refs,
                "stats": _scenario_stats_for_save(
                    doc,
                    fallback=existing_meta.get("stats") if isinstance(existing_meta, dict) else None,
                ),
            }

            staging_json.write_text(
                json.dumps(slim_doc, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )

            manifest = staging_dir / "manifest.json"
            manifest.write_text(json.dumps({"committedAt": _now_iso()}), encoding="utf-8")
            complete_marker.write_text(scenario_id, encoding="utf-8")
            if incomplete_marker.exists():
                incomplete_marker.unlink()

            # Atomic commit
            active_dir = _artifact_dir_for_scenario(scenario_id)
            old_dir = _STORE_DIR / f"{scenario_id}.old"
            active_json = scenario_meta_store.scenario_path(_STORE_DIR, scenario_id)
            old_json = _STORE_DIR / f"{scenario_id}.json.old"

            if old_dir.exists():
                _remove_tree_with_retries(old_dir, ignore_errors=True)
            if old_json.exists():
                _unlink_with_retries(old_json, missing_ok=True)

            try:
                if active_dir.exists():
                    _rename_with_retries(active_dir, old_dir)
                _rename_with_retries(staging_dir, active_dir)

                if active_json.exists():
                    _rename_with_retries(active_json, old_json)
                _rename_with_retries(staging_json, active_json)
            except OSError as exc:
                # Windows can keep handles open briefly and reject directory
                # rename. Fall back to non-atomic sync to avoid save failure.
                winerror = getattr(exc, "winerror", None)
                if winerror not in {5, 32} and not isinstance(exc, PermissionError):
                    raise
                if active_dir.exists():
                    _sync_tree_non_atomic(staging_dir, active_dir)
                    _remove_tree_with_retries(staging_dir, ignore_errors=True)
                else:
                    _rename_with_retries(staging_dir, active_dir)

                try:
                    if active_json.exists():
                        shutil.copy2(active_json, old_json)
                except Exception:
                    pass
                active_json.write_text(staging_json.read_text(encoding="utf-8"), encoding="utf-8")
                _unlink_with_retries(staging_json, missing_ok=True)

            if old_dir.exists():
                _remove_tree_with_retries(old_dir, ignore_errors=True)
            if old_json.exists():
                _unlink_with_retries(old_json, missing_ok=True)

            doc["refs"] = refs
            doc["stats"] = slim_doc["stats"]
            for field, value in preserved_artifacts.items():
                doc[field] = value
        except Exception:
            if staging_dir.exists():
                _remove_tree_with_retries(staging_dir, ignore_errors=True)
            if staging_json.exists():
                _unlink_with_retries(staging_json, missing_ok=True)
            raise


def _load_app_context() -> Dict[str, Any]:
    _ensure_dir()
    if not _APP_CONTEXT_PATH.exists():
        return _default_app_context()
    try:
        doc = json.loads(_APP_CONTEXT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return _default_app_context()
    normalized = _default_app_context()
    normalized.update({k: v for k, v in doc.items() if k in normalized})
    return normalized


def _save_app_context(doc: Dict[str, Any]) -> None:
    _ensure_dir()
    _APP_CONTEXT_PATH.write_text(
        json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _normalize_feed_context(
    feed_context: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    if not isinstance(feed_context, dict):
        return None
    feed_id = str(feed_context.get("feed_id") or feed_context.get("feedId") or "").strip()
    snapshot_id = str(
        feed_context.get("snapshot_id") or feed_context.get("snapshotId") or ""
    ).strip()
    dataset_id = str(
        feed_context.get("dataset_id") or feed_context.get("datasetId") or ""
    ).strip()
    dataset_fingerprint = str(
        feed_context.get("dataset_fingerprint") or feed_context.get("datasetFingerprint") or ""
    ).strip()
    manual_route_family_map_hash = str(
        feed_context.get("manual_route_family_map_hash") or feed_context.get("manualRouteFamilyMapHash") or ""
    ).strip()
    source = str(feed_context.get("source") or "").strip()
    if not any((feed_id, snapshot_id, dataset_id, dataset_fingerprint, source)):
        return None
    return {
        "feedId": feed_id or None,
        "snapshotId": snapshot_id or None,
        "datasetId": dataset_id or None,
        "datasetFingerprint": dataset_fingerprint or None,
        "manualRouteFamilyMapHash": manual_route_family_map_hash or None,
        "source": source or None,
    }


def _meta_payload(doc: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(doc["meta"])
    payload.setdefault("operatorId", "tokyu")
    payload["feedContext"] = _normalize_feed_context(doc.get("feed_context"))
    overlay = doc.get("scenario_overlay")
    if isinstance(overlay, dict):
        payload["datasetId"] = overlay.get("dataset_id")
        payload["datasetVersion"] = overlay.get("dataset_version")
        payload["randomSeed"] = overlay.get("random_seed")
        payload["scenarioOverlay"] = dict(overlay)
        dataset_id = overlay.get("dataset_id")
        if dataset_id:
            try:
                from src.research_dataset_loader import get_dataset_status

                payload["datasetStatus"] = get_dataset_status(str(dataset_id))
            except Exception:
                payload["datasetStatus"] = None
    if "refs" in doc:
        payload["refs"] = dict(doc.get("refs") or {})
    if "stats" in doc:
        payload["stats"] = _normalize_stats_payload(
            doc,
            fallback=dict(doc.get("stats") or {}),
            dispatch_invalidated=False,
        )
    return payload


def _bootstrap_state_from_overlay_and_feed(
    overlay: Optional[Dict[str, Any]],
    feed_context: Optional[Dict[str, Any]],
) -> Dict[str, Optional[str]]:
    overlay = overlay if isinstance(overlay, dict) else {}
    feed_context = feed_context if isinstance(feed_context, dict) else {}
    dataset_id = (
        overlay.get("dataset_id")
        or overlay.get("datasetId")
        or feed_context.get("datasetId")
        or feed_context.get("dataset_id")
    )
    dataset_version = (
        overlay.get("dataset_version")
        or overlay.get("datasetVersion")
        or feed_context.get("snapshotId")
        or feed_context.get("snapshot_id")
    )
    dataset_fingerprint = (
        feed_context.get("datasetFingerprint")
        or feed_context.get("dataset_fingerprint")
    )
    return {
        "datasetId": str(dataset_id).strip() or None if dataset_id is not None else None,
        "datasetVersion": str(dataset_version).strip() or None
        if dataset_version is not None
        else None,
        "datasetFingerprint": str(dataset_fingerprint).strip() or None
        if dataset_fingerprint is not None
        else None,
    }


def _bootstrap_state_from_doc(doc: Dict[str, Any]) -> Dict[str, Optional[str]]:
    state = _bootstrap_state_from_overlay_and_feed(
        doc.get("scenario_overlay"),
        doc.get("feed_context"),
    )
    meta = doc.get("meta") or {}
    if not state["datasetId"] and meta.get("datasetBootstrapDatasetId"):
        state["datasetId"] = str(meta.get("datasetBootstrapDatasetId")).strip() or None
    if not state["datasetVersion"] and meta.get("datasetBootstrapVersion"):
        state["datasetVersion"] = str(meta.get("datasetBootstrapVersion")).strip() or None
    if not state["datasetFingerprint"] and meta.get("datasetBootstrapFingerprint"):
        state["datasetFingerprint"] = (
            str(meta.get("datasetBootstrapFingerprint")).strip() or None
        )
    return state


def _bootstrap_state_from_payload(payload: Dict[str, Any]) -> Dict[str, Optional[str]]:
    return _bootstrap_state_from_overlay_and_feed(
        payload.get("scenario_overlay"),
        payload.get("feed_context"),
    )


def _has_materialized_dataset_bootstrap(doc: Dict[str, Any]) -> bool:
    return bool(doc.get("depots")) and bool(doc.get("routes")) and bool(
        doc.get("vehicle_templates")
    )


def _same_dataset_bootstrap(doc: Dict[str, Any], payload: Dict[str, Any]) -> bool:
    current = _bootstrap_state_from_doc(doc)
    incoming = _bootstrap_state_from_payload(payload)
    if not any(incoming.values()):
        return False
    for key, incoming_value in incoming.items():
        if incoming_value and current.get(key) != incoming_value:
            return False
    return True


def _normalize_operator_id(value: Any, default: Optional[str] = None) -> Optional[str]:
    operator_id = str(value or default or "").strip().lower()
    if not operator_id:
        return None
    if operator_id not in _VALID_OPERATOR_IDS:
        raise ValueError(f"Unknown operator '{operator_id}'")
    return operator_id


# ── Public helpers ─────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return str(uuid.uuid4())


def _invalidate_dispatch_artifacts(doc: Dict[str, Any]) -> None:
    unloaded_fields = _artifact_fields_unloaded(doc)
    doc["trips"] = None
    doc["graph"] = None
    doc["blocks"] = None
    doc["duties"] = None
    doc["dispatch_plan"] = None
    doc["simulation_result"] = None
    doc["optimization_result"] = None
    doc["problemdata_build_audit"] = None
    doc["optimization_audit"] = None
    doc["simulation_audit"] = None
    doc["meta"]["status"] = "draft"
    _mark_artifact_fields_unloaded(
        doc,
        unloaded_fields.difference(
            {
                "trips",
                "graph",
                "blocks",
                "duties",
                "dispatch_plan",
                "simulation_result",
                "optimization_result",
            }
        ),
    )


def _normalize_dispatch_scope(doc: Dict[str, Any]) -> Dict[str, Any]:
    scope = doc.setdefault("dispatch_scope", {})
    defaults = _default_dispatch_scope()

    depot_ids = {
        str(depot.get("id"))
        for depot in doc.get("depots") or []
        if depot.get("id") is not None
    }
    route_ids = {
        str(route.get("id"))
        for route in doc.get("routes") or []
        if route.get("id") is not None
    }
    route_family_code_by_route_id = {
        str(route.get("id")): str(
            route.get("routeFamilyCode")
            or route.get("routeCode")
            or route.get("routeLabel")
            or ""
        ).strip()
        for route in doc.get("routes") or []
        if route.get("id") is not None
    }
    valid_route_family_codes = {
        code for code in route_family_code_by_route_id.values() if code
    }
    service_ids = {
        str(entry.get("service_id"))
        for entry in doc.get("calendar") or _default_calendar()
        if entry.get("service_id") is not None
    }
    assignment_map = _route_assignment_map(doc)

    legacy_depot_id = scope.get("depotId")
    legacy_service_id = canonical_service_id(scope.get("serviceId"))

    depot_selection = scope.get("depotSelection")
    if not isinstance(depot_selection, dict):
        depot_selection = {}
    selected_depots = []
    for depot_id in depot_selection.get("depotIds") or []:
        depot_id = str(depot_id)
        if depot_id in depot_ids and depot_id not in selected_depots:
            selected_depots.append(depot_id)
    if legacy_depot_id is not None:
        legacy_depot_id = str(legacy_depot_id)
        if legacy_depot_id in depot_ids and legacy_depot_id not in selected_depots:
            selected_depots.insert(0, legacy_depot_id)
    primary_depot_id = depot_selection.get("primaryDepotId")
    if primary_depot_id is not None:
        primary_depot_id = str(primary_depot_id)
        if primary_depot_id not in depot_ids:
            primary_depot_id = None
    if primary_depot_id is None and selected_depots:
        primary_depot_id = selected_depots[0]
    if primary_depot_id and primary_depot_id not in selected_depots:
        selected_depots.insert(0, primary_depot_id)

    route_selection = scope.get("routeSelection")
    if not isinstance(route_selection, dict):
        route_selection = {}
    route_mode = str(route_selection.get("mode") or defaults["routeSelection"]["mode"])
    if route_mode not in {"all", "include", "exclude", "refine"}:
        route_mode = defaults["routeSelection"]["mode"]
    include_route_ids = []
    for route_id in route_selection.get("includeRouteIds") or []:
        route_id = str(route_id)
        if route_id in route_ids and route_id not in include_route_ids:
            include_route_ids.append(route_id)
    exclude_route_ids = []
    for route_id in route_selection.get("excludeRouteIds") or []:
        route_id = str(route_id)
        if route_id in route_ids and route_id not in exclude_route_ids:
            exclude_route_ids.append(route_id)
    include_route_family_codes = []
    for route_family_code in route_selection.get("includeRouteFamilyCodes") or []:
        route_family_code = str(route_family_code).strip()
        if route_family_code in valid_route_family_codes and route_family_code not in include_route_family_codes:
            include_route_family_codes.append(route_family_code)
    exclude_route_family_codes = []
    for route_family_code in route_selection.get("excludeRouteFamilyCodes") or []:
        route_family_code = str(route_family_code).strip()
        if route_family_code in valid_route_family_codes and route_family_code not in exclude_route_family_codes:
            exclude_route_family_codes.append(route_family_code)
    include_route_ids_from_family = [
        route_id
        for route_id, route_family_code in route_family_code_by_route_id.items()
        if route_family_code in include_route_family_codes
    ]
    exclude_route_ids_from_family = [
        route_id
        for route_id, route_family_code in route_family_code_by_route_id.items()
        if route_family_code in exclude_route_family_codes
    ]
    for route_id in include_route_ids_from_family:
        if route_id not in include_route_ids:
            include_route_ids.append(route_id)
    for route_id in exclude_route_ids_from_family:
        if route_id not in exclude_route_ids:
            exclude_route_ids.append(route_id)

    service_selection = scope.get("serviceSelection")
    if not isinstance(service_selection, dict):
        service_selection = {}
    selected_service_ids = []
    for service_id in service_selection.get("serviceIds") or []:
        service_id = canonical_service_id(service_id)
        if service_id in service_ids and service_id not in selected_service_ids:
            selected_service_ids.append(service_id)
    if not selected_service_ids:
        selected_service_ids = [legacy_service_id if legacy_service_id in service_ids else "WEEKDAY"]

    trip_selection = scope.get("tripSelection")
    if not isinstance(trip_selection, dict):
        trip_selection = {}
    normalized_trip_selection = {
        "includeShortTurn": bool(
            trip_selection.get(
                "includeShortTurn",
                defaults["tripSelection"]["includeShortTurn"],
            )
        ),
        "includeDepotMoves": bool(
            trip_selection.get(
                "includeDepotMoves",
                defaults["tripSelection"]["includeDepotMoves"],
            )
        ),
        "includeDeadhead": bool(
            trip_selection.get(
                "includeDeadhead",
                defaults["tripSelection"]["includeDeadhead"],
            )
        ),
    }

    candidate_route_ids: List[str] = []
    if selected_depots:
        for route_id, assignment in assignment_map.items():
            if str(assignment.get("depotId")) in selected_depots and route_id not in candidate_route_ids:
                candidate_route_ids.append(route_id)
        for route in doc.get("routes") or []:
            route_id = str(route.get("id") or "").strip()
            depot_id = str(route.get("depotId") or "").strip()
            if (
                route_id
                and depot_id in selected_depots
                and route_id in route_ids
                and route_id not in candidate_route_ids
            ):
                candidate_route_ids.append(route_id)
    else:
        candidate_route_ids = sorted(route_ids)

    if route_mode == "all":
        effective_route_ids = [route_id for route_id in candidate_route_ids if route_id not in exclude_route_ids]
    elif route_mode == "include":
        effective_route_ids = [route_id for route_id in include_route_ids if route_id not in exclude_route_ids]
    elif route_mode == "exclude":
        effective_route_ids = [route_id for route_id in candidate_route_ids if route_id not in exclude_route_ids]
    else:
        effective_route_ids = list(candidate_route_ids)
        for route_id in include_route_ids:
            if route_id not in effective_route_ids:
                effective_route_ids.append(route_id)
        effective_route_ids = [route_id for route_id in effective_route_ids if route_id not in exclude_route_ids]

    operator_id = scope.get("operatorId")
    if operator_id is None:
        operator_id = (doc.get("meta") or {}).get("operatorId")
    if operator_id is not None:
        operator_id = str(operator_id).strip().lower() or None

    normalized = {
        "scopeId": str(scope.get("scopeId")).strip() if scope.get("scopeId") else None,
        "operatorId": operator_id,
        "datasetVersion": str(scope.get("datasetVersion")).strip()
        if scope.get("datasetVersion")
        else None,
        "depotSelection": {
            "mode": "include",
            "depotIds": selected_depots,
            "primaryDepotId": primary_depot_id,
        },
        "routeSelection": {
            "mode": route_mode,
            "includeRouteIds": include_route_ids,
            "excludeRouteIds": exclude_route_ids,
            "includeRouteFamilyCodes": include_route_family_codes,
            "excludeRouteFamilyCodes": exclude_route_family_codes,
        },
        "serviceSelection": {
            "serviceIds": selected_service_ids,
        },
        "tripSelection": normalized_trip_selection,
        "allowIntraDepotRouteSwap": bool(scope.get("allowIntraDepotRouteSwap", False)),
        "allowInterDepotSwap": bool(scope.get("allowInterDepotSwap", False)),
        "fixedRouteBandMode": bool(scope.get("fixedRouteBandMode", True)),
        "depotId": primary_depot_id,
        "serviceId": selected_service_ids[0],
        "candidateRouteIds": candidate_route_ids,
        "effectiveRouteIds": effective_route_ids,
        "candidateRouteFamilyCodes": list(
            dict.fromkeys(
                route_family_code
                for route_family_code in [
                    route_family_code_by_route_id.get(route_id, "")
                    for route_id in candidate_route_ids
                ]
                if route_family_code
            )
        ),
        "effectiveRouteFamilyCodes": list(
            dict.fromkeys(
                route_family_code
                for route_family_code in [
                    route_family_code_by_route_id.get(route_id, "")
                    for route_id in effective_route_ids
                ]
                if route_family_code
            )
        ),
    }
    doc["dispatch_scope"] = normalized
    return dict(normalized)


def _sync_depot_route_permissions(
    doc: Dict[str, Any],
    permissions: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    depots = [
        str(depot.get("id"))
        for depot in doc.get("depots") or []
        if depot.get("id") is not None
    ]
    routes = [
        str(route.get("id"))
        for route in doc.get("routes") or []
        if route.get("id") is not None
    ]
    existing = {
        (str(item.get("depotId")), str(item.get("routeId"))): bool(item.get("allowed"))
        for item in doc.get("depot_route_permissions") or []
        if item.get("depotId") is not None and item.get("routeId") is not None
    }
    incoming = {
        (str(item.get("depotId")), str(item.get("routeId"))): bool(item.get("allowed"))
        for item in permissions or []
        if item.get("depotId") is not None and item.get("routeId") is not None
    }

    normalized: List[Dict[str, Any]] = []
    for depot_id in depots:
        for route_id in routes:
            key = (depot_id, route_id)
            allowed = incoming.get(key)
            if allowed is None:
                allowed = existing.get(key)
            if allowed is None:
                allowed = True
            normalized.append(
                {
                    "depotId": depot_id,
                    "routeId": route_id,
                    "allowed": bool(allowed),
                }
            )

    doc["depot_route_permissions"] = normalized
    return list(normalized)


def _sync_vehicle_route_permissions(
    doc: Dict[str, Any],
    permissions: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    valid_vehicle_ids = {
        str(vehicle.get("id"))
        for vehicle in doc.get("vehicles") or []
        if vehicle.get("id") is not None
    }
    valid_route_ids = {
        str(route.get("id"))
        for route in doc.get("routes") or []
        if route.get("id") is not None
    }

    merged: Dict[tuple[str, str], Dict[str, Any]] = {}
    for item in doc.get("vehicle_route_permissions") or []:
        vehicle_id = item.get("vehicleId")
        route_id = item.get("routeId")
        if vehicle_id is None or route_id is None:
            continue
        vehicle_id = str(vehicle_id)
        route_id = str(route_id)
        if vehicle_id not in valid_vehicle_ids or route_id not in valid_route_ids:
            continue
        merged[(vehicle_id, route_id)] = {
            "vehicleId": vehicle_id,
            "routeId": route_id,
            "allowed": bool(item.get("allowed")),
        }

    for item in permissions or []:
        vehicle_id = item.get("vehicleId")
        route_id = item.get("routeId")
        if vehicle_id is None or route_id is None:
            continue
        vehicle_id = str(vehicle_id)
        route_id = str(route_id)
        if vehicle_id not in valid_vehicle_ids or route_id not in valid_route_ids:
            continue
        merged[(vehicle_id, route_id)] = {
            "vehicleId": vehicle_id,
            "routeId": route_id,
            "allowed": bool(item.get("allowed")),
        }

    doc["vehicle_route_permissions"] = list(merged.values())
    return list(doc["vehicle_route_permissions"])


def _default_calendar() -> List[Dict[str, Any]]:
    """Seed three standard service types for every new scenario."""
    return [
        {
            "service_id": "WEEKDAY",
            "name": "平日",
            "mon": 1,
            "tue": 1,
            "wed": 1,
            "thu": 1,
            "fri": 1,
            "sat": 0,
            "sun": 0,
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
        {
            "service_id": "SAT",
            "name": "土曜",
            "mon": 0,
            "tue": 0,
            "wed": 0,
            "thu": 0,
            "fri": 0,
            "sat": 1,
            "sun": 0,
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
        {
            "service_id": "SUN_HOL",
            "name": "日曜・休日",
            "mon": 0,
            "tue": 0,
            "wed": 0,
            "thu": 0,
            "fri": 0,
            "sat": 0,
            "sun": 1,
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
        },
    ]


# ── Scenario CRUD ──────────────────────────────────────────────


def list_scenarios() -> List[Dict[str, Any]]:
    _ensure_dir()
    results = []
    for p in sorted(_STORE_DIR.glob("*.json")):
        if _is_auxiliary_path(p) or p == _APP_CONTEXT_PATH:
            continue
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
            results.append(_meta_payload(doc))
        except Exception:
            pass
    return results


def create_scenario(
    name: str,
    description: str,
    mode: str,
    operator_id: str = "tokyu",
) -> Dict[str, Any]:
    scenario_id = _new_id()
    now = _now_iso()
    normalized_operator_id = _normalize_operator_id(operator_id, "tokyu")
    meta = {
        "id": scenario_id,
        "name": name,
        "description": description,
        "mode": mode,
        "operatorId": normalized_operator_id,
        "createdAt": now,
        "updatedAt": now,
        "status": "draft",
    }
    dispatch_scope = _default_dispatch_scope()
    dispatch_scope["operatorId"] = normalized_operator_id
    doc: Dict[str, Any] = {
        "meta": meta,
        "depots": [],
        "vehicles": [],
        "vehicle_templates": [],
        "routes": [],
        "stops": [],
        "route_depot_assignments": [],
        "depot_route_permissions": [],
        "vehicle_route_permissions": [],
        "route_import_meta": {},
        "stop_import_meta": {},
        "timetable_import_meta": {},
        "timetable_rows": [],
        "stop_timetable_import_meta": {},
        "stop_timetables": [],
        "calendar": _default_calendar(),
        "calendar_dates": [],
        "dispatch_scope": dispatch_scope,
        "simulation_config": None,
        "trips": None,
        "graph": None,
        "blocks": None,
        "duties": None,
        "dispatch_plan": None,
        "simulation_result": None,
        "optimization_result": None,
        "public_data": _default_public_data_state(),
        "feed_context": None,
    }
    doc.update(_default_v1_2_fields())
    _save(doc)
    return _meta_payload(doc)


def get_scenario_document(
    scenario_id: str,
    *,
    repair_missing_master: bool = True,
    include_graph_arcs: bool = False,
) -> Dict[str, Any]:
    """Load a full scenario document.

    By default graph arcs are NOT loaded (skip_graph_arcs=True) because loading
    100K+ arcs takes several seconds and is rarely needed outside of graph-specific
    endpoints.  Pass include_graph_arcs=True when you explicitly need the arc data.
    """
    return _load(
        scenario_id,
        repair_missing_master=repair_missing_master,
        skip_graph_arcs=not include_graph_arcs,
    )


def get_scenario_document_shallow(scenario_id: str) -> Dict[str, Any]:
    """Lightweight load: master data only, no heavy artifacts.

    Use for editor-bootstrap and other fast reads that do not need
    timetable_rows, trips, graph, blocks, duties, or result artifacts.
    """
    return _load_shallow(scenario_id)


def get_scenario(scenario_id: str) -> Dict[str, Any]:
    return _meta_payload(_load_shallow(scenario_id))


def ensure_runtime_master_data(scenario_id: str) -> bool:
    with _scenario_lock(scenario_id):
        doc = _load(
            scenario_id,
            repair_missing_master=False,
            skip_graph_arcs=True,
            repair_route_metadata=False,
        )
        needs_master_refresh = _needs_master_repair(doc) or _needs_runtime_master_alignment(doc)
        route_metadata_repaired = _repair_route_metadata_from_preload(doc)
        if not needs_master_refresh and not route_metadata_repaired:
            return False
        repaired = False
        if needs_master_refresh:
            repaired = _repair_missing_master_defaults(doc, touch_updated_at=True)
            route_metadata_repaired = _repair_route_metadata_from_preload(doc) or route_metadata_repaired
            if not repaired and not route_metadata_repaired:
                return False
        _normalize_dispatch_scope(doc)
        doc["meta"]["updatedAt"] = _now_iso()
        if repaired:
            _invalidate_dispatch_artifacts(doc)
            _save(doc)
        else:
            _save_master_only(doc, invalidate_dispatch=False)
        return True


def update_scenario(
    scenario_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    mode: Optional[str] = None,
    operator_id: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    doc = _load_shallow(scenario_id)
    if name is not None:
        doc["meta"]["name"] = name
    if description is not None:
        doc["meta"]["description"] = description
    if mode is not None:
        doc["meta"]["mode"] = mode
    if operator_id is not None:
        normalized_operator_id = _normalize_operator_id(operator_id)
        doc["meta"]["operatorId"] = normalized_operator_id
        scope = doc.get("dispatch_scope") or _default_dispatch_scope()
        scope["operatorId"] = normalized_operator_id
        doc["dispatch_scope"] = scope
    if status is not None:
        doc["meta"]["status"] = status
    doc["meta"]["updatedAt"] = _now_iso()
    _save_master_only(doc, invalidate_dispatch=False)
    return _meta_payload(doc)


def delete_scenario(scenario_id: str) -> None:
    p = _path(scenario_id)
    if not p.exists():
        raise KeyError(scenario_id)
    p.unlink()
    artifact_dir = scenario_meta_store.artifact_dir(_STORE_DIR, scenario_id)
    if artifact_dir.exists():
        _remove_tree_with_retries(artifact_dir, ignore_errors=True)
    for extra_path in (
        _legacy_timetable_path(scenario_id),
        _legacy_stop_timetables_path(scenario_id),
    ):
        if extra_path.exists():
            extra_path.unlink()
    context = _load_app_context()
    if context.get("activeScenarioId") == scenario_id:
        context["activeScenarioId"] = None
        context["updatedAt"] = _now_iso()
        _save_app_context(context)
    _release_scenario_lock(scenario_id)


def duplicate_scenario(
    scenario_id: str, *, name: Optional[str] = None
) -> Dict[str, Any]:
    doc = _load(scenario_id, skip_graph_arcs=True)
    new_id = _new_id()
    now = _now_iso()
    cloned = json.loads(json.dumps(doc))
    cloned["meta"]["id"] = new_id
    cloned["meta"]["name"] = name or f"{doc['meta'].get('name') or 'Scenario'} Copy"
    cloned["meta"]["createdAt"] = now
    cloned["meta"]["updatedAt"] = now
    cloned["meta"]["status"] = "draft"
    cloned.pop("refs", None)
    cloned.pop("scenarioId", None)
    _save(cloned)
    return _meta_payload(cloned)


# ── Generic sub-document accessors ────────────────────────────


def get_field(scenario_id: str, field: str) -> Any:
    """Return a single artifact field without loading the entire scenario doc.

    For heavy artifact fields (trips, timetable_rows, graph, …) this reads
    directly from the SQLite/Parquet artifact store instead of calling _load()
    which would also load every other artifact.
    """
    meta = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
    refs = _refs_for_scenario(scenario_id, meta)
    artifact_db_path = _artifact_store_path(refs)

    if field == "timetable_rows":
        if trip_store.count_timetable_rows(artifact_db_path) > 0:
            # page_timetable_rows already excludes __vN GTFS duplicates
            return trip_store.page_timetable_rows(artifact_db_path, offset=0, limit=None)
        artifact_path = Path(refs["timetableRows"])
        if artifact_path.exists():
            return _drop_vn_duplicate_rows(_load_json_list(artifact_path))
        legacy = _legacy_timetable_path(scenario_id)
        if legacy.exists():
            return _drop_vn_duplicate_rows(_load_json_list(legacy))
        fallback_rows = _tokyu_bus_timetable_rows_for_doc(_load_shallow(scenario_id))
        if fallback_rows:
            return fallback_rows
        return []

    if field in _PARQUET_ROW_ARTIFACT_FIELDS:
        parquet_path = Path(refs[_ARTIFACT_REF_KEYS[field]])
        if parquet_path.exists() and trip_store.count_parquet_rows(parquet_path) > 0:
            return trip_store.load_parquet_rows(parquet_path)
        if trip_store.count_rows(artifact_db_path, field) > 0:
            return trip_store.load_rows(artifact_db_path, field)
        return _artifact_default(field)

    if field == "graph":
        return _load_graph_artifact(artifact_db_path, Path(refs["graph"]))

    if field in _SQLITE_ROW_ARTIFACT_FIELDS:
        if trip_store.count_rows(artifact_db_path, field) > 0:
            return trip_store.load_rows(artifact_db_path, field)
        artifact_path = Path(refs[_ARTIFACT_REF_KEYS[field]])
        if artifact_path.exists():
            return _load_json_list(artifact_path)
        return _artifact_default(field)

    if field in _SQLITE_SCALAR_ARTIFACT_FIELDS:
        try:
            value = trip_store.load_scalar(artifact_db_path, field, _artifact_default(field))
        except sqlite3.OperationalError:
            value = _artifact_default(field)
        if value is not None:
            return value
        artifact_path = Path(refs[_ARTIFACT_REF_KEYS[field]])
        if artifact_path.exists():
            return trip_store.load_json(artifact_path, _artifact_default(field))
        return _artifact_default(field)

    # For non-artifact fields, fall back to shallow load (master data only)
    return _load_shallow(scenario_id).get(field)


def count_field_rows(scenario_id: str, field: str) -> int:
    meta = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
    refs = _refs_for_scenario(scenario_id, meta)
    if field == "timetable_rows":
        # count_timetable_rows already excludes __vN GTFS duplicates
        db_count = trip_store.count_timetable_rows(_artifact_store_path(refs))
        # Return here regardless — don't fall through to the unfiltered
        # _SQLITE_ROW_ARTIFACT_FIELDS path which reads row_artifacts without
        # filtering __vN duplicates.
        if db_count > 0:
            return db_count
        # Fallback: count from row_artifacts with __vN filter applied in memory
        raw_rows = trip_store.load_rows(_artifact_store_path(refs), field)
        filtered_rows = _drop_vn_duplicate_rows(raw_rows)
        if filtered_rows:
            return len(filtered_rows)
        summary = _tokyu_bus_timetable_summary_for_doc(_load_shallow(scenario_id))
        if summary:
            return int(summary.get("totalRows") or 0)
        return 0
    if field in _PARQUET_ROW_ARTIFACT_FIELDS:
        parquet_count = trip_store.count_parquet_rows(Path(refs[_ARTIFACT_REF_KEYS[field]]))
        if parquet_count > 0:
            return parquet_count
    if field in _SQLITE_ROW_ARTIFACT_FIELDS:
        db_count = trip_store.count_rows(_artifact_store_path(refs), field)
        if db_count > 0:
            return db_count
    value = _load(scenario_id)[field]
    return len(list(value or [])) if isinstance(value, list) else 0


def page_field_rows(
    scenario_id: str,
    field: str,
    *,
    offset: int = 0,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    meta = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
    refs = _refs_for_scenario(scenario_id, meta)
    if field == "timetable_rows":
        db_path = _artifact_store_path(refs)
        db_count = trip_store.count_timetable_rows(db_path)
        if db_count > 0:
            # page_timetable_rows already excludes __vN GTFS duplicates
            return [
                dict(item)
                for item in trip_store.page_timetable_rows(db_path, offset=offset, limit=limit)
            ]
        # Fallback: read from row_artifacts with __vN filter
        raw_rows = _drop_vn_duplicate_rows(trip_store.load_rows(db_path, field))
        if not raw_rows:
            raw_rows = _tokyu_bus_timetable_rows_for_doc(_load_shallow(scenario_id))
        if limit is None:
            return [dict(item) for item in raw_rows[offset:]]
        return [dict(item) for item in raw_rows[offset: offset + limit]]
    if field in _PARQUET_ROW_ARTIFACT_FIELDS:
        parquet_path = Path(refs[_ARTIFACT_REF_KEYS[field]])
        parquet_count = trip_store.count_parquet_rows(parquet_path)
        if parquet_count > 0:
            return [
                dict(item)
                for item in trip_store.page_parquet_rows(parquet_path, offset=offset, limit=limit)
            ]
    if field in _SQLITE_ROW_ARTIFACT_FIELDS:
        db_path = _artifact_store_path(refs)
        db_count = trip_store.count_rows(db_path, field)
        if db_count > 0:
            return [dict(item) for item in trip_store.page_rows(db_path, field, offset=offset, limit=limit)]
    value = _load(scenario_id)[field] or []
    items = list(value)
    if limit is None:
        return [dict(item) for item in items[offset:]]
    return [dict(item) for item in items[offset: offset + limit]]


def page_timetable_rows(
    scenario_id: str,
    *,
    offset: int = 0,
    limit: Optional[int] = None,
    service_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    meta = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
    refs = _refs_for_scenario(scenario_id, meta)
    db_path = _artifact_store_path(refs)
    total_db_rows = trip_store.count_timetable_rows(db_path)
    if total_db_rows > 0:
        return [
            dict(item)
            for item in trip_store.page_timetable_rows(
                db_path,
                offset=offset,
                limit=limit,
                service_id=service_id,
            )
        ]
    rows = _load(scenario_id).get("timetable_rows") or []
    if not rows:
        rows = _tokyu_bus_timetable_rows_for_doc(
            _load_shallow(scenario_id),
            service_ids=[service_id] if service_id else None,
        )
    if service_id:
        rows = [row for row in rows if str(row.get("service_id") or "WEEKDAY") == service_id]
    if limit is None:
        return [dict(item) for item in rows[offset:]]
    return [dict(item) for item in rows[offset: offset + limit]]


def count_timetable_rows(scenario_id: str, *, service_id: Optional[str] = None) -> int:
    meta = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
    refs = _refs_for_scenario(scenario_id, meta)
    db_path = _artifact_store_path(refs)
    total_db_rows = trip_store.count_timetable_rows(db_path)
    if total_db_rows > 0:
        return trip_store.count_timetable_rows(db_path, service_id=service_id)
    rows = _load(scenario_id).get("timetable_rows") or []
    if not rows:
        summary = _tokyu_bus_timetable_summary_for_doc(
            _load_shallow(scenario_id),
            service_ids=[service_id] if service_id else None,
        )
        if summary:
            return int(summary.get("totalRows") or 0)
    if service_id:
        rows = [row for row in rows if str(row.get("service_id") or "WEEKDAY") == service_id]
    return len(rows)


def summarize_route_service_trip_counts(
    scenario_id: str,
) -> List[Dict[str, Any]]:
    meta = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
    refs = _refs_for_scenario(scenario_id, meta)
    db_path = _artifact_store_path(refs)

    summaries = trip_store.summarize_timetable_routes(db_path)
    if summaries:
        return [dict(item) for item in summaries]

    row_artifact_summaries = trip_store.summarize_timetable_routes_from_row_artifacts(
        db_path
    )
    if row_artifact_summaries:
        return [dict(item) for item in row_artifact_summaries]

    if (
        trip_store.count_timetable_rows(db_path) == 0
        and trip_store.count_rows(db_path, "timetable_rows") == 0
    ):
        timetable_path = Path(refs["timetableRows"])
        legacy_timetable_path = _legacy_timetable_path(scenario_id)
        if not timetable_path.exists() and not legacy_timetable_path.exists():
            fallback_rows = _tokyu_bus_route_service_count_rows_for_doc(_load_shallow(scenario_id))
            if fallback_rows:
                return fallback_rows
            return []

    rows = _load(scenario_id).get("timetable_rows") or []
    if not rows:
        fallback_rows = _tokyu_bus_route_service_count_rows_for_doc(_load_shallow(scenario_id))
        if fallback_rows:
            return fallback_rows
    grouped: Dict[tuple[str, str], int] = {}
    for row in rows:
        route_id = str((row or {}).get("route_id") or "").strip()
        if not route_id:
            continue
        service_id = str((row or {}).get("service_id") or "WEEKDAY")
        key = (route_id, service_id)
        grouped[key] = grouped.get(key, 0) + 1

    return [
        {
            "route_id": route_id,
            "service_id": service_id,
            "trip_count": count,
        }
        for (route_id, service_id), count in sorted(grouped.items())
    ]


def get_field_summary(scenario_id: str, field: str) -> Optional[Dict[str, Any]]:
    scalar_name = _SUMMARY_SCALAR_NAMES.get(field)
    if not scalar_name:
        return None
    meta = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
    refs = _refs_for_scenario(scenario_id, meta)
    db_path = _artifact_store_path(refs)

    # For timetable_rows: always recompute from the filtered SQLite source.
    # The cached scalar may have been stored with __vN GTFS duplicates inflating
    # the count to 210k+.  page_timetable_rows() already excludes those rows.
    if field == "timetable_rows":
        if trip_store.count_timetable_rows(db_path) > 0:
            rows = trip_store.page_timetable_rows(db_path, offset=0, limit=None)
            imports = _load_shallow(scenario_id).get("timetable_import_meta") or {}
            return _build_timetable_summary_artifact(rows, imports)
        # Fallback to JSON-backed rows (e.g. legacy scenarios without SQLite DB)
        shallow_doc = _load_shallow(scenario_id)
        items = shallow_doc.get(field) or []
        imports = shallow_doc.get("timetable_import_meta") or {}
        if not items:
            summary = _tokyu_bus_timetable_summary_for_doc(shallow_doc)
            if summary:
                return summary
        return _build_timetable_summary_artifact(items, imports)

    # For other fields, use the pre-computed scalar when available
    summary = trip_store.load_scalar(db_path, scalar_name, None)
    if summary is not None:
        return dict(summary)
    items = _load(scenario_id).get(field) or []
    if field == "trips":
        return _build_trips_summary_artifact(items)
    if field == "duties":
        return _build_duties_summary_artifact(items)
    return None


def get_graph_meta(scenario_id: str) -> Optional[Dict[str, Any]]:
    meta = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
    refs = _refs_for_scenario(scenario_id, meta)
    artifact_db = _artifact_store_path(refs)
    graph_meta = trip_store.load_scalar(artifact_db, _graph_meta_name(), None)
    if graph_meta is not None:
        return dict(graph_meta)
    graph = _load(scenario_id).get("graph")
    if graph is None:
        return None
    graph_dict = dict(graph)
    graph_dict.pop("arcs", None)
    return graph_dict


def count_graph_arcs(scenario_id: str, *, reason_code: Optional[str] = None) -> int:
    meta = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
    refs = _refs_for_scenario(scenario_id, meta)
    artifact_db = _artifact_store_path(refs)
    total_db_rows = trip_store.count_graph_arcs(artifact_db)
    if total_db_rows > 0:
        return trip_store.count_graph_arcs(artifact_db, reason_code=reason_code)
    graph = _load(scenario_id).get("graph") or {}
    arcs = list(graph.get("arcs") or [])
    if reason_code:
        arcs = [item for item in arcs if item.get("reason_code") == reason_code]
    return len(arcs)


def page_graph_arcs(
    scenario_id: str,
    *,
    offset: int = 0,
    limit: Optional[int] = None,
    reason_code: Optional[str] = None,
) -> List[Dict[str, Any]]:
    meta = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
    refs = _refs_for_scenario(scenario_id, meta)
    artifact_db = _artifact_store_path(refs)
    total_db_rows = trip_store.count_graph_arcs(artifact_db)
    if total_db_rows > 0:
        return [
            dict(item)
            for item in trip_store.page_graph_arcs(
                artifact_db,
                offset=offset,
                limit=limit,
                reason_code=reason_code,
            )
        ]
    graph = _load(scenario_id).get("graph") or {}
    arcs = list(graph.get("arcs") or [])
    if reason_code:
        arcs = [item for item in arcs if item.get("reason_code") == reason_code]
    if limit is None:
        return [dict(item) for item in arcs[offset:]]
    return [dict(item) for item in arcs[offset: offset + limit]]


def set_field(
    scenario_id: str, field: str, value: Any, *, invalidate_dispatch: bool = False
) -> None:
    def _refresh_meta_for_direct_artifact_update(
        *,
        reset_dispatch_state: bool,
    ) -> None:
        refreshed_meta = dict(meta)
        refreshed_meta_payload = dict(refreshed_meta.get("meta") or {})
        refreshed_meta_payload["updatedAt"] = _now_iso()
        if reset_dispatch_state:
            refreshed_meta_payload["status"] = "draft"
        refreshed_meta["meta"] = refreshed_meta_payload

        refreshed_stats = dict(refreshed_meta.get("stats") or {})
        if field == "timetable_rows":
            refreshed_stats["timetableRowCount"] = len(
                _drop_vn_duplicate_rows(list(value or []))
            )
        if reset_dispatch_state:
            refreshed_stats["tripCount"] = 0
            refreshed_stats["dutyCount"] = 0
        refreshed_meta["stats"] = refreshed_stats
        scenario_meta_store.save_meta(_STORE_DIR, scenario_id, refreshed_meta)

    meta = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
    refs = _refs_for_scenario(scenario_id, meta)
    db_path = _artifact_store_path(refs)

    # Directly update SQLite for scalar artifacts to avoid _save() wiping out row artifacts
    if field in _SQLITE_SCALAR_ARTIFACT_FIELDS:
        try:
            trip_store.save_scalar(db_path, field, value)
        except sqlite3.OperationalError:
            artifact_path = Path(refs[_ARTIFACT_REF_KEYS[field]])
            trip_store.save_json(artifact_path, value)
        return
        
    if field in _SQLITE_ROW_ARTIFACT_FIELDS:
        if field == "timetable_rows":
            trip_store.save_timetable_rows(db_path, value)
        trip_store.save_rows(db_path, field, value)
        # Update summary if needed
        if field in _SUMMARY_SCALAR_NAMES:
            doc = _load_shallow(scenario_id)
            if field == "timetable_rows":
                summary = _build_timetable_summary_artifact(value, doc.get("timetable_import_meta") or {})
            elif field == "trips":
                summary = _build_trips_summary_artifact(value)
            elif field == "duties":
                summary = _build_duties_summary_artifact(value)
            else:
                summary = None
            if summary:
                trip_store.save_scalar(db_path, _SUMMARY_SCALAR_NAMES[field], summary)
        if invalidate_dispatch:
            _clear_dispatch_artifacts(refs)
        _refresh_meta_for_direct_artifact_update(
            reset_dispatch_state=invalidate_dispatch,
        )
        return
        
    if field == "graph":
        _save_graph_artifact(db_path, value)
        return

    if field in ("optimization_audit", "simulation_audit", "problemdata_build_audit"):
        doc = _load_shallow(scenario_id)
        doc[field] = value
        if invalidate_dispatch:
            _invalidate_dispatch_artifacts(doc)
        doc["meta"]["updatedAt"] = _now_iso()
        _save_master_only(doc, invalidate_dispatch=invalidate_dispatch)
        return

    doc = _load(scenario_id, skip_graph_arcs=True)
    doc[field] = value
    if invalidate_dispatch:
        _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)


def get_feed_context(scenario_id: str) -> Optional[Dict[str, Any]]:
    return _normalize_feed_context(_load_shallow(scenario_id).get("feed_context"))


def get_scenario_overlay(scenario_id: str) -> Optional[Dict[str, Any]]:
    overlay = _load_shallow(scenario_id).get("scenario_overlay")
    if not isinstance(overlay, dict):
        return None
    return dict(overlay)


def set_scenario_overlay(
    scenario_id: str,
    overlay: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    normalized_overlay = dict(overlay) if isinstance(overlay, dict) else None
    _save_master_subset(
        scenario_id,
        updates={"scenario_overlay": normalized_overlay},
        invalidate_dispatch=False,
    )
    return get_scenario_overlay(scenario_id)


def apply_dataset_bootstrap(scenario_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    with _scenario_lock(scenario_id):
        doc = _load(scenario_id, repair_missing_master=False)
        if _same_dataset_bootstrap(doc, payload) and _has_materialized_dataset_bootstrap(doc):
            return _meta_payload(doc)

        invalidate_fields = {
            "depots",
            "routes",
            "route_depot_assignments",
            "depot_route_permissions",
            "dispatch_scope",
            "timetable_rows",
            "stop_timetables",
            "calendar",
            "calendar_dates",
        }
        if any(field in payload for field in invalidate_fields):
            _invalidate_dispatch_artifacts(doc)

        for field in (
            "depots",
            "routes",
            "stops",
            "vehicle_templates",
            "route_depot_assignments",
            "depot_route_permissions",
            "dispatch_scope",
            "timetable_rows",
            "trips",
            "stop_timetables",
            "calendar",
            "calendar_dates",
            "feed_context",
            "runtime_features",
            "scenario_overlay",
        ):
            if field not in payload:
                continue
            value = payload[field]
            if isinstance(value, list):
                doc[field] = [dict(item) if isinstance(item, dict) else item for item in value]
            elif isinstance(value, dict):
                doc[field] = dict(value)
            else:
                doc[field] = value

        bootstrap_state = _bootstrap_state_from_payload(payload)
        if bootstrap_state["datasetId"]:
            doc["meta"]["datasetBootstrapDatasetId"] = bootstrap_state["datasetId"]
        if bootstrap_state["datasetVersion"]:
            doc["meta"]["datasetBootstrapVersion"] = bootstrap_state["datasetVersion"]
        if bootstrap_state["datasetFingerprint"]:
            doc["meta"]["datasetBootstrapFingerprint"] = bootstrap_state["datasetFingerprint"]
        doc["meta"]["datasetBootstrapAppliedAt"] = _now_iso()
        doc["meta"]["updatedAt"] = _now_iso()
        _save(doc)
        return _meta_payload(doc)


def set_feed_context(
    scenario_id: str,
    feed_context: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    normalized_feed_context = _normalize_feed_context(feed_context)
    _save_master_subset(
        scenario_id,
        updates={"feed_context": normalized_feed_context},
        invalidate_dispatch=False,
    )
    return normalized_feed_context


# ── Master-data helpers ────────────────────────────────────────


def _list_items(scenario_id: str, field: str) -> List[Dict[str, Any]]:
    master_path = _master_data_path(scenario_id)
    payload = master_data_store.load_master_collection(master_path, field, [])
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    return list(get_field(scenario_id, field))


def _get_item(
    scenario_id: str, field: str, item_id_key: str, item_id: str
) -> Dict[str, Any]:
    items = _list_items(scenario_id, field)
    for item in items:
        if item.get(item_id_key) == item_id:
            return item
    raise KeyError(item_id)


def _create_item(scenario_id: str, field: str, data: Dict[str, Any]) -> Dict[str, Any]:
    doc = _load_shallow(scenario_id)
    item = dict(data)
    item["id"] = item.get("id") or _new_id()
    doc[field].append(item)
    invalidate_dispatch = field in {"depots", "vehicles", "routes"}
    if field in {"depots", "vehicles", "routes"}:
        _invalidate_dispatch_artifacts(doc)
    if field in {"depots", "routes"}:
        _sync_depot_route_permissions(doc)
        _normalize_dispatch_scope(doc)
    if field in {"vehicles", "routes"}:
        _sync_vehicle_route_permissions(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save_master_subset(
        scenario_id,
        updates={
            field: list(doc[field]),
            "dispatch_scope": doc.get("dispatch_scope"),
            "depot_route_permissions": doc.get("depot_route_permissions"),
            "vehicle_route_permissions": doc.get("vehicle_route_permissions"),
        },
        invalidate_dispatch=invalidate_dispatch,
    )
    return item


def _update_item(
    scenario_id: str, field: str, item_id_key: str, item_id: str, patch: Dict[str, Any]
) -> Dict[str, Any]:
    doc = _load_shallow(scenario_id)
    for item in doc[field]:
        if item.get(item_id_key) == item_id:
            item.update({k: v for k, v in patch.items() if v is not None})
            invalidate_dispatch = field in {"depots", "vehicles", "routes"}
            if field in {"depots", "vehicles", "routes"}:
                _invalidate_dispatch_artifacts(doc)
            if field in {"depots", "routes"}:
                _sync_depot_route_permissions(doc)
                _normalize_dispatch_scope(doc)
            if field in {"vehicles", "routes"}:
                _sync_vehicle_route_permissions(doc)
            doc["meta"]["updatedAt"] = _now_iso()
            _save_master_subset(
                scenario_id,
                updates={
                    field: list(doc[field]),
                    "dispatch_scope": doc.get("dispatch_scope"),
                    "depot_route_permissions": doc.get("depot_route_permissions"),
                    "vehicle_route_permissions": doc.get("vehicle_route_permissions"),
                },
                invalidate_dispatch=invalidate_dispatch,
            )
            return item
    raise KeyError(item_id)


def _delete_item(scenario_id: str, field: str, item_id_key: str, item_id: str) -> None:
    doc = _load_shallow(scenario_id)
    before = len(doc[field])
    doc[field] = [i for i in doc[field] if i.get(item_id_key) != item_id]
    if len(doc[field]) == before:
        raise KeyError(item_id)
    invalidate_dispatch = field in {"depots", "vehicles", "routes"}
    if field in {"depots", "vehicles", "routes"}:
        _invalidate_dispatch_artifacts(doc)
    if field in {"depots", "routes"}:
        _sync_depot_route_permissions(doc)
        _normalize_dispatch_scope(doc)
    if field in {"vehicles", "routes"}:
        _sync_vehicle_route_permissions(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save_master_subset(
        scenario_id,
        updates={
            field: list(doc[field]),
            "dispatch_scope": doc.get("dispatch_scope"),
            "depot_route_permissions": doc.get("depot_route_permissions"),
            "vehicle_route_permissions": doc.get("vehicle_route_permissions"),
        },
        invalidate_dispatch=invalidate_dispatch,
    )


# ── Depot helpers ──────────────────────────────────────────────


def list_depots(scenario_id: str) -> List[Dict[str, Any]]:
    return _list_items(scenario_id, "depots")


def get_depot(scenario_id: str, depot_id: str) -> Dict[str, Any]:
    return _get_item(scenario_id, "depots", "id", depot_id)


def create_depot(scenario_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return _create_item(scenario_id, "depots", data)


def update_depot(
    scenario_id: str, depot_id: str, patch: Dict[str, Any]
) -> Dict[str, Any]:
    return _update_item(scenario_id, "depots", "id", depot_id, patch)


def delete_depot(scenario_id: str, depot_id: str) -> None:
    _delete_item(scenario_id, "depots", "id", depot_id)
    doc = _load_shallow(scenario_id)
    doc["route_depot_assignments"] = [
        item
        for item in doc.get("route_depot_assignments") or []
        if str(item.get("depotId")) != depot_id
    ]
    doc["meta"]["updatedAt"] = _now_iso()
    _save_master_subset(
        scenario_id,
        updates={
            "route_depot_assignments": doc.get("route_depot_assignments"),
            "dispatch_scope": doc.get("dispatch_scope"),
        },
        invalidate_dispatch=True,
    )


def get_public_data_state(scenario_id: str) -> Dict[str, Any]:
    doc = _load_shallow(scenario_id)
    state = doc.get("public_data")
    if not isinstance(state, dict):
        return _default_public_data_state()
    normalized = _default_public_data_state()
    normalized.update(state)
    return normalized


def set_public_data_state(scenario_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    doc = _load_shallow(scenario_id)
    normalized = _default_public_data_state()
    normalized.update(state)
    doc["public_data"] = normalized
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return dict(normalized)


def get_app_context() -> Dict[str, Any]:
    return _load_app_context()


def set_active_scenario(
    scenario_id: Optional[str],
    *,
    last_opened_page: Optional[str] = None,
) -> Dict[str, Any]:
    context = _load_app_context()
    context["activeScenarioId"] = scenario_id
    context["selectedOperatorId"] = None
    if scenario_id is not None:
        scenario = _load(scenario_id)
        context["selectedOperatorId"] = (
            scenario.get("meta") or {}
        ).get("operatorId")
    if last_opened_page is not None:
        context["lastOpenedPage"] = last_opened_page
    context["updatedAt"] = _now_iso()
    _save_app_context(context)
    return dict(context)


# ── Vehicle helpers ────────────────────────────────────────────


def list_vehicles(
    scenario_id: str, depot_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    items = _list_items(scenario_id, "vehicles")
    if depot_id:
        items = [v for v in items if v.get("depotId") == depot_id]
    return items


def get_vehicle(scenario_id: str, vehicle_id: str) -> Dict[str, Any]:
    return _get_item(scenario_id, "vehicles", "id", vehicle_id)


def create_vehicle(scenario_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return _create_item(scenario_id, "vehicles", data)


def _next_vehicle_copy_name(existing_names: set[str], base_name: str) -> str:
    candidate = f"{base_name} (copy)"
    if candidate not in existing_names:
        existing_names.add(candidate)
        return candidate

    idx = 2
    while True:
        candidate = f"{base_name} (copy {idx})"
        if candidate not in existing_names:
            existing_names.add(candidate)
            return candidate
        idx += 1


def create_vehicle_batch(
    scenario_id: str, data: Dict[str, Any], quantity: int
) -> List[Dict[str, Any]]:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")

    if quantity == 1:
        return [create_vehicle(scenario_id, data)]

    doc = _load(scenario_id, skip_graph_arcs=True)
    base_name = (data.get("modelName") or "New vehicle").strip() or "New vehicle"
    created: List[Dict[str, Any]] = []

    for idx in range(quantity):
        item = dict(data)
        item["id"] = _new_id()
        item["modelName"] = f"{base_name} #{idx + 1}"
        doc["vehicles"].append(item)
        created.append(item)

    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return created


def _allowed_route_ids_for_depot(
    doc: Dict[str, Any], depot_id: str
) -> Optional[set[str]]:
    matching_permissions = [
        permission
        for permission in doc.get("depot_route_permissions", [])
        if permission.get("depotId") == depot_id
    ]
    if not matching_permissions:
        return None
    return {
        str(permission.get("routeId"))
        for permission in matching_permissions
        if permission.get("allowed") is True
    }


def duplicate_vehicle_batch(
    scenario_id: str,
    vehicle_id: str,
    quantity: int,
    target_depot_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    if quantity < 1:
        raise ValueError("quantity must be >= 1")

    doc = _load(scenario_id, skip_graph_arcs=True)
    source = next((v for v in doc["vehicles"] if v.get("id") == vehicle_id), None)
    if source is None:
        raise KeyError(vehicle_id)
    effective_target_depot_id = target_depot_id or source.get("depotId")

    existing_names = {
        (item.get("modelName") or "").strip()
        for item in doc["vehicles"]
        if isinstance(item.get("modelName"), str)
    }
    base_name = (source.get("modelName") or "Vehicle").strip() or "Vehicle"
    source_permissions = [
        perm
        for perm in doc.get("vehicle_route_permissions", [])
        if perm.get("vehicleId") == vehicle_id
    ]
    allowed_route_ids = (
        _allowed_route_ids_for_depot(doc, str(effective_target_depot_id))
        if effective_target_depot_id
        else set()
    )
    created_items: List[Dict[str, Any]] = []

    for _ in range(quantity):
        created = {k: v for k, v in source.items() if k != "id"}
        created["id"] = _new_id()
        if effective_target_depot_id:
            created["depotId"] = effective_target_depot_id
        created["modelName"] = _next_vehicle_copy_name(existing_names, base_name)
        doc["vehicles"].append(created)
        created_items.append(created)

        for perm in source_permissions:
            route_id = perm.get("routeId")
            if allowed_route_ids is not None and route_id not in allowed_route_ids:
                continue
            doc["vehicle_route_permissions"].append(
                {
                    **perm,
                    "vehicleId": created["id"],
                }
            )

    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return created_items


def update_vehicle(
    scenario_id: str, vehicle_id: str, patch: Dict[str, Any]
) -> Dict[str, Any]:
    return _update_item(scenario_id, "vehicles", "id", vehicle_id, patch)


def delete_vehicle(scenario_id: str, vehicle_id: str) -> None:
    doc = _load(scenario_id, skip_graph_arcs=True)
    before = len(doc["vehicles"])
    doc["vehicles"] = [v for v in doc["vehicles"] if v.get("id") != vehicle_id]
    if len(doc["vehicles"]) == before:
        raise KeyError(vehicle_id)
    doc["vehicle_route_permissions"] = [
        p for p in doc["vehicle_route_permissions"] if p.get("vehicleId") != vehicle_id
    ]
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)


def duplicate_vehicle(scenario_id: str, vehicle_id: str) -> Dict[str, Any]:
    return duplicate_vehicle_batch(scenario_id, vehicle_id, quantity=1)[0]


def duplicate_vehicle_to_depot(
    scenario_id: str,
    vehicle_id: str,
    *,
    target_depot_id: Optional[str] = None,
) -> Dict[str, Any]:
    return duplicate_vehicle_batch(
        scenario_id,
        vehicle_id,
        quantity=1,
        target_depot_id=target_depot_id,
    )[0]


def list_vehicle_templates(scenario_id: str) -> List[Dict[str, Any]]:
    doc = _load_shallow(scenario_id)
    return list(doc.get("vehicle_templates") or [])


def get_vehicle_template(scenario_id: str, template_id: str) -> Dict[str, Any]:
    doc = _load_shallow(scenario_id)
    for item in doc.get("vehicle_templates") or []:
        if item.get("id") == template_id:
            return item
    raise KeyError(template_id)


def create_vehicle_template(scenario_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    doc = _load(scenario_id, skip_graph_arcs=True)
    item = dict(data)
    item["id"] = _new_id()
    doc.setdefault("vehicle_templates", []).append(item)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return item


def update_vehicle_template(
    scenario_id: str, template_id: str, patch: Dict[str, Any]
) -> Dict[str, Any]:
    doc = _load(scenario_id, skip_graph_arcs=True)
    templates = doc.setdefault("vehicle_templates", [])
    for item in templates:
        if item.get("id") == template_id:
            item.update({k: v for k, v in patch.items() if v is not None})
            doc["meta"]["updatedAt"] = _now_iso()
            _save(doc)
            return item
    raise KeyError(template_id)


def delete_vehicle_template(scenario_id: str, template_id: str) -> None:
    doc = _load(scenario_id, skip_graph_arcs=True)
    templates = doc.setdefault("vehicle_templates", [])
    before = len(templates)
    doc["vehicle_templates"] = [i for i in templates if i.get("id") != template_id]
    if len(doc["vehicle_templates"]) == before:
        raise KeyError(template_id)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)


# ── Route helpers ──────────────────────────────────────────────


def _operator_matches_route(route: Dict[str, Any], operator: Optional[str]) -> bool:
    if not operator:
        return True
    source = str(route.get("source") or "").lower()
    if operator == "tokyu":
        return source in {"", "manual", "seed"}
    if operator == "toei":
        return source in {"", "manual", "gtfs"}
    return source == operator.lower()


def _route_assignment_map(doc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    valid_route_ids = {
        str(route.get("id"))
        for route in doc.get("routes") or []
        if route.get("id") is not None
    }
    valid_depot_ids = {
        str(depot.get("id"))
        for depot in doc.get("depots") or []
        if depot.get("id") is not None
    }
    assignments: Dict[str, Dict[str, Any]] = {}
    for item in doc.get("route_depot_assignments") or []:
        route_id = item.get("routeId")
        depot_id = item.get("depotId")
        if route_id is None or depot_id is None:
            continue
        route_id = str(route_id)
        depot_id = str(depot_id)
        if route_id not in valid_route_ids or depot_id not in valid_depot_ids:
            continue
        assignments[route_id] = {
            "routeId": route_id,
            "depotId": depot_id,
            "assignmentType": str(item.get("assignmentType") or "manual_override"),
            "confidence": float(item.get("confidence") or 0.0),
            "reason": str(item.get("reason") or ""),
            "sourceRefs": list(item.get("sourceRefs") or []),
            "updatedAt": str(item.get("updatedAt") or _now_iso()),
        }
    return assignments


def list_routes(
    scenario_id: str,
    depot_id: Optional[str] = None,
    operator: Optional[str] = None,
) -> List[Dict[str, Any]]:
    doc = _load_shallow(scenario_id)
    assignments = _route_assignment_map(doc)
    items: List[Dict[str, Any]] = []
    for route in doc.get("routes") or []:
        if not _operator_matches_route(route, operator):
            continue
        route_id = route.get("id")
        assignment = assignments.get(str(route_id)) if route_id is not None else None
        effective_depot_id = (
            assignment.get("depotId") if assignment else route.get("depotId")
        )
        if depot_id and effective_depot_id != depot_id:
            continue
        items.append(
            {
                **route,
                "depotId": effective_depot_id,
                "assignmentType": assignment.get("assignmentType")
                if assignment
                else None,
                "assignmentConfidence": assignment.get("confidence")
                if assignment
                else None,
                "assignmentReason": assignment.get("reason") if assignment else None,
                "stopCount": len(coerce_list(route.get("stopSequence"))),
            }
        )
    return items


def get_route(scenario_id: str, route_id: str) -> Dict[str, Any]:
    doc = _load_shallow(scenario_id)
    route = _get_item(scenario_id, "routes", "id", route_id)
    assignment = _route_assignment_map(doc).get(route_id)
    if assignment is None:
        return route
    return {
        **route,
        "depotId": assignment.get("depotId"),
        "assignmentType": assignment.get("assignmentType"),
        "assignmentConfidence": assignment.get("confidence"),
        "assignmentReason": assignment.get("reason"),
    }


def create_route(scenario_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    return _create_item(scenario_id, "routes", data)


def update_route(
    scenario_id: str, route_id: str, patch: Dict[str, Any]
) -> Dict[str, Any]:
    return _update_item(scenario_id, "routes", "id", route_id, patch)


def delete_route(scenario_id: str, route_id: str) -> None:
    _delete_item(scenario_id, "routes", "id", route_id)
    doc = _load(scenario_id, skip_graph_arcs=True)
    doc["route_depot_assignments"] = [
        item
        for item in doc.get("route_depot_assignments") or []
        if str(item.get("routeId")) != route_id
    ]
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)


def replace_routes_from_source(
    scenario_id: str,
    source: str,
    routes: List[Dict[str, Any]],
    import_meta: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id, skip_graph_arcs=True)
    route_import_meta = doc.setdefault("route_import_meta", {})
    preserved = [r for r in doc["routes"] if r.get("source") != source]
    doc["routes"] = preserved + routes
    surviving_route_ids = {
        str(r.get("id")) for r in doc["routes"] if r.get("id") is not None
    }
    doc["route_depot_assignments"] = [
        assignment
        for assignment in doc.get("route_depot_assignments") or []
        if str(assignment.get("routeId") or "") in surviving_route_ids
    ]
    if import_meta is not None:
        route_import_meta[source] = import_meta

    doc["depot_route_permissions"] = [
        perm
        for perm in doc.get("depot_route_permissions") or []
        if str(perm.get("routeId", "")) in surviving_route_ids
    ]
    doc["vehicle_route_permissions"] = [
        perm
        for perm in doc.get("vehicle_route_permissions") or []
        if str(perm.get("routeId", "")) in surviving_route_ids
    ]

    _invalidate_dispatch_artifacts(doc)
    _normalize_dispatch_scope(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return list(doc["routes"])


def get_route_import_meta(
    scenario_id: str, source: Optional[str] = None
) -> Dict[str, Any]:
    doc = _load_shallow(scenario_id)
    route_import_meta = doc.get("route_import_meta") or {}
    if source is None:
        return dict(route_import_meta)
    value = route_import_meta.get(source)
    return dict(value) if isinstance(value, dict) else {}


def list_route_depot_assignments(
    scenario_id: str,
    operator: Optional[str] = None,
    unresolved_only: bool = False,
) -> List[Dict[str, Any]]:
    doc = _load_shallow(scenario_id)
    routes_by_id = {
        str(route.get("id")): dict(route)
        for route in doc.get("routes") or []
        if route.get("id") is not None and _operator_matches_route(route, operator)
    }
    depots_by_id = {
        str(depot.get("id")): dict(depot)
        for depot in doc.get("depots") or []
        if depot.get("id") is not None
    }
    assignments = _route_assignment_map(doc)
    items: List[Dict[str, Any]] = []
    for route_id, route in routes_by_id.items():
        assignment = assignments.get(route_id)
        if unresolved_only and assignment is not None:
            continue
        depot = depots_by_id.get(str(assignment.get("depotId"))) if assignment else None
        items.append(
            {
                "routeId": route_id,
                "routeName": route.get("name"),
                "routeCode": route.get("routeCode") or route_id,
                "startStop": route.get("startStop"),
                "endStop": route.get("endStop"),
                "source": route.get("source"),
                "tripCount": route.get("tripCount") or 0,
                "stopCount": len(coerce_list(route.get("stopSequence"))),
                "depotId": assignment.get("depotId") if assignment else None,
                "depotName": depot.get("name") if depot else None,
                "assignmentType": assignment.get("assignmentType")
                if assignment
                else None,
                "confidence": assignment.get("confidence") if assignment else None,
                "reason": assignment.get("reason") if assignment else "",
                "sourceRefs": assignment.get("sourceRefs") if assignment else [],
                "updatedAt": assignment.get("updatedAt") if assignment else None,
            }
        )
    items.sort(
        key=lambda item: (
            str(item.get("depotName") or "~"),
            str(item.get("routeCode") or ""),
            str(item.get("routeName") or ""),
        )
    )
    return items


def upsert_route_depot_assignment(
    scenario_id: str,
    route_id: str,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    doc = _load_shallow(scenario_id)
    resolved_route_id = None
    for route in doc.get("routes") or []:
        route_keys = {
            str(value)
            for value in (
                route.get("id"),
                route.get("patternId"),
                route.get("routeExternalId"),
            )
            if value is not None
        }
        if route_id in route_keys:
            resolved_route_id = str(route.get("id"))
            break
    if resolved_route_id is None:
        raise KeyError(route_id)
    route_id = resolved_route_id

    depot_id = data.get("depotId")
    if depot_id is not None:
        depot_id = str(depot_id)
        valid_depot_ids = {
            str(depot.get("id"))
            for depot in doc.get("depots") or []
            if depot.get("id") is not None
        }
        if depot_id not in valid_depot_ids:
            raise ValueError(f"Unknown depot '{depot_id}'")

    doc["route_depot_assignments"] = [
        item
        for item in doc.get("route_depot_assignments") or []
        if str(item.get("routeId")) != route_id
    ]
    if depot_id is not None:
        doc["route_depot_assignments"].append(
            {
                "routeId": route_id,
                "depotId": depot_id,
                "assignmentType": str(data.get("assignmentType") or "manual_override"),
                "confidence": float(data.get("confidence") or 1.0),
                "reason": str(data.get("reason") or ""),
                "sourceRefs": list(data.get("sourceRefs") or []),
                "updatedAt": _now_iso(),
            }
        )
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save_master_only(doc, invalidate_dispatch=True)
    assignment = _route_assignment_map(doc).get(route_id)
    return {
        "routeId": route_id,
        "depotId": assignment.get("depotId") if assignment else None,
        "assignmentType": assignment.get("assignmentType") if assignment else None,
        "confidence": assignment.get("confidence") if assignment else None,
        "reason": assignment.get("reason") if assignment else "",
        "sourceRefs": assignment.get("sourceRefs") if assignment else [],
        "updatedAt": assignment.get("updatedAt") if assignment else None,
    }


def list_stops(scenario_id: str) -> List[Dict[str, Any]]:
    return _list_items(scenario_id, "stops")


def replace_stops_from_source(
    scenario_id: str,
    source: str,
    stops: List[Dict[str, Any]],
    import_meta: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    doc = _load_shallow(scenario_id)
    stop_import_meta = doc.setdefault("stop_import_meta", {})
    preserved = [stop for stop in doc.get("stops", []) if stop.get("source") != source]
    normalized_stops = []
    seen_ids = set()
    for stop in stops:
        stop_id = stop.get("id")
        if not stop_id or stop_id in seen_ids:
            continue
        seen_ids.add(stop_id)
        normalized_stops.append(dict(stop))
    doc["stops"] = preserved + normalized_stops
    if import_meta is not None:
        stop_import_meta[source] = import_meta
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return list(doc["stops"])


def get_stop_import_meta(
    scenario_id: str, source: Optional[str] = None
) -> Dict[str, Any]:
    doc = _load_shallow(scenario_id)
    stop_import_meta = doc.get("stop_import_meta") or {}
    if source is None:
        return dict(stop_import_meta)
    value = stop_import_meta.get(source)
    return dict(value) if isinstance(value, dict) else {}


def set_stop_import_meta(
    scenario_id: str, source: str, import_meta: Dict[str, Any]
) -> Dict[str, Any]:
    doc = _load_shallow(scenario_id)
    stop_import_meta = doc.setdefault("stop_import_meta", {})
    stop_import_meta[source] = import_meta
    doc["meta"]["updatedAt"] = _now_iso()
    _save_master_only(doc, invalidate_dispatch=False)
    return dict(import_meta)


def set_timetable_import_meta(
    scenario_id: str, source: str, import_meta: Dict[str, Any]
) -> Dict[str, Any]:
    doc = _load_shallow(scenario_id)
    timetable_import_meta = doc.setdefault("timetable_import_meta", {})
    timetable_import_meta[source] = import_meta
    doc["meta"]["updatedAt"] = _now_iso()
    _save_master_only(doc, invalidate_dispatch=False)
    return dict(import_meta)


def get_timetable_import_meta(
    scenario_id: str, source: Optional[str] = None
) -> Dict[str, Any]:
    doc = _load_shallow(scenario_id)
    timetable_import_meta = doc.get("timetable_import_meta") or {}
    if source is None:
        return dict(timetable_import_meta)
    value = timetable_import_meta.get(source)
    return dict(value) if isinstance(value, dict) else {}


def upsert_timetable_rows_from_source(
    scenario_id: str,
    source: str,
    rows: List[Dict[str, Any]],
    *,
    replace_existing_source: bool = False,
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id, skip_graph_arcs=True)
    existing_rows = list(doc.get("timetable_rows") or [])

    preserved_rows = [row for row in existing_rows if row.get("source") != source]
    source_rows = (
        []
        if replace_existing_source
        else [row for row in existing_rows if row.get("source") == source]
    )

    def _row_key(row: Dict[str, Any]) -> str:
        trip_id = row.get("trip_id")
        if trip_id:
            return f"trip:{trip_id}"
        return json.dumps(
            {
                "route_id": row.get("route_id"),
                "service_id": row.get("service_id"),
                "direction": row.get("direction"),
                "origin": row.get("origin"),
                "destination": row.get("destination"),
                "departure": row.get("departure"),
                "arrival": row.get("arrival"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )

    merged: Dict[str, Dict[str, Any]] = {}
    for row in source_rows:
        merged[_row_key(row)] = dict(row)
    for row in rows:
        candidate = dict(row)
        candidate["source"] = source
        merged[_row_key(candidate)] = candidate

    doc["timetable_rows"] = preserved_rows + list(merged.values())
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return list(doc["timetable_rows"])


def set_stop_timetable_import_meta(
    scenario_id: str, source: str, import_meta: Dict[str, Any]
) -> Dict[str, Any]:
    doc = _load_shallow(scenario_id)
    stop_timetable_import_meta = doc.setdefault("stop_timetable_import_meta", {})
    stop_timetable_import_meta[source] = import_meta
    doc["meta"]["updatedAt"] = _now_iso()
    _save_master_only(doc, invalidate_dispatch=False)
    return dict(import_meta)


def get_stop_timetable_import_meta(
    scenario_id: str, source: Optional[str] = None
) -> Dict[str, Any]:
    doc = _load_shallow(scenario_id)
    stop_timetable_import_meta = doc.get("stop_timetable_import_meta") or {}
    if source is None:
        return dict(stop_timetable_import_meta)
    value = stop_timetable_import_meta.get(source)
    return dict(value) if isinstance(value, dict) else {}


def upsert_stop_timetables_from_source(
    scenario_id: str,
    source: str,
    items: List[Dict[str, Any]],
    *,
    replace_existing_source: bool = False,
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id, skip_graph_arcs=True)
    existing_items = list(doc.get("stop_timetables") or [])
    preserved_items = [item for item in existing_items if item.get("source") != source]
    source_items = (
        []
        if replace_existing_source
        else [item for item in existing_items if item.get("source") == source]
    )

    merged: Dict[str, Dict[str, Any]] = {
        str(item.get("id") or item.get("stopId") or uuid.uuid4()): dict(item)
        for item in source_items
    }
    for item in items:
        candidate = dict(item)
        candidate["source"] = source
        merged[str(candidate.get("id") or candidate.get("stopId") or uuid.uuid4())] = (
            candidate
        )

    doc["stop_timetables"] = preserved_items + list(merged.values())
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return list(doc["stop_timetables"])


# ── Permission helpers ─────────────────────────────────────────


def get_depot_route_permissions(scenario_id: str) -> List[Dict[str, Any]]:
    doc = _load_shallow(scenario_id)
    return list(doc.get("depot_route_permissions") or [])


def set_depot_route_permissions(
    scenario_id: str, permissions: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    doc = _load_shallow(scenario_id)
    # Store permissions as given by the caller (may reference entities
    # not yet created, e.g. during cross-scenario setup). The _sync
    # helpers are called on entity lifecycle events to prune stale entries.
    sanitized = [
        {
            "depotId": str(item.get("depotId")),
            "routeId": str(item.get("routeId")),
            "allowed": bool(item.get("allowed")),
        }
        for item in permissions
        if item.get("depotId") is not None and item.get("routeId") is not None
    ]
    doc["depot_route_permissions"] = sanitized
    _invalidate_dispatch_artifacts(doc)
    _normalize_dispatch_scope(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save_master_only(doc, invalidate_dispatch=True)
    return list(sanitized)


def get_vehicle_route_permissions(scenario_id: str) -> List[Dict[str, Any]]:
    doc = _load_shallow(scenario_id)
    return list(doc.get("vehicle_route_permissions") or [])


def set_vehicle_route_permissions(
    scenario_id: str, permissions: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    doc = _load_shallow(scenario_id)
    # Store permissions as given by the caller (may reference entities
    # not yet created). The _sync helpers are called on entity lifecycle
    # events to prune stale entries.
    sanitized = [
        {
            "vehicleId": str(item.get("vehicleId")),
            "routeId": str(item.get("routeId")),
            "allowed": bool(item.get("allowed")),
        }
        for item in permissions
        if item.get("vehicleId") is not None and item.get("routeId") is not None
    ]
    doc["vehicle_route_permissions"] = sanitized
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save_master_only(doc, invalidate_dispatch=True)
    return list(sanitized)


def get_deadhead_rules(scenario_id: str) -> List[Dict[str, Any]]:
    doc = _load_shallow(scenario_id)
    return list(doc.get("deadhead_rules") or [])


def set_deadhead_rules(
    scenario_id: str, rules: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id, skip_graph_arcs=True)

    def _optional_float(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        return float(value)

    sanitized = [
        {
            "from_stop": str(item.get("from_stop")),
            "to_stop": str(item.get("to_stop")),
            "travel_time_min": int(item.get("travel_time_min") or 0),
            "distance_km": float(item.get("distance_km") or 0.0),
            "energy_kwh_bev": _optional_float(item.get("energy_kwh_bev")),
            "fuel_l_ice": _optional_float(item.get("fuel_l_ice")),
        }
        for item in rules
        if item.get("from_stop") is not None and item.get("to_stop") is not None
    ]
    doc["deadhead_rules"] = sanitized
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return list(sanitized)


def get_turnaround_rules(scenario_id: str) -> List[Dict[str, Any]]:
    doc = _load_shallow(scenario_id)
    return list(doc.get("turnaround_rules") or [])


def set_turnaround_rules(
    scenario_id: str, rules: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id, skip_graph_arcs=True)
    sanitized = [
        {
            "stop_id": str(item.get("stop_id")),
            "min_turnaround_min": int(item.get("min_turnaround_min") or 0),
        }
        for item in rules
        if item.get("stop_id") is not None
    ]
    doc["turnaround_rules"] = sanitized
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return list(sanitized)


def get_dispatch_scope(scenario_id: str) -> Dict[str, Any]:
    doc = _load_shallow(scenario_id)
    return _normalize_dispatch_scope(doc)


def set_dispatch_scope(scenario_id: str, scope: Dict[str, Any]) -> Dict[str, Any]:
    doc = _load(scenario_id, skip_graph_arcs=True)
    current = _normalize_dispatch_scope(doc)
    depot_selection = dict(current.get("depotSelection") or {})
    route_selection = dict(current.get("routeSelection") or {})
    service_selection = dict(current.get("serviceSelection") or {})
    trip_selection = dict(current.get("tripSelection") or {})

    incoming_depot_selection = scope.get("depotSelection")
    if isinstance(incoming_depot_selection, dict):
        depot_selection.update(incoming_depot_selection)
    if "depotId" in scope:
        depot_selection["primaryDepotId"] = scope.get("depotId")
        if scope.get("depotId") is None:
            depot_selection["depotIds"] = []
        else:
            depot_selection["depotIds"] = [scope.get("depotId")]

    incoming_route_selection = scope.get("routeSelection")
    if isinstance(incoming_route_selection, dict):
        route_selection.update(incoming_route_selection)

    incoming_service_selection = scope.get("serviceSelection")
    if isinstance(incoming_service_selection, dict):
        service_selection.update(incoming_service_selection)
    if "serviceId" in scope:
        service_selection["serviceIds"] = [scope.get("serviceId")]

    incoming_trip_selection = scope.get("tripSelection")
    if isinstance(incoming_trip_selection, dict):
        trip_selection.update(incoming_trip_selection)

    next_scope = {
        "scopeId": scope.get("scopeId", current.get("scopeId")),
        "operatorId": scope.get("operatorId", current.get("operatorId")),
        "datasetVersion": scope.get("datasetVersion", current.get("datasetVersion")),
        "depotSelection": depot_selection,
        "routeSelection": route_selection,
        "serviceSelection": service_selection,
        "tripSelection": trip_selection,
        "allowIntraDepotRouteSwap": scope.get(
            "allowIntraDepotRouteSwap",
            current.get("allowIntraDepotRouteSwap", False),
        ),
        "allowInterDepotSwap": scope.get(
            "allowInterDepotSwap",
            current.get("allowInterDepotSwap", False),
        ),
        "fixedRouteBandMode": scope.get(
            "fixedRouteBandMode",
            current.get("fixedRouteBandMode", True),
        ),
        "depotId": depot_selection.get("primaryDepotId"),
        "serviceId": (
            (service_selection.get("serviceIds") or [current.get("serviceId") or "WEEKDAY"])[0]
        ),
    }
    doc["dispatch_scope"] = next_scope
    normalized = _normalize_dispatch_scope(doc)
    overlay = doc.get("scenario_overlay")
    if isinstance(overlay, dict):
        updated_overlay = dict(overlay)
        updated_overlay["depot_ids"] = list(
            (normalized.get("depotSelection") or {}).get("depotIds") or []
        )
        updated_overlay["route_ids"] = list(normalized.get("effectiveRouteIds") or [])
        dataset_version = str(normalized.get("datasetVersion") or "").strip()
        if dataset_version:
            updated_overlay["dataset_version"] = dataset_version
        doc["scenario_overlay"] = updated_overlay
    if normalized != current:
        _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return normalized


def effective_route_ids_for_scope(
    scenario_id: str,
    scope: Optional[Dict[str, Any]] = None,
) -> List[str]:
    doc = _load_shallow(scenario_id)
    if scope is not None:
        doc["dispatch_scope"] = scope
    normalized = _normalize_dispatch_scope(doc)
    return list(normalized.get("effectiveRouteIds") or [])


def route_ids_for_selected_depots(
    scenario_id: str,
    scope: Optional[Dict[str, Any]] = None,
) -> List[str]:
    doc = _load_shallow(scenario_id)
    if scope is not None:
        doc["dispatch_scope"] = scope
    normalized = _normalize_dispatch_scope(doc)
    return list(normalized.get("candidateRouteIds") or [])


# ── Calendar helpers ───────────────────────────────────────────


def get_calendar(scenario_id: str) -> List[Dict[str, Any]]:
    """Return the list of service_id definitions for this scenario."""
    doc = _load(scenario_id, skip_graph_arcs=True)
    return doc.get("calendar") or _default_calendar()


def set_calendar(
    scenario_id: str, entries: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Replace the entire calendar (list of service_id definitions)."""
    doc = _load(scenario_id, skip_graph_arcs=True)
    doc["calendar"] = entries
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return entries


def upsert_calendar_entry(scenario_id: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Insert or update a single service_id entry (keyed by service_id)."""
    doc = _load(scenario_id, skip_graph_arcs=True)
    calendar: List[Dict[str, Any]] = doc.get("calendar") or _default_calendar()
    sid = entry["service_id"]
    replaced = False
    for i, e in enumerate(calendar):
        if e.get("service_id") == sid:
            calendar[i] = entry
            replaced = True
            break
    if not replaced:
        calendar.append(entry)
    doc["calendar"] = calendar
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return entry


def delete_calendar_entry(scenario_id: str, service_id: str) -> None:
    """Delete a service_id definition. Raises KeyError if not found."""
    doc = _load(scenario_id, skip_graph_arcs=True)
    calendar: List[Dict[str, Any]] = doc.get("calendar") or []
    before = len(calendar)
    doc["calendar"] = [e for e in calendar if e.get("service_id") != service_id]
    if len(doc["calendar"]) == before:
        raise KeyError(service_id)
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)


# ── Calendar dates helpers ─────────────────────────────────────


def get_calendar_dates(scenario_id: str) -> List[Dict[str, Any]]:
    """Return exception date overrides for this scenario."""
    doc = _load(scenario_id, skip_graph_arcs=True)
    return doc.get("calendar_dates") or []


def set_calendar_dates(
    scenario_id: str, entries: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Replace the entire calendar_dates list."""
    doc = _load(scenario_id, skip_graph_arcs=True)
    doc["calendar_dates"] = entries
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return entries


def upsert_calendar_date(scenario_id: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Insert or update a single date exception (keyed by date)."""
    doc = _load(scenario_id, skip_graph_arcs=True)
    dates: List[Dict[str, Any]] = doc.get("calendar_dates") or []
    date_key = entry["date"]
    replaced = False
    for i, e in enumerate(dates):
        if e.get("date") == date_key:
            dates[i] = entry
            replaced = True
            break
    if not replaced:
        dates.append(entry)
    doc["calendar_dates"] = dates
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return entry


def delete_calendar_date(scenario_id: str, date: str) -> None:
    """Delete a date exception. Raises KeyError if not found."""
    doc = _load(scenario_id, skip_graph_arcs=True)
    dates: List[Dict[str, Any]] = doc.get("calendar_dates") or []
    before = len(dates)
    doc["calendar_dates"] = [e for e in dates if e.get("date") != date]
    if len(doc["calendar_dates"]) == before:
        raise KeyError(date)
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
