"""Tokyu Bus reference data router.

This module serves summary-oriented reference APIs for depot, route, vehicle,
and permission management inside a single scenario.

Allowed responsibilities:
- depot summaries and detail CRUD
- route summaries by scenario/depot
- vehicle and permission management for planning
- aggregated route-family views and lightweight explorer summaries

Forbidden responsibilities:
- feed import or build logic
- legacy public explorer behavior
- nested bulk payload dumps for trip/timetable internals in list endpoints
- producer-side catalog operations
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field, model_validator

from bff.services.route_family import (
    build_route_family_detail,
    build_route_family_summary,
    enrich_routes_with_family,
)
from bff.services.ice_vehicle_reference import apply_ice_reference_defaults
from bff.services.service_ids import canonical_service_id
from bff.store import scenario_store as store
from src.route_family_runtime import (
    normalize_direction,
    normalize_variant_type,
)
from src.value_normalization import coerce_list

router = APIRouter(tags=["master-data"])


def _not_found(kind: str, id_: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{kind} '{id_}' not found")


def _scenario_not_found(scenario_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")


def _check_scenario(scenario_id: str) -> None:
    try:
        store.get_scenario(scenario_id)
        store.ensure_runtime_master_data(scenario_id)
    except KeyError:
        raise _scenario_not_found(scenario_id)
    except RuntimeError as e:
        if "artifacts are incomplete" in str(e):
            raise HTTPException(
                status_code=409,
                detail={"code": "INCOMPLETE_ARTIFACT", "message": str(e)},
            )
        raise


def _depot_summary(depot: Dict[str, Any]) -> Dict[str, Any]:
    route_count = int(depot.get("routeCount") or 0)
    return {
        "id": depot.get("id"),
        "name": depot.get("name"),
        "location": depot.get("location"),
        "lat": depot.get("lat"),
        "lon": depot.get("lon"),
        "routeCount": route_count,
    }


def _route_summaries_from_timetable(
    scenario_id: str,
    route_ids: Set[str],
) -> Dict[str, Dict[str, Any]]:
    by_route: Dict[str, Dict[str, Any]] = {}
    if not route_ids:
        return by_route

    summary_rows = store.summarize_route_service_trip_counts(scenario_id)
    if not summary_rows:
        return by_route

    for row in summary_rows:
        route_id = str(row.get("route_id") or "").strip()
        if not route_id or route_id not in route_ids:
            continue
        bucket = by_route.setdefault(
            route_id,
            {
                "tripCount": 0,
                "serviceTypes": set(),
            },
        )
        bucket["tripCount"] += int(row.get("trip_count") or 0)
        bucket["serviceTypes"].add(
            canonical_service_id(row.get("service_id") or "WEEKDAY")
        )

    for bucket in by_route.values():
        bucket["serviceTypes"] = sorted(bucket["serviceTypes"])
    return by_route


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _normalize_direction(value: Any, default: str = "outbound") -> str:
    return normalize_direction(value, default=default)


def _normalize_variant_type(value: Any) -> str:
    if str(value or "").strip() == "":
        return "unknown"
    return normalize_variant_type(value, direction="unknown")


# ── Depot Pydantic models ──────────────────────────────────────


class CreateDepotBody(BaseModel):
    name: str
    location: str = ""
    lat: float = 0.0
    lon: float = 0.0
    normalChargerCount: int = Field(default=0, ge=0)
    normalChargerPowerKw: float = Field(default=0.0, ge=0.0)
    fastChargerCount: int = Field(default=0, ge=0)
    fastChargerPowerKw: float = Field(default=0.0, ge=0.0)
    hasFuelFacility: bool = False
    parkingCapacity: int = Field(default=0, ge=0)
    overnightCharging: bool = False
    notes: str = ""


class UpdateDepotBody(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    normalChargerCount: Optional[int] = Field(default=None, ge=0)
    normalChargerPowerKw: Optional[float] = Field(default=None, ge=0.0)
    fastChargerCount: Optional[int] = Field(default=None, ge=0)
    fastChargerPowerKw: Optional[float] = Field(default=None, ge=0.0)
    hasFuelFacility: Optional[bool] = None
    parkingCapacity: Optional[int] = Field(default=None, ge=0)
    overnightCharging: Optional[bool] = None
    notes: Optional[str] = None


# ── Depot endpoints ────────────────────────────────────────────


class AutoAssignDepotsBody(BaseModel):
    minScore: int = Field(
        default=1,
        ge=0,
        le=6,
        description=(
            "Minimum additive score for a depot to be considered. "
            "0=all, 1=operator match or better (default), "
            "2=sidecar_map or better, 3=geographic or better."
        ),
    )
    applyNow: bool = Field(
        default=False,
        description=(
            "If true, the best-scoring depot for each route is immediately "
            "persisted as a depot_route_permission (allowed=True)."
        ),
    )
    operatorId: Optional[str] = Field(
        default=None,
        description="Filter routes to a specific operator.",
    )
    sidecarDepotCandidateMap: Optional[Dict[str, List[str]]] = Field(
        default=None,
        description=(
            "route_family_id → [depot_id, ...] map from GTFS sidecar / "
            "Layer-D feature data. Enables the sidecar_map scoring tier."
        ),
    )


@router.post("/scenarios/{scenario_id}/auto-assign-depots")
def auto_assign_depots_endpoint(
    scenario_id: str,
    body: Optional[AutoAssignDepotsBody] = None,
) -> Dict[str, Any]:
    """Compute score-based depot-route assignment suggestions.

    Scoring tiers (additive):
      3 pts  geographic  – route terminal stop IDs intersect depot stop IDs
      2 pts  sidecar_map – depot listed in sidecarDepotCandidateMap for this route family
      1 pt   operator    – depot.operatorId == route.operatorId

    Returns a ranked candidate list per route.
    If body.applyNow=true, also persists the top-scoring assignment for each route
    as a depot_route_permission entry (allowed=True).
    """
    from collections import defaultdict as _defaultdict

    from bff.services.depot_assignment import compute_depot_route_scores

    _check_scenario(scenario_id)
    body = body or AutoAssignDepotsBody()

    operator_filter = body.operatorId or None
    routes = store.list_routes(scenario_id, operator=operator_filter)
    depots = store.list_depots(scenario_id)
    sidecar_map: Dict[str, List[str]] = body.sidecarDepotCandidateMap or {}

    raw_scores = compute_depot_route_scores(depots, routes, sidecar_map)

    # Group by route, keeping only candidates that meet the score threshold
    by_route: Dict[str, list] = _defaultdict(list)
    for s in raw_scores:
        if s.score >= body.minScore:
            by_route[s.route_id].append(s)

    route_by_id = {str(r.get("id") or ""): r for r in routes}
    depot_by_id = {str(d.get("id") or ""): d for d in depots}

    suggestions = []
    apply_pairs: List[tuple] = []  # (route_id, depot_id)

    for route_id, candidates in by_route.items():
        candidates.sort(key=lambda x: -x.score)
        best = candidates[0]
        route = route_by_id.get(route_id, {})
        suggestions.append(
            {
                "routeId": route_id,
                "routeCode": route.get("routeCode") or route.get("routeFamilyCode"),
                "routeName": (
                    route.get("name") or route.get("routeFamilyLabel") or route_id
                ),
                "suggestedDepotId": best.depot_id,
                "suggestedDepotName": (
                    (depot_by_id.get(best.depot_id) or {}).get("name") or best.depot_id
                ),
                "score": best.score,
                "tier": best.tier,
                "reasons": best.reasons,
                "candidates": [
                    {
                        "depotId": c.depot_id,
                        "depotName": (
                            (depot_by_id.get(c.depot_id) or {}).get("name")
                            or c.depot_id
                        ),
                        "score": c.score,
                        "tier": c.tier,
                        "reasons": c.reasons,
                    }
                    for c in candidates
                ],
            }
        )
        if body.applyNow:
            apply_pairs.append((route_id, best.depot_id))

    # Persist assignments if requested
    applied_count = 0
    if body.applyNow and apply_pairs:
        existing_perms = store.get_depot_route_permissions(scenario_id) or []
        perm_map: Dict[tuple, Dict[str, Any]] = {
            (p["depotId"], p["routeId"]): p
            for p in existing_perms
            if "depotId" in p and "routeId" in p
        }
        for route_id, depot_id in apply_pairs:
            perm_map[(depot_id, route_id)] = {
                "depotId": depot_id,
                "routeId": route_id,
                "allowed": True,
            }
        store.set_depot_route_permissions(scenario_id, list(perm_map.values()))
        applied_count = len(apply_pairs)

    # Sort suggestions: geographic first, then sidecar_map, then operator_match
    suggestions.sort(key=lambda x: -x["score"])

    return {
        "suggestions": suggestions,
        "total": len(suggestions),
        "appliedCount": applied_count,
        "meta": {
            "minScore": body.minScore,
            "applyNow": body.applyNow,
            "depotCount": len(depots),
            "routeCount": len(routes),
        },
    }


@router.get("/scenarios/{scenario_id}/depots")
def list_depots(scenario_id: str) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    depots = store.list_depots(scenario_id)
    routes = store.list_routes(scenario_id)
    route_counts: Dict[str, int] = defaultdict(int)
    for route in routes:
        depot_id = str(route.get("depotId") or "").strip()
        if depot_id:
            route_counts[depot_id] += 1
    items = [
        _depot_summary(
            {
                **depot,
                "routeCount": route_counts.get(str(depot.get("id") or ""), 0),
            }
        )
        for depot in depots
    ]
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
    modelCode: Optional[str] = None
    modelName: str = ""
    capacityPassengers: int = Field(default=0, ge=0)
    batteryKwh: Optional[float] = Field(default=None, ge=0.0)
    fuelTankL: Optional[float] = Field(default=None, ge=0.0)
    energyConsumption: float = Field(default=0.0, ge=0.0)
    fuelEfficiencyKmPerL: Optional[float] = Field(default=None, ge=0.0)
    co2EmissionGPerKm: Optional[float] = Field(default=None, ge=0.0)
    co2EmissionKgPerL: Optional[float] = Field(default=None, ge=0.0)
    curbWeightKg: Optional[float] = Field(default=None, ge=0.0)
    grossVehicleWeightKg: Optional[float] = Field(default=None, ge=0.0)
    engineDisplacementL: Optional[float] = Field(default=None, ge=0.0)
    maxTorqueNm: Optional[float] = Field(default=None, ge=0.0)
    maxPowerKw: Optional[float] = Field(default=None, ge=0.0)
    chargePowerKw: Optional[float] = Field(default=None, ge=0.0)
    minSoc: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    maxSoc: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    acquisitionCost: float = Field(default=0.0, ge=0.0)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_soc_range(self) -> "CreateVehicleBody":
        if self.minSoc is not None and self.maxSoc is not None and self.minSoc > self.maxSoc:
            raise ValueError("minSoc must be <= maxSoc")
        return self


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
    modelCode: Optional[str] = None
    modelName: Optional[str] = None
    capacityPassengers: Optional[int] = Field(default=None, ge=0)
    batteryKwh: Optional[float] = Field(default=None, ge=0.0)
    fuelTankL: Optional[float] = Field(default=None, ge=0.0)
    energyConsumption: Optional[float] = Field(default=None, ge=0.0)
    fuelEfficiencyKmPerL: Optional[float] = Field(default=None, ge=0.0)
    co2EmissionGPerKm: Optional[float] = Field(default=None, ge=0.0)
    co2EmissionKgPerL: Optional[float] = Field(default=None, ge=0.0)
    curbWeightKg: Optional[float] = Field(default=None, ge=0.0)
    grossVehicleWeightKg: Optional[float] = Field(default=None, ge=0.0)
    engineDisplacementL: Optional[float] = Field(default=None, ge=0.0)
    maxTorqueNm: Optional[float] = Field(default=None, ge=0.0)
    maxPowerKw: Optional[float] = Field(default=None, ge=0.0)
    chargePowerKw: Optional[float] = Field(default=None, ge=0.0)
    minSoc: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    maxSoc: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    acquisitionCost: Optional[float] = Field(default=None, ge=0.0)
    enabled: Optional[bool] = None

    @model_validator(mode="after")
    def validate_soc_range(self) -> "UpdateVehicleBody":
        if self.minSoc is not None and self.maxSoc is not None and self.minSoc > self.maxSoc:
            raise ValueError("minSoc must be <= maxSoc")
        return self


class CreateVehicleTemplateBody(BaseModel):
    name: str
    type: str = "BEV"
    modelCode: Optional[str] = None
    modelName: str = ""
    capacityPassengers: int = Field(default=0, ge=0)
    batteryKwh: Optional[float] = Field(default=None, ge=0.0)
    fuelTankL: Optional[float] = Field(default=None, ge=0.0)
    energyConsumption: float = Field(default=0.0, ge=0.0)
    fuelEfficiencyKmPerL: Optional[float] = Field(default=None, ge=0.0)
    co2EmissionGPerKm: Optional[float] = Field(default=None, ge=0.0)
    co2EmissionKgPerL: Optional[float] = Field(default=None, ge=0.0)
    curbWeightKg: Optional[float] = Field(default=None, ge=0.0)
    grossVehicleWeightKg: Optional[float] = Field(default=None, ge=0.0)
    engineDisplacementL: Optional[float] = Field(default=None, ge=0.0)
    maxTorqueNm: Optional[float] = Field(default=None, ge=0.0)
    maxPowerKw: Optional[float] = Field(default=None, ge=0.0)
    chargePowerKw: Optional[float] = Field(default=None, ge=0.0)
    minSoc: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    maxSoc: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    acquisitionCost: float = Field(default=0.0, ge=0.0)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_soc_range(self) -> "CreateVehicleTemplateBody":
        if self.minSoc is not None and self.maxSoc is not None and self.minSoc > self.maxSoc:
            raise ValueError("minSoc must be <= maxSoc")
        return self


class UpdateVehicleTemplateBody(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    modelCode: Optional[str] = None
    modelName: Optional[str] = None
    capacityPassengers: Optional[int] = Field(default=None, ge=0)
    batteryKwh: Optional[float] = Field(default=None, ge=0.0)
    fuelTankL: Optional[float] = Field(default=None, ge=0.0)
    energyConsumption: Optional[float] = Field(default=None, ge=0.0)
    fuelEfficiencyKmPerL: Optional[float] = Field(default=None, ge=0.0)
    co2EmissionGPerKm: Optional[float] = Field(default=None, ge=0.0)
    co2EmissionKgPerL: Optional[float] = Field(default=None, ge=0.0)
    curbWeightKg: Optional[float] = Field(default=None, ge=0.0)
    grossVehicleWeightKg: Optional[float] = Field(default=None, ge=0.0)
    engineDisplacementL: Optional[float] = Field(default=None, ge=0.0)
    maxTorqueNm: Optional[float] = Field(default=None, ge=0.0)
    maxPowerKw: Optional[float] = Field(default=None, ge=0.0)
    chargePowerKw: Optional[float] = Field(default=None, ge=0.0)
    minSoc: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    maxSoc: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    acquisitionCost: Optional[float] = Field(default=None, ge=0.0)
    enabled: Optional[bool] = None

    @model_validator(mode="after")
    def validate_soc_range(self) -> "UpdateVehicleTemplateBody":
        if self.minSoc is not None and self.maxSoc is not None and self.minSoc > self.maxSoc:
            raise ValueError("minSoc must be <= maxSoc")
        return self


# ── Stop Pydantic models ────────────────────────────────────────


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
    payload = apply_ice_reference_defaults(body.model_dump())
    return store.create_vehicle(scenario_id, payload)


@router.post("/scenarios/{scenario_id}/vehicles/bulk", status_code=201)
def create_vehicle_batch(
    scenario_id: str, body: CreateVehicleBatchBody
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    payload = apply_ice_reference_defaults(body.model_dump())
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
        existing = store.get_vehicle(scenario_id, vehicle_id)
        patch_for_defaults = dict(patch)
        patch_for_defaults.setdefault("type", existing.get("type"))
        normalized = apply_ice_reference_defaults(patch_for_defaults)
        if "type" not in patch:
            normalized.pop("type", None)
        derived_fields = {
            "modelCode",
            "fuelEfficiencyKmPerL",
            "co2EmissionGPerKm",
            "co2EmissionKgPerL",
            "curbWeightKg",
            "grossVehicleWeightKg",
            "engineDisplacementL",
            "maxTorqueNm",
            "maxPowerKw",
            "energyConsumption",
            "capacityPassengers",
        }
        patch = {
            key: value
            for key, value in normalized.items()
            if key in patch or key in derived_fields
        }
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
    payload = apply_ice_reference_defaults(body.model_dump())
    return store.create_vehicle_template(scenario_id, payload)


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
        existing = store.get_vehicle_template(scenario_id, template_id)
        patch_for_defaults = dict(patch)
        patch_for_defaults.setdefault("type", existing.get("type"))
        normalized = apply_ice_reference_defaults(patch_for_defaults)
        if "type" not in patch:
            normalized.pop("type", None)
        derived_fields = {
            "modelCode",
            "fuelEfficiencyKmPerL",
            "co2EmissionGPerKm",
            "co2EmissionKgPerL",
            "curbWeightKg",
            "grossVehicleWeightKg",
            "engineDisplacementL",
            "maxTorqueNm",
            "maxPowerKw",
            "energyConsumption",
            "capacityPassengers",
        }
        patch = {
            key: value
            for key, value in normalized.items()
            if key in patch or key in derived_fields
        }
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
    routeFamilyCode: Optional[str] = None
    routeFamilyLabel: Optional[str] = None
    routeSeriesCode: Optional[str] = None
    routeSeriesPrefix: Optional[str] = None
    routeSeriesNumber: Optional[int] = None
    routeVariantType: Optional[str] = None
    canonicalDirection: Optional[str] = None
    isPrimaryVariant: Optional[bool] = None
    routeVariantTypeManual: Optional[str] = None
    canonicalDirectionManual: Optional[str] = None
    depotId: Optional[str] = None


class UpsertRouteDepotAssignmentBody(BaseModel):
    depotId: Optional[str] = None
    assignmentType: str = "manual_override"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = ""
    sourceRefs: List[Dict[str, Any]] = Field(default_factory=list)


def _build_explorer_overview(
    scenario_id: str, operator: Optional[str]
) -> Dict[str, Any]:
    routes = _enrich_routes_for_display(
        scenario_id,
        store.list_routes(scenario_id, operator=operator),
    )
    unresolved_assignments = sum(1 for route in routes if not route.get("depotId"))
    routes_with_stops = sum(
        1
        for route in routes
        if int((route.get("linkStatus") or {}).get("stopsResolved") or 0) > 0
        or len(coerce_list(route.get("stopSequence"))) > 0
    )
    routes_with_timetable = sum(
        1
        for route in routes
        if int((route.get("linkStatus") or {}).get("tripsLinked") or 0) > 0
    )
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
    items = enrich_routes_with_family([dict(route) for route in items])

    route_ids = {
        str(route.get("id") or "").strip()
        for route in items
        if route.get("id") is not None
    }
    route_summaries = _route_summaries_from_timetable(scenario_id, route_ids)

    if group_by_family:
        items = sorted(
            items,
            key=lambda route: (
                str(
                    route.get("routeFamilyCode")
                    or route.get("routeCode")
                    or route.get("name")
                    or ""
                ),
                int(route.get("familySortOrder") or 999),
                str(route.get("routeLabel") or route.get("name") or ""),
                str(route.get("id") or ""),
            ),
        )

    summarized_items = []
    for route in items:
        route_id = str(route.get("id") or "").strip()
        summary = route_summaries.get(route_id)
        service_types = list(summary.get("serviceTypes") or []) if summary else []
        trip_count = int(summary.get("tripCount") or 0) if summary else 0
        route_item = {
            "id": route.get("id"),
            "name": route.get("name"),
            "routeCode": route.get("routeCode"),
            "routeLabel": route.get("routeLabel"),
            "startStop": route.get("startStop"),
            "endStop": route.get("endStop"),
            "distanceKm": route.get("distanceKm"),
            "durationMin": route.get("durationMin"),
            "color": route.get("color"),
            "enabled": route.get("enabled"),
            "source": route.get("source"),
            "depotId": route.get("depotId"),
            "assignmentType": route.get("assignmentType"),
            "assignmentConfidence": route.get("assignmentConfidence"),
            "assignmentReason": route.get("assignmentReason"),
            "tripCount": _safe_int(route.get("tripCount")) or trip_count,
            "serviceTypes": service_types,
            "routeFamilyId": route.get("routeFamilyId"),
            "routeFamilyCode": route.get("routeFamilyCode"),
            "routeFamilyLabel": route.get("routeFamilyLabel"),
            "routeSeriesCode": route.get("routeSeriesCode"),
            "routeSeriesPrefix": route.get("routeSeriesPrefix"),
            "routeSeriesNumber": route.get("routeSeriesNumber"),
            "routeVariantId": route.get("routeVariantId"),
            "routeVariantType": _normalize_variant_type(route.get("routeVariantType")),
            "routeVariantTypeManual": _normalize_variant_type(route.get("routeVariantTypeManual")) if route.get("routeVariantTypeManual") else None,
            "canonicalDirection": _normalize_direction(route.get("canonicalDirection") or "outbound"),
            "canonicalDirectionManual": _normalize_direction(route.get("canonicalDirectionManual")) if route.get("canonicalDirectionManual") else None,
            "isPrimaryVariant": route.get("isPrimaryVariant"),
            "familySortOrder": route.get("familySortOrder"),
        }
        summarized_items.append(route_item)

    return {
        "items": summarized_items,
        "total": len(summarized_items),
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
            route.get("routeCode"),
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
        direct_route_id = stop_timetable.get("route_id") or stop_timetable.get(
            "routeId"
        )
        if direct_route_id and str(direct_route_id) in route_keys:
            count += len(stop_timetable.get("items") or [])
            continue

        for entry in stop_timetable.get("items") or []:
            busroute_pattern = entry.get("busroutePattern") or entry.get("route_id")
            bus_timetable = entry.get("busTimetable") or entry.get("trip_id")
            if (busroute_pattern and str(busroute_pattern) in route_keys) or (
                bus_timetable and str(bus_timetable) in trip_ids
            ):
                count += 1

    return count


def _route_service_summary(
    schedule_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "serviceId": "",
            "tripCount": 0,
            "firstDeparture": None,
            "lastDeparture": None,
        }
    )
    for row in schedule_rows:
        service_id = canonical_service_id(row.get("service_id"))
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
    schedule_rows: List[Dict[str, Any]],
    stop_timetables: List[Dict[str, Any]],
) -> Dict[str, Any]:
    stop_sequence = [str(item) for item in coerce_list(route.get("stopSequence")) if item is not None]
    stop_index = {
        str(stop.get("id")): stop for stop in stops if stop.get("id") is not None
    }

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
    matching_rows = [row for row in schedule_rows if str(row.get("route_id") or "") in route_keys]
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
    schedule_rows = store.get_field(scenario_id, "timetable" "_rows") or []
    stop_timetables = store.get_field(scenario_id, "stop_timetables") or []

    enriched = [dict(route) for route in routes]
    for route in enriched:
        route.update(
            _build_route_link_data(
                route,
                stops=stops,
                schedule_rows=schedule_rows,
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
        str(route.get("id")): route for route in routes if route.get("id") is not None
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
            str(
                item.get("routeFamilyCode")
                or item.get("routeCode")
                or item.get("routeName")
                or ""
            ),
            int(item.get("familySortOrder") or 999),
            str(item.get("routeCode") or ""),
            str(item.get("routeName") or ""),
            str(item.get("startStop") or ""),
            str(item.get("endStop") or ""),
        )
    )
    return enriched


def _build_route_family_indexes(
    scenario_id: str,
) -> tuple[
    Dict[str, Dict[str, Any]],
    Dict[str, List[Dict[str, Any]]],
]:
    routes = _enrich_routes_for_display(scenario_id, store.list_routes(scenario_id))
    summaries = {
        str(item.get("routeFamilyId")): item
        for item in build_route_family_summary(routes)
        if item.get("routeFamilyId")
    }
    members: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for route in routes:
        family_id = route.get("routeFamilyId")
        if family_id:
            members[str(family_id)].append(route)
    for family_id in members:
        members[family_id] = sorted(
            members[family_id],
            key=lambda item: (
                int(item.get("familySortOrder") or 999),
                str(item.get("routeLabel") or item.get("name") or ""),
                str(item.get("id") or ""),
            ),
        )
    return summaries, members


def _aggregate_route_family_permissions(
    *,
    scenario_id: str,
    principals: List[Dict[str, Any]],
    principal_key: str,
    raw_permissions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    family_summaries, members_by_family = _build_route_family_indexes(scenario_id)
    permission_map = {
        (str(item.get(principal_key)), str(item.get("routeId"))): bool(
            item.get("allowed")
        )
        for item in raw_permissions
        if item.get(principal_key) is not None and item.get("routeId") is not None
    }
    items: List[Dict[str, Any]] = []

    for principal in principals:
        principal_id = principal.get("id")
        if principal_id is None:
            continue
        principal_id = str(principal_id)
        for family_id, summary in family_summaries.items():
            member_route_ids = [
                str(route.get("id"))
                for route in members_by_family.get(family_id, [])
                if route.get("id") is not None
            ]
            total_route_count = len(member_route_ids)
            allowed_route_count = sum(
                1
                for route_id in member_route_ids
                if permission_map.get((principal_id, route_id), False)
            )
            items.append(
                {
                    principal_key: principal_id,
                    "routeFamilyId": family_id,
                    "routeFamilyCode": summary.get("routeFamilyCode"),
                    "routeFamilyLabel": summary.get("routeFamilyLabel"),
                    "primaryColor": summary.get("primaryColor"),
                    "memberRouteIds": member_route_ids,
                    "totalRouteCount": total_route_count,
                    "allowedRouteCount": allowed_route_count,
                    "allowed": total_route_count > 0
                    and allowed_route_count == total_route_count,
                    "partiallyAllowed": 0 < allowed_route_count < total_route_count,
                }
            )

    items.sort(
        key=lambda item: (
            str(item.get(principal_key) or ""),
            str(item.get("routeFamilyCode") or item.get("routeFamilyLabel") or ""),
        )
    )
    return items


def _expand_route_family_permissions(
    *,
    scenario_id: str,
    principal_key: str,
    requested_permissions: List[Dict[str, Any]],
    existing_permissions: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    _family_summaries, members_by_family = _build_route_family_indexes(scenario_id)

    requested_by_principal: Dict[str, Dict[str, bool]] = defaultdict(dict)
    targeted_route_ids: Set[str] = set()
    targeted_principal_ids: Set[str] = set()

    for item in requested_permissions:
        principal_id = item.get(principal_key)
        family_id = item.get("routeFamilyId")
        if principal_id is None or family_id is None:
            continue
        principal_id = str(principal_id)
        family_id = str(family_id)
        members = members_by_family.get(family_id)
        if not members:
            raise ValueError(f"Unknown route family '{family_id}'")
        requested_by_principal[principal_id][family_id] = bool(item.get("allowed"))
        targeted_principal_ids.add(principal_id)
        targeted_route_ids.update(
            str(route.get("id")) for route in members if route.get("id") is not None
        )

    preserved = [
        item
        for item in existing_permissions
        if not (
            str(item.get(principal_key)) in targeted_principal_ids
            and str(item.get("routeId")) in targeted_route_ids
        )
    ]

    expanded: List[Dict[str, Any]] = []
    for principal_id, families in requested_by_principal.items():
        for family_id, allowed in families.items():
            for route in members_by_family.get(family_id, []):
                route_id = route.get("id")
                if route_id is None:
                    continue
                expanded.append(
                    {
                        principal_key: principal_id,
                        "routeId": str(route_id),
                        "allowed": allowed,
                    }
                )

    return preserved + expanded


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
    depotId: Optional[str] = Query(None),
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    depot_filter = depotId if isinstance(depotId, str) and depotId.strip() else None
    items = store.list_routes(scenario_id, depot_id=depot_filter, operator=operator)
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
        if "routeVariantType" in patch:
            patch["routeVariantType"] = _normalize_variant_type(patch.get("routeVariantType"))
        if "routeVariantTypeManual" in patch:
            raw_manual = patch.get("routeVariantTypeManual")
            patch["routeVariantTypeManual"] = (
                _normalize_variant_type(raw_manual) if raw_manual not in (None, "") else None
            )
        if "canonicalDirection" in patch:
            patch["canonicalDirection"] = _normalize_direction(patch.get("canonicalDirection") or "outbound")
        if "canonicalDirectionManual" in patch:
            raw_direction = patch.get("canonicalDirectionManual")
            patch["canonicalDirectionManual"] = (
                _normalize_direction(raw_direction) if raw_direction not in (None, "") else None
            )
        if "depotId" in patch:
            raw_depot_id = str(patch.get("depotId") or "").strip()
            patch["depotId"] = raw_depot_id or None
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
        item = store.upsert_route_depot_assignment(
            scenario_id, route_id, body.model_dump()
        )
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


class DepotRouteFamilyPermissionItem(BaseModel):
    depotId: str
    routeFamilyId: str
    allowed: bool


class UpdateDepotRouteFamilyPermissionsBody(BaseModel):
    permissions: List[DepotRouteFamilyPermissionItem]


class VehicleRouteFamilyPermissionItem(BaseModel):
    vehicleId: str
    routeFamilyId: str
    allowed: bool


class UpdateVehicleRouteFamilyPermissionsBody(BaseModel):
    permissions: List[VehicleRouteFamilyPermissionItem]


# ── Permission endpoints ───────────────────────────────────────


@router.get("/scenarios/{scenario_id}/depot-route-permissions")
def get_depot_route_permissions(scenario_id: str) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    items = store.get_depot_route_permissions(scenario_id)
    return {"items": items, "total": len(items)}


@router.get("/scenarios/{scenario_id}/depot-route-family-permissions")
def get_depot_route_family_permissions(scenario_id: str) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    items = _aggregate_route_family_permissions(
        scenario_id=scenario_id,
        principals=store.list_depots(scenario_id),
        principal_key="depotId",
        raw_permissions=store.get_depot_route_permissions(scenario_id),
    )
    return {"items": items, "total": len(items)}


@router.get("/scenarios/{scenario_id}/depots/{depot_id}/route-family-permissions")
def get_depot_scoped_route_family_permissions(
    scenario_id: str,
    depot_id: str,
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    principals = [
        item
        for item in store.list_depots(scenario_id)
        if str(item.get("id") or "") == depot_id
    ]
    if not principals:
        raise _not_found("Depot", depot_id)

    items = _aggregate_route_family_permissions(
        scenario_id=scenario_id,
        principals=principals,
        principal_key="depotId",
        raw_permissions=store.get_depot_route_permissions(scenario_id),
    )
    return {"items": items, "total": len(items)}


@router.put("/scenarios/{scenario_id}/depot-route-permissions")
def update_depot_route_permissions(
    scenario_id: str, body: UpdateDepotRoutePermissionsBody
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    perms = [p.model_dump() for p in body.permissions]
    store.set_depot_route_permissions(scenario_id, perms)
    return {"items": perms, "total": len(perms)}


@router.put("/scenarios/{scenario_id}/depot-route-family-permissions")
def update_depot_route_family_permissions(
    scenario_id: str,
    body: UpdateDepotRouteFamilyPermissionsBody,
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    requested = [p.model_dump() for p in body.permissions]
    try:
        expanded = _expand_route_family_permissions(
            scenario_id=scenario_id,
            principal_key="depotId",
            requested_permissions=requested,
            existing_permissions=store.get_depot_route_permissions(scenario_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    store.set_depot_route_permissions(scenario_id, expanded)
    items = _aggregate_route_family_permissions(
        scenario_id=scenario_id,
        principals=store.list_depots(scenario_id),
        principal_key="depotId",
        raw_permissions=expanded,
    )
    return {"items": items, "total": len(items)}


@router.get("/scenarios/{scenario_id}/vehicle-route-permissions")
def get_vehicle_route_permissions(scenario_id: str) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    items = store.get_vehicle_route_permissions(scenario_id)
    return {"items": items, "total": len(items)}


@router.get("/scenarios/{scenario_id}/vehicle-route-family-permissions")
def get_vehicle_route_family_permissions(scenario_id: str) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    items = _aggregate_route_family_permissions(
        scenario_id=scenario_id,
        principals=store.list_vehicles(scenario_id),
        principal_key="vehicleId",
        raw_permissions=store.get_vehicle_route_permissions(scenario_id),
    )
    return {"items": items, "total": len(items)}


@router.get("/scenarios/{scenario_id}/depots/{depot_id}/vehicle-route-family-permissions")
def get_depot_scoped_vehicle_route_family_permissions(
    scenario_id: str,
    depot_id: str,
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    depots = store.list_depots(scenario_id)
    if not any(str(item.get("id") or "") == depot_id for item in depots):
        raise _not_found("Depot", depot_id)

    items = _aggregate_route_family_permissions(
        scenario_id=scenario_id,
        principals=store.list_vehicles(scenario_id, depot_id=depot_id),
        principal_key="vehicleId",
        raw_permissions=store.get_vehicle_route_permissions(scenario_id),
    )
    return {"items": items, "total": len(items)}


@router.put("/scenarios/{scenario_id}/vehicle-route-permissions")
def update_vehicle_route_permissions(
    scenario_id: str, body: UpdateVehicleRoutePermissionsBody
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    perms = [p.model_dump() for p in body.permissions]
    store.set_vehicle_route_permissions(scenario_id, perms)
    return {"items": perms, "total": len(perms)}


@router.put("/scenarios/{scenario_id}/vehicle-route-family-permissions")
def update_vehicle_route_family_permissions(
    scenario_id: str,
    body: UpdateVehicleRouteFamilyPermissionsBody,
) -> Dict[str, Any]:
    _check_scenario(scenario_id)
    requested = [p.model_dump() for p in body.permissions]
    try:
        expanded = _expand_route_family_permissions(
            scenario_id=scenario_id,
            principal_key="vehicleId",
            requested_permissions=requested,
            existing_permissions=store.get_vehicle_route_permissions(scenario_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    store.set_vehicle_route_permissions(scenario_id, expanded)
    items = _aggregate_route_family_permissions(
        scenario_id=scenario_id,
        principals=store.list_vehicles(scenario_id),
        principal_key="vehicleId",
        raw_permissions=expanded,
    )
    return {"items": items, "total": len(items)}
