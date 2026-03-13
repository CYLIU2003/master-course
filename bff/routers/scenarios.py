"""
bff/routers/scenarios.py

Scenario CRUD + app context + timetable + deadhead/turnaround rules endpoints.

Routes:
  GET    /scenarios                    → list
  GET    /scenarios/default            → get latest scenario metadata (legacy helper)
  POST   /scenarios                    → create
  GET    /scenarios/{id}               → get
  PUT    /scenarios/{id}               → update
  DELETE /scenarios/{id}               → delete
  POST   /scenarios/{id}/duplicate     → duplicate
  POST   /scenarios/{id}/activate      → set active scenario
  GET    /app/context                  → get app context

  GET    /scenarios/{id}/timetable               → get timetable rows (optional ?service_id=)
  PUT    /scenarios/{id}/timetable               → replace timetable rows
  POST   /scenarios/{id}/timetable/import-csv    → import rows from CSV text body
  POST   /scenarios/{id}/timetable/import-gtfs   → import rows from local GTFS feed
  GET    /scenarios/{id}/timetable/export-csv    → export rows as CSV text body

  GET    /scenarios/{id}/deadhead-rules    → list
  GET    /scenarios/{id}/turnaround-rules  → list
"""

from __future__ import annotations

import csv
import hashlib
import io
from threading import Lock
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from bff.services import runtime_catalog, transit_catalog
from bff.services.gtfs_import import (
    DEFAULT_GTFS_FEED_PATH,
    summarize_gtfs_stop_timetable_import,
    summarize_gtfs_timetable_import,
)
from bff.services.odpt_routes import DEFAULT_OPERATOR
from bff.services.odpt_stop_timetables import (
    summarize_stop_timetable_import,
)
from bff.services.odpt_timetable import (
    normalize_timetable_row_indexes,
    summarize_timetable_import,
)
from bff.services.service_ids import canonical_service_id
from bff.store import scenario_store as store
from src.dispatch.models import hhmm_to_min
from src.feed_identity import TOKYU_ODPT_GTFS_FEED_ID, build_dataset_id, infer_feed_id
from src.tokyubus_gtfs.constants import DEFAULT_TURNAROUND_SEC, ROUTE_FAMILY_MAP_PATH

router = APIRouter(tags=["scenarios"])
_default_scenario_lock = Lock()

# ── CSV column spec ────────────────────────────────────────────
# Canonical column order for import/export
_CSV_COLUMNS = [
    "trip_id",
    "route_id",
    "service_id",
    "direction",
    "origin",
    "destination",
    "departure",
    "arrival",
    "distance_km",
    "allowed_vehicle_types",
]

_MAX_PAGE_LIMIT = 500


