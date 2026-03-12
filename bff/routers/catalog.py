from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from bff.services.gtfs_import import DEFAULT_GTFS_FEED_PATH
from bff.services.odpt_routes import DEFAULT_OPERATOR
from bff.services.route_family import (
    build_route_family_detail,
    build_route_family_summary,
    enrich_routes_with_family,
)
from bff.services.service_ids import canonical_service_id
from bff.services import runtime_catalog
from bff.services import transit_catalog
from bff.services import transit_db
from src.dispatch.models import hhmm_to_min

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


class OperatorOverviewItem(BaseModel):
    operatorId: str
    routeCount: int
    stopCount: int
    serviceCount: int
    tripCount: int
    depotCount: int
    updatedAt: Optional[str] = None


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
    depot_id: Optional[str] = Query(default=None, alias="depotId"),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    """Return paginated routes from an operator's per-operator DB."""
    del depot_id
    try:
        items = transit_db.list_routes(operator_id, q=q, limit=limit, offset=offset)
        total = transit_db.count_routes(operator_id, q=q)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown operator: {operator_id}")
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def _operator_family_enriched_routes(operator_id: str) -> List[Dict[str, Any]]:
    total_routes = max(transit_db.count_routes(operator_id), 1)
    raw_routes = transit_db.list_routes(operator_id, limit=total_routes, offset=0)
    total_timetable_rows = max(transit_db.count_timetable_rows(operator_id), 1)
    timetable_rows = transit_db.list_timetable_rows(
        operator_id,
        limit=total_timetable_rows,
        offset=0,
    )

    route_services: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for row in timetable_rows:
        route_id = str(row.get("route_id") or "")
        service_id = canonical_service_id(row.get("service_id"))
        if not route_id:
            continue
        bucket = route_services[route_id].setdefault(
            service_id,
            {
                "serviceId": service_id,
                "tripCount": 0,
                "firstDeparture": None,
                "lastArrival": None,
            },
        )
        bucket["tripCount"] += 1
        departure = row.get("departure")
        arrival = row.get("arrival")
        if departure and (
            bucket["firstDeparture"] is None
            or hhmm_to_min(str(departure)) < hhmm_to_min(str(bucket["firstDeparture"]))
        ):
            bucket["firstDeparture"] = departure
        if arrival and (
            bucket["lastArrival"] is None
            or hhmm_to_min(str(arrival)) > hhmm_to_min(str(bucket["lastArrival"]))
        ):
            bucket["lastArrival"] = arrival

    enriched_routes: List[Dict[str, Any]] = []
    for raw in raw_routes:
        route_id = str(raw.get("route_id") or "")
        detail_raw = transit_db.get_route(operator_id, route_id)
        detail: Dict[str, Any] = {}
        if isinstance(detail_raw, dict):
            detail = detail_raw
        extra_raw = detail.get("extra_json")
        extra: Dict[str, Any] = {}
        if isinstance(extra_raw, dict):
            extra = extra_raw
        stop_sequence: Any = detail.get("stop_sequence_json")
        if not isinstance(stop_sequence, list):
            stop_sequence = extra.get("stopSequence") if isinstance(extra.get("stopSequence"), list) else []
        route = {
            "id": route_id,
            "name": extra.get("name") or raw.get("route_name") or route_id,
            "routeCode": extra.get("routeCode") or raw.get("route_code") or route_id,
            "routeLabel": extra.get("routeLabel") or raw.get("route_name") or route_id,
            "startStop": extra.get("startStop") or detail.get("origin_stop_id") or "",
            "endStop": extra.get("endStop") or detail.get("destination_stop_id") or "",
            "stopSequence": stop_sequence,
            "distanceKm": raw.get("distance_km"),
            "durationMin": extra.get("durationMin") or extra.get("duration_min"),
            "tripCount": raw.get("trip_count") or sum(
                item["tripCount"] for item in route_services.get(route_id, {}).values()
            ),
            "firstDeparture": raw.get("first_departure"),
            "lastArrival": raw.get("last_arrival"),
            "source": raw.get("source"),
            "direction": raw.get("direction"),
            "serviceSummary": list(route_services.get(route_id, {}).values()),
        }
        enriched_routes.append(route)

    return enrich_routes_with_family(enriched_routes)


