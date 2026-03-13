from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

import logging as _logging

from bff.services.gtfs_import import (
    DEFAULT_GTFS_FEED_PATH,
    build_gtfs_route_timetables,
    build_gtfs_stop_timetables,
    gtfs_feed_signature,
    load_gtfs_core_bundle,
    resolve_gtfs_feed_path,
)
from bff.services.odpt_routes import (
    DEFAULT_OPERATOR,
    build_routes_from_operational,
    fetch_operational_dataset,
    fetch_operational_stage_dataset,
    fetch_stop_timetable_stage_dataset,
)
from bff.services.odpt_fetch import (
    fetch_tokyu_odpt_bundle,
    load_manifest as load_raw_manifest,
    list_snapshots as list_raw_snapshots,
)
from bff.services.odpt_normalize import (
    normalize_odpt_snapshot,
    load_normalized_bundle,
)
from bff.services.odpt_stop_timetables import build_stop_timetables_from_normalized
from bff.services.odpt_stops import build_stops_from_normalized
from bff.services.odpt_timetable import (
    build_timetable_rows_from_operational,
    normalize_timetable_row_indexes,
)
from bff.services.runtime_paths import resolve_runtime_path
from bff.services import transit_db as _tdb
from src.feed_identity import build_dataset_id, infer_feed_id

_log = _logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CATALOG_DB_PATH_DEFAULT = resolve_runtime_path("transit_catalog_db_path", "./outputs/transit_catalog.sqlite")
_ODPT_SAVED_SNAPSHOT_DIR_DEFAULT = resolve_runtime_path("odpt_snapshot_dir", "./data/odpt/tokyu")
_CATALOG_SUMMARY_DIR_DEFAULT = resolve_runtime_path("catalog_summary_dir", "./outputs/catalog_summaries")

_ENTITY_TYPES = (
    "stops",
    "routes",
    "timetable_rows",
    "stop_timetables",
    "calendar_entries",
    "calendar_date_entries",
)
_ODPT_REQUIRED_ENTITY_TYPES = (
    "stops",
    "routes",
    "timetable_rows",
    "stop_timetables",
)
_GTFS_REQUIRED_ENTITY_TYPES = (
    "stops",
    "routes",
    "timetable_rows",
    "stop_timetables",
    "calendar_entries",
)

ProgressCallback = Callable[[str, Dict[str, Any]], None]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _catalog_summary_dir() -> Path:
    return Path(_CATALOG_SUMMARY_DIR_DEFAULT)


def _summary_artifact_path(snapshot_key: str) -> Path:
    safe_name = snapshot_key.replace(":", "_").replace("/", "_")
    return _catalog_summary_dir() / f"{safe_name}.summary.json"


def _build_operator_summary_artifact(
    *,
    snapshot_key: str,
    operator_id: str,
    source_type: str,
    routes: List[Dict[str, Any]],
    stops: List[Dict[str, Any]],
    timetable_rows: List[Dict[str, Any]],
    stop_timetables: List[Dict[str, Any]],
    updated_at: Optional[str],
) -> Dict[str, Any]:
    geo_stops = [
        stop for stop in stops if stop.get("lat") is not None and stop.get("lon") is not None
    ]
    bounds = None
    if geo_stops:
        latitudes = [float(stop["lat"]) for stop in geo_stops]
        longitudes = [float(stop["lon"]) for stop in geo_stops]
        bounds = {
            "minLat": min(latitudes),
            "maxLat": max(latitudes),
            "minLon": min(longitudes),
            "maxLon": max(longitudes),
        }

    cluster_counts: Dict[tuple[float, float], int] = {}
    for stop in geo_stops:
        key = (round(float(stop["lat"]), 2), round(float(stop["lon"]), 2))
        cluster_counts[key] = cluster_counts.get(key, 0) + 1

    stop_clusters = [
        {
            "id": f"{operator_id}:c:{index}",
            "lat": lat,
            "lon": lon,
            "count": count,
        }
        for index, ((lat, lon), count) in enumerate(
            sorted(cluster_counts.items(), key=lambda item: item[1], reverse=True)[:500]
        )
    ]

    depot_points = [
        {
            "id": f"{operator_id}:depot:{stop.get('stop_id') or stop.get('id')}",
            "label": str(stop.get("stop_name") or stop.get("name") or ""),
            "lat": stop.get("lat"),
            "lon": stop.get("lon"),
        }
        for stop in geo_stops
        if any(
            keyword in str(stop.get("stop_name") or stop.get("name") or "")
            for keyword in ("営業所", "車庫", "操車所")
        )
    ]

    route_with_trips_count = sum(
        1 for route in routes if int(route.get("trip_count") or route.get("tripCount") or 0) > 0
    )
    geo_stop_count = len(geo_stops)
    stop_timetable_stop_ids = {
        str(item.get("stopId") or item.get("stop_id") or "")
        for item in stop_timetables
        if item.get("stopId") or item.get("stop_id")
    }
    classified_route_count = sum(
        1 for route in routes if route.get("classificationConfidence") is not None
    )
    low_confidence_route_count = sum(
        1
        for route in routes
        if route.get("classificationConfidence") is not None
        and float(route.get("classificationConfidence") or 0.0) < 0.6
    )

    return {
        "snapshotKey": snapshot_key,
        "operatorId": operator_id,
        "sourceType": source_type,
        "counts": {
            "routes": len(routes),
            "stops": len(stops),
            "timetableRows": len(timetable_rows),
            "stopTimetables": len(stop_timetables),
            "depotCount": len(depot_points),
        },
        "bounds": bounds,
        "stopClusters": stop_clusters,
        "depotPoints": depot_points,
        "quality": {
            "routeWithTripsCount": route_with_trips_count,
            "routeWithTripsRatio": round(route_with_trips_count / len(routes), 4) if routes else 0.0,
            "geoStopCount": geo_stop_count,
            "geoStopRatio": round(geo_stop_count / len(stops), 4) if stops else 0.0,
            "stopTimetableStopCount": len(stop_timetable_stop_ids),
            "stopTimetableStopRatio": round(len(stop_timetable_stop_ids) / len(stops), 4) if stops else 0.0,
            "classifiedRouteCount": classified_route_count,
            "lowConfidenceRouteCount": low_confidence_route_count,
        },
        "updatedAt": updated_at,
    }


