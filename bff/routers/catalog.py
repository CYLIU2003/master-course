from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from bff.services.gtfs_import import DEFAULT_GTFS_FEED_PATH
from bff.services.odpt_routes import DEFAULT_OPERATOR
from bff.services import transit_catalog

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