def _operator_route_family_payloads(operator_id: str) -> List[Dict[str, Any]]:
    enriched_routes = _operator_family_enriched_routes(operator_id)
    family_summaries = build_route_family_summary(enriched_routes)
    members_by_family: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for route in enriched_routes:
        family_id = str(route.get("routeFamilyId") or "")
        if family_id:
            members_by_family[family_id].append(route)

    payloads: List[Dict[str, Any]] = []
    for summary in family_summaries:
        family_id = str(summary.get("routeFamilyId") or "")
        members = members_by_family.get(family_id, [])
        service_ids = sorted(
            {
                str(item.get("serviceId"))
                for route in members
                for item in (route.get("serviceSummary") or [])
                if item.get("serviceId")
            }
        )
        departures = [
            str(route.get("firstDeparture"))
            for route in members
            if route.get("firstDeparture")
        ]
        arrivals = [
            str(route.get("lastArrival"))
            for route in members
            if route.get("lastArrival")
        ]
        payloads.append(
            {
                **summary,
                "tripCount": sum(int(route.get("tripCount") or 0) for route in members),
                "stopCount": max((len(route.get("stopSequence") or []) for route in members), default=0),
                "firstDeparture": min(departures, key=hhmm_to_min) if departures else None,
                "lastArrival": max(arrivals, key=hhmm_to_min) if arrivals else None,
                "serviceIds": service_ids,
                "directionCount": len(
                    {
                        str(route.get("canonicalDirection") or "")
                        for route in members
                        if route.get("canonicalDirection")
                        and str(route.get("canonicalDirection")) != "unknown"
                    }
                ),
                "patternCount": len(members),
                "routeIds": [str(route.get("id") or "") for route in members],
                "routeNames": [str(route.get("name") or "") for route in members],
            }
        )
    return payloads


def _operator_route_family_detail_payload(
    operator_id: str,
    route_family_id: str,
) -> Optional[Dict[str, Any]]:
    enriched_routes = _operator_family_enriched_routes(operator_id)
    detail = build_route_family_detail(route_family_id, enriched_routes)
    if not detail:
        return None

    summary_by_id = {
        str(item.get("routeFamilyId") or ""): item
        for item in _operator_route_family_payloads(operator_id)
        if item.get("routeFamilyId")
    }
    payload = dict(detail)
    payload["summary"] = summary_by_id.get(route_family_id, payload.get("summary") or {})
    return payload