def _write_operator_summary_artifact(
    *,
    snapshot_key: str,
    operator_id: str,
    source_type: str,
    routes: List[Dict[str, Any]],
    stops: List[Dict[str, Any]],
    timetable_rows: List[Dict[str, Any]],
    stop_timetables: List[Dict[str, Any]],
    updated_at: Optional[str],
) -> str:
    payload = _build_operator_summary_artifact(
        snapshot_key=snapshot_key,
        operator_id=operator_id,
        source_type=source_type,
        routes=routes,
        stops=stops,
        timetable_rows=timetable_rows,
        stop_timetables=stop_timetables,
        updated_at=updated_at,
    )
    path = _summary_artifact_path(snapshot_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def load_snapshot_operator_summary(snapshot_key: str) -> Optional[Dict[str, Any]]:
    snapshot = get_snapshot(snapshot_key)
    if snapshot is None:
        return None
    meta = dict(snapshot.get("meta") or {})
    artifacts = dict(meta.get("artifacts") or {})
    summary_path = artifacts.get("operatorSummary")
    if not summary_path:
        return None
    path = Path(str(summary_path))
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_repo_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = (_REPO_ROOT / path).resolve()
    return path


def _catalog_db_path() -> Path:
    configured = os.environ.get("TRANSIT_CATALOG_DB_PATH")
    if configured:
        return _resolve_repo_path(configured)
    return resolve_runtime_path("transit_catalog_db_path", _CATALOG_DB_PATH_DEFAULT)


def _odpt_saved_snapshot_dir(operator: str) -> Optional[Path]:
    configured = os.environ.get("ODPT_SNAPSHOT_DIR")
    if configured:
        return _resolve_repo_path(configured)
    if operator == DEFAULT_OPERATOR:
        return resolve_runtime_path("odpt_snapshot_dir", _ODPT_SAVED_SNAPSHOT_DIR_DEFAULT)
    return None


def _normalize_exception_type(value: Any) -> int:
    return _tdb._normalize_exception_type(value)


def _normalize_calendar_date_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(entry)
    normalized["exception_type"] = _normalize_exception_type(entry.get("exception_type"))
    return normalized


def _normalize_calendar_date_entries(entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [_normalize_calendar_date_entry(entry) for entry in entries]


def _db_warning(code: str, exc: Exception) -> Dict[str, Any]:
    return {"code": code, "message": str(exc)}


def _append_warning_list(meta: Dict[str, Any], warning: Optional[Dict[str, Any]]) -> None:
    if warning is None:
        return
    warnings = list(meta.get("warnings") or [])
    warnings.append(f"{warning['code']}: {warning['message']}")
    meta["warnings"] = list(dict.fromkeys(warnings))


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _connect() -> sqlite3.Connection:
    db_path = _catalog_db_path()
    _ensure_parent_dir(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS catalog_snapshots (
            snapshot_key TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            dataset_ref TEXT NOT NULL,
            signature TEXT,
            generated_at TEXT,
            refreshed_at TEXT NOT NULL,
            meta_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS catalog_entities (
            snapshot_key TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            sort_key TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (snapshot_key, entity_type, entity_id),
            FOREIGN KEY (snapshot_key) REFERENCES catalog_snapshots(snapshot_key) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_catalog_entities_lookup
            ON catalog_entities(snapshot_key, entity_type, sort_key);

        CREATE TABLE IF NOT EXISTS catalog_route_payloads (
            snapshot_key TEXT NOT NULL,
            route_id TEXT NOT NULL,
            route_code TEXT NOT NULL,
            route_label TEXT NOT NULL,
            trip_count INTEGER NOT NULL DEFAULT 0,
            first_departure TEXT,
            last_arrival TEXT,
            services_json TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            PRIMARY KEY (snapshot_key, route_id),
            FOREIGN KEY (snapshot_key) REFERENCES catalog_snapshots(snapshot_key) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_catalog_route_payloads_lookup
            ON catalog_route_payloads(snapshot_key, route_code, route_label);
        """
    )
    conn.commit()


def _serialize(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _deserialize(value: str | bytes | bytearray | None) -> Any:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        return json.loads(value.decode("utf-8"))
    return json.loads(value)


def _read_json_object(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return None
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        return None
    return payload


def _file_signature(paths: Iterable[Path]) -> str:
    signature: List[tuple[str, int, int]] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        stat = path.stat()
        signature.append((path.name, stat.st_mtime_ns, stat.st_size))
    return _serialize(signature)


def _normalize_snapshot_key(source: str, dataset_ref: str) -> str:
    return f"{source}::{dataset_ref}"


def _snapshot_identity(
    source: str,
    dataset_ref: str,
    meta: Dict[str, Any],
) -> Dict[str, Any]:
    feed_id = str(meta.get("feed_id") or "")
    snapshot_id = meta.get("snapshot_id")
    if source == "gtfs" and not feed_id:
        feed_id = infer_feed_id(dataset_ref) or "gtfs"
    dataset_id = str(meta.get("dataset_id") or "")
    if feed_id and not dataset_id:
        dataset_id = build_dataset_id(feed_id, str(snapshot_id) if snapshot_id else None)
    return {
        "feedId": feed_id or None,
        "snapshotId": str(snapshot_id) if snapshot_id else None,
        "datasetId": dataset_id or None,
    }


def _entity_id(entity_type: str, item: Dict[str, Any], index: int) -> str:
    if entity_type in {"stops", "routes", "stop_timetables"}:
        candidate = item.get("id")
        if candidate:
            return str(candidate)
    if entity_type == "timetable_rows":
        candidate = item.get("trip_id")
        if candidate:
            return str(candidate)
        return "|".join(
            [
                str(item.get("route_id") or ""),
                str(item.get("service_id") or ""),
                str(item.get("direction") or ""),
                str(item.get("trip_index") or index),
                str(item.get("departure") or ""),
                str(item.get("arrival") or ""),
            ]
        )
    if entity_type == "calendar_entries":
        candidate = item.get("service_id")
        if candidate:
            return str(candidate)
    if entity_type == "calendar_date_entries":
        return "|".join(
            [
                str(item.get("date") or ""),
                str(item.get("service_id") or ""),
                str(item.get("exception_type") or ""),
            ]
        )
    return f"{entity_type}:{index}"


def _sort_key(entity_type: str, item: Dict[str, Any], index: int) -> str:
    if entity_type == "stops":
        return str(item.get("name") or item.get("id") or index)
    if entity_type == "routes":
        return str(
            item.get("routeCode")
            or item.get("route_code")
            or item.get("name")
            or item.get("id")
            or index
        )
    if entity_type == "timetable_rows":
        return "|".join(
            [
                str(item.get("service_id") or ""),
                str(item.get("route_id") or ""),
                str(item.get("direction") or ""),
                str(item.get("departure") or ""),
                str(item.get("arrival") or ""),
                str(item.get("trip_id") or index),
            ]
        )
    if entity_type == "stop_timetables":
        return "|".join(
            [
                str(item.get("stopName") or ""),
                str(item.get("service_id") or ""),
                str(item.get("id") or index),
            ]
        )
    if entity_type == "calendar_entries":
        return str(item.get("service_id") or index)
    if entity_type == "calendar_date_entries":
        return "|".join(
            [
                str(item.get("date") or ""),
                str(item.get("service_id") or ""),
                str(item.get("exception_type") or ""),
            ]
        )
    return f"{index:08d}"


def _route_payload_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "route_id": str(payload.get("route_id") or ""),
        "route_code": str(payload.get("route_code") or payload.get("route_id") or ""),
        "route_label": str(payload.get("route_label") or payload.get("route_code") or ""),
        "trip_count": int(payload.get("trip_count") or 0),
        "first_departure": payload.get("first_departure"),
        "last_arrival": payload.get("last_arrival"),
        "services": list(payload.get("services") or []),
    }


def _canonicalize_odpt_route_payloads(
    payloads: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for payload in payloads:
        route_id = str(payload.get("busroute_id") or payload.get("route_id") or "")
        if not route_id:
            continue
        items.append(
            {
                "route_id": route_id,
                "route_code": str(payload.get("route_code") or route_id),
                "route_label": str(payload.get("route_label") or payload.get("route_code") or route_id),
                "trip_count": int(payload.get("trip_count") or 0),
                "first_departure": payload.get("first_departure"),
                "last_arrival": payload.get("last_arrival"),
                "patterns": list(payload.get("patterns") or []),
                "services": list(payload.get("services") or []),
                "trips": list(payload.get("trips") or []),
                "source": "odpt",
            }
        )
    return items


def _merge_odpt_route_payloads(
    payloads: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for payload in payloads:
        route_id = str(payload.get("busroute_id") or payload.get("route_id") or "")
        if not route_id:
            continue
        item = merged.setdefault(
            route_id,
            {
                "route_id": route_id,
                "route_code": str(payload.get("route_code") or route_id),
                "route_label": str(
                    payload.get("route_label") or payload.get("route_code") or route_id
                ),
                "patterns": {},
                "trips": {},
            },
        )
        if payload.get("route_code"):
            item["route_code"] = str(payload.get("route_code"))
        if payload.get("route_label"):
            item["route_label"] = str(payload.get("route_label"))

        for pattern in list(payload.get("patterns") or []):
            pattern_id = str(pattern.get("pattern_id") or "")
            if pattern_id:
                item["patterns"][pattern_id] = dict(pattern)

        for trip in list(payload.get("trips") or []):
            trip_id = str(trip.get("trip_id") or "")
            if trip_id:
                item["trips"][trip_id] = dict(trip)

    items: List[Dict[str, Any]] = []
    for route_id, payload in merged.items():
        trips = sorted(
            payload["trips"].values(),
            key=lambda trip: (
                str(trip.get("service_id") or ""),
                str(trip.get("departure") or ""),
                str(trip.get("arrival") or ""),
                str(trip.get("trip_id") or ""),
            ),
        )
        services: Dict[str, Dict[str, Any]] = {}
        first_departure: Optional[str] = None
        last_arrival: Optional[str] = None
        for trip in trips:
            departure = trip.get("departure")
            arrival = trip.get("arrival")
            if departure and (first_departure is None or departure < first_departure):
                first_departure = departure
            if arrival and (last_arrival is None or arrival > last_arrival):
                last_arrival = arrival
            service_id = str(trip.get("service_id") or "unknown")
            summary = services.setdefault(
                service_id,
                {
                    "service_id": service_id,
                    "trip_count": 0,
                    "first_departure": None,
                    "last_arrival": None,
                },
            )
            summary["trip_count"] += 1
            if departure and (
                summary["first_departure"] is None or departure < summary["first_departure"]
            ):
                summary["first_departure"] = departure
            if arrival and (
                summary["last_arrival"] is None or arrival > summary["last_arrival"]
            ):
                summary["last_arrival"] = arrival

        items.append(
            {
                "route_id": route_id,
                "route_code": payload["route_code"],
                "route_label": payload["route_label"],
                "trip_count": len(trips),
                "first_departure": first_departure,
                "last_arrival": last_arrival,
                "patterns": sorted(
                    payload["patterns"].values(),
                    key=lambda pattern: str(pattern.get("pattern_id") or ""),
                ),
                "services": [services[key] for key in sorted(services)],
                "trips": trips,
                "source": "odpt",
            }
        )

    return items


def _merge_stage_entity_maps(
    target: Dict[str, Dict[str, Any]],
    incoming: Dict[str, Dict[str, Any]],
) -> None:
    for key, value in incoming.items():
        if key:
            target[str(key)] = dict(value)


def _merge_stage_indexes(
    target: Dict[str, Dict[str, List[str]]],
    incoming: Dict[str, Dict[str, List[str]]],
) -> None:
    for index_name, groups in incoming.items():
        if not isinstance(groups, dict):
            continue
        target_groups = target.setdefault(index_name, {})
        for group_key, values in groups.items():
            bucket = list(target_groups.get(group_key) or [])
            seen = {str(value) for value in bucket}
            for value in values or []:
                value_str = str(value)
                if value_str not in seen:
                    bucket.append(value_str)
                    seen.add(value_str)
            target_groups[group_key] = bucket


def _refresh_odpt_snapshot_via_stage_bff(
    *,
    operator: str,
    dump: bool,
    force_refresh: bool,
    ttl_sec: int,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    merged_dataset: Dict[str, Any] = {
        "meta": {},
        "stops": {},
        "routePatterns": {},
        "trips": {},
        "stopTimetables": {},
        "indexes": {},
    }
    route_payloads: List[Dict[str, Any]] = []
    warnings: List[str] = []
    progress_meta: Dict[str, Dict[str, Any]] = {}
    generated_at: Optional[str] = None

    bus_cursor = 0
    while True:
        stage = fetch_operational_stage_dataset(
            operator=operator,
            dump=False,
            force_refresh=force_refresh and bus_cursor == 0,
            ttl_sec=ttl_sec,
            bus_timetable_cursor=bus_cursor,
            bus_timetable_batch_size=25,
        )
        meta = dict(stage.get("meta") or {})
        generated_at = generated_at or meta.get("generatedAt")
        warnings.extend(list(meta.get("warnings") or []))
        progress = dict(((meta.get("progress") or {}).get("busTimetables")) or {})
        if progress:
            progress_meta["busTimetables"] = progress
            if progress_callback is not None:
                progress_callback(
                    "odpt_bus_timetables",
                    {
                        "resource": "busTimetables",
                        "progress": progress,
                        "counts": {
                            "stops": len(merged_dataset["stops"]),
                            "routePayloads": len(route_payloads),
                            "timetableRows": len(merged_dataset["trips"]),
                        },
                    },
                )
        _merge_stage_entity_maps(merged_dataset["stops"], dict(stage.get("stops") or {}))
        _merge_stage_entity_maps(
            merged_dataset["routePatterns"],
            dict(stage.get("routePatterns") or {}),
        )
        _merge_stage_entity_maps(merged_dataset["trips"], dict(stage.get("trips") or {}))
        _merge_stage_indexes(merged_dataset["indexes"], dict(stage.get("indexes") or {}))
        route_payloads.extend(list(stage.get("routeTimetables") or []))

        next_cursor = int(progress.get("nextCursor") or 0)
        if progress.get("complete"):
            break
        if next_cursor <= bus_cursor:
            warnings.append("BusTimetable staged fetch stopped before completion")
            break
        bus_cursor = next_cursor

    stop_cursor = 0
    while True:
        stage = fetch_stop_timetable_stage_dataset(
            operator=operator,
            dump=False,
            force_refresh=force_refresh and stop_cursor == 0,
            ttl_sec=ttl_sec,
            stop_timetable_cursor=stop_cursor,
            stop_timetable_batch_size=50,
        )
        meta = dict(stage.get("meta") or {})
        generated_at = generated_at or meta.get("generatedAt")
        warnings.extend(list(meta.get("warnings") or []))
        progress = dict(((meta.get("progress") or {}).get("stopTimetables")) or {})
        if progress:
            progress_meta["stopTimetables"] = progress
            if progress_callback is not None:
                progress_callback(
                    "odpt_stop_timetables",
                    {
                        "resource": "stopTimetables",
                        "progress": progress,
                        "counts": {
                            "stops": len(merged_dataset["stops"]),
                            "stopTimetables": len(merged_dataset["stopTimetables"]),
                        },
                    },
                )
        _merge_stage_entity_maps(merged_dataset["stops"], dict(stage.get("stops") or {}))
        _merge_stage_entity_maps(
            merged_dataset["stopTimetables"],
            dict(stage.get("stopTimetables") or {}),
        )

        next_cursor = int(progress.get("nextCursor") or 0)
        if progress.get("complete"):
            break
        if next_cursor <= stop_cursor:
            warnings.append("BusstopPoleTimetable staged fetch stopped before completion")
            break
        stop_cursor = next_cursor

    merged_dataset["meta"] = {
        "generatedAt": generated_at,
        "warnings": [],
        "cache": {"staged": True},
    }
    signature = _serialize(
        {
            "operator": operator,
            "snapshotStrategy": "bff-staged",
            "tripCount": len(merged_dataset["trips"]),
            "stopTimetableCount": len(merged_dataset["stopTimetables"]),
        }
    )

    return _store_odpt_snapshot(
        operator=operator,
        dataset=merged_dataset,
        route_payloads=_merge_odpt_route_payloads(route_payloads),
        signature=signature,
        requested_dump=dump,
        effective_dump=False,
        snapshot_source="bff-staged",
        extra_meta={
            "warnings": warnings,
            "progress": progress_meta,
        },
    )


def _trip_stop_times_from_route_payloads(
    route_payloads: Iterable[Dict[str, Any]],
    *,
    source: str,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for payload in route_payloads:
        for trip in list(payload.get("trips") or []):
            trip_id = str(trip.get("trip_id") or "")
            if not trip_id:
                continue
            for index, stop_time in enumerate(list(trip.get("stop_times") or [])):
                if not isinstance(stop_time, dict):
                    continue
                stop_id = str(stop_time.get("stop_id") or "")
                if not stop_id:
                    continue
                items.append(
                    {
                        "trip_id": trip_id,
                        "stop_id": stop_id,
                        "stop_name": stop_time.get("stop_name"),
                        "sequence": stop_time.get("index", index),
                        "departure": stop_time.get("departure"),
                        "arrival": stop_time.get("arrival"),
                        "source": source,
                        "time": stop_time.get("time"),
                    }
                )
    return items


def _replace_snapshot(
    *,
    snapshot_key: str,
    source: str,
    dataset_ref: str,
    signature: str,
    meta: Dict[str, Any],
    entities: Dict[str, List[Dict[str, Any]]],
    route_payloads: List[Dict[str, Any]],
) -> Dict[str, Any]:
    with closing(_connect()) as conn:
        _ensure_schema(conn)
        conn.execute("DELETE FROM catalog_entities WHERE snapshot_key = ?", (snapshot_key,))
        conn.execute(
            "DELETE FROM catalog_route_payloads WHERE snapshot_key = ?", (snapshot_key,)
        )
        conn.execute(
            """
            INSERT INTO catalog_snapshots (
                snapshot_key,
                source,
                dataset_ref,
                signature,
                generated_at,
                refreshed_at,
                meta_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_key) DO UPDATE SET
                source = excluded.source,
                dataset_ref = excluded.dataset_ref,
                signature = excluded.signature,
                generated_at = excluded.generated_at,
                refreshed_at = excluded.refreshed_at,
                meta_json = excluded.meta_json
            """,
            (
                snapshot_key,
                source,
                dataset_ref,
                signature,
                meta.get("generatedAt"),
                meta.get("refreshedAt") or _now_iso(),
                _serialize(meta),
            ),
        )

        for entity_type, items in entities.items():
            deduped: Dict[str, tuple[str, str, str, str, str]] = {}
            for index, item in enumerate(items):
                entity_id = _entity_id(entity_type, item, index)
                deduped[entity_id] = (
                    snapshot_key,
                    entity_type,
                    entity_id,
                    _sort_key(entity_type, item, index),
                    _serialize(item),
                )
            rows = list(deduped.values())
            conn.executemany(
                """
                INSERT INTO catalog_entities (
                    snapshot_key,
                    entity_type,
                    entity_id,
                    sort_key,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )

        route_rows = []
        for payload in route_payloads:
            summary = _route_payload_summary(payload)
            route_rows.append(
                (
                    snapshot_key,
                    summary["route_id"],
                    summary["route_code"],
                    summary["route_label"],
                    summary["trip_count"],
                    summary.get("first_departure"),
                    summary.get("last_arrival"),
                    _serialize(summary.get("services") or []),
                    _serialize(payload),
                )
            )
        conn.executemany(
            """
            INSERT INTO catalog_route_payloads (
                snapshot_key,
                route_id,
                route_code,
                route_label,
                trip_count,
                first_departure,
                last_arrival,
                services_json,
                payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            route_rows,
        )
        conn.commit()
    return get_snapshot(snapshot_key) or {}


def _load_entities(snapshot_key: str, entity_type: str) -> List[Dict[str, Any]]:
    with closing(_connect()) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT payload_json
            FROM catalog_entities
            WHERE snapshot_key = ? AND entity_type = ?
            ORDER BY sort_key ASC, entity_id ASC
            """,
            (snapshot_key, entity_type),
        ).fetchall()
    return [dict(_deserialize(row["payload_json"]) or {}) for row in rows]


def _has_snapshot_payload(snapshot_key: str, required_entity_types: Iterable[str]) -> bool:
    with closing(_connect()) as conn:
        _ensure_schema(conn)
        for entity_type in required_entity_types:
            count = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM catalog_entities
                WHERE snapshot_key = ? AND entity_type = ?
                """,
                (snapshot_key, entity_type),
            ).fetchone()["n"]
            if int(count or 0) == 0:
                return False
        route_count = conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM catalog_route_payloads
            WHERE snapshot_key = ?
            """,
            (snapshot_key,),
        ).fetchone()["n"]
    return int(route_count or 0) > 0


def list_snapshots() -> List[Dict[str, Any]]:
    with closing(_connect()) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT snapshot_key, source, dataset_ref, signature, generated_at, refreshed_at, meta_json
            FROM catalog_snapshots
            ORDER BY refreshed_at DESC, snapshot_key ASC
            """
        ).fetchall()

    items: List[Dict[str, Any]] = []
    for row in rows:
        meta = dict(_deserialize(row["meta_json"]) or {})
        items.append(
            {
                "snapshotKey": row["snapshot_key"],
                "source": row["source"],
                "datasetRef": row["dataset_ref"],
                "signature": row["signature"],
                "generatedAt": row["generated_at"],
                "refreshedAt": row["refreshed_at"],
                "meta": meta,
                **_snapshot_identity(str(row["source"]), str(row["dataset_ref"]), meta),
            }
        )
    return items


def get_snapshot(snapshot_key: str) -> Optional[Dict[str, Any]]:
    with closing(_connect()) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT snapshot_key, source, dataset_ref, signature, generated_at, refreshed_at, meta_json
            FROM catalog_snapshots
            WHERE snapshot_key = ?
            """,
            (snapshot_key,),
        ).fetchone()
    if row is None:
        return None
    meta = dict(_deserialize(row["meta_json"]) or {})
    return {
        "snapshotKey": row["snapshot_key"],
        "source": row["source"],
        "datasetRef": row["dataset_ref"],
        "signature": row["signature"],
        "generatedAt": row["generated_at"],
        "refreshedAt": row["refreshed_at"],
        "meta": meta,
        **_snapshot_identity(str(row["source"]), str(row["dataset_ref"]), meta),
    }


def find_snapshot(source: str, dataset_ref: str) -> Optional[Dict[str, Any]]:
    with closing(_connect()) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT snapshot_key
            FROM catalog_snapshots
            WHERE source = ? AND dataset_ref = ?
            ORDER BY refreshed_at DESC, snapshot_key DESC
            LIMIT 1
            """,
            (source, dataset_ref),
        ).fetchone()
    if row is None:
        return None
    return get_snapshot(str(row["snapshot_key"]))


def load_snapshot_bundle(snapshot_key: str) -> Dict[str, Any]:
    snapshot = get_snapshot(snapshot_key)
    if snapshot is None:
        raise KeyError(snapshot_key)
    meta = dict(snapshot.get("meta") or {})
    return {
        "snapshot": snapshot,
        "meta": {
            **meta,
            **_snapshot_identity(
                str(snapshot.get("source") or ""),
                str(snapshot.get("datasetRef") or ""),
                meta,
            ),
        },
        "stops": _load_entities(snapshot_key, "stops"),
        "routes": _load_entities(snapshot_key, "routes"),
        "timetable_rows": _load_entities(snapshot_key, "timetable_rows"),
        "stop_timetables": _load_entities(snapshot_key, "stop_timetables"),
        "calendar_entries": _load_entities(snapshot_key, "calendar_entries"),
        "calendar_date_entries": _load_entities(snapshot_key, "calendar_date_entries"),
        "route_payloads": _load_route_payloads(snapshot_key),
    }


def load_snapshot_bundle_slim(snapshot_key: str) -> Dict[str, Any]:
    snapshot = get_snapshot(snapshot_key)
    if snapshot is None:
        raise KeyError(snapshot_key)
    meta = dict(snapshot.get("meta") or {})
    return {
        "snapshot": snapshot,
        "meta": {
            **meta,
            **_snapshot_identity(
                str(snapshot.get("source") or ""),
                str(snapshot.get("datasetRef") or ""),
                meta,
            ),
        },
        "stops": _load_entities(snapshot_key, "stops"),
        "routes": _load_entities(snapshot_key, "routes"),
        "route_payloads": _load_route_payloads(snapshot_key),
    }


def _load_route_payloads(snapshot_key: str) -> List[Dict[str, Any]]:
    with closing(_connect()) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT payload_json
            FROM catalog_route_payloads
            WHERE snapshot_key = ?
            ORDER BY route_code ASC, route_label ASC, route_id ASC
            """,
            (snapshot_key,),
        ).fetchall()
    return [dict(_deserialize(row["payload_json"]) or {}) for row in rows]


def load_existing_odpt_snapshot(operator: str = DEFAULT_OPERATOR) -> Optional[Dict[str, Any]]:
    snapshot = find_snapshot("odpt", operator)
    if snapshot is None:
        return None
    return load_snapshot_bundle(str(snapshot["snapshotKey"]))


def load_existing_gtfs_snapshot(
    feed_path: str | Path = DEFAULT_GTFS_FEED_PATH,
) -> Optional[Dict[str, Any]]:
    snapshot = find_snapshot("gtfs", _gtfs_dataset_ref(feed_path))
    if snapshot is None:
        return None
    return load_snapshot_bundle(str(snapshot["snapshotKey"]))


def list_route_payload_summaries(snapshot_key: str) -> List[Dict[str, Any]]:
    with closing(_connect()) as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT route_id, route_code, route_label, trip_count, first_departure, last_arrival, services_json
            FROM catalog_route_payloads
            WHERE snapshot_key = ?
            ORDER BY route_code ASC, route_label ASC, route_id ASC
            """,
            (snapshot_key,),
        ).fetchall()

    return [
        {
            "route_id": row["route_id"],
            "route_code": row["route_code"],
            "route_label": row["route_label"],
            "trip_count": int(row["trip_count"] or 0),
            "first_departure": row["first_departure"],
            "last_arrival": row["last_arrival"],
            "services": list(_deserialize(row["services_json"]) or []),
        }
        for row in rows
    ]


def get_route_payload(snapshot_key: str, route_id: str) -> Optional[Dict[str, Any]]:
    with closing(_connect()) as conn:
        _ensure_schema(conn)
        row = conn.execute(
            """
            SELECT payload_json
            FROM catalog_route_payloads
            WHERE snapshot_key = ? AND route_id = ?
            """,
            (snapshot_key, route_id),
        ).fetchone()
    if row is None:
        return None
    return dict(_deserialize(row["payload_json"]) or {})


def _odpt_snapshot_key(operator: str) -> str:
    return _normalize_snapshot_key("odpt", operator)


def _gtfs_dataset_ref(feed_path: str | Path) -> str:
    feed_root = resolve_gtfs_feed_path(feed_path)
    try:
        return str(feed_root.relative_to(_REPO_ROOT))
    except ValueError:
        return str(feed_root)


def _gtfs_snapshot_key(feed_path: str | Path) -> str:
    return _normalize_snapshot_key("gtfs", _gtfs_dataset_ref(feed_path))


def _load_saved_odpt_snapshot(operator: str) -> Optional[Dict[str, Any]]:
    snapshot_dir = _odpt_saved_snapshot_dir(operator)
    if snapshot_dir is None:
        return None

    operational_path = snapshot_dir / "operational_dataset.json"
    operational_dataset = _read_json_object(operational_path)
    if operational_dataset is None:
        return None

    route_payloads = operational_dataset.get("routeTimetables")
    route_timetables_path = snapshot_dir / "route_timetables_dataset.json"
    if not isinstance(route_payloads, list):
        route_timetable_dataset = _read_json_object(route_timetables_path)
        route_items = (
            route_timetable_dataset.get("items") if route_timetable_dataset else None
        )
        route_payloads = route_items if isinstance(route_items, list) else []

    return {
        "dataset": operational_dataset,
        "route_payloads": list(route_payloads or []),
        "signature": _file_signature([operational_path, route_timetables_path]),
        "snapshot_dir": str(snapshot_dir),
    }


def _populate_operator_db_from_bundle(
    *,
    operator_id: str,
    bundle: Dict[str, Any],
    snapshot_key: str,
    source: str,
) -> Optional[Dict[str, Any]]:
    trip_stop_times = list(bundle.get("stop_times") or [])
    if not trip_stop_times:
        trip_stop_times = _trip_stop_times_from_route_payloads(
            list(bundle.get("route_payloads") or []),
            source=source,
        )

    try:
        meta_payload: Dict[str, str] = {
            "catalog_snapshot_key": str(snapshot_key),
            "feed_id": str((bundle.get("meta") or {}).get("feed_id") or ""),
            "snapshot_id": str(
                (bundle.get("meta") or {}).get("snapshot_id")
                or (bundle.get("meta") or {}).get("snapshotId")
                or ""
            ),
            "dataset_id": str((bundle.get("meta") or {}).get("dataset_id") or ""),
            "feed_path": str((bundle.get("meta") or {}).get("feedPath") or ""),
        }
        _tdb.replace_all(
            operator_id,
            routes=list(bundle.get("routes") or []),
            stops=list(bundle.get("stops") or []),
            timetable_rows=list(bundle.get("timetable_rows") or []),
            trip_stop_times=trip_stop_times,
            stop_timetables=list(bundle.get("stop_timetables") or []),
            calendar_entries=list(bundle.get("calendar_entries") or []),
            calendar_date_entries=_normalize_calendar_date_entries(
                list(bundle.get("calendar_date_entries") or [])
            ),
            meta=meta_payload,
        )
        return None
    except Exception as exc:
        _log.exception("transit_db: failed to populate %s DB", operator_id)
        return _db_warning("TRANSIT_DB_POPULATE_FAILED", exc)


def _odpt_snapshot_is_incomplete(bundle: Dict[str, Any]) -> bool:
    routes = list(bundle.get("routes") or [])
    timetable_rows = list(bundle.get("timetable_rows") or [])
    stop_timetables = list(bundle.get("stop_timetables") or [])
    if not routes:
        return False
    return len(timetable_rows) == 0 and len(stop_timetables) > 0


def _operator_db_matches_snapshot(operator_id: str, snapshot_key: str) -> bool:
    if not _tdb.db_exists(operator_id):
        return False
    return _tdb.get_metadata(operator_id, "catalog_snapshot_key") == snapshot_key


def _store_odpt_snapshot(
    *,
    operator: str,
    dataset: Dict[str, Any],
    route_payloads: Iterable[Dict[str, Any]],
    signature: str,
    requested_dump: bool,
    effective_dump: bool,
    snapshot_source: str,
    extra_meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    dataset_meta = dict(dataset.get("meta") or {})
    stops = build_stops_from_normalized(dataset)
    routes = build_routes_from_operational(dataset)
    timetable_rows = normalize_timetable_row_indexes(
        build_timetable_rows_from_operational(dataset)
    )
    stop_timetables = build_stop_timetables_from_normalized(dataset)
    canonical_route_payloads = _canonicalize_odpt_route_payloads(route_payloads)

    merged_meta = dict(extra_meta or {})
    extra_warnings = list(merged_meta.pop("warnings", []) or [])
    warnings = list(dict.fromkeys(list(dataset_meta.get("warnings") or []) + extra_warnings))

    meta = {
        "source": "odpt",
        "datasetRef": operator,
        "operator": operator,
        "dump": effective_dump,
        "requestedDump": requested_dump,
        "effectiveDump": effective_dump,
        "generatedAt": dataset_meta.get("generatedAt"),
        "refreshedAt": _now_iso(),
        "warnings": warnings,
        "cache": dict(dataset_meta.get("cache") or {}),
        "snapshotSource": snapshot_source,
        "counts": {
            "stops": len(stops),
            "routes": len(routes),
            "timetableRows": len(timetable_rows),
            "stopTimetables": len(stop_timetables),
            "routePayloads": len(canonical_route_payloads),
        },
    }
    meta["artifacts"] = {
        "operatorSummary": _write_operator_summary_artifact(
            snapshot_key=_odpt_snapshot_key(operator),
            operator_id=operator,
            source_type="odpt",
            routes=routes,
            stops=stops,
            timetable_rows=timetable_rows,
            stop_timetables=stop_timetables,
            updated_at=meta.get("refreshedAt"),
        )
    }
    meta.update(merged_meta)

    result = _replace_snapshot(
        snapshot_key=_odpt_snapshot_key(operator),
        source="odpt",
        dataset_ref=operator,
        signature=signature,
        meta=meta,
        entities={
            "stops": stops,
            "routes": routes,
            "timetable_rows": timetable_rows,
            "stop_timetables": stop_timetables,
            "calendar_entries": [],
            "calendar_date_entries": [],
        },
        route_payloads=canonical_route_payloads,
    )

    # --- Populate per-operator SQLite DB ---
    try:
        _tdb.replace_all(
            "tokyu",
            routes=routes,
            stops=stops,
            timetable_rows=timetable_rows,
            trip_stop_times=_trip_stop_times_from_route_payloads(
                canonical_route_payloads,
                source="odpt",
            ),
            stop_timetables=stop_timetables,
            calendar_entries=[],
            calendar_date_entries=[],
            meta={"catalog_snapshot_key": _odpt_snapshot_key(operator)},
        )
        _log.info("transit_db: tokyu DB populated (%d routes, %d stops, %d tt_rows)",
                   len(routes), len(stops), len(timetable_rows))
    except Exception:
        _log.exception("transit_db: failed to populate tokyu DB")

    return result


def bootstrap_odpt_snapshot_from_saved(
    *,
    operator: str = DEFAULT_OPERATOR,
) -> Optional[Dict[str, Any]]:
    saved = _load_saved_odpt_snapshot(operator)
    if saved is None:
        return None

    return _store_odpt_snapshot(
        operator=operator,
        dataset=dict(saved.get("dataset") or {}),
        route_payloads=list(saved.get("route_payloads") or []),
        signature=str(saved.get("signature") or operator),
        requested_dump=True,
        effective_dump=True,
        snapshot_source="saved-json",
        extra_meta={
            "snapshotDir": saved.get("snapshot_dir"),
            "warnings": [
                "Catalog bootstrapped from saved ODPT operational_dataset.json."
            ],
        },
    )


def refresh_odpt_snapshot(
    *,
    operator: str = DEFAULT_OPERATOR,
    dump: bool = True,
    force_refresh: bool = False,
    ttl_sec: int = 3600,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    """Refresh ODPT snapshot.

    Prefer the chunked ODPT Explorer BFF staged pipeline for complete
    timetable coverage. Fall back to the raw streaming fetch pipeline when
    the BFF is unavailable.
    """
    try:
        _log.info("refresh_odpt_snapshot: trying staged BFF pipeline")
        return _refresh_odpt_snapshot_via_stage_bff(
            operator=operator,
            dump=dump,
            force_refresh=force_refresh,
            ttl_sec=ttl_sec,
            progress_callback=progress_callback,
        )
    except Exception:
        _log.exception("refresh_odpt_snapshot: staged BFF pipeline failed; falling back")

    _log.info("refresh_odpt_snapshot: starting streaming file-based fallback pipeline")

    # -- Step 1: Fetch raw resources via streaming download --
    manifest = fetch_tokyu_odpt_bundle(operator_id=operator)
    snapshot_dir = Path(manifest["snapshot_dir"])
    snapshot_id = manifest["snapshot_id"]
    fetch_warnings = list(manifest.get("warnings") or [])

    _log.info(
        "refresh_odpt_snapshot: raw fetch complete, snapshot_id=%s, dir=%s",
        snapshot_id,
        snapshot_dir,
    )
    if progress_callback is not None:
        progress_callback(
            "odpt_raw_fetch_complete",
            {"snapshotId": snapshot_id, "counts": {"warnings": len(fetch_warnings)}},
        )

    # -- Step 2: Normalize from files --
    normalize_summary = normalize_odpt_snapshot(snapshot_dir)
    normalized_dir = Path(normalize_summary["normalized_dir"])
    normalize_warnings = list(normalize_summary.get("warnings") or [])

    _log.info(
        "refresh_odpt_snapshot: normalization complete, dir=%s",
        normalized_dir,
    )
    if progress_callback is not None:
        progress_callback(
            "odpt_normalize_complete",
            {"normalizedDir": str(normalized_dir), "counts": {"warnings": len(normalize_warnings)}},
        )

    # -- Step 3: Load normalized entities and store in catalog DB --
    bundle = load_normalized_bundle(normalized_dir)
    routes = bundle.get("routes", [])
    stops = bundle.get("stops", [])
    trips = bundle.get("trips", [])
    stop_timetables = bundle.get("stop_timetables", [])
    if progress_callback is not None:
        progress_callback(
            "odpt_bundle_loaded",
            {
                "counts": {
                    "routes": len(routes),
                    "stops": len(stops),
                    "timetableRows": len(trips),
                    "stopTimetables": len(stop_timetables),
                }
            },
        )

    all_warnings = list(dict.fromkeys(fetch_warnings + normalize_warnings))
    all_warnings.insert(
        0,
        "ODPT refresh uses streaming file-based pipeline (no large in-memory payloads).",
    )

    signature = _serialize(
        {
            "operator": operator,
            "snapshotId": snapshot_id,
            "snapshotStrategy": "streaming-file",
        }
    )

    meta = {
        "source": "odpt",
        "datasetRef": operator,
        "operator": operator,
        "dump": False,
        "requestedDump": dump,
        "effectiveDump": False,
        "generatedAt": manifest.get("started_at"),
        "refreshedAt": _now_iso(),
        "warnings": all_warnings,
        "snapshotSource": "streaming-file",
        "snapshotId": snapshot_id,
        "snapshotDir": str(snapshot_dir),
        "normalizedDir": str(normalized_dir),
        "counts": {
            "stops": len(stops),
            "routes": len(routes),
            "timetableRows": len(trips),
            "stopTimetables": len(stop_timetables),
            "routePayloads": 0,
        },
    }
    meta["artifacts"] = {
        "operatorSummary": _write_operator_summary_artifact(
            snapshot_key=_odpt_snapshot_key(operator),
            operator_id=operator,
            source_type="odpt",
            routes=routes,
            stops=stops,
            timetable_rows=trips,
            stop_timetables=stop_timetables,
            updated_at=meta.get("refreshedAt"),
        )
    }

    result = _replace_snapshot(
        snapshot_key=_odpt_snapshot_key(operator),
        source="odpt",
        dataset_ref=operator,
        signature=signature,
        meta=meta,
        entities={
            "stops": stops,
            "routes": routes,
            "timetable_rows": trips,
            "stop_timetables": stop_timetables,
            "calendar_entries": bundle.get("service_calendars", []),
            "calendar_date_entries": [],
        },
        route_payloads=[],
    )

    # Populate per-operator SQLite DB
    try:
        _tdb.replace_all(
            "tokyu",
            routes=routes,
            stops=stops,
            timetable_rows=trips,
            trip_stop_times=bundle.get("stop_times", []),
            stop_timetables=stop_timetables,
            calendar_entries=bundle.get("service_calendars", []),
            calendar_date_entries=[],
            meta={"catalog_snapshot_key": _odpt_snapshot_key(operator)},
        )
        _log.info(
            "transit_db: tokyu DB populated (%d routes, %d stops, %d trips)",
            len(routes),
            len(stops),
            len(trips),
        )
    except Exception:
        _log.exception("transit_db: failed to populate tokyu DB")

    return result


def get_or_refresh_odpt_snapshot(
    *,
    operator: str = DEFAULT_OPERATOR,
    dump: bool = True,
    force_refresh: bool = False,
    ttl_sec: int = 3600,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    snapshot_key = _odpt_snapshot_key(operator)
    snapshot = get_snapshot(snapshot_key)
    if (
        not force_refresh
        and snapshot is not None
        and _has_snapshot_payload(snapshot_key, _ODPT_REQUIRED_ENTITY_TYPES)
    ):
        bundle = load_snapshot_bundle(snapshot_key)
        if _odpt_snapshot_is_incomplete(bundle):
            _log.warning(
                "ODPT catalog snapshot %s is incomplete (routes=%d, timetable_rows=%d, stop_timetables=%d); refreshing",
                snapshot_key,
                len(bundle.get("routes") or []),
                len(bundle.get("timetable_rows") or []),
                len(bundle.get("stop_timetables") or []),
            )
        else:
            if not _operator_db_matches_snapshot("tokyu", snapshot_key):
                _populate_operator_db_from_bundle(
                    operator_id="tokyu",
                    bundle=bundle,
                    snapshot_key=snapshot_key,
                    source="odpt",
                )
            if progress_callback is not None:
                progress_callback(
                    "odpt_cached_snapshot",
                    {
                        "snapshotMode": "catalog",
                        "counts": {
                            "routes": len(bundle.get("routes") or []),
                            "stops": len(bundle.get("stops") or []),
                            "timetableRows": len(bundle.get("timetable_rows") or []),
                            "stopTimetables": len(bundle.get("stop_timetables") or []),
                        },
                    },
                )
            bundle["meta"]["snapshotMode"] = "catalog"
            return bundle

    if not force_refresh:
        bootstrapped = bootstrap_odpt_snapshot_from_saved(operator=operator)
        if bootstrapped is not None:
            bundle = load_snapshot_bundle(bootstrapped["snapshotKey"])
            _populate_operator_db_from_bundle(
                operator_id="tokyu",
                bundle=bundle,
                snapshot_key=bootstrapped["snapshotKey"],
                source="odpt",
            )
            if progress_callback is not None:
                progress_callback(
                    "odpt_saved_snapshot",
                    {
                        "snapshotMode": "saved-json",
                        "counts": {
                            "routes": len(bundle.get("routes") or []),
                            "stops": len(bundle.get("stops") or []),
                            "timetableRows": len(bundle.get("timetable_rows") or []),
                            "stopTimetables": len(bundle.get("stop_timetables") or []),
                        },
                    },
                )
            bundle["meta"]["snapshotMode"] = "saved-json"
            return bundle

    refreshed = refresh_odpt_snapshot(
        operator=operator,
        dump=dump,
        force_refresh=force_refresh,
        ttl_sec=ttl_sec,
        progress_callback=progress_callback,
    )
    bundle = load_snapshot_bundle(refreshed["snapshotKey"])
    bundle["meta"]["snapshotMode"] = "refreshed"
    return bundle


def refresh_gtfs_snapshot(
    *,
    feed_path: str | Path = DEFAULT_GTFS_FEED_PATH,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    dataset_ref = _gtfs_dataset_ref(feed_path)
    signature = _serialize(gtfs_feed_signature(feed_path))
    core = load_gtfs_core_bundle(feed_path)
    if progress_callback is not None:
        progress_callback(
            "gtfs_core_loaded",
            {
                "counts": {
                    "stops": len(list(core.get("stops") or [])),
                    "routes": len(list(core.get("routes") or [])),
                    "timetableRows": len(list(core.get("timetable_rows") or [])),
                    "calendarEntries": len(list(core.get("calendar_entries") or [])),
                }
            },
        )
    stop_bundle = build_gtfs_stop_timetables(feed_path)
    if progress_callback is not None:
        progress_callback(
            "gtfs_stop_timetables_built",
            {"counts": {"stopTimetables": len(list(stop_bundle.get("stop_timetables") or []))}},
        )
    route_bundle = build_gtfs_route_timetables(feed_path)
    if progress_callback is not None:
        progress_callback(
            "gtfs_route_payloads_built",
            {"counts": {"routePayloads": len(list(route_bundle.get("route_timetables") or []))}},
        )
    meta = {
        **dict(core.get("meta") or {}),
        "source": "gtfs",
        "datasetRef": dataset_ref,
        "signature": signature,
        "refreshedAt": _now_iso(),
        "counts": {
            "stops": len(list(core.get("stops") or [])),
            "routes": len(list(core.get("routes") or [])),
            "timetableRows": len(list(core.get("timetable_rows") or [])),
            "stopTimetables": len(list(stop_bundle.get("stop_timetables") or [])),
            "routePayloads": len(list(route_bundle.get("route_timetables") or [])),
        },
    }
    _stops = list(core.get("stops") or [])
    _routes = list(core.get("routes") or [])
    _tt_rows = list(core.get("timetable_rows") or [])
    _st = list(stop_bundle.get("stop_timetables") or [])
    _cal = list(core.get("calendar_entries") or [])
    _cal_dates = _normalize_calendar_date_entries(list(core.get("calendar_date_entries") or []))
    meta["artifacts"] = {
        "operatorSummary": _write_operator_summary_artifact(
            snapshot_key=_gtfs_snapshot_key(feed_path),
            operator_id="toei",
            source_type="gtfs",
            routes=_routes,
            stops=_stops,
            timetable_rows=_tt_rows,
            stop_timetables=_st,
            updated_at=meta.get("refreshedAt"),
        )
    }

    result = _replace_snapshot(
        snapshot_key=_gtfs_snapshot_key(feed_path),
        source="gtfs",
        dataset_ref=dataset_ref,
        signature=signature,
        meta=meta,
        entities={
            "stops": _stops,
            "routes": _routes,
            "timetable_rows": _tt_rows,
            "stop_timetables": _st,
            "calendar_entries": _cal,
            "calendar_date_entries": _cal_dates,
        },
        route_payloads=list(route_bundle.get("route_timetables") or []),
    )

    db_warning = _populate_operator_db_from_bundle(
        operator_id="toei",
        bundle={
            "routes": _routes,
            "stops": _stops,
            "timetable_rows": _tt_rows,
            "stop_times": _trip_stop_times_from_route_payloads(
                list(route_bundle.get("route_timetables") or []),
                source="gtfs",
            ),
            "stop_timetables": _st,
            "calendar_entries": _cal,
            "calendar_date_entries": _cal_dates,
        },
        snapshot_key=_gtfs_snapshot_key(feed_path),
        source="gtfs",
    )
    if db_warning is None:
        _log.info("transit_db: toei DB populated (%d routes, %d stops, %d tt_rows)",
                   len(_routes), len(_stops), len(_tt_rows))
    else:
        _append_warning_list(meta, db_warning)
        result["meta"] = meta
        result["warning"] = db_warning

    return result


def get_or_refresh_gtfs_snapshot(
    *,
    feed_path: str | Path = DEFAULT_GTFS_FEED_PATH,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, Any]:
    snapshot_key = _gtfs_snapshot_key(feed_path)
    expected_signature = _serialize(gtfs_feed_signature(feed_path))
    snapshot = get_snapshot(snapshot_key)
    if (
        snapshot is not None
        and snapshot.get("signature") == expected_signature
        and _has_snapshot_payload(snapshot_key, _GTFS_REQUIRED_ENTITY_TYPES)
    ):
        bundle = load_snapshot_bundle(snapshot_key)
        db_warning = None
        if not _operator_db_matches_snapshot("toei", snapshot_key):
            db_warning = _populate_operator_db_from_bundle(
                operator_id="toei",
                bundle=bundle,
                snapshot_key=snapshot_key,
                source="gtfs",
            )
        _append_warning_list(bundle["meta"], db_warning)
        if db_warning is not None:
            bundle["warning"] = db_warning
        if progress_callback is not None:
            progress_callback(
                "gtfs_cached_snapshot",
                {
                    "snapshotMode": "catalog",
                    "counts": {
                        "routes": len(bundle.get("routes") or []),
                        "stops": len(bundle.get("stops") or []),
                        "timetableRows": len(bundle.get("timetable_rows") or []),
                        "stopTimetables": len(bundle.get("stop_timetables") or []),
                    },
                },
            )
        bundle["meta"]["snapshotMode"] = "catalog"
        return bundle

    refreshed = refresh_gtfs_snapshot(feed_path=feed_path, progress_callback=progress_callback)
    bundle = load_snapshot_bundle(refreshed["snapshotKey"])
    bundle["meta"]["snapshotMode"] = "refreshed"
    return bundle
