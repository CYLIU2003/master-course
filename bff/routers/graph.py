"""
bff/routers/graph.py

Dispatch pipeline endpoints: trips, graph, blocks, duties, dispatch plans.

Routes:
  GET   /scenarios/{id}/trips                   → get built trips
  POST  /scenarios/{id}/build-trips             → async: build Trip list from timetable
  GET   /scenarios/{id}/graph                   → get built connection graph
  POST  /scenarios/{id}/build-graph             → async: build feasibility graph
  GET   /scenarios/{id}/blocks                  → get generated vehicle blocks
  POST  /scenarios/{id}/build-blocks            → async: build greedy vehicle blocks
  GET   /scenarios/{id}/duties                  → get generated duties
  POST  /scenarios/{id}/generate-duties         → async: generate duties
  GET   /scenarios/{id}/dispatch-plan           → get greedy dispatch plan artifact
  POST  /scenarios/{id}/build-dispatch-plan     → async: build greedy dispatch plan
  GET   /scenarios/{id}/duties/validate         → validate duties

All POST operations return a JobResponse immediately and execute in a
BackgroundTask. Poll GET /jobs/{job_id} for status.
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel

from bff.dependencies import require_built
from bff.mappers.dispatch_mappers import (
    build_graph_response,
    dict_to_trip,
    trip_to_dict,
    vehicle_duty_to_dict,
    validation_result_to_dict,
)
from bff.mappers.scenario_to_problemdata import _collect_trips_for_scope, _filter_rows_for_scope
from bff.services.route_family import build_route_family_summary
from bff.services.runtime_route_family import (
    effective_route_direction,
    effective_route_variant_type,
    reclassify_routes_for_runtime,
)
from bff.store import job_store, output_paths, scenario_store as store
from src.dispatch.graph_builder import ConnectionGraphBuilder
from src.dispatch.models import (
    DispatchContext,
    Trip,
    TurnaroundRule,
    DeadheadRule,
    VehicleProfile,
)
from src.route_family_runtime import (
    merge_deadhead_metrics,
    normalize_direction,
    normalize_variant_type,
    route_variant_bucket,
)
from src.route_code_utils import extract_route_series_from_candidates
from src.dispatch.pipeline import TimetableDispatchPipeline
from src.tokyu_bus_data import (
    load_trip_rows_for_scope as load_tokyu_bus_trip_rows_for_scope,
    tokyu_bus_data_ready,
)
from src.tokyu_shard_loader import (
    load_dispatch_trip_rows_for_scope,
    load_trip_rows_for_scope as load_trip_rows_for_scope_from_shard,
    shard_runtime_ready,
)

router = APIRouter(tags=["graph"])
_MAX_PAGE_LIMIT = 500


# ── Pydantic models ────────────────────────────────────────────


class BuildTripsBody(BaseModel):
    force: bool = False
    service_id: Optional[str] = None  # filter timetable rows by service_id
    depot_id: Optional[str] = None


class BuildGraphBody(BaseModel):
    force: bool = False
    service_id: Optional[str] = None  # filter timetable rows by service_id
    depot_id: Optional[str] = None


class GenerateDutiesBody(BaseModel):
    vehicle_type: Optional[str] = None
    strategy: str = "greedy"
    service_id: Optional[str] = None  # filter timetable rows by service_id
    depot_id: Optional[str] = None


class BuildBlocksBody(BaseModel):
    vehicle_type: Optional[str] = None
    strategy: str = "greedy"
    service_id: Optional[str] = None
    depot_id: Optional[str] = None


class BuildDispatchPlanBody(BaseModel):
    vehicle_type: Optional[str] = None
    strategy: str = "greedy"
    service_id: Optional[str] = None
    depot_id: Optional[str] = None


class ExportSubsetBody(BaseModel):
    service_id: Optional[str] = None
    depot_id: Optional[str] = None
    save: bool = True


# ── Helpers ────────────────────────────────────────────────────


def _not_found(scenario_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")


def _require_scenario(scenario_id: str) -> None:
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    except RuntimeError as e:
        if "artifacts are incomplete" in str(e):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "INCOMPLETE_ARTIFACT",
                    "message": str(e)
                }
            )
        raise


def _resolve_dispatch_scope(
    scenario_id: str,
    *,
    service_id: Optional[str] = None,
    depot_id: Optional[str] = None,
    persist: bool = False,
) -> Dict[str, Any]:
    current = store.get_dispatch_scope(scenario_id)
    scope: Dict[str, Any] = {}
    if service_id is not None:
        scope["serviceId"] = service_id
    if depot_id is not None:
        scope["depotId"] = depot_id
    if not scope:
        return current
    if persist:
        return store.set_dispatch_scope(scenario_id, scope)
    merged = dict(current)
    merged.update(scope)
    doc = store.get_scenario_document_shallow(scenario_id)
    doc["dispatch_scope"] = merged
    return store._normalize_dispatch_scope(doc)


def _subset_export_dir(scenario_id: str) -> Path:
    return output_paths.outputs_root() / "subset_exports" / scenario_id


def _effective_scope_routes(scenario_id: str, scope: Dict[str, Any]) -> List[Dict[str, Any]]:
    route_ids = {
        str(route_id)
        for route_id in scope.get("effectiveRouteIds") or []
        if route_id is not None
    }
    routes = store.list_routes(scenario_id)
    if route_ids:
        routes = [route for route in routes if str(route.get("id") or "") in route_ids]
    return reclassify_routes_for_runtime([dict(route) for route in routes])


def _route_family_subset_summary(routes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    families = build_route_family_summary(routes)
    members_by_family: Dict[str, List[Dict[str, Any]]] = {}
    for route in routes:
        family_id = str(route.get("routeFamilyId") or "")
        if not family_id:
            continue
        members_by_family.setdefault(family_id, []).append(route)

    payload: List[Dict[str, Any]] = []
    for family in families:
        family_id = str(family.get("routeFamilyId") or "")
        members = members_by_family.get(family_id, [])
        payload.append(
            {
                **family,
                "routeIds": [str(route.get("id") or "") for route in members],
                "routeNames": [str(route.get("name") or "") for route in members],
            }
        )
    return payload


def _build_scope_subset_export(
    scenario_id: str,
    scope: Dict[str, Any],
) -> Dict[str, Any]:
    depot_id = str(scope.get("depotId") or "")
    service_id = str(scope.get("serviceId") or "WEEKDAY")
    if not depot_id:
        raise ValueError("No depot selected. Configure dispatch scope first.")

    scenario = store._load(scenario_id)
    timetable_rows = _filter_rows_for_scope(
        scenario,
        depot_id=depot_id,
        service_id=service_id,
        analysis_scope=scope,
    )
    dispatch_trips = _collect_trips_for_scope(
        scenario,
        depot_id=depot_id,
        service_id=service_id,
        analysis_scope=scope,
    )
    routes = _effective_scope_routes(scenario_id, scope)
    route_families = _route_family_subset_summary(routes)

    selected_depot_ids = {
        str(depot_key)
        for depot_key in (scope.get("depotSelection") or {}).get("depotIds") or []
        if depot_key is not None
    }
    if depot_id:
        selected_depot_ids.add(depot_id)
    depots = [
        depot
        for depot in store.list_depots(scenario_id)
        if str(depot.get("id") or "") in selected_depot_ids
    ]
    vehicles = [
        vehicle
        for vehicle in store.list_vehicles(scenario_id)
        if str(vehicle.get("depotId") or "") == depot_id
    ]

    trip_ids = [str(item.get("trip_id") or "") for item in dispatch_trips if item.get("trip_id")]
    route_ids = [str(route.get("id") or "") for route in routes if route.get("id")]
    route_family_ids = [
        str(family.get("routeFamilyId") or "")
        for family in route_families
        if family.get("routeFamilyId")
    ]

    return {
        "scenarioId": scenario_id,
        "feedContext": (store.get_scenario(scenario_id) or {}).get("feedContext"),
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "scope": scope,
        "summary": {
            "selectedDepotCount": len(depots),
            "selectedRouteFamilyCount": len(route_family_ids),
            "selectedRouteCount": len(route_ids),
            "timetableRowCount": len(timetable_rows),
            "dispatchTripCount": len(dispatch_trips),
            "vehicleCount": len(vehicles),
        },
        "depots": depots,
        "routeFamilies": route_families,
        "routes": routes,
        "timetableRows": timetable_rows,
        "dispatchTrips": dispatch_trips,
        "simulationInputPreview": {
            "primaryDepotId": depot_id,
            "serviceId": service_id,
            "routeFamilyIds": route_family_ids,
            "routeIds": route_ids,
            "tripIds": trip_ids,
            "vehicleIds": [str(vehicle.get("id") or "") for vehicle in vehicles if vehicle.get("id")],
        },
    }


def _allowed_vehicle_types_for_route(
    scenario_id: str,
    depot_id: str,
    route_id: str,
    vehicles: List[Dict[str, Any]],
    _permissions_cache: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Set[str]]:
    """
    Resolve which vehicle types at the selected depot may serve the route.

    If no vehicles exist at the depot, return None so timetable-side allowed types
    remain unchanged. If explicit vehicle-route permissions exist, they are honored;
    otherwise a vehicle defaults to allowed for that route.

    Pass _permissions_cache to avoid re-fetching permissions on every call when
    iterating over many trips.
    """
    if not vehicles:
        return None

    permissions = _permissions_cache if _permissions_cache is not None else store.get_vehicle_route_permissions(scenario_id)
    by_vehicle_route: Dict[Tuple[str, str], bool] = {
        (str(item.get("vehicleId")), str(item.get("routeId"))): bool(item.get("allowed"))
        for item in permissions
        if item.get("vehicleId") is not None and item.get("routeId") is not None
    }

    allowed_types: Set[str] = set()
    for vehicle in vehicles:
        vehicle_id = vehicle.get("id")
        if vehicle_id is None:
            continue
        route_allowed = by_vehicle_route.get((str(vehicle_id), str(route_id)), True)
        if route_allowed:
            allowed_types.add(str(vehicle.get("type") or "BEV"))
    return allowed_types


def _normalize_allowed_types(
    raw_allowed: Any,
    route_allowed_types: Optional[Set[str]],
) -> Tuple[str, ...]:
    allowed = tuple(str(item) for item in (raw_allowed or ["BEV", "ICE"]))
    if route_allowed_types is None:
        return allowed
    return tuple(item for item in allowed if item in route_allowed_types)


def _normalize_direction(value: Any, default: str = "outbound") -> str:
    return normalize_direction(value, default=default)


def _normalize_variant_type(value: Any, *, direction: str = "outbound") -> str:
    return normalize_variant_type(value, direction=direction)


def _build_turnaround_rules(
    scenario_id: str,
) -> Dict[str, TurnaroundRule]:
    rules: Dict[str, TurnaroundRule] = {}
    for item in store.get_turnaround_rules(scenario_id):
        stop_id = item.get("stop_id")
        if stop_id is None:
            continue
        rules[str(stop_id)] = TurnaroundRule(
            stop_id=str(stop_id),
            min_turnaround_min=max(0, int(item.get("min_turnaround_min") or 0)),
        )
    return rules


def _build_dispatch_context(
    scenario_id: str,
    service_id: Optional[str] = None,
    depot_id: Optional[str] = None,
) -> DispatchContext:
    """
    Build a DispatchContext from the scenario's timetable and stored trips.
    Uses timetable_rows if no trips have been built yet.
    If service_id is provided, only rows matching that service_id are used.

    When scope.allowInterDepotSwap=True, trips from all selected depots are
    merged into a single DispatchContext so the optimizer can assign vehicles
    from any depot to any route in the combined scope.
    """
    scenario_doc = store.get_scenario_document_shallow(scenario_id)
    simulation_cfg = dict(scenario_doc.get("simulation_config") or {})
    overlay_solver_cfg = dict(((scenario_doc.get("scenario_overlay") or {}).get("solver_config") or {}))
    try:
        deadhead_speed_kmh = float(
            simulation_cfg.get("deadhead_speed_kmh", overlay_solver_cfg.get("deadhead_speed_kmh"))
            or 18.0
        )
    except (TypeError, ValueError):
        deadhead_speed_kmh = 18.0

    scope = _resolve_dispatch_scope(
        scenario_id,
        service_id=service_id,
        depot_id=depot_id,
        persist=False,
    )
    depot_id = scope.get("depotId")
    service_id = scope.get("serviceId")
    allow_inter_depot_swap = bool(scope.get("allowInterDepotSwap", False))

    # When inter-depot swap is enabled, collect all selected depot IDs so
    # trips from every depot are loaded into the same context.
    if allow_inter_depot_swap:
        all_depot_ids: List[str] = [
            str(d) for d in ((scope.get("depotSelection") or {}).get("depotIds") or [])
            if str(d or "").strip()
        ]
        if depot_id and depot_id not in all_depot_ids:
            all_depot_ids.insert(0, depot_id)
        if not all_depot_ids and depot_id:
            all_depot_ids = [depot_id]
    else:
        all_depot_ids = [depot_id] if depot_id else []

    if not depot_id:
        raise ValueError("No depot selected. Configure dispatch scope first.")

    raw_trips = store.get_field(scenario_id, "trips") or []
    timetable_rows = store.get_field(scenario_id, "timetable_rows") or []
    effective_route_ids = set(store.effective_route_ids_for_scope(scenario_id, scope))
    trip_selection = dict(scope.get("tripSelection") or {})
    route_lookup = {
        str(route.get("id")): route for route in store.list_routes(scenario_id)
    }
    if not raw_trips or not timetable_rows:
        feed_context = dict(scenario_doc.get("feed_context") or {})
        overlay = dict(scenario_doc.get("scenario_overlay") or {})
        dataset_id = str(
            feed_context.get("datasetId")
            or overlay.get("dataset_id")
            or overlay.get("datasetId")
            or ""
        ).strip()
        if dataset_id and (tokyu_bus_data_ready(dataset_id) or shard_runtime_ready(dataset_id)):
            # Use all_depot_ids for inter-depot swap; single depot_id otherwise
            scoped_depot_ids = list(all_depot_ids)
            scoped_service_ids = list((scope.get("serviceSelection") or {}).get("serviceIds") or [])
            if service_id and service_id not in scoped_service_ids:
                scoped_service_ids.insert(0, service_id)
            scoped_route_ids = list(effective_route_ids)
            runtime_trip_rows = (
                load_tokyu_bus_trip_rows_for_scope(
                    dataset_id=dataset_id,
                    route_ids=scoped_route_ids,
                    depot_ids=scoped_depot_ids,
                    service_ids=scoped_service_ids,
                )
                if tokyu_bus_data_ready(dataset_id)
                else None
            )
            if not raw_trips:
                if runtime_trip_rows is not None:
                    raw_trips = [
                        {
                            "trip_id": row["trip_id"],
                            "route_id": row["route_id"],
                            "origin": row["origin"],
                            "destination": row["destination"],
                            "origin_stop_id": row.get("origin_stop_id"),
                            "destination_stop_id": row.get("destination_stop_id"),
                            "departure": row["departure"],
                            "arrival": row["arrival"],
                            "distance_km": row["distance_km"],
                            "allowed_vehicle_types": list(row.get("allowed_vehicle_types") or ["BEV", "ICE"]),
                            "direction": row["direction"],
                            "source": "tokyu_bus_data",
                        }
                        for row in runtime_trip_rows
                    ]
                else:
                    raw_trips = load_dispatch_trip_rows_for_scope(
                        dataset_id=dataset_id,
                        route_ids=scoped_route_ids,
                        depot_ids=scoped_depot_ids,
                        service_ids=scoped_service_ids,
                    )
            if not timetable_rows:
                timetable_rows = (
                    runtime_trip_rows
                    if runtime_trip_rows is not None
                    else load_trip_rows_for_scope_from_shard(
                        dataset_id=dataset_id,
                        route_ids=scoped_route_ids,
                        depot_ids=scoped_depot_ids,
                        service_ids=scoped_service_ids,
                    )
                )

    if service_id:
        timetable_rows = [r for r in timetable_rows if r.get("service_id", "WEEKDAY") == service_id]

    if effective_route_ids:
        timetable_rows = [row for row in timetable_rows if str(row.get("route_id")) in effective_route_ids]
        raw_trips = [trip for trip in raw_trips if str(trip.get("route_id")) in effective_route_ids]

    def _trip_allowed_by_variant(route_id: str) -> bool:
        route = route_lookup.get(route_id) or {}
        variant_type = _normalize_variant_type(
            effective_route_variant_type(route)
            or "unknown"
        )
        variant_bucket = route_variant_bucket(variant_type)
        if not trip_selection.get("includeShortTurn", True) and variant_bucket == "short_turn":
            return False
        if (
            not trip_selection.get("includeDepotMoves", True)
            and variant_bucket == "depot"
        ):
            return False
        return True

    timetable_rows = [
        row for row in timetable_rows if _trip_allowed_by_variant(str(row.get("route_id") or ""))
    ]
    raw_trips = [
        trip for trip in raw_trips if _trip_allowed_by_variant(str(trip.get("route_id") or ""))
    ]

    timetable_by_trip_id = {
        str(row.get("trip_id") or "").strip(): dict(row)
        for row in timetable_rows
        if str(row.get("trip_id") or "").strip()
    }
    merged_trip_rows: List[Dict[str, Any]] = []
    for item in raw_trips or timetable_rows:
        if not isinstance(item, dict):
            continue
        trip_id = str(item.get("trip_id") or "").strip()
        merged = dict(timetable_by_trip_id.get(trip_id) or {})
        merged.update(item)
        merged_trip_rows.append(merged)

    if not raw_trips and not timetable_rows:
        raise ValueError(
            "No timetable rows found for the selected depot and service. "
            "Import ODPT or GTFS timetable data, or adjust the depot route selection."
        )

    # When inter-depot swap is allowed, collect vehicles from all selected depots.
    # Otherwise only use vehicles from the primary depot.
    if allow_inter_depot_swap and len(all_depot_ids) > 1:
        vehicles: List[Dict[str, Any]] = []
        for did in all_depot_ids:
            vehicles.extend(store.list_vehicles(scenario_id, depot_id=did))
    else:
        vehicles = store.list_vehicles(scenario_id, depot_id=depot_id)

    # Convert raw trips to Trip objects
    trips: List[Trip] = []

    if raw_trips:
        # Cache permissions once outside the loop — calling get_vehicle_route_permissions
        # per trip previously triggered a full _load() on every iteration.
        _permissions_cache = store.get_vehicle_route_permissions(scenario_id)
        for td in (merged_trip_rows or raw_trips):
            route_id = str(td["route_id"])
            route_like = route_lookup.get(route_id) or {}
            route_series_code, _route_series_prefix, _route_series_number, _series_source = extract_route_series_from_candidates(
                str(route_like.get("routeCode") or ""),
                str(route_like.get("routeFamilyCode") or ""),
                str(route_like.get("routeLabel") or route_like.get("name") or ""),
            )
            route_family_code = str(
                td.get("routeFamilyCode")
                or td.get("route_family_code")
                or td.get("routeSeriesCode")
                or td.get("route_series_code")
                or route_like.get("routeFamilyCode")
                or route_series_code
                or route_id
            )
            route_allowed_types = _allowed_vehicle_types_for_route(
                scenario_id,
                depot_id,
                route_id,
                vehicles,
                _permissions_cache=_permissions_cache,
            )
            # Preserve direction and variant type from the stored trip dict
            # so the greedy dispatcher can prefer return-leg connections.
            direction = _normalize_direction(
                td.get("direction")
                or td.get("canonicalDirection")
                or td.get("canonicalDirectionManual")
                or effective_route_direction(route_like, default="outbound")
                or "outbound"
            )
            variant = _normalize_variant_type(
                td.get("routeVariantTypeManual")
                or effective_route_variant_type(route_like)
                or td.get("routeVariantType")
                or td.get("route_variant_type")
                or "unknown",
                direction=direction,
            )
            trips.append(dict_to_trip(td))
            trips[-1] = Trip(
                trip_id=trips[-1].trip_id,
                route_id=trips[-1].route_id,
                origin=trips[-1].origin,
                destination=trips[-1].destination,
                departure_time=trips[-1].departure_time,
                arrival_time=trips[-1].arrival_time,
                distance_km=trips[-1].distance_km,
                allowed_vehicle_types=_normalize_allowed_types(
                    td.get("allowed_vehicle_types"),
                    route_allowed_types,
                ),
                origin_stop_id=str(td.get("origin_stop_id") or ""),
                destination_stop_id=str(td.get("destination_stop_id") or ""),
                route_family_code=route_family_code,
                direction=direction,
                route_variant_type=variant,
            )
    else:
        # Build trips from timetable rows
        _permissions_cache = store.get_vehicle_route_permissions(scenario_id)
        for i, row in enumerate(timetable_rows):
            route_id = str(row["route_id"])
            route_like = route_lookup.get(route_id) or {}
            route_series_code, _route_series_prefix, _route_series_number, _series_source = extract_route_series_from_candidates(
                str(route_like.get("routeCode") or ""),
                str(route_like.get("routeFamilyCode") or ""),
                str(route_like.get("routeLabel") or route_like.get("name") or ""),
            )
            route_family_code = str(
                row.get("routeFamilyCode")
                or row.get("route_family_code")
                or row.get("routeSeriesCode")
                or row.get("route_series_code")
                or route_like.get("routeFamilyCode")
                or route_series_code
                or route_id
            )
            trip_id = str(
                row.get("trip_id")
                or f"trip_{row['route_id']}_{row.get('direction', 'out')}_{i:03d}"
            )
            route_allowed_types = _allowed_vehicle_types_for_route(
                scenario_id,
                depot_id,
                route_id,
                vehicles,
                _permissions_cache=_permissions_cache,
            )
            direction = _normalize_direction(
                row.get("direction")
                or row.get("canonicalDirection")
                or row.get("canonicalDirectionManual")
                or effective_route_direction(route_like, default="outbound")
                or "outbound"
            )
            variant = _normalize_variant_type(
                row.get("routeVariantTypeManual")
                or effective_route_variant_type(route_like)
                or row.get("routeVariantType")
                or row.get("route_variant_type")
                or "unknown",
                direction=direction,
            )
            trips.append(
                Trip(
                    trip_id=trip_id,
                    route_id=route_id,
                    origin=row["origin"],
                    destination=row["destination"],
                    departure_time=row["departure"],
                    arrival_time=row["arrival"],
                    distance_km=float(row.get("distance_km", 0.0)),
                    allowed_vehicle_types=_normalize_allowed_types(
                        row.get("allowed_vehicle_types"),
                        route_allowed_types,
                    ),
                    origin_stop_id=str(row.get("origin_stop_id") or ""),
                    destination_stop_id=str(row.get("destination_stop_id") or ""),
                    route_family_code=route_family_code,
                    direction=direction,
                    route_variant_type=variant,
                )
            )

    # Build turnaround and deadhead rules from scenario.
    turnaround_rules = _build_turnaround_rules(scenario_id)
    deadhead_metrics = merge_deadhead_metrics(
        existing_rules=store.get_deadhead_rules(scenario_id),
        trip_rows=merged_trip_rows or timetable_rows or raw_trips,
        routes=list(route_lookup.values()),
        stops=store.get_field(scenario_id, "stops") or [],
        assumed_speed_kmh=deadhead_speed_kmh,
    )
    deadhead_rules = {
        key: DeadheadRule(
            from_stop=metric.from_stop,
            to_stop=metric.to_stop,
            travel_time_min=max(0, int(metric.travel_time_min)),
        )
        for key, metric in deadhead_metrics.items()
    }

    # Build vehicle profiles from scenario vehicles
    vehicle_profiles: Dict[str, VehicleProfile] = {}
    seen_types = set()
    for v in vehicles:
        vt = v.get("type", "BEV")
        if vt not in seen_types:
            seen_types.add(vt)
            vehicle_profiles[vt] = VehicleProfile(
                vehicle_type=vt,
                battery_capacity_kwh=v.get("batteryKwh"),
                energy_consumption_kwh_per_km=v.get("energyConsumption"),
                fuel_tank_capacity_l=v.get("fuelTankL"),
            )

    # Default profiles if no vehicles defined
    if not vehicle_profiles:
        vehicle_profiles = {
            "BEV": VehicleProfile(vehicle_type="BEV"),
            "ICE": VehicleProfile(vehicle_type="ICE"),
        }

    return DispatchContext(
        service_date="2026-01-01",
        trips=trips,
        turnaround_rules=turnaround_rules,
        deadhead_rules=deadhead_rules,
        vehicle_profiles=vehicle_profiles,
        allow_intra_depot_swap=bool(scope.get("allowIntraDepotRouteSwap", False)),
        allow_inter_depot_swap=bool(scope.get("allowInterDepotSwap", False)),
    )


def _build_trips_payload(
    scenario_id: str,
    service_id: Optional[str] = None,
    depot_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    context = _build_dispatch_context(scenario_id, service_id, depot_id)
    return [trip_to_dict(t) for t in context.trips]


def _build_graph_payload(
    scenario_id: str,
    service_id: Optional[str] = None,
    depot_id: Optional[str] = None,
) -> Dict[str, Any]:
    context = _build_dispatch_context(scenario_id, service_id, depot_id)
    builder = ConnectionGraphBuilder()

    combined_graph: Dict[str, Any] = {
        "trips": [trip_to_dict(t) for t in context.trips],
        "arcs": [],
        "total_arcs": 0,
        "feasible_arcs": 0,
        "infeasible_arcs": 0,
        "reason_counts": {},
    }

    for vt in list(context.vehicle_profiles.keys()):
        analyzed_arcs = builder.analyze(context, vt)
        partial = build_graph_response(context.trips, analyzed_arcs)
        combined_graph["arcs"].extend(partial["arcs"])
        combined_graph["feasible_arcs"] += partial["feasible_arcs"]
        combined_graph["infeasible_arcs"] += partial["infeasible_arcs"]
        combined_graph["total_arcs"] += partial["total_arcs"]
        for reason_code, count in partial["reason_counts"].items():
            combined_graph["reason_counts"][reason_code] = (
                combined_graph["reason_counts"].get(reason_code, 0) + count
            )

    return combined_graph


def _build_duties_payload(
    scenario_id: str,
    vehicle_type: Optional[str],
    strategy: str,
    service_id: Optional[str] = None,
    depot_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    # strategy is reserved for future dispatch variants; greedy is the current baseline.
    _ = strategy
    context = _build_dispatch_context(scenario_id, service_id, depot_id)
    pipeline = TimetableDispatchPipeline()
    vehicle_types = (
        [vehicle_type] if vehicle_type else list(context.vehicle_profiles.keys())
    )

    all_duties_json: List[Dict[str, Any]] = []
    for vt in vehicle_types:
        result = pipeline.run(context, vt)
        for duty in result.duties:
            all_duties_json.append(vehicle_duty_to_dict(duty))
    return all_duties_json


def _build_blocks_payload(
    scenario_id: str,
    vehicle_type: Optional[str],
    strategy: str,
    service_id: Optional[str] = None,
    depot_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    _ = strategy
    from src.dispatch.dispatcher import DispatchGenerator

    context = _build_dispatch_context(scenario_id, service_id, depot_id)
    generator = DispatchGenerator()
    vehicle_types = [vehicle_type] if vehicle_type else list(context.vehicle_profiles.keys())

    items: List[Dict[str, Any]] = []
    for vt in vehicle_types:
        blocks = generator.generate_greedy_blocks(context, vt)
        for block in blocks:
            items.append(
                {
                    "block_id": block.block_id,
                    "vehicle_type": block.vehicle_type,
                    "trip_ids": list(block.trip_ids),
                }
            )
    return items


def _build_dispatch_plan_payload(
    scenario_id: str,
    vehicle_type: Optional[str],
    strategy: str,
    service_id: Optional[str] = None,
    depot_id: Optional[str] = None,
) -> Dict[str, Any]:
    _ = strategy
    from src.dispatch.dispatcher import DispatchGenerator

    context = _build_dispatch_context(scenario_id, service_id, depot_id)
    generator = DispatchGenerator()
    vehicle_types = [vehicle_type] if vehicle_type else list(context.vehicle_profiles.keys())

    plans: List[Dict[str, Any]] = []
    total_blocks = 0
    total_duties = 0
    for vt in vehicle_types:
        plan = generator.generate_greedy_plan(context, vt)
        total_blocks += len(plan.vehicle_blocks)
        total_duties += len(plan.duties)
        plans.append(
            {
                "plan_id": plan.plan_id,
                "vehicle_type": vt,
                "blocks": [
                    {
                        "block_id": block.block_id,
                        "vehicle_type": block.vehicle_type,
                        "trip_ids": list(block.trip_ids),
                    }
                    for block in plan.vehicle_blocks
                ],
                "duties": [vehicle_duty_to_dict(duty) for duty in plan.duties],
                "charging_plan": list(plan.charging_plan),
            }
        )

    return {
        "plans": plans,
        "total_plans": len(plans),
        "total_blocks": total_blocks,
        "total_duties": total_duties,
    }


def _job_metadata(
    *,
    scenario_id: str,
    service_id: Optional[str],
    depot_id: Optional[str],
    stage: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "service_id": service_id,
        "depot_id": depot_id,
        "stage": stage,
        **(extra or {}),
    }


def _paginate_items(
    items: List[Dict[str, Any]],
    limit: Optional[int],
    offset: int,
) -> Tuple[List[Dict[str, Any]], Optional[int]]:
    if limit is None:
        return items, None
    return items[offset : offset + limit], limit


def _build_trips_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    route_counts: Dict[str, int] = {}
    earliest_departure: Optional[str] = None
    latest_arrival: Optional[str] = None
    for item in items:
        route_id = str(item.get("route_id") or "")
        if route_id:
            route_counts[route_id] = route_counts.get(route_id, 0) + 1
        departure = item.get("departure")
        arrival = item.get("arrival")
        if isinstance(departure, str) and departure:
            earliest_departure = (
                departure
                if earliest_departure is None or departure < earliest_departure
                else earliest_departure
            )
        if isinstance(arrival, str) and arrival:
            latest_arrival = (
                arrival if latest_arrival is None or arrival > latest_arrival else latest_arrival
            )

    by_route = [
        {"route_id": route_id, "trip_count": count}
        for route_id, count in sorted(route_counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]
    return {
        "totalTrips": len(items),
        "routeCount": len(route_counts),
        "firstDeparture": earliest_departure,
        "lastArrival": latest_arrival,
        "byRoute": by_route[:50],
    }


def _build_graph_summary(graph: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "totalTrips": len(graph.get("trips") or []),
        "totalArcs": int(graph.get("total_arcs") or 0),
        "feasibleArcs": int(graph.get("feasible_arcs") or 0),
        "infeasibleArcs": int(graph.get("infeasible_arcs") or 0),
        "reasonCounts": dict(graph.get("reason_counts") or {}),
    }


def _build_duties_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    vehicle_type_counts: Dict[str, int] = {}
    total_legs = 0
    total_distance_km = 0.0
    for item in items:
        vehicle_type = str(item.get("vehicle_type") or "unknown")
        vehicle_type_counts[vehicle_type] = vehicle_type_counts.get(vehicle_type, 0) + 1
        total_legs += len(item.get("legs") or [])
        total_distance_km += float(item.get("total_distance_km") or 0.0)
    return {
        "totalDuties": len(items),
        "totalLegs": total_legs,
        "averageLegsPerDuty": round(total_legs / len(items), 2) if items else 0.0,
        "totalDistanceKm": round(total_distance_km, 3),
        "vehicleTypeCounts": vehicle_type_counts,
    }


# ── Background task implementations ───────────────────────────


def _run_build_trips(
    scenario_id: str,
    job_id: str,
    service_id: Optional[str] = None,
    depot_id: Optional[str] = None,
) -> None:
    try:
        job_store.update_job(
            job_id,
            status="running",
            progress=10,
            message="Building trips from timetable...",
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="build_trips",
            ),
        )
        trips_json = _build_trips_payload(scenario_id, service_id, depot_id)
        store.set_field(scenario_id, "trips", trips_json)
        store.update_scenario(scenario_id, status="trips_built")
        job_store.update_job(
            job_id,
            status="completed",
            progress=100,
            message=f"Built {len(trips_json)} trips.",
            result_key="trips",
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="completed",
                extra={"trip_count": len(trips_json)},
            ),
        )
    except Exception as e:
        job_store.update_job(
            job_id,
            status="failed",
            message="Build trips failed.",
            error=traceback.format_exc(),
        )


def _run_build_graph(
    scenario_id: str,
    job_id: str,
    service_id: Optional[str] = None,
    depot_id: Optional[str] = None,
) -> None:
    try:
        job_store.update_job(
            job_id,
            status="running",
            progress=10,
            message="Building feasibility graph...",
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="build_graph",
            ),
        )
        combined_graph = _build_graph_payload(scenario_id, service_id, depot_id)
        store.set_field(scenario_id, "graph", combined_graph)
        store.update_scenario(scenario_id, status="graph_built")
        job_store.update_job(
            job_id,
            status="completed",
            progress=100,
            message=f"Graph built: {combined_graph['feasible_arcs']} feasible arcs.",
            result_key="graph",
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="completed",
                extra={
                    "total_arcs": combined_graph["total_arcs"],
                    "feasible_arcs": combined_graph["feasible_arcs"],
                },
            ),
        )
    except Exception as e:
        job_store.update_job(
            job_id,
            status="failed",
            message="Build graph failed.",
            error=traceback.format_exc(),
        )


def _run_generate_duties(
    scenario_id: str,
    job_id: str,
    vehicle_type: Optional[str],
    strategy: str,
    service_id: Optional[str] = None,
    depot_id: Optional[str] = None,
) -> None:
    try:
        job_store.update_job(
            job_id,
            status="running",
            progress=10,
            message="Generating duties...",
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="generate_duties",
            ),
        )
        all_duties_json = _build_duties_payload(
            scenario_id,
            vehicle_type,
            strategy,
            service_id,
            depot_id,
        )
        store.set_field(scenario_id, "duties", all_duties_json)
        store.update_scenario(scenario_id, status="duties_generated")
        job_store.update_job(
            job_id,
            status="completed",
            progress=100,
            message=f"Generated {len(all_duties_json)} duties.",
            result_key="duties",
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="completed",
                extra={"duty_count": len(all_duties_json)},
            ),
        )
    except Exception as e:
        job_store.update_job(
            job_id,
            status="failed",
            message="Generate duties failed.",
            error=traceback.format_exc(),
        )


def _run_build_blocks(
    scenario_id: str,
    job_id: str,
    vehicle_type: Optional[str],
    strategy: str,
    service_id: Optional[str] = None,
    depot_id: Optional[str] = None,
) -> None:
    try:
        job_store.update_job(
            job_id,
            status="running",
            progress=10,
            message="Building vehicle blocks...",
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="build_blocks",
            ),
        )
        blocks_json = _build_blocks_payload(
            scenario_id,
            vehicle_type,
            strategy,
            service_id,
            depot_id,
        )
        store.set_field(scenario_id, "blocks", blocks_json)
        job_store.update_job(
            job_id,
            status="completed",
            progress=100,
            message=f"Built {len(blocks_json)} blocks.",
            result_key="blocks",
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="completed",
                extra={"block_count": len(blocks_json)},
            ),
        )
    except Exception:
        job_store.update_job(
            job_id,
            status="failed",
            message="Build blocks failed.",
            error=traceback.format_exc(),
        )


def _run_build_dispatch_plan(
    scenario_id: str,
    job_id: str,
    vehicle_type: Optional[str],
    strategy: str,
    service_id: Optional[str] = None,
    depot_id: Optional[str] = None,
) -> None:
    try:
        job_store.update_job(
            job_id,
            status="running",
            progress=10,
            message="Building dispatch plan...",
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="build_dispatch_plan",
            ),
        )
        plan_json = _build_dispatch_plan_payload(
            scenario_id,
            vehicle_type,
            strategy,
            service_id,
            depot_id,
        )
        store.set_field(scenario_id, "dispatch_plan", plan_json)
        store.set_field(
            scenario_id,
            "blocks",
            [
                block
                for plan in plan_json["plans"]
                for block in plan.get("blocks", [])
            ],
        )
        store.set_field(
            scenario_id,
            "duties",
            [
                duty
                for plan in plan_json["plans"]
                for duty in plan.get("duties", [])
            ],
        )
        store.update_scenario(scenario_id, status="duties_generated")
        job_store.update_job(
            job_id,
            status="completed",
            progress=100,
            message=(
                f"Built {plan_json['total_blocks']} blocks and "
                f"{plan_json['total_duties']} duties."
            ),
            result_key="dispatch_plan",
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="completed",
                extra={
                    "total_blocks": plan_json["total_blocks"],
                    "total_duties": plan_json["total_duties"],
                },
            ),
        )
    except Exception:
        job_store.update_job(
            job_id,
            status="failed",
            message="Build dispatch plan failed.",
            error=traceback.format_exc(),
        )


# ── Trips endpoints ────────────────────────────────────────────


@router.get("/scenarios/{scenario_id}/trips")
def get_trips(
    scenario_id: str,
    limit: Optional[int] = Query(
        default=None,
        ge=1,
        le=_MAX_PAGE_LIMIT,
        description="Optional page size. Omit to return all trips.",
    ),
    offset: int = Query(default=0, ge=0),
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    if limit is None:
        items = store.get_field(scenario_id, "trips") or []
        page_limit = len(items)
        total = len(items)
        paged_items = items[offset:]
    else:
        paged_items = store.page_field_rows(scenario_id, "trips", offset=offset, limit=limit)
        page_limit = limit
        total = store.count_field_rows(scenario_id, "trips")
    return {"items": paged_items, "total": total, "limit": page_limit, "offset": offset}


@router.get("/scenarios/{scenario_id}/trips/summary")
def get_trips_summary(scenario_id: str) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    summary = store.get_field_summary(scenario_id, "trips")
    if summary is not None:
        return {"item": summary}
    items = store.get_field(scenario_id, "trips") or []
    return {"item": _build_trips_summary(items)}


@router.post("/scenarios/{scenario_id}/subset-export")
def export_subset(
    scenario_id: str,
    body: Optional[ExportSubsetBody] = None,
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    scope = _resolve_dispatch_scope(
        scenario_id,
        service_id=body.service_id if body else None,
        depot_id=body.depot_id if body else None,
        persist=True,
    )
    try:
        payload = _build_scope_subset_export(scenario_id, scope)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    saved_to = None
    if body is None or body.save:
        export_dir = _subset_export_dir(scenario_id)
        export_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        suffix = f"{scope.get('depotId') or 'no-depot'}_{scope.get('serviceId') or 'WEEKDAY'}"
        out_path = export_dir / f"subset_{suffix}_{timestamp}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        saved_to = str(out_path)

    return {"item": payload, "savedTo": saved_to}


@router.post("/scenarios/{scenario_id}/build-trips")
def build_trips(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[BuildTripsBody] = None,
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    scope = _resolve_dispatch_scope(
        scenario_id,
        service_id=body.service_id if body else None,
        depot_id=body.depot_id if body else None,
        persist=True,
    )
    job = job_store.create_job()
    background_tasks.add_task(
        _run_build_trips,
        scenario_id,
        job.job_id,
        scope.get("serviceId"),
        scope.get("depotId"),
    )
    return job_store.job_to_dict(job)


# ── Graph endpoints ────────────────────────────────────────────


@router.get("/scenarios/{scenario_id}/graph")
def get_graph(
    scenario_id: str,
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    graph = store.get_field(scenario_id, "graph")
    if graph is None:
        raise HTTPException(
            status_code=404,
            detail="Graph has not been built yet. POST to /build-graph first.",
        )
    return graph


@router.get("/scenarios/{scenario_id}/graph/summary")
def get_graph_summary(
    scenario_id: str,
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    graph = store.get_graph_meta(scenario_id)
    if graph is None:
        raise HTTPException(
            status_code=404,
            detail="Graph has not been built yet. POST to /build-graph first.",
        )
    return {"item": _build_graph_summary(graph)}


@router.get("/scenarios/{scenario_id}/graph/arcs")
def get_graph_arcs(
    scenario_id: str,
    reason_code: Optional[str] = Query(default=None),
    limit: Optional[int] = Query(
        default=None,
        ge=1,
        le=_MAX_PAGE_LIMIT,
        description="Optional page size. Omit to return all arcs.",
    ),
    offset: int = Query(default=0, ge=0),
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    graph = store.get_graph_meta(scenario_id)
    if graph is None:
        raise HTTPException(
            status_code=404,
            detail="Graph has not been built yet. POST to /build-graph first.",
        )
    if limit is None:
        arcs = store.page_graph_arcs(scenario_id, offset=offset, limit=None, reason_code=reason_code)
        page_limit = None
        total = store.count_graph_arcs(scenario_id, reason_code=reason_code)
    else:
        arcs = store.page_graph_arcs(scenario_id, offset=offset, limit=limit, reason_code=reason_code)
        page_limit = limit
        total = store.count_graph_arcs(scenario_id, reason_code=reason_code)
    return {"items": arcs, "total": total, "limit": page_limit, "offset": offset}


@router.post("/scenarios/{scenario_id}/build-graph")
def build_graph(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[BuildGraphBody] = None,
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    scope = _resolve_dispatch_scope(
        scenario_id,
        service_id=body.service_id if body else None,
        depot_id=body.depot_id if body else None,
        persist=True,
    )
    job = job_store.create_job()
    background_tasks.add_task(
        _run_build_graph,
        scenario_id,
        job.job_id,
        scope.get("serviceId"),
        scope.get("depotId"),
    )
    return job_store.job_to_dict(job)


# ── Duties endpoints ───────────────────────────────────────────


@router.get("/scenarios/{scenario_id}/duties")
def get_duties(
    scenario_id: str,
    limit: Optional[int] = Query(
        default=None,
        ge=1,
        le=_MAX_PAGE_LIMIT,
        description="Optional page size. Omit to return all duties.",
    ),
    offset: int = Query(default=0, ge=0),
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    if limit is None:
        items = store.get_field(scenario_id, "duties") or []
        page_limit = len(items)
        total = len(items)
        paged_items = items[offset:]
    else:
        paged_items = store.page_field_rows(scenario_id, "duties", offset=offset, limit=limit)
        page_limit = limit
        total = store.count_field_rows(scenario_id, "duties")
    return {"items": paged_items, "total": total, "limit": page_limit, "offset": offset}


@router.get("/scenarios/{scenario_id}/duties/summary")
def get_duties_summary(
    scenario_id: str,
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    summary = store.get_field_summary(scenario_id, "duties")
    if summary is not None:
        return {"item": summary}
    items = store.get_field(scenario_id, "duties") or []
    return {"item": _build_duties_summary(items)}


@router.get("/scenarios/{scenario_id}/blocks")
def get_blocks(
    scenario_id: str,
    limit: Optional[int] = Query(
        default=None,
        ge=1,
        le=_MAX_PAGE_LIMIT,
        description="Optional page size. Omit to return all blocks.",
    ),
    offset: int = Query(default=0, ge=0),
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    if limit is None:
        items = store.get_field(scenario_id, "blocks") or []
        page_limit = len(items)
        total = len(items)
        paged_items = items[offset:]
    else:
        paged_items = store.page_field_rows(scenario_id, "blocks", offset=offset, limit=limit)
        page_limit = limit
        total = store.count_field_rows(scenario_id, "blocks")
    return {"items": paged_items, "total": total, "limit": page_limit, "offset": offset}


@router.get("/scenarios/{scenario_id}/dispatch-plan")
def get_dispatch_plan(
    scenario_id: str,
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    plan = store.get_field(scenario_id, "dispatch_plan")
    if plan is None:
        raise HTTPException(
            status_code=404,
            detail="Dispatch plan has not been built yet. POST to /build-dispatch-plan first.",
        )
    return plan


@router.post("/scenarios/{scenario_id}/build-blocks")
def build_blocks(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[BuildBlocksBody] = None,
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    vt = body.vehicle_type if body else None
    strategy = body.strategy if body else "greedy"
    scope = _resolve_dispatch_scope(
        scenario_id,
        service_id=body.service_id if body else None,
        depot_id=body.depot_id if body else None,
        persist=True,
    )
    job = job_store.create_job()
    background_tasks.add_task(
        _run_build_blocks,
        scenario_id,
        job.job_id,
        vt,
        strategy,
        scope.get("serviceId"),
        scope.get("depotId"),
    )
    return job_store.job_to_dict(job)


@router.post("/scenarios/{scenario_id}/build-dispatch-plan")
def build_dispatch_plan(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[BuildDispatchPlanBody] = None,
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    vt = body.vehicle_type if body else None
    strategy = body.strategy if body else "greedy"
    scope = _resolve_dispatch_scope(
        scenario_id,
        service_id=body.service_id if body else None,
        depot_id=body.depot_id if body else None,
        persist=True,
    )
    job = job_store.create_job()
    background_tasks.add_task(
        _run_build_dispatch_plan,
        scenario_id,
        job.job_id,
        vt,
        strategy,
        scope.get("serviceId"),
        scope.get("depotId"),
    )
    return job_store.job_to_dict(job)


@router.post("/scenarios/{scenario_id}/generate-duties")
def generate_duties(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[GenerateDutiesBody] = None,
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    vt = body.vehicle_type if body else None
    strategy = body.strategy if body else "greedy"
    scope = _resolve_dispatch_scope(
        scenario_id,
        service_id=body.service_id if body else None,
        depot_id=body.depot_id if body else None,
        persist=True,
    )
    job = job_store.create_job()
    background_tasks.add_task(
        _run_generate_duties,
        scenario_id,
        job.job_id,
        vt,
        strategy,
        scope.get("serviceId"),
        scope.get("depotId"),
    )
    return job_store.job_to_dict(job)


@router.get("/scenarios/{scenario_id}/duties/validate")
def validate_duties(
    scenario_id: str,
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    from src.dispatch.validator import DutyValidator
    from bff.mappers.dispatch_mappers import dict_to_trip
    from src.dispatch.models import DutyLeg as PyDutyLeg, VehicleDuty as PyVehicleDuty

    duties_raw = store.get_field(scenario_id, "duties") or []
    if not duties_raw:
        return {"items": [], "total": 0}

    scope = _resolve_dispatch_scope(scenario_id)
    context = _build_dispatch_context(
        scenario_id,
        scope.get("serviceId"),
        scope.get("depotId"),
    )
    validator = DutyValidator()

    results = []
    for d in duties_raw:
        legs = []
        for leg in d.get("legs", []):
            trip = dict_to_trip(leg["trip"])
            legs.append(
                PyDutyLeg(
                    trip=trip, deadhead_from_prev_min=leg.get("deadhead_time_min", 0)
                )
            )
        duty = PyVehicleDuty(
            duty_id=d["duty_id"],
            vehicle_type=d["vehicle_type"],
            legs=tuple(legs),
        )
        vr = validator.validate_vehicle_duty(duty, context)
        results.append(validation_result_to_dict(d["duty_id"], vr))

    return {"items": results, "total": len(results)}