def _paginate_items(
    items: List[Dict[str, Any]],
    limit: Optional[int],
    offset: int,
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    if limit is None:
        return items[offset:], None
    bounded_limit = max(1, min(limit, _MAX_PAGE_LIMIT))
    start = max(0, offset)
    end = start + bounded_limit
    return items[start:end], bounded_limit


def _updated_at_from_imports(imports: Dict[str, Any]) -> Optional[str]:
    generated_values = [
        str(meta.get("generatedAt"))
        for meta in (imports or {}).values()
        if isinstance(meta, dict) and meta.get("generatedAt")
    ]
    return max(generated_values) if generated_values else None


def _min_hhmm(values: List[str]) -> Optional[str]:
    usable = [value for value in values if isinstance(value, str) and value.strip()]
    if not usable:
        return None
    return min(usable, key=hhmm_to_min)


def _max_hhmm(values: List[str]) -> Optional[str]:
    usable = [value for value in values if isinstance(value, str) and value.strip()]
    if not usable:
        return None
    return max(usable, key=hhmm_to_min)


def _build_timetable_summary(
    rows: List[Dict[str, Any]],
    imports: Dict[str, Any],
) -> Dict[str, Any]:
    by_service: Dict[str, Dict[str, Any]] = {}
    by_route: Dict[str, Dict[str, Any]] = {}
    route_service_counts: Dict[str, Dict[str, int]] = {}
    stop_counts: Dict[str, int] = {}

    for row in rows:
        service_id = canonical_service_id(row.get("service_id"))
        route_id = str(row.get("route_id") or "")
        departure = str(row.get("departure") or "")
        arrival = str(row.get("arrival") or "")
        origin = str(row.get("origin") or "")
        destination = str(row.get("destination") or "")
        trip_id = str(row.get("trip_id") or "")

        service_bucket = by_service.setdefault(
            service_id,
            {
                "serviceId": service_id,
                "rowCount": 0,
                "routeIds": set(),
                "departures": [],
                "arrivals": [],
            },
        )
        service_bucket["rowCount"] += 1
        if route_id:
            service_bucket["routeIds"].add(route_id)
        if departure:
            service_bucket["departures"].append(departure)
        if arrival:
            service_bucket["arrivals"].append(arrival)

        route_bucket = by_route.setdefault(
            route_id or "__unknown__",
            {
                "routeId": route_id,
                "rowCount": 0,
                "serviceIds": set(),
                "departures": [],
                "arrivals": [],
                "sampleTripIds": [],
            },
        )
        route_bucket["rowCount"] += 1
        route_bucket["serviceIds"].add(service_id)
        if departure:
            route_bucket["departures"].append(departure)
        if arrival:
            route_bucket["arrivals"].append(arrival)
        if trip_id and len(route_bucket["sampleTripIds"]) < 5:
            route_bucket["sampleTripIds"].append(trip_id)

        route_service_counts.setdefault(service_id, {})
        if route_id:
            route_service_counts[service_id][route_id] = (
                route_service_counts[service_id].get(route_id, 0) + 1
            )

        if origin:
            stop_counts[origin] = stop_counts.get(origin, 0) + 1
        if destination:
            stop_counts[destination] = stop_counts.get(destination, 0) + 1

    service_summaries = sorted(
        [
            {
                "serviceId": bucket["serviceId"],
                "rowCount": bucket["rowCount"],
                "routeCount": len(bucket["routeIds"]),
                "firstDeparture": _min_hhmm(bucket["departures"]),
                "lastArrival": _max_hhmm(bucket["arrivals"]),
            }
            for bucket in by_service.values()
        ],
        key=lambda item: str(item.get("serviceId") or ""),
    )

    route_summaries = sorted(
        [
            {
                "routeId": bucket["routeId"],
                "rowCount": bucket["rowCount"],
                "serviceCount": len(bucket["serviceIds"]),
                "firstDeparture": _min_hhmm(bucket["departures"]),
                "lastArrival": _max_hhmm(bucket["arrivals"]),
                "sampleTripIds": bucket["sampleTripIds"],
            }
            for bucket in by_route.values()
            if bucket["routeId"]
        ],
        key=lambda item: (
            str(item.get("routeId") or ""),
            str(item.get("firstDeparture") or ""),
        ),
    )

    return {
        "totalRows": len(rows),
        "serviceCount": len(service_summaries),
        "routeCount": len(route_summaries),
        "stopCount": len(stop_counts),
        "updatedAt": _updated_at_from_imports(imports),
        "byService": service_summaries,
        "byRoute": route_summaries[:200],
        "routeServiceCounts": route_service_counts,
        "previewTripIds": [
            str(row.get("trip_id") or "")
            for row in rows[: min(100, len(rows))]
            if row.get("trip_id")
        ],
        "imports": imports,
    }


def _build_stop_timetable_summary(
    items: List[Dict[str, Any]],
    imports: Dict[str, Any],
) -> Dict[str, Any]:
    by_service: Dict[str, Dict[str, Any]] = {}
    by_stop: Dict[str, Dict[str, Any]] = {}
    total_entries = 0

    for item in items:
        service_id = canonical_service_id(item.get("service_id"))
        stop_id = str(item.get("stopId") or item.get("stop_id") or "")
        stop_name = str(item.get("stopName") or item.get("stop_name") or stop_id)
        entry_count = len(item.get("items") or [])
        total_entries += entry_count

        service_bucket = by_service.setdefault(
            service_id,
            {
                "serviceId": service_id,
                "timetableCount": 0,
                "entryCount": 0,
                "stopIds": set(),
            },
        )
        service_bucket["timetableCount"] += 1
        service_bucket["entryCount"] += entry_count
        if stop_id:
            service_bucket["stopIds"].add(stop_id)

        stop_bucket = by_stop.setdefault(
            stop_id or "__unknown__",
            {
                "stopId": stop_id,
                "stopName": stop_name,
                "timetableCount": 0,
                "entryCount": 0,
                "serviceIds": set(),
            },
        )
        stop_bucket["timetableCount"] += 1
        stop_bucket["entryCount"] += entry_count
        stop_bucket["serviceIds"].add(service_id)

    return {
        "totalTimetables": len(items),
        "totalEntries": total_entries,
        "serviceCount": len(by_service),
        "stopCount": len([key for key in by_stop.keys() if key != "__unknown__"]),
        "updatedAt": _updated_at_from_imports(imports),
        "byService": sorted(
            [
                {
                    "serviceId": bucket["serviceId"],
                    "timetableCount": bucket["timetableCount"],
                    "entryCount": bucket["entryCount"],
                    "stopCount": len(bucket["stopIds"]),
                }
                for bucket in by_service.values()
            ],
            key=lambda item: item["serviceId"],
        ),
        "byStop": sorted(
            [
                {
                    "stopId": bucket["stopId"],
                    "stopName": bucket["stopName"],
                    "timetableCount": bucket["timetableCount"],
                    "entryCount": bucket["entryCount"],
                    "serviceCount": len(bucket["serviceIds"]),
                }
                for bucket in by_stop.values()
                if bucket["stopId"]
            ],
            key=lambda item: (item["stopName"], item["stopId"]),
        )[:200],
        "imports": imports,
    }


# ── Pydantic models ────────────────────────────────────────────


class CreateScenarioBody(BaseModel):
    name: str
    description: str = ""
    mode: str = "thesis_mode"
    operatorId: Literal["tokyu", "toei"]


class UpdateScenarioBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    mode: Optional[str] = None
    operatorId: Optional[Literal["tokyu", "toei"]] = None


class DuplicateScenarioBody(BaseModel):
    name: Optional[str] = None


class UpdateDispatchScopeBody(BaseModel):
    scopeId: Optional[str] = None
    operatorId: Optional[str] = None
    datasetVersion: Optional[str] = None
    depotId: Optional[str] = None
    serviceId: Optional[str] = None
    depotSelection: Optional[Dict[str, Any]] = None
    routeSelection: Optional[Dict[str, Any]] = None
    serviceSelection: Optional[Dict[str, Any]] = None
    tripSelection: Optional[Dict[str, Any]] = None


class TimetableRowBody(BaseModel):
    route_id: str
    service_id: str = "WEEKDAY"
    direction: str = "outbound"
    trip_index: int = 0
    origin: str
    destination: str
    departure: str  # HH:MM (24h, may exceed 24 for overnight)
    arrival: str  # HH:MM
    distance_km: float = 0.0
    allowed_vehicle_types: List[str] = ["BEV", "ICE"]


class UpdateTimetableBody(BaseModel):
    rows: List[TimetableRowBody]


class ImportCsvBody(BaseModel):
    content: str  # raw CSV text (UTF-8)


class ImportOdptTimetableBody(BaseModel):
    operator: str = DEFAULT_OPERATOR
    dump: bool = True
    forceRefresh: bool = False
    ttlSec: int = 3600
    chunkBusTimetables: bool = False
    busTimetableCursor: int = 0
    busTimetableBatchSize: int = 25
    reset: bool = True


class ImportGtfsTimetableBody(BaseModel):
    feedPath: str = DEFAULT_GTFS_FEED_PATH
    forceRefresh: bool = False
    reset: bool = True


class ImportOdptStopTimetableBody(BaseModel):
    operator: str = DEFAULT_OPERATOR
    dump: bool = True
    forceRefresh: bool = False
    ttlSec: int = 3600
    stopTimetableCursor: int = 0
    stopTimetableBatchSize: int = 50
    reset: bool = True


class ImportGtfsStopTimetableBody(BaseModel):
    feedPath: str = DEFAULT_GTFS_FEED_PATH
    forceRefresh: bool = False
    reset: bool = True


class ImportRuntimeSnapshotBody(BaseModel):
    snapshotId: Optional[str] = None
    importDeadheadRules: bool = True
    importTurnaroundRules: bool = True
    resetRuntimeSource: bool = True


# ── Helpers ────────────────────────────────────────────────────


def _not_found(scenario_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")


def _runtime_err_to_http(e: RuntimeError) -> HTTPException:
    """Convert a store RuntimeError into an HTTPException.

    RuntimeError with 'artifacts are incomplete' → 409 INCOMPLETE_ARTIFACT.
    Other RuntimeErrors → re-raise as-is (FastAPI will 500 them).
    """
    msg = str(e)
    if "artifacts are incomplete" in msg:
        return HTTPException(
            status_code=409,
            detail={"code": "INCOMPLETE_ARTIFACT", "message": msg},
        )
    raise e


def _load_odpt_bundle(
    *,
    operator: str,
    dump: bool,
    force_refresh: bool,
    ttl_sec: int,
    progress_callback: Optional[transit_catalog.ProgressCallback] = None,
) -> Dict[str, Any]:
    if force_refresh:
        return transit_catalog.refresh_odpt_snapshot(
            operator=operator,
            dump=dump,
            force_refresh=True,
            ttl_sec=ttl_sec,
            progress_callback=progress_callback,
        )
    bundle = transit_catalog.load_existing_odpt_snapshot(operator=operator)
    if bundle is not None:
        return bundle
    raise RuntimeError(
        "No saved ODPT snapshot is available. Run `python3 catalog_update_app.py refresh odpt` "
        "or retry with forceRefresh=true."
    )


def _load_gtfs_bundle(
    *,
    feed_path: str,
    force_refresh: bool,
    progress_callback: Optional[transit_catalog.ProgressCallback] = None,
) -> Dict[str, Any]:
    if force_refresh:
        return transit_catalog.refresh_gtfs_snapshot(
            feed_path=feed_path,
            progress_callback=progress_callback,
        )
    bundle = transit_catalog.load_existing_gtfs_snapshot(feed_path=feed_path)
    if bundle is not None:
        return bundle
    raise RuntimeError(
        "No saved GTFS snapshot is available. Run `python3 catalog_update_app.py refresh gtfs` "
        "or retry with forceRefresh=true."
    )


def _pick_latest_scenario(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not items:
        return None
    return sorted(
        items,
        key=lambda x: (
            str(x.get("updatedAt", "")),
            str(x.get("createdAt", "")),
            str(x.get("id", "")),
        ),
        reverse=True,
    )[0]


def _build_odpt_import_meta(
    *,
    dataset: Dict[str, Any],
    operator: str,
    dump: bool,
    quality: Dict[str, Any],
    progress_key: str,
    resource_type: str,
) -> Dict[str, Any]:
    meta = dataset.get("meta", {}) if isinstance(dataset, dict) else {}
    progress = (meta.get("progress") or {}).get(progress_key)
    return {
        "operator": operator,
        "dump": meta.get("effectiveDump", meta.get("dump", dump)),
        "requestedDump": dump,
        "source": "odpt",
        "feed_id": str(meta.get("feed_id") or TOKYU_ODPT_GTFS_FEED_ID),
        "snapshot_id": meta.get("snapshotId"),
        "dataset_id": str(
            meta.get("dataset_id")
            or build_dataset_id(
                str(meta.get("feed_id") or TOKYU_ODPT_GTFS_FEED_ID),
                str(meta.get("snapshotId") or "") or None,
            )
        ),
        "resourceType": resource_type,
        "generatedAt": meta.get("generatedAt"),
        "warnings": meta.get("warnings", []),
        "cache": meta.get("cache", {}),
        "progress": progress,
        "snapshotKey": (dataset.get("snapshot") or {}).get("snapshotKey"),
        "snapshotMode": meta.get("snapshotMode"),
        "quality": quality,
    }


def _build_gtfs_import_meta(
    *,
    bundle: Dict[str, Any],
    quality: Dict[str, Any],
    resource_type: str,
) -> Dict[str, Any]:
    meta = bundle.get("meta", {}) if isinstance(bundle, dict) else {}
    feed_id = str(
        meta.get("feed_id") or infer_feed_id(meta.get("feedPath") or "") or ""
    )
    snapshot_id = str(meta.get("snapshot_id") or "") or None
    dataset_id = str(meta.get("dataset_id") or "") or (
        build_dataset_id(feed_id, snapshot_id) if feed_id else ""
    )
    return {
        "feedPath": meta.get("feedPath"),
        "agencyName": meta.get("agencyName"),
        "source": "gtfs",
        "feed_id": feed_id or None,
        "snapshot_id": snapshot_id,
        "dataset_id": dataset_id or None,
        "resourceType": resource_type,
        "generatedAt": meta.get("generatedAt"),
        "warnings": meta.get("warnings", []),
        "snapshotKey": (bundle.get("snapshot") or {}).get("snapshotKey"),
        "snapshotMode": meta.get("snapshotMode"),
        "quality": quality,
    }


def _build_runtime_import_meta(
    *,
    bundle: Dict[str, Any],
    quality: Dict[str, Any],
    resource_type: str,
) -> Dict[str, Any]:
    meta = bundle.get("meta", {}) if isinstance(bundle, dict) else {}
    return {
        "source": "gtfs_runtime",
        "operator": meta.get("operator") or "tokyu",
        "feed_id": meta.get("feed_id"),
        "snapshot_id": meta.get("snapshotId"),
        "dataset_id": meta.get("dataset_id"),
        "resourceType": resource_type,
        "generatedAt": meta.get("generatedAt"),
        "warnings": meta.get("warnings", []),
        "snapshotId": meta.get("snapshotId"),
        "snapshotKey": (bundle.get("snapshot") or {}).get("snapshotKey"),
        "snapshotMode": meta.get("snapshotMode"),
        "canonicalDir": meta.get("canonicalDir"),
        "featuresDir": meta.get("featuresDir"),
        "featureCounts": meta.get("featureCounts") or {},
        "quality": quality,
    }


def _runtime_deadhead_rules(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    items = list(((bundle.get("features") or {}).get("deadhead_candidates") or []))
    return [
        {
            "from_stop": str(item.get("from_stop_id") or ""),
            "to_stop": str(item.get("to_stop_id") or ""),
            "travel_time_min": int(round(float(item.get("estimated_time_min") or 0.0))),
            "distance_km": float(item.get("estimated_road_km") or 0.0),
        }
        for item in items
        if item.get("from_stop_id") is not None and item.get("to_stop_id") is not None
    ]


def _runtime_turnaround_rules(bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    route_items = list(bundle.get("routes") or [])
    turnaround_min = max(1, int(round(DEFAULT_TURNAROUND_SEC / 60)))
    stop_ids = {
        str(stop_id)
        for route in route_items
        for stop_id in (route.get("startStopId"), route.get("endStopId"))
        if stop_id
    }
    if not stop_ids:
        stop_ids = {
            str(item.get("id"))
            for item in list(bundle.get("stops") or [])
            if item.get("id") is not None
        }
    return [
        {"stop_id": stop_id, "min_turnaround_min": turnaround_min}
        for stop_id in sorted(stop_ids)
    ]


def _bundle_feed_context(
    source: str, bundle: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    meta = bundle.get("meta", {}) if isinstance(bundle, dict) else {}
    feed_id = str(
        meta.get("feed_id")
        or infer_feed_id(meta.get("feedPath") or "")
        or (TOKYU_ODPT_GTFS_FEED_ID if source in {"odpt", "gtfs_runtime"} else "")
    ).strip()
    snapshot_id = str(meta.get("snapshot_id") or meta.get("snapshotId") or "").strip()
    dataset_id = str(meta.get("dataset_id") or "").strip()
    if feed_id and not dataset_id:
        dataset_id = build_dataset_id(feed_id, snapshot_id or None)
    manual_hash = str(
        meta.get("manualRouteFamilyMapHash") or _manual_route_family_map_hash() or ""
    ).strip()
    dataset_fingerprint = dataset_id or build_dataset_id(
        feed_id or source, snapshot_id or None
    )
    if manual_hash:
        dataset_fingerprint = (
            f"{dataset_fingerprint}::route_family_map:{manual_hash[:12]}"
        )
    if not any((feed_id, snapshot_id, dataset_id)):
        return None
    return {
        "feed_id": feed_id or None,
        "snapshot_id": snapshot_id or None,
        "dataset_id": dataset_id or None,
        "dataset_fingerprint": dataset_fingerprint or None,
        "manual_route_family_map_hash": manual_hash or None,
        "source": source,
    }


def _manual_route_family_map_hash() -> Optional[str]:
    try:
        if not ROUTE_FAMILY_MAP_PATH.exists():
            return None
        return hashlib.sha256(ROUTE_FAMILY_MAP_PATH.read_bytes()).hexdigest()
    except Exception:
        return None


def _source_snapshot_from_bundle(source: str, bundle: Dict[str, Any]) -> Dict[str, Any]:
    meta = bundle.get("meta", {}) if isinstance(bundle, dict) else {}
    feed_id = meta.get("feed_id") or infer_feed_id(meta.get("feedPath") or "")
    snapshot_id = meta.get("snapshot_id") or meta.get("snapshotId")
    dataset_id = meta.get("dataset_id")
    manual_hash = (
        str(
            meta.get("manualRouteFamilyMapHash")
            or _manual_route_family_map_hash()
            or ""
        ).strip()
        or None
    )
    dataset_fingerprint = dataset_id or build_dataset_id(
        str(feed_id or source), str(snapshot_id or "") or None
    )
    if manual_hash:
        dataset_fingerprint = (
            f"{dataset_fingerprint}::route_family_map:{manual_hash[:12]}"
        )
    snapshot = {
        "source": source,
        "snapshotId": snapshot_id,
        "snapshotKey": (bundle.get("snapshot") or {}).get("snapshotKey"),
        "feedId": feed_id,
        "datasetId": dataset_id,
        "datasetFingerprint": dataset_fingerprint,
        "manualRouteFamilyMapHash": manual_hash,
    }
    if source == "gtfs_runtime":
        snapshot.update(
            {
                "canonicalDir": meta.get("canonicalDir"),
                "featuresDir": meta.get("featuresDir"),
                "featureCounts": meta.get("featureCounts") or {},
            }
        )
    return snapshot


# ── Scenario CRUD ──────────────────────────────────────────────


@router.get("/scenarios")
def list_scenarios() -> Dict[str, Any]:
    items = store.list_scenarios()
    return {"items": items, "total": len(items)}


@router.get("/scenarios/default")
def get_or_create_default_scenario() -> Dict[str, Any]:
    """
    Legacy helper retained for compatibility.
    Returns the latest scenario metadata if one exists.
    """
    with _default_scenario_lock:
        items = store.list_scenarios()
        latest = _pick_latest_scenario(items)
        if latest is None:
            raise HTTPException(status_code=404, detail="No scenarios found")
        return latest


@router.post("/scenarios", status_code=201)
def create_scenario(body: CreateScenarioBody) -> Dict[str, Any]:
    return store.create_scenario(
        name=body.name,
        description=body.description,
        mode=body.mode,
        operator_id=body.operatorId,
    )


@router.post("/scenarios/{scenario_id}/duplicate", status_code=201)
def duplicate_scenario(
    scenario_id: str, body: Optional[DuplicateScenarioBody] = None
) -> Dict[str, Any]:
    try:
        return store.duplicate_scenario(scenario_id, name=body.name if body else None)
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)


@router.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: str) -> Dict[str, Any]:
    try:
        return store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        if "artifacts are incomplete" in str(e):
            raise HTTPException(
                status_code=409,
                detail={"code": "INCOMPLETE_ARTIFACT", "message": str(e)},
            )
        raise


@router.put("/scenarios/{scenario_id}")
def update_scenario(scenario_id: str, body: UpdateScenarioBody) -> Dict[str, Any]:
    try:
        return store.update_scenario(
            scenario_id,
            name=body.name,
            description=body.description,
            mode=body.mode,
            operator_id=body.operatorId,
        )
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)


@router.get("/scenarios/{scenario_id}/dispatch-scope")
def get_dispatch_scope(scenario_id: str) -> Dict[str, Any]:
    try:
        return store.get_dispatch_scope(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)


@router.put("/scenarios/{scenario_id}/dispatch-scope")
def update_dispatch_scope(
    scenario_id: str, body: UpdateDispatchScopeBody
) -> Dict[str, Any]:
    try:
        return store.set_dispatch_scope(scenario_id, body.model_dump())
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)


@router.get("/planning/depot-scope/{depot_id}/trips")
def get_depot_scope_trips(
    depot_id: str,
    scenario_id: str = Query(..., alias="scenarioId"),
    service_id: Optional[str] = Query(default=None, alias="serviceId"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    try:
        current_scope = store.get_dispatch_scope(scenario_id)
        scoped_scope = {
            **current_scope,
            "depotId": depot_id,
            "depotSelection": {
                **dict(current_scope.get("depotSelection") or {}),
                "mode": "include",
                "depotIds": [depot_id],
                "primaryDepotId": depot_id,
            },
        }
        if service_id:
            scoped_scope["serviceId"] = service_id
            scoped_scope["serviceSelection"] = {"serviceIds": [service_id]}
        route_ids = set(store.effective_route_ids_for_scope(scenario_id, scoped_scope))
        rows = list(store.get_field(scenario_id, "timetable_rows") or [])
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)

    filtered = [
        row
        for row in rows
        if (not route_ids or str(row.get("route_id") or "") in route_ids)
        and (not service_id or str(row.get("service_id") or "") == service_id)
    ]
    paged = filtered[offset : offset + limit]
    return {
        "items": paged,
        "total": len(filtered),
        "limit": limit,
        "offset": offset,
        "meta": {
            "depotId": depot_id,
            "routeCount": len(route_ids),
        },
    }


@router.delete("/scenarios/{scenario_id}", status_code=204)
def delete_scenario(scenario_id: str) -> Response:
    try:
        store.delete_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    return Response(status_code=204)


@router.post("/scenarios/{scenario_id}/activate")
def activate_scenario(scenario_id: str) -> Dict[str, Any]:
    try:
        scenario = store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)
    context = store.set_active_scenario(scenario_id)
    return {
        "activeScenarioId": scenario_id,
        "scenarioName": scenario.get("name"),
        "selectedOperatorId": scenario.get("operatorId"),
        "availableModules": [
            "planning",
            "simulation",
            "dispatch",
            "results",
            "public-data",
        ],
        "lastOpenedPage": context.get("lastOpenedPage"),
        "updatedAt": context.get("updatedAt"),
    }


@router.get("/app/context")
def get_app_context() -> Dict[str, Any]:
    context = store.get_app_context()
    scenario_id = context.get("activeScenarioId")
    scenario = None
    if isinstance(scenario_id, str):
        try:
            scenario = store.get_scenario(scenario_id)
        except (KeyError, RuntimeError):
            context = store.set_active_scenario(
                None,
                last_opened_page=context.get("lastOpenedPage"),
            )
            scenario_id = None
    return {
        "activeScenarioId": scenario_id,
        "scenarioName": scenario.get("name") if scenario else None,
        "selectedOperatorId": context.get("selectedOperatorId")
        or (scenario.get("operatorId") if scenario else None),
        "availableModules": [
            "planning",
            "simulation",
            "dispatch",
            "results",
            "public-data",
        ],
        "lastOpenedPage": context.get("lastOpenedPage"),
        "updatedAt": context.get("updatedAt"),
    }


# ── Timetable ──────────────────────────────────────────────────


@router.get("/scenarios/{scenario_id}/timetable")
def get_timetable(
    scenario_id: str,
    service_id: Optional[str] = Query(
        default=None, description="Filter by service_id (WEEKDAY / SAT / SUN_HOL)"
    ),
    limit: Optional[int] = Query(
        default=None,
        ge=1,
        le=_MAX_PAGE_LIMIT,
        description="Optional page size. Omit to return all rows.",
    ),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    try:
        if limit is not None:
            paged_rows = (
                store.page_timetable_rows(
                    scenario_id,
                    offset=offset,
                    limit=limit,
                    service_id=service_id,
                )
                if service_id is not None
                else store.page_field_rows(
                    scenario_id,
                    "timetable_rows",
                    offset=offset,
                    limit=limit,
                )
            )
            total = (
                store.count_timetable_rows(scenario_id, service_id=service_id)
                if service_id is not None
                else store.count_field_rows(scenario_id, "timetable_rows")
            )
            page_limit = limit
            return {
                "items": paged_rows,
                "total": total,
                "limit": page_limit,
                "offset": offset,
                "meta": {"imports": store.get_timetable_import_meta(scenario_id)},
            }
        rows = store.get_field(scenario_id, "timetable_rows")
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)
    rows = rows or []
    if service_id:
        rows = [r for r in rows if r.get("service_id", "WEEKDAY") == service_id]
    paged_rows, page_limit = _paginate_items(rows, limit, offset)
    total = len(rows)
    return {
        "items": paged_rows,
        "total": total,
        "limit": page_limit,
        "offset": offset,
        "meta": {"imports": store.get_timetable_import_meta(scenario_id)},
    }


@router.get("/scenarios/{scenario_id}/timetable/summary")
def get_timetable_summary(scenario_id: str) -> Dict[str, Any]:
    try:
        summary = store.get_field_summary(scenario_id, "timetable_rows")
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)
    if summary is not None:
        return {"item": summary}
    rows = store.get_field(scenario_id, "timetable_rows") or []
    imports = store.get_timetable_import_meta(scenario_id)
    return {"item": _build_timetable_summary(rows, imports)}


@router.put("/scenarios/{scenario_id}/timetable")
def update_timetable(scenario_id: str, body: UpdateTimetableBody) -> Dict[str, Any]:
    try:
        rows = [r.model_dump() for r in body.rows]
        store.set_field(scenario_id, "timetable_rows", rows, invalidate_dispatch=True)
        return {"items": rows, "total": len(rows)}
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        raise _runtime_err_to_http(e)


@router.post("/scenarios/{scenario_id}/timetable/import-csv")
def import_timetable_csv(scenario_id: str, body: ImportCsvBody) -> Dict[str, Any]:
    """
    Parse CSV text and replace the scenario's timetable rows.
    Expected columns (in any order):
      trip_id (optional), route_id, service_id, direction, origin, destination,
      departure, arrival, distance_km, allowed_vehicle_types
    allowed_vehicle_types may be semicolon-separated: BEV;ICE
    """
    try:
        store.get_scenario(scenario_id)  # verify exists
    except KeyError:
        raise _not_found(scenario_id)

    reader = csv.DictReader(io.StringIO(body.content.strip()))
    rows: List[Dict[str, Any]] = []
    errors: List[str] = []

    for i, raw in enumerate(reader, start=2):  # 2 = first data row
        try:
            avt_raw = raw.get("allowed_vehicle_types", "BEV;ICE").strip()
            avt = [v.strip() for v in avt_raw.replace(",", ";").split(";") if v.strip()]
            row: Dict[str, Any] = {
                "route_id": raw.get("route_id", "").strip(),
                "service_id": raw.get("service_id", "WEEKDAY").strip() or "WEEKDAY",
                "direction": raw.get("direction", "outbound").strip() or "outbound",
                "trip_index": i - 2,
                "origin": raw.get("origin", raw.get("from_stop_id", "")).strip(),
                "destination": raw.get(
                    "destination", raw.get("to_stop_id", "")
                ).strip(),
                "departure": raw.get("departure", raw.get("dep_time", "")).strip(),
                "arrival": raw.get("arrival", raw.get("arr_time", "")).strip(),
                "distance_km": float(
                    raw.get("distance_km", raw.get("dist_km", 0)) or 0
                ),
                "allowed_vehicle_types": avt if avt else ["BEV", "ICE"],
            }
            if not row["route_id"]:
                errors.append(f"Row {i}: route_id is required")
                continue
            if not row["departure"] or not row["arrival"]:
                errors.append(f"Row {i}: departure and arrival are required")
                continue
            rows.append(row)
        except Exception as exc:
            errors.append(f"Row {i}: {exc}")

    if errors:
        raise HTTPException(
            status_code=422, detail={"errors": errors, "parsed": len(rows)}
        )

    store.set_field(scenario_id, "timetable_rows", rows, invalidate_dispatch=True)
    return {"items": rows, "total": len(rows)}


def _import_odpt_timetable_data(
    scenario_id: str,
    body: ImportOdptTimetableBody,
    progress_callback: Optional[transit_catalog.ProgressCallback] = None,
) -> Dict[str, Any]:
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)

    bundle = _load_odpt_bundle(
        operator=body.operator,
        dump=body.dump,
        force_refresh=body.forceRefresh,
        ttl_sec=body.ttlSec,
        progress_callback=progress_callback,
    )
    rows = list(bundle.get("timetable_rows") or [])
    merged_rows = store.upsert_timetable_rows_from_source(
        scenario_id,
        "odpt",
        rows,
        replace_existing_source=body.reset,
    )
    normalized_rows = normalize_timetable_row_indexes(merged_rows)
    store.set_field(
        scenario_id,
        "timetable_rows",
        normalized_rows,
        invalidate_dispatch=True,
    )
    odpt_rows = [row for row in normalized_rows if row.get("source") == "odpt"]
    quality = summarize_timetable_import(
        odpt_rows,
        {
            "meta": bundle.get("meta") or {},
            "stopTimetables": list(bundle.get("stop_timetables") or []),
        },
    )
    for entry in list(bundle.get("calendar_entries") or []):
        store.upsert_calendar_entry(scenario_id, entry)
    import_meta = _build_odpt_import_meta(
        dataset=bundle,
        operator=body.operator,
        dump=body.dump,
        quality=quality,
        progress_key="busTimetables",
        resource_type="BusTimetable",
    )
    store.set_timetable_import_meta(scenario_id, "odpt", import_meta)
    store.set_field(
        scenario_id,
        "source_snapshot",
        _source_snapshot_from_bundle("odpt", bundle),
    )
    store.set_feed_context(scenario_id, _bundle_feed_context("odpt", bundle))
    return {
        "items": odpt_rows,
        "total": len(odpt_rows),
        "meta": import_meta,
    }


