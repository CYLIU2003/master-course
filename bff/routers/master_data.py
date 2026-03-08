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

from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

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


def _load_odpt_bundle(
    *,
    operator: str,
    dump: bool,
    force_refresh: bool,
    ttl_sec: int,
) -> Dict[str, Any]:
    if force_refresh:
        return transit_catalog.refresh_odpt_snapshot(
            operator=operator,
            dump=dump,
            force_refresh=True,
            ttl_sec=ttl_sec,
        )
    bundle = transit_catalog.load_existing_odpt_snapshot(operator=operator)
    if bundle is not None:
        return bundle
    raise RuntimeError(
        "No saved ODPT snapshot is available. Run `python3 catalog_update_app.py refresh odpt` "
        "or retry with forceRefresh=true."
    )


def _load_gtfs_bundle(*, feed_path: str, force_refresh: bool) -> Dict[str, Any]:
    if force_refresh:
        return transit_catalog.refresh_gtfs_snapshot(feed_path=feed_path)
    bundle = transit_catalog.load_existing_gtfs_snapshot(feed_path=feed_path)
    if bundle is not None:
        return bundle
    raise RuntimeError(
        "No saved GTFS snapshot is available. Run `python3 catalog_update_app.py refresh gtfs` "
        "or retry with forceRefresh=true."
    )


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
    forceRefresh: bool = False


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
    routeVariantTypeManual: Optional[str] = None
    canonicalDirectionManual: Optional[str] = None


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
    forceRefresh: bool = False


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
        bundle = _load_odpt_bundle(
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
        bundle = _load_gtfs_bundle(
            feed_path=body.feedPath,
            force_refresh=body.forceRefresh,
        )
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
    items = _enrich_routes_for_display(scenario_id, items)
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


def _route_match_keys(route: Dict[str, Any]) -> Set[str]:
    return {
        str(value)
        for value in (
            route.get("id"),
            route.get("odptPatternId"),
            route.get("odptBusrouteId"),
        )
        if value
    }


def _route_stop_timetable_entry_count(
    route: Dict[str, Any],
    stop_timetables: List[Dict[str, Any]],
    trip_ids: Set[str],
) -> int:
    route_keys = _route_match_keys(route)
    if not route_keys and not trip_ids:
        return 0

    count = 0
    for stop_timetable in stop_timetables:
        direct_route_id = stop_timetable.get("route_id") or stop_timetable.get("routeId")
        if direct_route_id and str(direct_route_id) in route_keys:
            count += len(stop_timetable.get("items") or [])
            continue

        for entry in stop_timetable.get("items") or []:
            busroute_pattern = entry.get("busroutePattern") or entry.get("route_id")
            bus_timetable = entry.get("busTimetable") or entry.get("trip_id")
            if (
                (busroute_pattern and str(busroute_pattern) in route_keys)
                or (bus_timetable and str(bus_timetable) in trip_ids)
            ):
                count += 1

    return count


def _route_service_summary(timetable_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "serviceId": "",
            "tripCount": 0,
            "firstDeparture": None,
            "lastDeparture": None,
        }
    )
    for row in timetable_rows:
        service_id = str(row.get("service_id") or "WEEKDAY")
        summary = grouped[service_id]
        summary["serviceId"] = service_id
        summary["tripCount"] += 1

        departure = row.get("departure")
        if departure and (
            summary["firstDeparture"] is None or departure < summary["firstDeparture"]
        ):
            summary["firstDeparture"] = departure
        if departure and (
            summary["lastDeparture"] is None or departure > summary["lastDeparture"]
        ):
            summary["lastDeparture"] = departure

    return [grouped[key] for key in sorted(grouped)]


