"""
bff/routers/master_data.py

Depots, Vehicles, Routes, and Permission tables endpoints.

Routes:
  GET/POST        /scenarios/{id}/depots
  GET/PUT/DELETE  /scenarios/{id}/depots/{depot_id}
  GET/POST        /scenarios/{id}/vehicles          (optional ?depotId=)
  GET/PUT/DELETE  /scenarios/{id}/vehicles/{vehicle_id}
  GET/POST        /scenarios/{id}/routes
  GET/PUT/DELETE  /scenarios/{id}/routes/{route_id}
  GET/PUT         /scenarios/{id}/depot-route-permissions
  GET/PUT         /scenarios/{id}/vehicle-route-permissions
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

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


@router.delete("/scenarios/{scenario_id}/vehicles/{vehicle_id}", status_code=204)
def delete_vehicle(scenario_id: str, vehicle_id: str) -> Response:
    _check_scenario(scenario_id)
    try:
        store.delete_vehicle(scenario_id, vehicle_id)
    except KeyError:
        raise _not_found("Vehicle", vehicle_id)
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


# ── Route endpoints ────────────────────────────────────────────


@router.get("/scenarios/{scenario_id}/routes")
def list_routes(scenario_id: str) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    items = store.list_routes(scenario_id)
    return {"items": items, "total": len(items)}


@router.post("/scenarios/{scenario_id}/routes", status_code=201)
def create_route(scenario_id: str, body: CreateRouteBody) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    return store.create_route(scenario_id, body.model_dump())


@router.get("/scenarios/{scenario_id}/routes/{route_id}")
def get_route(scenario_id: str, route_id: str) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    try:
        return store.get_route(scenario_id, route_id)
    except KeyError:
        raise _not_found("Route", route_id)


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