def _import_gtfs_timetable_data(
    scenario_id: str,
    body: ImportGtfsTimetableBody,
    progress_callback: Optional[transit_catalog.ProgressCallback] = None,
) -> Dict[str, Any]:
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)

    bundle = _load_gtfs_bundle(
        feed_path=body.feedPath,
        force_refresh=body.forceRefresh,
        progress_callback=progress_callback,
    )
    rows = list(bundle.get("timetable_rows") or [])
    merged_rows = store.upsert_timetable_rows_from_source(
        scenario_id,
        "gtfs",
        rows,
        replace_existing_source=body.reset,
    )
    normalized_rows = normalize_timetable_row_indexes(merged_rows)
    store.set_field(
        scenario_id,
        "timetable_rows",
        normalized_rows,
        invalidate_dispatch=True,
    )
    gtfs_rows = [row for row in normalized_rows if row.get("source") == "gtfs"]
    quality = summarize_gtfs_timetable_import(
        gtfs_rows,
        {
            "meta": bundle.get("meta") or {},
            "stop_timetable_count": len(list(bundle.get("stop_timetables") or [])),
        },
    )

    calendar_entries = list(bundle.get("calendar_entries") or [])
    calendar_date_entries = list(bundle.get("calendar_date_entries") or [])
    for entry in calendar_entries:
        store.upsert_calendar_entry(scenario_id, entry)
    for entry in calendar_date_entries:
        store.upsert_calendar_date(scenario_id, entry)
    quality["calendarEntriesSynced"] = len(calendar_entries)
    quality["calendarDateEntriesSynced"] = len(calendar_date_entries)

    import_meta = _build_gtfs_import_meta(
        bundle=bundle,
        quality=quality,
        resource_type="GTFSTrip",
    )
    store.set_timetable_import_meta(scenario_id, "gtfs", import_meta)
    store.set_field(
        scenario_id,
        "source_snapshot",
        _source_snapshot_from_bundle("gtfs", bundle),
    )
    store.set_feed_context(scenario_id, _bundle_feed_context("gtfs", bundle))
    return {
        "items": gtfs_rows,
        "total": len(gtfs_rows),
        "meta": import_meta,
    }