def _build_route_link_data(
    route: Dict[str, Any],
    *,
    stops: List[Dict[str, Any]],
    timetable_rows: List[Dict[str, Any]],
    stop_timetables: List[Dict[str, Any]],
) -> Dict[str, Any]:
    stop_sequence = list(route.get("stopSequence") or [])
    stop_index = {str(stop.get("id")): stop for stop in stops if stop.get("id") is not None}

    resolved_stops: List[Dict[str, Any]] = []
    missing_stop_ids: List[str] = []
    for seq, stop_id in enumerate(stop_sequence, start=1):
        stop = stop_index.get(str(stop_id))
        if stop:
            resolved_stops.append(
                {
                    "id": stop["id"],
                    "name": stop.get("name", stop_id),
                    "kana": stop.get("kana"),
                    "lat": stop.get("lat"),
                    "lon": stop.get("lon"),
                    "platformCode": stop.get("poleNumber") or stop.get("platformCode"),
                    "sequence": seq,
                }
            )
        else:
            missing_stop_ids.append(str(stop_id))

    route_keys = _route_match_keys(route)
    matching_rows = [
        row
        for row in timetable_rows
        if str(row.get("route_id") or "") in route_keys
    ]
    trip_ids = {str(row.get("trip_id")) for row in matching_rows if row.get("trip_id")}
    stop_tt_linked = _route_stop_timetable_entry_count(route, stop_timetables, trip_ids)

    warnings = [f"missing stop: {sid}" for sid in missing_stop_ids]
    if not matching_rows:
        warnings.append("no linked timetable rows")
    if stop_timetables and stop_tt_linked == 0:
        warnings.append("no linked stop timetable entries")

    has_stop_sequence = bool(stop_sequence)
    stops_complete = (not has_stop_sequence) or (
        len(resolved_stops) > 0 and not missing_stop_ids
    )
    trips_complete = len(matching_rows) > 0
    stop_timetable_complete = (not stop_timetables) or stop_tt_linked > 0

    if stops_complete and trips_complete and stop_timetable_complete:
        link_state = "linked"
    elif resolved_stops or matching_rows or stop_tt_linked or missing_stop_ids:
        link_state = "partial"
    else:
        link_state = "unlinked"

    return {
        "resolvedStops": resolved_stops,
        "linkState": link_state,
        "linkStatus": {
            "stopsResolved": len(resolved_stops),
            "stopsMissing": len(missing_stop_ids),
            "missingStopIds": missing_stop_ids,
            "tripsLinked": len(matching_rows),
            "stopTimetableEntriesLinked": stop_tt_linked,
            "warnings": warnings,
        },
        "serviceSummary": _route_service_summary(matching_rows),
    }


def _enrich_routes_for_display(
    scenario_id: str,
    routes: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    stops = store.list_stops(scenario_id)
    timetable_rows = store.get_field(scenario_id, "timetable_rows") or []
    stop_timetables = store.get_field(scenario_id, "stop_timetables") or []

    enriched = [dict(route) for route in routes]
    for route in enriched:
        route.update(
            _build_route_link_data(
                route,
                stops=stops,
                timetable_rows=timetable_rows,
                stop_timetables=stop_timetables,
            )
        )

    return enrich_routes_with_family(enriched)


def _enrich_explorer_assignments_for_display(
    scenario_id: str,
    assignments: List[Dict[str, Any]],
    *,
    operator: Optional[str],
) -> List[Dict[str, Any]]:
    routes = _enrich_routes_for_display(
        scenario_id,
        store.list_routes(scenario_id, operator=operator),
    )
    route_meta = {
        str(route.get("id")): route
        for route in routes
        if route.get("id") is not None
    }
    enriched: List[Dict[str, Any]] = []
    for assignment in assignments:
        route = route_meta.get(str(assignment.get("routeId")))
        item = dict(assignment)
        if route:
            item["routeCode"] = (
                route.get("routeCode")
                or route.get("routeFamilyCode")
                or assignment.get("routeCode")
            )
            item["routeFamilyCode"] = route.get("routeFamilyCode")
            item["routeVariantType"] = route.get("routeVariantType")
            item["familySortOrder"] = route.get("familySortOrder")
        enriched.append(item)
    enriched.sort(
        key=lambda item: (
            str(item.get("routeFamilyCode") or item.get("routeCode") or item.get("routeName") or ""),
            int(item.get("familySortOrder") or 999),
            str(item.get("routeCode") or ""),
            str(item.get("routeName") or ""),
            str(item.get("startStop") or ""),
            str(item.get("endStop") or ""),
        )
    )
    return enriched


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

    return _enrich_routes_for_display(scenario_id, [route])[0]


# ── Route Family endpoints ─────────────────────────────────────


@router.get("/scenarios/{scenario_id}/route-families")
def list_route_families(
    scenario_id: str,
    operator: Optional[str] = Query(None),
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    items = store.list_routes(scenario_id, operator=operator)
    items = _enrich_routes_for_display(scenario_id, items)
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
    items = _enrich_routes_for_display(scenario_id, items)
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
        patch = body.model_dump(exclude_unset=True)
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
        bundle = _load_odpt_bundle(
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
        bundle = _load_gtfs_bundle(
            feed_path=body.feedPath,
            force_refresh=body.forceRefresh,
        )
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
    items = _enrich_explorer_assignments_for_display(
        scenario_id,
        items,
        operator=operator,
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
