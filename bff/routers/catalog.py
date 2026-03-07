from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from bff.services.gtfs_import import DEFAULT_GTFS_FEED_PATH
from bff.services.odpt_routes import DEFAULT_OPERATOR
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


@router.get("/catalog/routes")
def list_catalog_routes(
    snapshot_key: str = Query(..., alias="snapshotKey"),
) -> Dict[str, Any]:
    snapshot = transit_catalog.get_snapshot(snapshot_key)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"Snapshot '{snapshot_key}' not found")
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
        raise HTTPException(status_code=404, detail=f"Snapshot '{snapshot_key}' not found")
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
def list_operator_routes(operator_id: str) -> Dict[str, Any]:
    """Return all routes from an operator's per-operator DB."""
    try:
        items = transit_db.list_routes(operator_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown operator: {operator_id}")
    return {"items": items, "total": len(items)}


@router.get("/catalog/operators/{operator_id}/stops")
def list_operator_stops(operator_id: str) -> Dict[str, Any]:
    """Return all stops from an operator's per-operator DB."""
    try:
        items = transit_db.list_stops(operator_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown operator: {operator_id}")
    return {"items": items, "total": len(items)}


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