def _import_odpt_stop_timetables_data(
    scenario_id: str,
    body: ImportOdptStopTimetableBody,
    progress_callback: Optional[transit_catalog.ProgressCallback] = None,
) -> Dict[str, Any]:
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)

    bundle = _load_odpt_bundle(
        operator=body.operator,
        dump=body.dump,
        force_refresh=body.forceRefresh,
        ttl_sec=body.ttlSec,
        progress_callback=progress_callback,
    )
    items = list(bundle.get("stop_timetables") or [])
    merged_items = store.upsert_stop_timetables_from_source(
        scenario_id,
        "odpt",
        items,
        replace_existing_source=body.reset,
    )
    odpt_items = [item for item in merged_items if item.get("source") == "odpt"]
    quality = summarize_stop_timetable_import(
        odpt_items,
        {"meta": bundle.get("meta") or {}},
    )
    for entry in list(bundle.get("calendar_entries") or []):
        store.upsert_calendar_entry(scenario_id, entry)
    import_meta = _build_odpt_import_meta(
        dataset=bundle,
        operator=body.operator,
        dump=body.dump,
        quality=quality,
        progress_key="stopTimetables",
        resource_type="BusstopPoleTimetable",
    )
    store.set_stop_timetable_import_meta(scenario_id, "odpt", import_meta)
    store.set_field(
        scenario_id,
        "source_snapshot",
        _source_snapshot_from_bundle("odpt", bundle),
    )
    store.set_feed_context(scenario_id, _bundle_feed_context("odpt", bundle))
    return {"items": merged_items, "total": len(merged_items), "meta": import_meta}


