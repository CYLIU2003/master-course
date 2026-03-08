"""
bff/routers/master_data.py

Depots, Vehicles, Stops, Routes, and Permission tables endpoints.

Routes:
  GET/POST        /scenarios/{id}/depots
  GET/PUT/DELETE  /scenarios/{id}/depots/{depot_id}
  GET/POST        /scenarios/{id}/vehicles          (optional ?depotId=)
  GET/PUT/DELETE  /scenarios/{id}/vehicles/{vehicle_id}
  GET             /scenarios/{id}/stops
  POST            /scenarios/{id}/stops/import-odpt
  POST            /scenarios/{id}/stops/import-gtfs
  GET/POST        /scenarios/{id}/routes
  POST            /scenarios/{id}/routes/import-gtfs
  GET/PUT/DELETE  /scenarios/{id}/routes/{route_id}
  GET/PUT         /scenarios/{id}/depot-route-permissions
  GET/PUT         /scenarios/{id}/vehicle-route-permissions
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from bff.services.gtfs_import import (
    DEFAULT_GTFS_FEED_PATH,
    summarize_gtfs_routes_import,
    summarize_gtfs_stop_import,
)
from bff.services.odpt_routes import (
    DEFAULT_OPERATOR,
    summarize_routes_import,
)
from bff.services.odpt_stops import summarize_stop_import
from bff.services import transit_catalog
from bff.services.route_family import (
    enrich_routes_with_family,
    build_route_family_summary,
    build_route_family_detail,
    derive_route_family_metadata,
)
from bff.store import scenario_store as store

router = APIRouter(tags=["master-data"])


def _not_found(kind: str, id_: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{kind} '{id_}' not found")


def _scenario_not_found(scenario_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")


def _check_scenario(scenario_id: str) -> None:
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _scenario_not_found(scenario_id)


# ── Depot Pydantic models ──────────────────────────────────────


class CreateDepotBody(BaseModel):
    name: str
    location: str = ""
    lat: float = 0.0
    lon: float = 0.0
    normalChargerCount: int = 0
    normalChargerPowerKw: float = 0.0
    fastChargerCount: int = 0
    fastChargerPowerKw: float = 0.0
    hasFuelFacility: bool = False
    parkingCapacity: int = 0
    overnightCharging: bool = False
    notes: str = ""


class UpdateDepotBody(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    normalChargerCount: Optional[int] = None
    normalChargerPowerKw: Optional[float] = None
    fastChargerCount: Optional[int] = None
    fastChargerPowerKw: Optional[float] = None
    hasFuelFacility: Optional[bool] = None
    parkingCapacity: Optional[int] = None
    overnightCharging: Optional[bool] = None
    notes: Optional[str] = None


# ── Depot endpoints ────────────────────────────────────────────


@router.get("/scenarios/{scenario_id}/depots")
def list_depots(scenario_id: str) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    items = store.list_depots(scenario_id)
    return {"items": items, "total": len(items)}


@router.post("/scenarios/{scenario_id}/depots", status_code=201)
def create_depot(scenario_id: str, body: CreateDepotBody) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    return store.create_depot(scenario_id, body.model_dump())


@router.get("/scenarios/{scenario_id}/depots/{depot_id}")
def get_depot(scenario_id: str, depot_id: str) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    try:
        return store.get_depot(scenario_id, depot_id)
    except KeyError:
        raise _not_found("Depot", depot_id)


@router.put("/scenarios/{scenario_id}/depots/{depot_id}")
def update_depot(
    scenario_id: str, depot_id: str, body: UpdateDepotBody
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    try:
        patch = {k: v for k, v in body.model_dump().items() if v is not None}
        return store.update_depot(scenario_id, depot_id, patch)
    except KeyError:
        raise _not_found("Depot", depot_id)


@router.delete("/scenarios/{scenario_id}/depots/{depot_id}", status_code=204)
def delete_depot(scenario_id: str, depot_id: str) -> Response:
    _check_scenario(scenario_id)
    try:
        store.delete_depot(scenario_id, depot_id)
    except KeyError:
        raise _not_found("Depot", depot_id)
    return Response(status_code=204)


# ── Vehicle Pydantic models ────────────────────────────────────


class CreateVehicleBody(BaseModel):
    depotId: str
    type: str = "BEV"  # BEV | ICE
    modelName: str = ""
    capacityPassengers: int = 0
    batteryKwh: Optional[float] = None
    fuelTankL: Optional[float] = None
    energyConsumption: float = 0.0
    chargePowerKw: Optional[float] = None
    minSoc: Optional[float] = None
    maxSoc: Optional[float] = None
    acquisitionCost: float = 0.0
    enabled: bool = True


class CreateVehicleBatchBody(CreateVehicleBody):
    quantity: int = Field(default=1, ge=1)


class DuplicateVehicleBatchBody(BaseModel):
    quantity: int = Field(default=1, ge=1)
    targetDepotId: Optional[str] = None


class DuplicateVehicleBody(BaseModel):
    targetDepotId: Optional[str] = None


class UpdateVehicleBody(BaseModel):
    depotId: Optional[str] = None
    type: Optional[str] = None
    modelName: Optional[str] = None
    capacityPassengers: Optional[int] = None
    batteryKwh: Optional[float] = None
    fuelTankL: Optional[float] = None
    energyConsumption: Optional[float] = None
    chargePowerKw: Optional[float] = None
    minSoc: Optional[float] = None
    maxSoc: Optional[float] = None
    acquisitionCost: Optional[float] = None
    enabled: Optional[bool] = None


class CreateVehicleTemplateBody(BaseModel):
    name: str
    type: str = "BEV"
    modelName: str = ""
    capacityPassengers: int = 0
    batteryKwh: Optional[float] = None
    fuelTankL: Optional[float] = None
    energyConsumption: float = 0.0
    chargePowerKw: Optional[float] = None
    minSoc: Optional[float] = None
    maxSoc: Optional[float] = None
    acquisitionCost: float = 0.0
    enabled: bool = True


class UpdateVehicleTemplateBody(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    modelName: Optional[str] = None
    capacityPassengers: Optional[int] = None
    batteryKwh: Optional[float] = None
    fuelTankL: Optional[float] = None
    energyConsumption: Optional[float] = None
    chargePowerKw: Optional[float] = None
    minSoc: Optional[float] = None
    maxSoc: Optional[float] = None
    acquisitionCost: Optional[float] = None
    enabled: Optional[bool] = None


# ── Stop Pydantic models ────────────────────────────────────────


class ImportOdptStopsBody(BaseModel):
    operator: str = DEFAULT_OPERATOR
    dump: bool = True
    forceRefresh: bool = False
    ttlSec: int = 3600


class ImportGtfsStopsBody(BaseModel):
    feedPath: str = DEFAULT_GTFS_FEED_PATH


# ── Vehicle endpoints ──────────────────────────────────────────


@router.get("/scenarios/{scenario_id}/vehicles")
def list_vehicles(
    scenario_id: str,
    depotId: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    items = store.list_vehicles(scenario_id, depot_id=depotId)
    return {"items": items, "total": len(items)}


@router.post("/scenarios/{scenario_id}/vehicles", status_code=201)
def create_vehicle(scenario_id: str, body: CreateVehicleBody) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    return store.create_vehicle(scenario_id, body.model_dump())


@router.post("/scenarios/{scenario_id}/vehicles/bulk", status_code=201)
def create_vehicle_batch(
    scenario_id: str, body: CreateVehicleBatchBody
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    payload = body.model_dump()
    quantity = payload.pop("quantity", 1)
    items = store.create_vehicle_batch(scenario_id, payload, quantity)
    return {"items": items, "total": len(items)}


@router.get("/scenarios/{scenario_id}/vehicles/{vehicle_id}")
def get_vehicle(scenario_id: str, vehicle_id: str) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    try:
        return store.get_vehicle(scenario_id, vehicle_id)
    except KeyError:
        raise _not_found("Vehicle", vehicle_id)


@router.put("/scenarios/{scenario_id}/vehicles/{vehicle_id}")
def update_vehicle(
    scenario_id: str, vehicle_id: str, body: UpdateVehicleBody
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    try:
        patch = {k: v for k, v in body.model_dump().items() if v is not None}
        return store.update_vehicle(scenario_id, vehicle_id, patch)
    except KeyError:
        raise _not_found("Vehicle", vehicle_id)


@router.post(
    "/scenarios/{scenario_id}/vehicles/{vehicle_id}/duplicate", status_code=201
)
def duplicate_vehicle(
    scenario_id: str,
    vehicle_id: str,
    body: Optional[DuplicateVehicleBody] = None,
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    try:
        return store.duplicate_vehicle_to_depot(
            scenario_id,
            vehicle_id,
            target_depot_id=body.targetDepotId if body else None,
        )
    except KeyError:
        raise _not_found("Vehicle", vehicle_id)


@router.post(
    "/scenarios/{scenario_id}/vehicles/{vehicle_id}/duplicate-bulk", status_code=201
)
def duplicate_vehicle_batch(
    scenario_id: str, vehicle_id: str, body: DuplicateVehicleBatchBody
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    try:
        items = store.duplicate_vehicle_batch(
            scenario_id,
            vehicle_id,
            body.quantity,
            target_depot_id=body.targetDepotId,
        )
        return {"items": items, "total": len(items)}
    except KeyError:
        raise _not_found("Vehicle", vehicle_id)


@router.delete("/scenarios/{scenario_id}/vehicles/{vehicle_id}", status_code=204)
def delete_vehicle(scenario_id: str, vehicle_id: str) -> Response:
    _check_scenario(scenario_id)
    try:
        store.delete_vehicle(scenario_id, vehicle_id)
    except KeyError:
        raise _not_found("Vehicle", vehicle_id)
    return Response(status_code=204)


@router.get("/scenarios/{scenario_id}/vehicle-templates")
def list_vehicle_templates(scenario_id: str) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    items = store.list_vehicle_templates(scenario_id)
    return {"items": items, "total": len(items)}


@router.post("/scenarios/{scenario_id}/vehicle-templates", status_code=201)
def create_vehicle_template(
    scenario_id: str, body: CreateVehicleTemplateBody
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    return store.create_vehicle_template(scenario_id, body.model_dump())


@router.get("/scenarios/{scenario_id}/vehicle-templates/{template_id}")
def get_vehicle_template(scenario_id: str, template_id: str) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    try:
        return store.get_vehicle_template(scenario_id, template_id)
    except KeyError:
        raise _not_found("Vehicle template", template_id)


@router.put("/scenarios/{scenario_id}/vehicle-templates/{template_id}")
def update_vehicle_template(
    scenario_id: str, template_id: str, body: UpdateVehicleTemplateBody
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    try:
        patch = {k: v for k, v in body.model_dump().items() if v is not None}
        return store.update_vehicle_template(scenario_id, template_id, patch)
    except KeyError:
        raise _not_found("Vehicle template", template_id)


@router.delete(
    "/scenarios/{scenario_id}/vehicle-templates/{template_id}", status_code=204
)
def delete_vehicle_template(scenario_id: str, template_id: str) -> Response:
    _check_scenario(scenario_id)
    try:
        store.delete_vehicle_template(scenario_id, template_id)
    except KeyError:
        raise _not_found("Vehicle template", template_id)
    return Response(status_code=204)


# ── Route Pydantic models ──────────────────────────────────────


class CreateRouteBody(BaseModel):
    name: str
    startStop: str = ""
    endStop: str = ""
    distanceKm: float = 0.0
    durationMin: int = 0
    color: str = "#3B82F6"
    enabled: bool = True


class UpdateRouteBody(BaseModel):
    name: Optional[str] = None
    startStop: Optional[str] = None
    endStop: Optional[str] = None
    distanceKm: Optional[float] = None
    durationMin: Optional[int] = None
    color: Optional[str] = None
    enabled: Optional[bool] = None


class UpsertRouteDepotAssignmentBody(BaseModel):
    depotId: Optional[str] = None
    assignmentType: str = "manual_override"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = ""
    sourceRefs: List[Dict[str, Any]] = Field(default_factory=list)


class ImportOdptRoutesBody(BaseModel):
    operator: str = DEFAULT_OPERATOR
    dump: bool = True
    forceRefresh: bool = False
    ttlSec: int = 3600


class ImportGtfsRoutesBody(BaseModel):
    feedPath: str = DEFAULT_GTFS_FEED_PATH


def _build_explorer_overview(scenario_id: str, operator: Optional[str]) -> Dict[str, Any]:
    routes = store.list_routes(scenario_id, operator=operator)
    assignments = store.list_route_depot_assignments(scenario_id, operator=operator)
    unresolved_assignments = sum(1 for item in assignments if not item.get("depotId"))
    routes_with_stops = sum(1 for route in routes if len(route.get("stopSequence") or []) > 0)
    routes_with_timetable = sum(1 for route in routes if int(route.get("tripCount") or 0) > 0)
    import_sources = (
        store.get_route_import_meta(scenario_id),
        store.get_stop_import_meta(scenario_id),
        store.get_timetable_import_meta(scenario_id),
        store.get_stop_timetable_import_meta(scenario_id),
    )
    warning_count = 0
    for meta_group in import_sources:
        for meta in meta_group.values():
            warning_count += len(list((meta or {}).get("warnings") or []))
    return {
        "routeCount": len(routes),
        "routeWithDepotCount": len(routes) - unresolved_assignments,
        "routeWithStopsCount": routes_with_stops,
        "routeWithTimetableCount": routes_with_timetable,
        "unresolvedDepotAssignmentCount": unresolved_assignments,
        "warningCount": warning_count,
        "imports": {
            "routes": store.get_route_import_meta(scenario_id),
            "stops": store.get_stop_import_meta(scenario_id),
            "timetable": store.get_timetable_import_meta(scenario_id),
            "stopTimetables": store.get_stop_timetable_import_meta(scenario_id),
        },
    }


# ── Stop endpoints ──────────────────────────────────────────────


@router.get("/scenarios/{scenario_id}/stops")
def list_stops(scenario_id: str) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    items = store.list_stops(scenario_id)
    return {
        "items": items,
        "total": len(items),
        "meta": {
            "imports": store.get_stop_import_meta(scenario_id),
        },
    }


@router.post("/scenarios/{scenario_id}/stops/import-odpt")
def import_odpt_stops(scenario_id: str, body: ImportOdptStopsBody) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    try:
        bundle = transit_catalog.get_or_refresh_odpt_snapshot(
            operator=body.operator,
            dump=body.dump,
            force_refresh=body.forceRefresh,
            ttl_sec=body.ttlSec,
        )
        imported_stops = list(bundle.get("stops") or [])
        meta = bundle.get("meta") or {}
        quality = summarize_stop_import(imported_stops, {"meta": meta})
        import_meta = {
            "operator": body.operator,
            "dump": meta.get("effectiveDump", meta.get("dump", body.dump)),
            "requestedDump": body.dump,
            "source": "odpt",
            "resourceType": "BusstopPole",
            "generatedAt": meta.get("generatedAt"),
            "warnings": meta.get("warnings", []),
            "cache": meta.get("cache", {}),
            "snapshotKey": (bundle.get("snapshot") or {}).get("snapshotKey"),
            "snapshotMode": meta.get("snapshotMode"),
            "quality": quality,
        }
        all_stops = store.replace_stops_from_source(
            scenario_id, "odpt", imported_stops, import_meta=import_meta
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return {
        "items": imported_stops,
        "total": len(imported_stops),
        "allStopsTotal": len(all_stops),
        "meta": import_meta,
    }


@router.post("/scenarios/{scenario_id}/stops/import-gtfs")
def import_gtfs_stops(scenario_id: str, body: ImportGtfsStopsBody) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    try:
        bundle = transit_catalog.get_or_refresh_gtfs_snapshot(feed_path=body.feedPath)
        imported_stops = list(bundle.get("stops") or [])
        meta = bundle.get("meta") or {}
        quality = summarize_gtfs_stop_import(imported_stops, {"meta": meta})
        import_meta = {
            "source": "gtfs",
            "feedPath": meta.get("feedPath") or body.feedPath,
            "agencyName": meta.get("agencyName"),
            "resourceType": "GTFSStop",
            "generatedAt": meta.get("generatedAt"),
            "warnings": meta.get("warnings", []),
            "snapshotKey": (bundle.get("snapshot") or {}).get("snapshotKey"),
            "snapshotMode": meta.get("snapshotMode"),
            "quality": quality,
        }
        all_stops = store.replace_stops_from_source(
            scenario_id, "gtfs", imported_stops, import_meta=import_meta
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "items": imported_stops,
        "total": len(imported_stops),
        "allStopsTotal": len(all_stops),
        "meta": import_meta,
    }


# ── Route endpoints ────────────────────────────────────────────


@router.get("/scenarios/{scenario_id}/routes")
def list_routes(
    scenario_id: str,
    depot_id: Optional[str] = Query(None, alias="depotId"),
    operator: Optional[str] = Query(None),
    group_by_family: bool = Query(False, alias="groupByFamily"),
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    items = store.list_routes(scenario_id, depot_id=depot_id, operator=operator)

    # Always enrich with family metadata
    items = enrich_routes_with_family(items)
    if group_by_family:
        items = sorted(
            items,
            key=lambda route: (
                str(route.get("routeFamilyCode") or route.get("routeCode") or route.get("name") or ""),
                int(route.get("familySortOrder") or 999),
                str(route.get("routeLabel") or route.get("name") or ""),
                str(route.get("id") or ""),
            ),
        )

    return {
        "items": items,
        "total": len(items),
        "meta": {
            "imports": store.get_route_import_meta(scenario_id),
            "groupedByFamily": group_by_family,
        },
    }


@router.post("/scenarios/{scenario_id}/routes", status_code=201)
def create_route(scenario_id: str, body: CreateRouteBody) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    return store.create_route(scenario_id, body.model_dump())


@router.get("/scenarios/{scenario_id}/routes/{route_id}")
def get_route(scenario_id: str, route_id: str) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    try:
        route = store.get_route(scenario_id, route_id)
    except KeyError:
        raise _not_found("Route", route_id)

    # ── Resolve stopSequence against stop catalog ────────────
    stop_sequence = route.get("stopSequence") or []
    if stop_sequence:
        all_stops = store.list_stops(scenario_id)
        stop_index: Dict[str, Dict[str, Any]] = {s["id"]: s for s in all_stops}

        resolved_stops: List[Dict[str, Any]] = []
        missing_stop_ids: List[str] = []

        for seq, stop_id in enumerate(stop_sequence, start=1):
            stop = stop_index.get(stop_id)
            if stop:
                resolved_stops.append({
                    "id": stop["id"],
                    "name": stop.get("name", stop_id),
                    "kana": stop.get("kana"),
                    "lat": stop.get("lat"),
                    "lon": stop.get("lon"),
                    "platformCode": stop.get("poleNumber") or stop.get("platformCode"),
                    "sequence": seq,
                })
            else:
                missing_stop_ids.append(stop_id)

        stops_resolved = len(resolved_stops)
        stops_missing = len(missing_stop_ids)
        if stops_missing == 0 and stops_resolved > 0:
            link_state = "linked"
        elif stops_resolved > 0:
            link_state = "partial"
        else:
            link_state = "unlinked"

        route["resolvedStops"] = resolved_stops
        route["linkStatus"] = {
            "stopsResolved": stops_resolved,
            "stopsMissing": stops_missing,
            "missingStopIds": missing_stop_ids,
            "tripsLinked": int(route.get("tripCount") or 0),
            "stopTimetableEntriesLinked": 0,
            "warnings": [f"missing stop: {sid}" for sid in missing_stop_ids],
        }
        route["linkState"] = link_state
    else:
        route["resolvedStops"] = []
        route["linkStatus"] = {
            "stopsResolved": 0,
            "stopsMissing": 0,
            "missingStopIds": [],
            "tripsLinked": int(route.get("tripCount") or 0),
            "stopTimetableEntriesLinked": 0,
            "warnings": [],
        }
        route["linkState"] = "unlinked"

    # ── Enrich with family/variant metadata ──────────────────
    all_routes = store.list_routes(scenario_id)
    family_meta = derive_route_family_metadata(all_routes)
    route_meta = family_meta.get(route.get("id", ""))
    if route_meta:
        route.update(route_meta.to_dict())

    return route


# ── Route Family endpoints ─────────────────────────────────────


@router.get("/scenarios/{scenario_id}/route-families")
def list_route_families(
    scenario_id: str,
    operator: Optional[str] = Query(None),
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    items = store.list_routes(scenario_id, operator=operator)
    items = enrich_routes_with_family(items)
    families = build_route_family_summary(items)
    return {
        "items": families,
        "total": len(families),
    }


@router.get("/scenarios/{scenario_id}/route-families/{route_family_id}")
def get_route_family(
    scenario_id: str,
    route_family_id: str,
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    items = store.list_routes(scenario_id)
    items = enrich_routes_with_family(items)
    detail = build_route_family_detail(route_family_id, items)
    if not detail:
        raise _not_found("RouteFamily", route_family_id)
    return {"item": detail}


@router.put("/scenarios/{scenario_id}/routes/{route_id}")
def update_route(
    scenario_id: str, route_id: str, body: UpdateRouteBody
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    try:
        patch = {k: v for k, v in body.model_dump().items() if v is not None}
        return store.update_route(scenario_id, route_id, patch)
    except KeyError:
        raise _not_found("Route", route_id)


@router.delete("/scenarios/{scenario_id}/routes/{route_id}", status_code=204)
def delete_route(scenario_id: str, route_id: str) -> Response:
    _check_scenario(scenario_id)
    try:
        store.delete_route(scenario_id, route_id)
    except KeyError:
        raise _not_found("Route", route_id)
    return Response(status_code=204)


@router.post("/scenarios/{scenario_id}/routes/import-odpt")
def import_odpt_routes(scenario_id: str, body: ImportOdptRoutesBody) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    try:
        bundle = transit_catalog.get_or_refresh_odpt_snapshot(
            operator=body.operator,
            dump=body.dump,
            force_refresh=body.forceRefresh,
            ttl_sec=body.ttlSec,
        )
        imported_routes = list(bundle.get("routes") or [])
        meta = bundle.get("meta") or {}
        quality = summarize_routes_import(imported_routes, {"meta": meta})
        import_meta = {
            "operator": body.operator,
            "dump": meta.get("effectiveDump", meta.get("dump", body.dump)),
            "requestedDump": body.dump,
            "source": "odpt",
            "generatedAt": meta.get("generatedAt"),
            "warnings": meta.get("warnings", []),
            "cache": meta.get("cache", {}),
            "snapshotKey": (bundle.get("snapshot") or {}).get("snapshotKey"),
            "snapshotMode": meta.get("snapshotMode"),
            "quality": quality,
        }
        all_routes = store.replace_routes_from_source(
            scenario_id, "odpt", imported_routes, import_meta=import_meta
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    return {
        "items": imported_routes,
        "total": len(imported_routes),
        "allRoutesTotal": len(all_routes),
        "meta": import_meta,
    }


@router.post("/scenarios/{scenario_id}/routes/import-gtfs")
def import_gtfs_routes(scenario_id: str, body: ImportGtfsRoutesBody) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    try:
        bundle = transit_catalog.get_or_refresh_gtfs_snapshot(feed_path=body.feedPath)
        imported_routes = list(bundle.get("routes") or [])
        meta = bundle.get("meta") or {}
        quality = summarize_gtfs_routes_import(imported_routes, {"meta": meta})
        import_meta = {
            "source": "gtfs",
            "feedPath": meta.get("feedPath") or body.feedPath,
            "agencyName": meta.get("agencyName"),
            "resourceType": "GTFSRoutePattern",
            "generatedAt": meta.get("generatedAt"),
            "warnings": meta.get("warnings", []),
            "snapshotKey": (bundle.get("snapshot") or {}).get("snapshotKey"),
            "snapshotMode": meta.get("snapshotMode"),
            "quality": quality,
        }
        all_routes = store.replace_routes_from_source(
            scenario_id, "gtfs", imported_routes, import_meta=import_meta
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "items": imported_routes,
        "total": len(imported_routes),
        "allRoutesTotal": len(all_routes),
        "meta": import_meta,
    }


@router.get("/scenarios/{scenario_id}/explorer/overview")
def explorer_overview(
    scenario_id: str,
    operator: Optional[str] = Query(None),
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    return {"item": _build_explorer_overview(scenario_id, operator)}


@router.get("/scenarios/{scenario_id}/explorer/depot-assignments")
def list_explorer_depot_assignments(
    scenario_id: str,
    operator: Optional[str] = Query(None),
    unresolved_only: bool = Query(False, alias="unresolvedOnly"),
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    items = store.list_route_depot_assignments(
        scenario_id,
        operator=operator,
        unresolved_only=unresolved_only,
    )
    return {"items": items, "total": len(items)}


@router.patch("/scenarios/{scenario_id}/explorer/depot-assignments/{route_id}")
def patch_explorer_depot_assignment(
    scenario_id: str,
    route_id: str,
    body: UpsertRouteDepotAssignmentBody,
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    try:
        item = store.upsert_route_depot_assignment(scenario_id, route_id, body.model_dump())
    except KeyError:
        raise _not_found("Route", route_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"item": item}


# ── Permission Pydantic models ─────────────────────────────────


class DepotRoutePermissionItem(BaseModel):
    depotId: str
    routeId: str
    allowed: bool


class UpdateDepotRoutePermissionsBody(BaseModel):
    permissions: List[DepotRoutePermissionItem]


class VehicleRoutePermissionItem(BaseModel):
    vehicleId: str
    routeId: str
    allowed: bool


class UpdateVehicleRoutePermissionsBody(BaseModel):
    permissions: List[VehicleRoutePermissionItem]


# ── Permission endpoints ───────────────────────────────────────


@router.get("/scenarios/{scenario_id}/depot-route-permissions")
def get_depot_route_permissions(scenario_id: str) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    items = store.get_depot_route_permissions(scenario_id)
    return {"items": items, "total": len(items)}


@router.put("/scenarios/{scenario_id}/depot-route-permissions")
def update_depot_route_permissions(
    scenario_id: str, body: UpdateDepotRoutePermissionsBody
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    perms = [p.model_dump() for p in body.permissions]
    store.set_depot_route_permissions(scenario_id, perms)
    return {"items": perms, "total": len(perms)}


@router.get("/scenarios/{scenario_id}/vehicle-route-permissions")
def get_vehicle_route_permissions(scenario_id: str) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    items = store.get_vehicle_route_permissions(scenario_id)
    return {"items": items, "total": len(items)}


@router.put("/scenarios/{scenario_id}/vehicle-route-permissions")
def update_vehicle_route_permissions(
    scenario_id: str, body: UpdateVehicleRoutePermissionsBody
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    perms = [p.model_dump() for p in body.permissions]
    store.set_vehicle_route_permissions(scenario_id, perms)
    return {"items": perms, "total": len(perms)}
