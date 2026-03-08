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
import io
from threading import Lock
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

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
from bff.services import transit_catalog
from bff.store import scenario_store as store

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


# ── Pydantic models ────────────────────────────────────────────


class CreateScenarioBody(BaseModel):
    name: str
    description: str = ""
    mode: str = "thesis_mode"


class UpdateScenarioBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    mode: Optional[str] = None


class DuplicateScenarioBody(BaseModel):
    name: Optional[str] = None


class UpdateDispatchScopeBody(BaseModel):
    depotId: Optional[str] = None
    serviceId: Optional[str] = None


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
    reset: bool = True


# ── Helpers ────────────────────────────────────────────────────


def _not_found(scenario_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")


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
    return {
        "feedPath": meta.get("feedPath"),
        "agencyName": meta.get("agencyName"),
        "source": "gtfs",
        "resourceType": resource_type,
        "generatedAt": meta.get("generatedAt"),
        "warnings": meta.get("warnings", []),
        "snapshotKey": (bundle.get("snapshot") or {}).get("snapshotKey"),
        "snapshotMode": meta.get("snapshotMode"),
        "quality": quality,
    }


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
    )


@router.post("/scenarios/{scenario_id}/duplicate", status_code=201)
def duplicate_scenario(
    scenario_id: str, body: Optional[DuplicateScenarioBody] = None
) -> Dict[str, Any]:
    try:
        return store.duplicate_scenario(scenario_id, name=body.name if body else None)
    except KeyError:
        raise _not_found(scenario_id)


@router.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: str) -> Dict[str, Any]:
    try:
        return store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)


@router.put("/scenarios/{scenario_id}")
def update_scenario(scenario_id: str, body: UpdateScenarioBody) -> Dict[str, Any]:
    try:
        return store.update_scenario(
            scenario_id,
            name=body.name,
            description=body.description,
            mode=body.mode,
        )
    except KeyError:
        raise _not_found(scenario_id)


@router.get("/scenarios/{scenario_id}/dispatch-scope")
def get_dispatch_scope(scenario_id: str) -> Dict[str, Any]:
    try:
        return store.get_dispatch_scope(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)


@router.put("/scenarios/{scenario_id}/dispatch-scope")
def update_dispatch_scope(
    scenario_id: str, body: UpdateDispatchScopeBody
) -> Dict[str, Any]:
    try:
        return store.set_dispatch_scope(scenario_id, body.model_dump())
    except KeyError:
        raise _not_found(scenario_id)


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
    context = store.set_active_scenario(scenario_id)
    return {
        "activeScenarioId": scenario_id,
        "scenarioName": scenario.get("name"),
        "selectedOperatorId": None,
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
        except KeyError:
            context = store.set_active_scenario(
                None,
                last_opened_page=context.get("lastOpenedPage"),
            )
            scenario_id = None
    return {
        "activeScenarioId": scenario_id,
        "scenarioName": scenario.get("name") if scenario else None,
        "selectedOperatorId": None,
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
) -> Dict[str, Any]:
    try:
        rows = store.get_field(scenario_id, "timetable_rows")
    except KeyError:
        raise _not_found(scenario_id)
    rows = rows or []
    if service_id:
        rows = [r for r in rows if r.get("service_id", "WEEKDAY") == service_id]
    return {
        "items": rows,
        "total": len(rows),
        "meta": {"imports": store.get_timetable_import_meta(scenario_id)},
    }


@router.put("/scenarios/{scenario_id}/timetable")
def update_timetable(scenario_id: str, body: UpdateTimetableBody) -> Dict[str, Any]:
    try:
        rows = [r.model_dump() for r in body.rows]
        store.set_field(scenario_id, "timetable_rows", rows, invalidate_dispatch=True)
        return {"items": rows, "total": len(rows)}
    except KeyError:
        raise _not_found(scenario_id)


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


@router.post("/scenarios/{scenario_id}/timetable/import-odpt")
def import_timetable_odpt(
    scenario_id: str, body: ImportOdptTimetableBody
) -> Dict[str, Any]:
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)

    try:
        bundle = transit_catalog.get_or_refresh_odpt_snapshot(
            operator=body.operator,
            dump=body.dump,
            force_refresh=body.forceRefresh,
            ttl_sec=body.ttlSec,
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
        import_meta = _build_odpt_import_meta(
            dataset=bundle,
            operator=body.operator,
            dump=body.dump,
            quality=quality,
            progress_key="busTimetables",
            resource_type="BusTimetable",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    store.set_timetable_import_meta(scenario_id, "odpt", import_meta)
    return {
        "items": odpt_rows,
        "total": len(odpt_rows),
        "meta": import_meta,
    }


@router.post("/scenarios/{scenario_id}/timetable/import-gtfs")
def import_timetable_gtfs(
    scenario_id: str, body: ImportGtfsTimetableBody
) -> Dict[str, Any]:
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)

    try:
        bundle = transit_catalog.get_or_refresh_gtfs_snapshot(feed_path=body.feedPath)
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

        # Sync calendar data from GTFS feed into scenario store
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
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    store.set_timetable_import_meta(scenario_id, "gtfs", import_meta)
    return {
        "items": gtfs_rows,
        "total": len(gtfs_rows),
        "meta": import_meta,
    }


@router.get("/scenarios/{scenario_id}/stop-timetables")
def get_stop_timetables(
    scenario_id: str,
    stop_id: Optional[str] = Query(default=None),
    service_id: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    try:
        items = store.get_field(scenario_id, "stop_timetables") or []
    except KeyError:
        raise _not_found(scenario_id)

    if stop_id:
        items = [item for item in items if item.get("stopId") == stop_id]
    if service_id:
        items = [item for item in items if item.get("service_id") == service_id]

    return {
        "items": items,
        "total": len(items),
        "meta": {"imports": store.get_stop_timetable_import_meta(scenario_id)},
    }


@router.post("/scenarios/{scenario_id}/stop-timetables/import-odpt")
def import_stop_timetables_odpt(
    scenario_id: str, body: ImportOdptStopTimetableBody
) -> Dict[str, Any]:
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)

    try:
        bundle = transit_catalog.get_or_refresh_odpt_snapshot(
            operator=body.operator,
            dump=body.dump,
            force_refresh=body.forceRefresh,
            ttl_sec=body.ttlSec,
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
        import_meta = _build_odpt_import_meta(
            dataset=bundle,
            operator=body.operator,
            dump=body.dump,
            quality=quality,
            progress_key="stopTimetables",
            resource_type="BusstopPoleTimetable",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    store.set_stop_timetable_import_meta(scenario_id, "odpt", import_meta)
    return {"items": merged_items, "total": len(merged_items), "meta": import_meta}


@router.post("/scenarios/{scenario_id}/stop-timetables/import-gtfs")
def import_stop_timetables_gtfs(
    scenario_id: str, body: ImportGtfsStopTimetableBody
) -> Dict[str, Any]:
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)

    try:
        bundle = transit_catalog.get_or_refresh_gtfs_snapshot(feed_path=body.feedPath)
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
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    store.set_stop_timetable_import_meta(scenario_id, "gtfs", import_meta)
    return {"items": merged_items, "total": len(merged_items), "meta": import_meta}


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