def _import_gtfs_stop_timetables_data(
    scenario_id: str,
    body: ImportGtfsStopTimetableBody,
    progress_callback: Optional[transit_catalog.ProgressCallback] = None,
) -> Dict[str, Any]:
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)

    bundle = _load_gtfs_bundle(
        feed_path=body.feedPath,
        force_refresh=body.forceRefresh,
        progress_callback=progress_callback,
    )
    items = list(bundle.get("stop_timetables") or [])
    merged_items = store.upsert_stop_timetables_from_source(
        scenario_id,
        "gtfs",
        items,
        replace_existing_source=body.reset,
    )
    gtfs_items = [item for item in merged_items if item.get("source") == "gtfs"]
    quality = summarize_gtfs_stop_timetable_import(gtfs_items, bundle)
    import_meta = _build_gtfs_import_meta(
        bundle=bundle,
        quality=quality,
        resource_type="GTFSStopTimetable",
    )
    store.set_stop_timetable_import_meta(scenario_id, "gtfs", import_meta)
    store.set_field(
        scenario_id,
        "source_snapshot",
        _source_snapshot_from_bundle("gtfs", bundle),
    )
    store.set_feed_context(scenario_id, _bundle_feed_context("gtfs", bundle))
    return {"items": merged_items, "total": len(merged_items), "meta": import_meta}


