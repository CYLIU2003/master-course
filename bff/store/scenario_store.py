"""
bff/store/scenario_store.py

JSON-file-backed scenario store.
One file per scenario: outputs/scenarios/{scenario_id}.json

Each file stores the complete scenario document:
{
    "meta":    { id, name, description, mode, createdAt, updatedAt, status },
    "depots":  [ Depot ... ],
    "vehicles": [ Vehicle ... ],
    "routes":  [ Route ... ],
    "stops":   [ Stop ... ],
    "depot_route_permissions":   [ {depotId, routeId, allowed} ... ],
    "vehicle_route_permissions": [ {vehicleId, routeId, allowed} ... ],
    "route_import_meta": { "odpt": { ... } },
    "stop_import_meta": { "odpt": { ... } },
    "timetable_import_meta": { "odpt": { ... } },
    "stop_timetable_import_meta": { "odpt": { ... } },
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
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from bff.services.service_ids import canonical_service_id
from bff.store import master_data_store, scenario_meta_store, trip_store

_STORE_DIR = Path(__file__).parent.parent.parent / "outputs" / "scenarios"
_APP_CONTEXT_PATH = Path(__file__).parent.parent.parent / "outputs" / "app_context.json"
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
_SQLITE_ROW_ARTIFACT_FIELDS = {"timetable_rows", "stop_timetables", "trips", "blocks", "duties"}
_SQLITE_SCALAR_ARTIFACT_FIELDS = {"dispatch_plan", "simulation_result", "optimization_result"}
_SUMMARY_SCALAR_NAMES = {
    "timetable_rows": "timetable_summary",
    "trips": "trips_summary",
    "duties": "duties_summary",
}


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
        },
        "serviceSelection": {
            "serviceIds": ["WEEKDAY"],
        },
        "tripSelection": {
            "includeShortTurn": True,
            "includeDepotMoves": True,
            "includeDeadhead": True,
        },
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


def _path(scenario_id: str) -> Path:
    return scenario_meta_store.scenario_path(_STORE_DIR, scenario_id)


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
        refs.update({k: str(v) for k, v in (payload.get("refs") or {}).items() if v})
    return refs


def _artifact_store_path(refs: Dict[str, str]) -> Path:
    return Path(refs["artifactStore"])


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


def _build_timetable_summary_artifact(rows: List[Dict[str, Any]], imports: Dict[str, Any]) -> Dict[str, Any]:
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


def _load(scenario_id: str) -> Dict[str, Any]:
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
            graph_value = _load_graph_artifact(artifact_db_path, artifact_path)
            doc[field] = graph_value
            continue
        if field == "timetable_rows":
            if trip_store.count_timetable_rows(artifact_db_path) > 0:
                doc[field] = trip_store.page_timetable_rows(artifact_db_path, offset=0, limit=None)
            elif trip_store.count_rows(artifact_db_path, field) > 0:
                doc[field] = trip_store.load_rows(artifact_db_path, field)
            elif artifact_path.exists():
                doc[field] = _load_json_list(artifact_path)
            elif _legacy_timetable_path(scenario_id).exists():
                doc[field] = _load_json_list(_legacy_timetable_path(scenario_id))
            else:
                doc[field] = _load_split_or_inline(artifact_path, doc.get(field))
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

    doc.setdefault("calendar", _default_calendar())
    doc.setdefault("calendar_dates", [])
    doc.setdefault("simulation_config", None)
    doc.setdefault("dispatch_scope", _default_dispatch_scope())
    doc.setdefault("public_data", _default_public_data_state())
    doc.setdefault("stats", _scenario_stats(doc))
    for key, value in _default_v1_2_fields().items():
        doc.setdefault(key, value)
    return doc


def _save(doc: Dict[str, Any]) -> None:
    _ensure_dir()
    scenario_id = doc["meta"]["id"]
    refs = _refs_for_scenario(scenario_id, doc)
    artifact_db_path = _artifact_store_path(refs)

    master_payload = {key: doc.get(key) for key in _MASTER_DATA_KEYS}
    master_data_store.save_master_data(Path(refs["masterData"]), master_payload)

    preserved_artifacts: Dict[str, Any] = {}
    for field, ref_key in _ARTIFACT_REF_KEYS.items():
        preserved_artifacts[field] = doc.get(field)
        target_path = Path(refs[ref_key])
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
        if target_path.exists():
            target_path.unlink()

    slim_doc = {
        "scenarioId": scenario_id,
        "name": doc.get("meta", {}).get("name"),
        "meta": {
            **dict(doc.get("meta") or {}),
            **_scope_summary(doc.get("dispatch_scope")),
        },
        "feed_context": doc.get("feed_context"),
        "refs": refs,
        "stats": _scenario_stats(doc),
    }
    scenario_meta_store.save_meta(_STORE_DIR, scenario_id, slim_doc)

    doc["refs"] = refs
    doc["stats"] = slim_doc["stats"]
    for field, value in preserved_artifacts.items():
        doc[field] = value


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
    source = str(feed_context.get("source") or "").strip()
    if not any((feed_id, snapshot_id, dataset_id, source)):
        return None
    return {
        "feedId": feed_id or None,
        "snapshotId": snapshot_id or None,
        "datasetId": dataset_id or None,
        "source": source or None,
    }


def _meta_payload(doc: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(doc["meta"])
    payload.setdefault("operatorId", "tokyu")
    payload["feedContext"] = _normalize_feed_context(doc.get("feed_context"))
    if "refs" in doc:
        payload["refs"] = dict(doc.get("refs") or {})
    if "stats" in doc:
        payload["stats"] = dict(doc.get("stats") or {})
    return payload


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
        for item in doc.get("depot_route_permissions") or []:
            route_id = item.get("routeId")
            depot_id = item.get("depotId")
            if route_id is None or depot_id is None:
                continue
            route_id = str(route_id)
            if (
                route_id in route_ids
                and str(depot_id) in selected_depots
                and bool(item.get("allowed")) is True
                and route_id not in candidate_route_ids
            ):
                candidate_route_ids.append(route_id)
    else:
        candidate_route_ids = sorted(route_ids)

    if route_mode == "all":
        effective_route_ids = [route_id for route_id in sorted(route_ids) if route_id not in exclude_route_ids]
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
        },
        "serviceSelection": {
            "serviceIds": selected_service_ids,
        },
        "tripSelection": normalized_trip_selection,
        "depotId": primary_depot_id,
        "serviceId": selected_service_ids[0],
        "candidateRouteIds": candidate_route_ids,
        "effectiveRouteIds": effective_route_ids,
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


def get_scenario(scenario_id: str) -> Dict[str, Any]:
    return _meta_payload(_load(scenario_id))


def update_scenario(
    scenario_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    mode: Optional[str] = None,
    operator_id: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    doc = _load(scenario_id)
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
    _save(doc)
    return _meta_payload(doc)


def delete_scenario(scenario_id: str) -> None:
    p = _path(scenario_id)
    if not p.exists():
        raise KeyError(scenario_id)
    p.unlink()
    artifact_dir = scenario_meta_store.artifact_dir(_STORE_DIR, scenario_id)
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
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


def duplicate_scenario(
    scenario_id: str, *, name: Optional[str] = None
) -> Dict[str, Any]:
    doc = _load(scenario_id)
    new_id = _new_id()
    now = _now_iso()
    cloned = json.loads(json.dumps(doc))
    cloned["meta"]["id"] = new_id
    cloned["meta"]["name"] = name or f"{doc['meta'].get('name') or 'Scenario'} Copy"
    cloned["meta"]["createdAt"] = now
    cloned["meta"]["updatedAt"] = now
    cloned["meta"]["status"] = "draft"
    _save(cloned)
    return _meta_payload(cloned)


# ── Generic sub-document accessors ────────────────────────────


def get_field(scenario_id: str, field: str) -> Any:
    return _load(scenario_id)[field]


def count_field_rows(scenario_id: str, field: str) -> int:
    meta = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
    refs = _refs_for_scenario(scenario_id, meta)
    if field == "timetable_rows":
        db_count = trip_store.count_timetable_rows(_artifact_store_path(refs))
        if db_count > 0:
            return db_count
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
            return [
                dict(item)
                for item in trip_store.page_timetable_rows(db_path, offset=offset, limit=limit)
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
    db_count = trip_store.count_timetable_rows(db_path, service_id=service_id)
    if db_count > 0 or service_id is not None:
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
    if service_id:
        rows = [row for row in rows if str(row.get("service_id") or "WEEKDAY") == service_id]
    if limit is None:
        return [dict(item) for item in rows[offset:]]
    return [dict(item) for item in rows[offset: offset + limit]]


def count_timetable_rows(scenario_id: str, *, service_id: Optional[str] = None) -> int:
    meta = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
    refs = _refs_for_scenario(scenario_id, meta)
    db_path = _artifact_store_path(refs)
    db_count = trip_store.count_timetable_rows(db_path, service_id=service_id)
    if db_count > 0 or service_id is not None:
        return db_count
    rows = _load(scenario_id).get("timetable_rows") or []
    if service_id:
        rows = [row for row in rows if str(row.get("service_id") or "WEEKDAY") == service_id]
    return len(rows)


def get_field_summary(scenario_id: str, field: str) -> Optional[Dict[str, Any]]:
    scalar_name = _SUMMARY_SCALAR_NAMES.get(field)
    if not scalar_name:
        return None
    meta = scenario_meta_store.load_meta(_STORE_DIR, scenario_id)
    refs = _refs_for_scenario(scenario_id, meta)
    summary = trip_store.load_scalar(_artifact_store_path(refs), scalar_name, None)
    if summary is not None:
        return dict(summary)
    items = _load(scenario_id).get(field) or []
    if field == "timetable_rows":
        return _build_timetable_summary_artifact(items, _load(scenario_id).get("timetable_import_meta") or {})
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
    db_count = trip_store.count_graph_arcs(artifact_db, reason_code=reason_code)
    if db_count > 0 or reason_code is not None:
        return db_count
    graph = _load(scenario_id).get("graph") or {}
    arcs = list(graph.get("arcs") or [])
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
    db_count = trip_store.count_graph_arcs(artifact_db, reason_code=reason_code)
    if db_count > 0 or reason_code is not None:
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
    doc = _load(scenario_id)
    doc[field] = value
    if invalidate_dispatch:
        _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)


def get_feed_context(scenario_id: str) -> Optional[Dict[str, Any]]:
    return _normalize_feed_context(_load(scenario_id).get("feed_context"))


def set_feed_context(
    scenario_id: str,
    feed_context: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    doc = _load(scenario_id)
    doc["feed_context"] = _normalize_feed_context(feed_context)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return doc["feed_context"]


# ── Master-data helpers ────────────────────────────────────────


def _list_items(scenario_id: str, field: str) -> List[Dict[str, Any]]:
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
    doc = _load(scenario_id)
    item = dict(data)
    item["id"] = item.get("id") or _new_id()
    doc[field].append(item)
    if field in {"depots", "vehicles", "routes"}:
        _invalidate_dispatch_artifacts(doc)
    if field in {"depots", "routes"}:
        _sync_depot_route_permissions(doc)
        _normalize_dispatch_scope(doc)
    if field in {"vehicles", "routes"}:
        _sync_vehicle_route_permissions(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return item


def _update_item(
    scenario_id: str, field: str, item_id_key: str, item_id: str, patch: Dict[str, Any]
) -> Dict[str, Any]:
    doc = _load(scenario_id)
    for item in doc[field]:
        if item.get(item_id_key) == item_id:
            item.update({k: v for k, v in patch.items() if v is not None})
            if field in {"depots", "vehicles", "routes"}:
                _invalidate_dispatch_artifacts(doc)
            if field in {"depots", "routes"}:
                _sync_depot_route_permissions(doc)
                _normalize_dispatch_scope(doc)
            if field in {"vehicles", "routes"}:
                _sync_vehicle_route_permissions(doc)
            doc["meta"]["updatedAt"] = _now_iso()
            _save(doc)
            return item
    raise KeyError(item_id)


def _delete_item(scenario_id: str, field: str, item_id_key: str, item_id: str) -> None:
    doc = _load(scenario_id)
    before = len(doc[field])
    doc[field] = [i for i in doc[field] if i.get(item_id_key) != item_id]
    if len(doc[field]) == before:
        raise KeyError(item_id)
    if field in {"depots", "vehicles", "routes"}:
        _invalidate_dispatch_artifacts(doc)
    if field in {"depots", "routes"}:
        _sync_depot_route_permissions(doc)
        _normalize_dispatch_scope(doc)
    if field in {"vehicles", "routes"}:
        _sync_vehicle_route_permissions(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)


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
    doc = _load(scenario_id)
    doc["route_depot_assignments"] = [
        item
        for item in doc.get("route_depot_assignments") or []
        if str(item.get("depotId")) != depot_id
    ]
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)


def get_public_data_state(scenario_id: str) -> Dict[str, Any]:
    doc = _load(scenario_id)
    state = doc.get("public_data")
    if not isinstance(state, dict):
        return _default_public_data_state()
    normalized = _default_public_data_state()
    normalized.update(state)
    return normalized


def set_public_data_state(scenario_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
    doc = _load(scenario_id)
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

    doc = _load(scenario_id)
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

    doc = _load(scenario_id)
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
    doc = _load(scenario_id)
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
    doc = _load(scenario_id)
    return list(doc.get("vehicle_templates") or [])


def get_vehicle_template(scenario_id: str, template_id: str) -> Dict[str, Any]:
    doc = _load(scenario_id)
    for item in doc.get("vehicle_templates") or []:
        if item.get("id") == template_id:
            return item
    raise KeyError(template_id)


def create_vehicle_template(scenario_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    doc = _load(scenario_id)
    item = dict(data)
    item["id"] = _new_id()
    doc.setdefault("vehicle_templates", []).append(item)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return item


def update_vehicle_template(
    scenario_id: str, template_id: str, patch: Dict[str, Any]
) -> Dict[str, Any]:
    doc = _load(scenario_id)
    templates = doc.setdefault("vehicle_templates", [])
    for item in templates:
        if item.get("id") == template_id:
            item.update({k: v for k, v in patch.items() if v is not None})
            doc["meta"]["updatedAt"] = _now_iso()
            _save(doc)
            return item
    raise KeyError(template_id)


def delete_vehicle_template(scenario_id: str, template_id: str) -> None:
    doc = _load(scenario_id)
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
        return source in {"", "manual", "odpt"}
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
    doc = _load(scenario_id)
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
            }
        )
    return items


def get_route(scenario_id: str, route_id: str) -> Dict[str, Any]:
    doc = _load(scenario_id)
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
    doc = _load(scenario_id)
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
    doc = _load(scenario_id)
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
    doc = _load(scenario_id)
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
    doc = _load(scenario_id)
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
                "stopCount": len(list(route.get("stopSequence") or [])),
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
    doc = _load(scenario_id)
    resolved_route_id = None
    for route in doc.get("routes") or []:
        route_keys = {
            str(value)
            for value in (
                route.get("id"),
                route.get("odptPatternId"),
                route.get("odptBusrouteId"),
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
    _save(doc)
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
    doc = _load(scenario_id)
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
    doc = _load(scenario_id)
    stop_import_meta = doc.get("stop_import_meta") or {}
    if source is None:
        return dict(stop_import_meta)
    value = stop_import_meta.get(source)
    return dict(value) if isinstance(value, dict) else {}


def set_stop_import_meta(
    scenario_id: str, source: str, import_meta: Dict[str, Any]
) -> Dict[str, Any]:
    doc = _load(scenario_id)
    stop_import_meta = doc.setdefault("stop_import_meta", {})
    stop_import_meta[source] = import_meta
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return dict(import_meta)


def set_timetable_import_meta(
    scenario_id: str, source: str, import_meta: Dict[str, Any]
) -> Dict[str, Any]:
    doc = _load(scenario_id)
    timetable_import_meta = doc.setdefault("timetable_import_meta", {})
    timetable_import_meta[source] = import_meta
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return dict(import_meta)


def get_timetable_import_meta(
    scenario_id: str, source: Optional[str] = None
) -> Dict[str, Any]:
    doc = _load(scenario_id)
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
    doc = _load(scenario_id)
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
    doc = _load(scenario_id)
    stop_timetable_import_meta = doc.setdefault("stop_timetable_import_meta", {})
    stop_timetable_import_meta[source] = import_meta
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return dict(import_meta)


def get_stop_timetable_import_meta(
    scenario_id: str, source: Optional[str] = None
) -> Dict[str, Any]:
    doc = _load(scenario_id)
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
    doc = _load(scenario_id)
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
    doc = _load(scenario_id)
    return list(doc.get("depot_route_permissions") or [])


def set_depot_route_permissions(
    scenario_id: str, permissions: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
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
    _save(doc)
    return list(sanitized)


def get_vehicle_route_permissions(scenario_id: str) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
    return list(doc.get("vehicle_route_permissions") or [])


def set_vehicle_route_permissions(
    scenario_id: str, permissions: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
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
    _save(doc)
    return list(sanitized)


def get_deadhead_rules(scenario_id: str) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
    return list(doc.get("deadhead_rules") or [])


def set_deadhead_rules(
    scenario_id: str, rules: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)

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
    doc = _load(scenario_id)
    return list(doc.get("turnaround_rules") or [])


def set_turnaround_rules(
    scenario_id: str, rules: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    doc = _load(scenario_id)
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
    doc = _load(scenario_id)
    return _normalize_dispatch_scope(doc)


def set_dispatch_scope(scenario_id: str, scope: Dict[str, Any]) -> Dict[str, Any]:
    doc = _load(scenario_id)
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
        "depotId": depot_selection.get("primaryDepotId"),
        "serviceId": (
            (service_selection.get("serviceIds") or [current.get("serviceId") or "WEEKDAY"])[0]
        ),
    }
    doc["dispatch_scope"] = next_scope
    normalized = _normalize_dispatch_scope(doc)
    if normalized != current:
        _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return normalized


def effective_route_ids_for_scope(
    scenario_id: str,
    scope: Optional[Dict[str, Any]] = None,
) -> List[str]:
    doc = _load(scenario_id)
    if scope is not None:
        doc["dispatch_scope"] = scope
    normalized = _normalize_dispatch_scope(doc)
    return list(normalized.get("effectiveRouteIds") or [])


def route_ids_for_selected_depots(
    scenario_id: str,
    scope: Optional[Dict[str, Any]] = None,
) -> List[str]:
    doc = _load(scenario_id)
    if scope is not None:
        doc["dispatch_scope"] = scope
    normalized = _normalize_dispatch_scope(doc)
    return list(normalized.get("candidateRouteIds") or [])


# ── Calendar helpers ───────────────────────────────────────────


def get_calendar(scenario_id: str) -> List[Dict[str, Any]]:
    """Return the list of service_id definitions for this scenario."""
    doc = _load(scenario_id)
    return doc.get("calendar") or _default_calendar()


def set_calendar(
    scenario_id: str, entries: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Replace the entire calendar (list of service_id definitions)."""
    doc = _load(scenario_id)
    doc["calendar"] = entries
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return entries


def upsert_calendar_entry(scenario_id: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Insert or update a single service_id entry (keyed by service_id)."""
    doc = _load(scenario_id)
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
    doc = _load(scenario_id)
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
    doc = _load(scenario_id)
    return doc.get("calendar_dates") or []


def set_calendar_dates(
    scenario_id: str, entries: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Replace the entire calendar_dates list."""
    doc = _load(scenario_id)
    doc["calendar_dates"] = entries
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
    return entries


def upsert_calendar_date(scenario_id: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    """Insert or update a single date exception (keyed by date)."""
    doc = _load(scenario_id)
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
    doc = _load(scenario_id)
    dates: List[Dict[str, Any]] = doc.get("calendar_dates") or []
    before = len(dates)
    doc["calendar_dates"] = [e for e in dates if e.get("date") != date]
    if len(doc["calendar_dates"]) == before:
        raise KeyError(date)
    _invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = _now_iso()
    _save(doc)
