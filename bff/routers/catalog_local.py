"""Local SQLite catalog router.

This router exposes read-only catalog endpoints backed by a local Tokyu SQLite
catalog. It is mounted only when `CATALOG_BACKEND=local_sqlite`.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from bff.services import local_db_catalog as db


router = APIRouter(prefix="/catalog", tags=["catalog"])


def _split_csv(value: Optional[str]) -> list[str] | None:
    if not value:
        return None
    items = [item.strip() for item in value.split(",") if item.strip()]
    return items or None


@router.get("/health")
def catalog_health() -> dict:
    return db.health_check()


@router.get("/operators")
def list_operators() -> list[dict]:
    return db.list_operators()


@router.get("/operators/{operator_id}/depots")
def list_depots(operator_id: str) -> list[dict]:
    return db.list_depots(operator_id=operator_id)


@router.get("/depots")
def list_depot_summaries(
    calendar_type: str = Query(default="平日"),
) -> list[dict]:
    return db.list_depot_summaries(calendar_type=calendar_type)


@router.get("/operators/{operator_id}/depots/{depot_id}")
def get_depot(operator_id: str, depot_id: str) -> dict:
    depot = db.get_depot(depot_id)
    if not depot or str(depot.get("operator_id") or "") != operator_id:
        raise HTTPException(status_code=404, detail=f"Depot not found: {depot_id}")
    return depot


@router.get("/depots/{depot_id}/routes")
def list_depot_routes(
    depot_id: str,
    include_depot_moves: bool = Query(default=False),
) -> list[dict]:
    return db.list_depot_route_summaries(
        depot_id,
        include_depot_moves=include_depot_moves,
    )


@router.get("/operators/{operator_id}/route-families")
def list_route_families(
    operator_id: str,
    depot_id: Optional[str] = Query(default=None),
    depot_ids: Optional[str] = Query(default=None, description="comma-separated depot ids"),
) -> list[dict]:
    return db.list_route_families(
        operator_id=operator_id,
        depot_id=depot_id,
        depot_ids=_split_csv(depot_ids),
    )


@router.get("/operators/{operator_id}/route-families/{route_family_id}")
def get_route_family(operator_id: str, route_family_id: str) -> dict:
    detail = db.get_route_family_detail(operator_id, route_family_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Route family not found: {route_family_id}")
    return detail


@router.get("/route-families/{route_family_id}/patterns")
def get_route_family_patterns(
    route_family_id: str,
    depot_id: Optional[str] = Query(default=None),
) -> list[dict]:
    return db.get_route_family_patterns(route_family_id, depot_id=depot_id)


@router.get("/operators/{operator_id}/route-families/{route_family_id}/timetable")
def route_family_timetable(
    operator_id: str,
    route_family_id: str,
    calendar_type: str = Query(default="平日"),
    direction: Optional[str] = Query(default=None),
    depot_id: Optional[str] = Query(default=None),
    depot_ids: Optional[str] = Query(default=None),
) -> dict:
    del operator_id
    trips = db.get_timetable_trips(
        route_family=route_family_id,
        calendar_type=calendar_type,
        direction=direction,
        depot_id=depot_id,
        depot_ids=_split_csv(depot_ids),
    )
    return {
        "route_family": route_family_id,
        "calendar_type": calendar_type,
        "direction": direction,
        "trip_count": len(trips),
        "trips": trips,
    }


@router.get("/operators/{operator_id}/patterns")
def list_patterns(
    operator_id: str,
    route_family: Optional[str] = Query(default=None),
    depot_id: Optional[str] = Query(default=None),
    depot_ids: Optional[str] = Query(default=None, description="comma-separated depot ids"),
) -> list[dict]:
    return db.list_route_patterns(
        operator_id=operator_id,
        route_family=route_family,
        depot_id=depot_id,
        depot_ids=_split_csv(depot_ids),
    )


@router.get("/patterns/{pattern_id}/stops")
def pattern_stops(pattern_id: str) -> list[dict]:
    return db.get_pattern_stops(pattern_id)


@router.get("/stops")
def list_stops(operator_id: Optional[str] = Query(default=None)) -> list[dict]:
    return db.list_stops(operator_id=operator_id)


@router.get("/stops/{stop_id}")
def get_stop(stop_id: str) -> dict:
    stop = db.get_stop(stop_id)
    if stop is None:
        raise HTTPException(status_code=404, detail=f"Stop not found: {stop_id}")
    return stop


@router.get("/stops/{stop_id}/timetable")
def stop_timetable(
    stop_id: str,
    pattern_id: Optional[str] = Query(default=None),
    calendar_type: str = Query(default="平日"),
) -> dict:
    entries = db.get_stop_timetable(stop_id, pattern_id, calendar_type)
    return {
        "stop_id": stop_id,
        "calendar_type": calendar_type,
        "entry_count": len(entries),
        "entries": entries,
    }


@router.get("/trips/summary")
def trip_summary(
    calendar_type: str = Query(default="平日"),
    depot_id: Optional[str] = Query(default=None),
    depot_ids: Optional[str] = Query(default=None),
) -> dict:
    return db.get_trip_summary(
        calendar_type=calendar_type,
        depot_id=depot_id,
        depot_ids=_split_csv(depot_ids),
    )


@router.get("/trips/{trip_id}/stops")
def trip_stops(trip_id: str) -> list[dict]:
    return db.get_trip_stops(trip_id)


@router.get("/milp-trips")
def milp_trips(
    depot_id: Optional[str] = Query(default=None, description="single depot id"),
    depot_ids: Optional[str] = Query(default=None, description="comma-separated depot ids"),
    route_families: Optional[str] = Query(default=None, description="comma-separated route families"),
    calendar_type: str = Query(default="平日"),
    min_dep_min: int = Query(default=0),
    max_dep_min: int = Query(default=1440),
) -> dict:
    route_family_list = _split_csv(route_families)
    depot_list = _split_csv(depot_ids)
    normalized_depots = db._normalize_depot_ids(depot_id, depot_list)
    trips = db.build_milp_trips(
        route_families=route_family_list,
        depot_id=depot_id,
        depot_ids=depot_list,
        calendar_type=calendar_type,
        min_dep_min=min_dep_min,
        max_dep_min=max_dep_min,
    )
    return {
        "depot_id": normalized_depots[0] if normalized_depots else None,
        "depot_ids": normalized_depots,
        "route_families": route_family_list or [],
        "calendar_type": calendar_type,
        "trip_count": len(trips),
        "trips": trips,
    }