@router.post("/scenarios/{scenario_id}/timetable/import-odpt")
def import_timetable_odpt(
    scenario_id: str, body: ImportOdptTimetableBody
) -> Dict[str, Any]:
    try:
        return _import_odpt_timetable_data(scenario_id, body)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/scenarios/{scenario_id}/timetable/import-gtfs")
def import_timetable_gtfs(
    scenario_id: str, body: ImportGtfsTimetableBody
) -> Dict[str, Any]:
    try:
        return _import_gtfs_timetable_data(scenario_id, body)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/scenarios/{scenario_id}/import-runtime-snapshot")
def import_runtime_snapshot(
    scenario_id: str,
    body: Optional[ImportRuntimeSnapshotBody] = None,
) -> Dict[str, Any]:
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)

    request = body or ImportRuntimeSnapshotBody()
    try:
        bundle = runtime_catalog.load_runtime_snapshot(request.snapshotId)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    stops = list(bundle.get("stops") or [])
    routes = list(bundle.get("routes") or [])
    timetable_rows = list(bundle.get("timetable_rows") or [])
    stop_timetables = list(bundle.get("stop_timetables") or [])
    calendar_entries = list(bundle.get("calendar_entries") or [])
    calendar_date_entries = list(bundle.get("calendar_date_entries") or [])
    features = dict(bundle.get("features") or {})

    stop_import_meta = _build_runtime_import_meta(
        bundle=bundle,
        quality={"stopCount": len(stops)},
        resource_type="RuntimeStop",
    )
    route_import_meta = _build_runtime_import_meta(
        bundle=bundle,
        quality={"routeCount": len(routes)},
        resource_type="RuntimeRoute",
    )
    timetable_import_meta = _build_runtime_import_meta(
        bundle=bundle,
        quality=summarize_gtfs_timetable_import(
            timetable_rows,
            {
                "meta": bundle.get("meta") or {},
                "stop_timetable_count": len(stop_timetables),
            },
        ),
        resource_type="RuntimeTrip",
    )
    stop_timetable_import_meta = _build_runtime_import_meta(
        bundle=bundle,
        quality=summarize_gtfs_stop_timetable_import(stop_timetables, bundle),
        resource_type="RuntimeStopTimetable",
    )

    store.replace_stops_from_source(
        scenario_id,
        "gtfs_runtime",
        stops,
        import_meta=stop_import_meta,
    )
    store.replace_routes_from_source(
        scenario_id,
        "gtfs_runtime",
        routes,
        import_meta=route_import_meta,
    )
    merged_rows = store.upsert_timetable_rows_from_source(
        scenario_id,
        "gtfs_runtime",
        timetable_rows,
        replace_existing_source=request.resetRuntimeSource,
    )
    store.set_field(
        scenario_id,
        "timetable_rows",
        normalize_timetable_row_indexes(merged_rows),
        invalidate_dispatch=True,
    )
    store.set_timetable_import_meta(scenario_id, "gtfs_runtime", timetable_import_meta)
    store.upsert_stop_timetables_from_source(
        scenario_id,
        "gtfs_runtime",
        stop_timetables,
        replace_existing_source=request.resetRuntimeSource,
    )
    store.set_stop_timetable_import_meta(
        scenario_id,
        "gtfs_runtime",
        stop_timetable_import_meta,
    )
    if calendar_entries:
        store.set_calendar(scenario_id, calendar_entries)
    if calendar_date_entries or request.resetRuntimeSource:
        store.set_calendar_dates(scenario_id, calendar_date_entries)

    if request.importDeadheadRules:
        store.set_deadhead_rules(scenario_id, _runtime_deadhead_rules(bundle))
    if request.importTurnaroundRules:
        store.set_turnaround_rules(scenario_id, _runtime_turnaround_rules(bundle))

    source_snapshot = _source_snapshot_from_bundle("gtfs_runtime", bundle)
    store.set_field(scenario_id, "source_snapshot", source_snapshot)
    store.set_feed_context(scenario_id, _bundle_feed_context("gtfs_runtime", bundle))
    store.set_field(scenario_id, "runtime_features", features)

    return {
        "snapshot": source_snapshot,
        "counts": {
            "stops": len(stops),
            "routes": len(routes),
            "timetableRows": len(timetable_rows),
            "stopTimetables": len(stop_timetables),
            "calendarEntries": len(calendar_entries),
            "deadheadRules": len(store.get_deadhead_rules(scenario_id) or []),
            "turnaroundRules": len(store.get_turnaround_rules(scenario_id) or []),
        },
        "imports": {
            "stops": stop_import_meta,
            "routes": route_import_meta,
            "timetable": timetable_import_meta,
            "stopTimetables": stop_timetable_import_meta,
        },
    }


