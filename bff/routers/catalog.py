from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from bff.services.gtfs_import import DEFAULT_GTFS_FEED_PATH
from bff.services.odpt_routes import DEFAULT_OPERATOR
from bff.services import runtime_catalog
from bff.services import transit_catalog
from bff.services import transit_db

router = APIRouter(tags=["catalog"])


class RefreshOdptSnapshotBody(BaseModel):
    operator: str = DEFAULT_OPERATOR
    dump: bool = True
    forceRefresh: bool = True
    ttlSec: int = 3600


class RefreshGtfsSnapshotBody(BaseModel):
    feedPath: str = DEFAULT_GTFS_FEED_PATH


class RefreshRuntimeSnapshotBody(BaseModel):
    snapshotId: Optional[str] = None


@router.get("/catalog/snapshots")
def list_catalog_snapshots() -> Dict[str, Any]:
    items = transit_catalog.list_snapshots()
    return {"items": items, "total": len(items)}


@router.post("/catalog/refresh/odpt")
def refresh_catalog_odpt(body: RefreshOdptSnapshotBody) -> Dict[str, Any]:
    snapshot = transit_catalog.refresh_odpt_snapshot(
        operator=body.operator,
        dump=body.dump,
        force_refresh=body.forceRefresh,
        ttl_sec=body.ttlSec,
    )
    return {"item": snapshot}


@router.post("/catalog/refresh/gtfs")
def refresh_catalog_gtfs(body: RefreshGtfsSnapshotBody) -> Dict[str, Any]:
    snapshot = transit_catalog.refresh_gtfs_snapshot(feed_path=body.feedPath)
    return {"item": snapshot}


@router.get("/catalog/runtime-snapshots")
def list_runtime_snapshots() -> Dict[str, Any]:
    items = runtime_catalog.list_runtime_snapshots()
    return {
        "items": items,
        "total": len(items),
        "latestSnapshotId": runtime_catalog.get_latest_runtime_snapshot_id(),
    }


@router.get("/catalog/runtime-snapshots/{snapshot_id}")
def get_runtime_snapshot(snapshot_id: str) -> Dict[str, Any]:
    try:
        bundle = runtime_catalog.load_runtime_snapshot(snapshot_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"item": bundle}


@router.post("/catalog/refresh/runtime")
def refresh_runtime_snapshot(
    body: Optional[RefreshRuntimeSnapshotBody] = None,
) -> Dict[str, Any]:
    try:
        bundle = runtime_catalog.load_runtime_snapshot(
            (body or RefreshRuntimeSnapshotBody()).snapshotId
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"item": bundle}


@router.get("/catalog/routes")
def list_catalog_routes(
    snapshot_key: str = Query(..., alias="snapshotKey"),
) -> Dict[str, Any]:
    snapshot = transit_catalog.get_snapshot(snapshot_key)
    if snapshot is None:
        raise HTTPException(
            status_code=404, detail=f"Snapshot '{snapshot_key}' not found"
        )
    items = transit_catalog.list_route_payload_summaries(snapshot_key)
    return {
        "items": items,
        "total": len(items),
        "meta": {
            "snapshot": snapshot,
        },
    }


@router.get("/catalog/routes/{route_id}")
def get_catalog_route(
    route_id: str,
    snapshot_key: str = Query(..., alias="snapshotKey"),
) -> Dict[str, Any]:
    snapshot = transit_catalog.get_snapshot(snapshot_key)
    if snapshot is None:
        raise HTTPException(
            status_code=404, detail=f"Snapshot '{snapshot_key}' not found"
        )
    payload = transit_catalog.get_route_payload(snapshot_key, route_id)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"Route '{route_id}' not found in snapshot '{snapshot_key}'",
        )
    return {
        "item": payload,
        "meta": {
            "snapshot": snapshot,
        },
    }


# ---------------------------------------------------------------------------
# Per-operator SQLite DB endpoints
# ---------------------------------------------------------------------------


@router.get("/catalog/operators")
def list_operators() -> Dict[str, Any]:
    """Return all registered operators with DB status."""
    items = transit_db.list_operators()
    return {"items": items, "total": len(items)}