@router.get("/catalog/operators/{operator_id}/route-families")
def list_operator_route_families(
    operator_id: str,
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    try:
        items = _operator_route_family_payloads(operator_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown operator: {operator_id}")

    if q:
        needle = q.strip().lower()
        items = [
            item
            for item in items
            if needle in str(item.get("routeFamilyCode") or "").lower()
            or needle in str(item.get("routeFamilyLabel") or "").lower()
            or any(needle in name.lower() for name in item.get("routeNames") or [])
        ]

    total = len(items)
    paged = items[offset: offset + limit]
    return {"items": paged, "total": total, "limit": limit, "offset": offset}


@router.get("/catalog/operators/{operator_id}/route-families/{route_family_id}")
def get_operator_route_family(
    operator_id: str,
    route_family_id: str,
) -> Dict[str, Any]:
    try:
        item = _operator_route_family_detail_payload(operator_id, route_family_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown operator: {operator_id}")
    if item is None:
        raise HTTPException(
            status_code=404,
            detail=f"Route family '{route_family_id}' not found for operator '{operator_id}'",
        )
    return {"item": item}


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
    limit: int = Query(default=50, ge=1, le=200),
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
    limit: int = Query(100, ge=1, le=200),
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
def operator_timetable_summary(
    operator_id: str,
    route_id: Optional[str] = Query(default=None, alias="routeId"),
    service_id: Optional[str] = Query(default=None, alias="serviceId"),
) -> Dict[str, Any]:
    """Return aggregated timetable statistics per service_id."""
    try:
        summary = transit_db.timetable_summary(
            operator_id,
            route_id=route_id,
            service_id=service_id,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown operator: {operator_id}")
    return {"item": summary}


@router.get("/catalog/operators/{operator_id}/overview")
def get_operator_overview(operator_id: str) -> Dict[str, Any]:
    operator_id = _require_operator_id(operator_id)
    summary = _build_operator_summary(operator_id)
    item = OperatorOverviewItem(
        operatorId=operator_id,
        routeCount=int((summary.get("counts") or {}).get("routes") or 0),
        stopCount=int((summary.get("counts") or {}).get("stops") or 0),
        serviceCount=len(transit_db.list_calendar(operator_id)),
        tripCount=int((summary.get("counts") or {}).get("timetableRows") or 0),
        depotCount=transit_db.count_depot_candidates(operator_id),
        updatedAt=summary.get("updatedAt"),
    )
    return {"item": item.model_dump()}


@router.get("/catalog/operators/{operator_id}/timetable-summary")
def get_operator_timetable_summary_alias(
    operator_id: str,
    route_id: Optional[str] = Query(default=None, alias="routeId"),
    service_id: Optional[str] = Query(default=None, alias="serviceId"),
    depot_id: Optional[str] = Query(default=None, alias="depotId"),
) -> Dict[str, Any]:
    del depot_id
    return operator_timetable_summary(
        operator_id=operator_id,
        route_id=route_id,
        service_id=service_id,
    )


@router.get("/catalog/operators/{operator_id}/timetable-rows")
def list_operator_timetable_rows(
    operator_id: str,
    route_id: Optional[str] = Query(default=None, alias="routeId"),
    service_id: Optional[str] = Query(default=None, alias="serviceId"),
    depot_id: Optional[str] = Query(default=None, alias="depotId"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    del depot_id
    return list_operator_timetable(
        operator_id=operator_id,
        route_id=route_id,
        service_id=service_id,
        limit=limit,
        offset=offset,
    )


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
    snapshot_key = str(metadata.get("catalog_snapshot_key") or "")
    artifact_summary = (
        transit_catalog.load_snapshot_operator_summary(snapshot_key) if snapshot_key else None
    )

    if artifact_summary is not None:
        counts = dict(artifact_summary.get("counts") or {})
        return {
            "operatorId": operator_id,
            "operatorLabel": info.get("name_ja", operator_id),
            "sourceType": info.get("source", artifact_summary.get("sourceType") or "unknown"),
            "datasetVersion": metadata.get("dataset_id") or metadata.get("snapshot_id") or "",
            "counts": {
                "routes": counts.get("routes", tables.get("routes", 0)),
                "stops": counts.get("stops", tables.get("stops", 0)),
                "timetableRows": counts.get("timetableRows", tables.get("timetable_rows", 0)),
                "stopTimetables": counts.get("stopTimetables", tables.get("stop_timetables", 0)),
                "stopTimetableEntries": tables.get("stop_timetable_entries", 0),
                "tripStopTimes": tables.get("trip_stop_times", 0),
                "calendar": tables.get("calendar", 0),
                "calendarDates": tables.get("calendar_dates", 0),
            },
            "quality": dict(artifact_summary.get("quality") or {}),
            "dbExists": db_info.get("exists", False),
            "updatedAt": artifact_summary.get("updatedAt") or metadata.get("last_import_at"),
        }

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
        "quality": {},
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
    db_info = transit_db.get_db_info(operator_id)
    if not db_info.get("exists"):
        return {
            "operatorId": operator_id,
            "bounds": None,
            "stopClusters": [],
            "depotPoints": [],
            "updatedAt": None,
        }
    metadata = db_info.get("metadata") or {}
    snapshot_key = str(metadata.get("catalog_snapshot_key") or "")
    artifact_summary = (
        transit_catalog.load_snapshot_operator_summary(snapshot_key) if snapshot_key else None
    )
    if artifact_summary is not None:
        return {
            "operatorId": operator_id,
            "bounds": artifact_summary.get("bounds"),
            "stopClusters": list(artifact_summary.get("stopClusters") or []),
            "depotPoints": list(artifact_summary.get("depotPoints") or []),
            "updatedAt": artifact_summary.get("updatedAt"),
        }

    stops: List[Dict[str, Any]] = []
    if snapshot_key:
        try:
            slim_bundle = transit_catalog.load_snapshot_bundle_slim(snapshot_key)
            stops = list(slim_bundle.get("stops") or [])
        except KeyError:
            stops = []

    if not stops:
        total_stops = max(transit_db.count_stops(operator_id), 1)
        stops = transit_db.list_stops(operator_id, limit=total_stops, offset=0)

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

    cluster_counts: Dict[tuple[float, float], int] = defaultdict(int)
    for stop in geo_stops:
        cluster_counts[(round(float(stop["lat"]), 2), round(float(stop["lon"]), 2))] += 1
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
    return {
        "operatorId": operator_id,
        "bounds": bounds,
        "stopClusters": stop_clusters,
        "depotPoints": depot_points,
        "updatedAt": metadata.get("last_import_at"),
    }