@router.get("/scenarios/{scenario_id}/stop-timetables")
def get_stop_timetables(
    scenario_id: str,
    stop_id: Optional[str] = Query(default=None),
    service_id: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(
        default=None,
        ge=1,
        le=_MAX_PAGE_LIMIT,
        description="Optional page size. Omit to return all stop timetables.",
    ),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    try:
        items = store.get_field(scenario_id, "stop_timetables") or []
    except KeyError:
        raise _not_found(scenario_id)

    if stop_id:
        items = [item for item in items if item.get("stopId") == stop_id]
    if service_id:
        items = [item for item in items if item.get("service_id") == service_id]
    paged_items, page_limit = _paginate_items(items, limit, offset)

    return {
        "items": paged_items,
        "total": len(items),
        "limit": page_limit,
        "offset": offset,
        "meta": {"imports": store.get_stop_timetable_import_meta(scenario_id)},
    }


@router.get("/scenarios/{scenario_id}/stop-timetables/summary")
def get_stop_timetables_summary(scenario_id: str) -> Dict[str, Any]:
    try:
        items = store.get_field(scenario_id, "stop_timetables") or []
    except KeyError:
        raise _not_found(scenario_id)
    imports = store.get_stop_timetable_import_meta(scenario_id)
    return {"item": _build_stop_timetable_summary(items, imports)}


@router.post("/scenarios/{scenario_id}/stop-timetables/import-odpt")
def import_stop_timetables_odpt(
    scenario_id: str, body: ImportOdptStopTimetableBody
) -> Dict[str, Any]:
    try:
        return _import_odpt_stop_timetables_data(scenario_id, body)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@router.post("/scenarios/{scenario_id}/stop-timetables/import-gtfs")
def import_stop_timetables_gtfs(
    scenario_id: str, body: ImportGtfsStopTimetableBody
) -> Dict[str, Any]:
    try:
        return _import_gtfs_stop_timetables_data(scenario_id, body)
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/scenarios/{scenario_id}/timetable/export-csv")
def export_timetable_csv(
    scenario_id: str,
    service_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """
    Export timetable rows as CSV text (JSON envelope so the client can name the file).
    """
    try:
        rows = store.get_field(scenario_id, "timetable_rows")
    except KeyError:
        raise _not_found(scenario_id)
    rows = rows or []
    if service_id:
        rows = [r for r in rows if r.get("service_id", "WEEKDAY") == service_id]

    buf = io.StringIO()
    writer = csv.DictWriter(
        buf, fieldnames=_CSV_COLUMNS, extrasaction="ignore", lineterminator="\n"
    )
    writer.writeheader()
    for i, row in enumerate(rows):
        writer.writerow(
            {
                "trip_id": row.get("trip_id", f"trip_{i:04d}"),
                "route_id": row.get("route_id", ""),
                "service_id": row.get("service_id", "WEEKDAY"),
                "direction": row.get("direction", "outbound"),
                "origin": row.get("origin", ""),
                "destination": row.get("destination", ""),
                "departure": row.get("departure", ""),
                "arrival": row.get("arrival", ""),
                "distance_km": row.get("distance_km", 0),
                "allowed_vehicle_types": ";".join(row.get("allowed_vehicle_types", [])),
            }
        )

    tag = f"_{service_id}" if service_id else ""
    return {
        "content": buf.getvalue(),
        "filename": f"timetable{tag}.csv",
        "rows": len(rows),
    }


# ── Rules (read-only from static data for now) ─────────────────


@router.get("/scenarios/{scenario_id}/deadhead-rules")
def get_deadhead_rules(scenario_id: str) -> Dict[str, Any]:
    try:
        store.get_scenario(scenario_id)  # verify exists
    except KeyError:
        raise _not_found(scenario_id)
    items = store.get_deadhead_rules(scenario_id)
    return {"items": items, "total": len(items)}


@router.get("/scenarios/{scenario_id}/turnaround-rules")
def get_turnaround_rules(scenario_id: str) -> Dict[str, Any]:
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    items = store.get_turnaround_rules(scenario_id)
    return {"items": items, "total": len(items)}