@router.get("/catalog/operators/{operator_id}")
def get_operator_info(operator_id: str) -> Dict[str, Any]:
    """Return summary information about a specific operator DB."""
    try:
        info = transit_db.get_db_info(operator_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown operator: {operator_id}")
    return {"item": info}


@router.get("/catalog/operators/{operator_id}/schema")
def get_operator_schema(operator_id: str) -> Dict[str, Any]:
    """Return the table schema of an operator DB."""
    try:
        schema = transit_db.table_schema(operator_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown operator: {operator_id}")
    return {"items": schema}


@router.get("/catalog/operators/{operator_id}/routes")
def list_operator_routes(
    operator_id: str,
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    """Return paginated routes from an operator's per-operator DB."""
    try:
        items = transit_db.list_routes(operator_id, q=q, limit=limit, offset=offset)
        total = transit_db.count_routes(operator_id, q=q)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown operator: {operator_id}")
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/catalog/operators/{operator_id}/routes/{route_id}")
def get_operator_route(operator_id: str, route_id: str) -> Dict[str, Any]:
    try:
        item = transit_db.get_route(operator_id, route_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown operator: {operator_id}")
    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"Route '{route_id}' not found for operator '{operator_id}'",
        )
    return {"item": item}


@router.get("/catalog/operators/{operator_id}/stops")
def list_operator_stops(
    operator_id: str,
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    """Return paginated stops from an operator's per-operator DB."""
    try:
        items = transit_db.list_stops(operator_id, q=q, limit=limit, offset=offset)
        total = transit_db.count_stops(operator_id, q=q)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown operator: {operator_id}")
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/catalog/operators/{operator_id}/timetable")
def list_operator_timetable(
    operator_id: str,
    service_id: Optional[str] = Query(None, alias="serviceId"),
    route_id: Optional[str] = Query(None, alias="routeId"),
    limit: int = Query(5000, ge=1, le=100000),
    offset: int = Query(0, ge=0),
) -> Dict[str, Any]:
    """Return timetable rows from an operator's per-operator DB."""
    try:
        items = transit_db.list_timetable_rows(
            operator_id,
            service_id=service_id,
            route_id=route_id,
            limit=limit,
            offset=offset,
        )
        total = transit_db.count_timetable_rows(
            operator_id,
            service_id=service_id,
            route_id=route_id,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown operator: {operator_id}")
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/catalog/operators/{operator_id}/timetable/summary")
def operator_timetable_summary(operator_id: str) -> Dict[str, Any]:
    """Return aggregated timetable statistics per service_id."""
    try:
        summary = transit_db.timetable_summary(operator_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown operator: {operator_id}")
    return {"item": summary}


@router.get("/catalog/operators/{operator_id}/timetable/{trip_id}/stop-times")
def list_operator_trip_stop_times(operator_id: str, trip_id: str) -> Dict[str, Any]:
    try:
        items = transit_db.list_trip_stop_times(operator_id, trip_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown operator: {operator_id}")
    return {"items": items, "total": len(items)}


@router.get("/catalog/operators/{operator_id}/stop-timetables/{stop_id}")
def list_operator_stop_timetables(
    operator_id: str,
    stop_id: str,
    service_id: Optional[str] = Query(default=None, alias="serviceId"),
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    try:
        items = transit_db.list_stop_timetables(
            operator_id,
            stop_id,
            service_id=service_id,
            limit=limit,
            offset=offset,
        )
        total = transit_db.count_stop_timetable_entries(
            operator_id,
            stop_id,
            service_id=service_id,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown operator: {operator_id}")
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/catalog/operators/{operator_id}/calendar")
def list_operator_calendar(operator_id: str) -> Dict[str, Any]:
    """Return calendar definitions from an operator's per-operator DB."""
    try:
        items = transit_db.list_calendar(operator_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown operator: {operator_id}")
    return {"items": items, "total": len(items)}


@router.get("/catalog/operators/{operator_id}/calendar-dates")
def list_operator_calendar_dates(operator_id: str) -> Dict[str, Any]:
    """Return calendar date exceptions from an operator's per-operator DB."""
    try:
        items = transit_db.list_calendar_dates(operator_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown operator: {operator_id}")
    return {"items": items, "total": len(items)}


@router.get("/catalog/operators/{operator_id}/dispatch-trips")
def extract_operator_dispatch_trips(
    operator_id: str,
    service_id: str = Query(..., alias="serviceId"),
) -> Dict[str, Any]:
    """Extract dispatch-ready trips for a service day.

    Returns dicts with the exact keys expected by
    ``src.dispatch.models.Trip``.
    """
    try:
        items = transit_db.extract_dispatch_trips(operator_id, service_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown operator: {operator_id}")
    return {"items": items, "total": len(items)}


# ---------------------------------------------------------------------------
# Operator boundary helpers
# ---------------------------------------------------------------------------

_VALID_OPERATOR_IDS = frozenset(transit_db.OPERATORS.keys())


def _require_operator_id(operator_id: str | None) -> str:
    """Validate and return the operator_id, raising HTTP errors for invalid values."""
    if operator_id is None:
        raise HTTPException(status_code=400, detail="operatorId is required")
    if operator_id not in _VALID_OPERATOR_IDS:
        raise HTTPException(status_code=404, detail=f"unknown operatorId: {operator_id}")
    return operator_id


def _build_operator_summary(operator_id: str) -> Dict[str, Any]:
    """Build a summary dict for a single operator from its transit_db."""
    info = transit_db.OPERATORS.get(operator_id)
    if info is None:
        raise ValueError(f"Unknown operator_id: {operator_id!r}")
    db_info = transit_db.get_db_info(operator_id)
    tables = db_info.get("tables") or {}
    metadata = db_info.get("metadata") or {}

    return {
        "operatorId": operator_id,
        "operatorLabel": info.get("name_ja", operator_id),
        "sourceType": info.get("source", "unknown"),
        "datasetVersion": metadata.get("dataset_id") or metadata.get("snapshot_id") or "",
        "counts": {
            "routes": tables.get("routes", 0),
            "stops": tables.get("stops", 0),
            "timetableRows": tables.get("timetable_rows", 0),
            "stopTimetables": tables.get("stop_timetables", 0),
            "stopTimetableEntries": tables.get("stop_timetable_entries", 0),
            "tripStopTimes": tables.get("trip_stop_times", 0),
            "calendar": tables.get("calendar", 0),
            "calendarDates": tables.get("calendar_dates", 0),
        },
        "dbExists": db_info.get("exists", False),
        "updatedAt": metadata.get("last_import_at"),
    }


# ---------------------------------------------------------------------------
# Summary & map-overview endpoints (operator boundary enforced)
# ---------------------------------------------------------------------------


@router.get("/catalog/summary")
def get_catalog_summary(
    operator_id: Optional[str] = Query(default=None, alias="operatorId"),
) -> Dict[str, Any]:
    """Return aggregate summary counts.

    - Without operatorId: returns summaries for ALL operators.
    - With operatorId: returns summary for the specified operator only.
    """
    if operator_id is not None:
        operator_id = _require_operator_id(operator_id)
        return {"item": _build_operator_summary(operator_id)}

    # All operators
    items = []
    for op_id in transit_db.OPERATORS:
        try:
            items.append(_build_operator_summary(op_id))
        except Exception:
            items.append({"operatorId": op_id, "error": True})
    return {"items": items, "total": len(items)}


@router.get("/catalog/map-overview")
def get_catalog_map_overview(
    operator_id: str = Query(..., alias="operatorId"),
) -> Dict[str, Any]:
    """Return lightweight map preview data for an operator.

    operatorId is **required** (per Operator Boundary Invariants).
    Returns bounds, stop clusters, and depot points from the operator DB.
    """
    operator_id = _require_operator_id(operator_id)

    info = transit_db.OPERATORS[operator_id]
    db_info = transit_db.get_db_info(operator_id)
    if not db_info.get("exists"):
        return {
            "operatorId": operator_id,
            "bounds": None,
            "stopClusters": [],
            "depotPoints": [],
            "updatedAt": None,
        }

    # Compute bounds and basic stop cluster data from DB
    from contextlib import closing as _closing
    from bff.services.transit_db import _connect, _ensure_ready

    with _closing(_connect(operator_id)) as conn:
        _ensure_ready(conn)

        # Bounds from stops with coordinates
        bounds_row = conn.execute(
            "SELECT MIN(lat) AS min_lat, MAX(lat) AS max_lat, "
            "       MIN(lon) AS min_lon, MAX(lon) AS max_lon "
            "FROM stops WHERE lat IS NOT NULL AND lon IS NOT NULL"
        ).fetchone()

        bounds = None
        if bounds_row and bounds_row["min_lat"] is not None:
            bounds = {
                "minLat": bounds_row["min_lat"],
                "maxLat": bounds_row["max_lat"],
                "minLon": bounds_row["min_lon"],
                "maxLon": bounds_row["max_lon"],
            }

        # Simple stop clusters: group by rounded (lat, lon) at ~0.01 degree (~1km)
        cluster_rows = conn.execute(
            "SELECT ROUND(lat, 2) AS clat, ROUND(lon, 2) AS clon, COUNT(*) AS cnt "
            "FROM stops WHERE lat IS NOT NULL AND lon IS NOT NULL "
            "GROUP BY ROUND(lat, 2), ROUND(lon, 2) "
            "ORDER BY cnt DESC "
            "LIMIT 500"
        ).fetchall()

        stop_clusters = [
            {
                "id": f"{operator_id}:c:{i}",
                "lat": row["clat"],
                "lon": row["clon"],
                "count": row["cnt"],
            }
            for i, row in enumerate(cluster_rows)
        ]

        # Depot candidate points: stops whose name contains depot-like keywords
        depot_rows = conn.execute(
            "SELECT stop_id, stop_name, lat, lon FROM stops "
            "WHERE (stop_name LIKE '%営業所%' OR stop_name LIKE '%車庫%' "
            "       OR stop_name LIKE '%操車所%') "
            "  AND lat IS NOT NULL AND lon IS NOT NULL"
        ).fetchall()

        depot_points = [
            {
                "id": f"{operator_id}:depot:{row['stop_id']}",
                "label": row["stop_name"],
                "lat": row["lat"],
                "lon": row["lon"],
            }
            for row in depot_rows
        ]

    metadata = db_info.get("metadata") or {}
    return {
        "operatorId": operator_id,
        "bounds": bounds,
        "stopClusters": stop_clusters,
        "depotPoints": depot_points,
        "updatedAt": metadata.get("last_import_at"),
    }
