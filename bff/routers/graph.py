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

import traceback
from typing import Any, Dict, List, Optional, Set, Tuple

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel

from bff.mappers.dispatch_mappers import (
    build_graph_response,
    dict_to_trip,
    trip_to_dict,
    vehicle_duty_to_dict,
    validation_result_to_dict,
)
from bff.store import job_store, scenario_store as store
from src.dispatch.graph_builder import ConnectionGraphBuilder
from src.dispatch.models import (
    DispatchContext,
    Trip,
    TurnaroundRule,
    DeadheadRule,
    VehicleProfile,
)
from src.dispatch.pipeline import TimetableDispatchPipeline

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


# ── Helpers ────────────────────────────────────────────────────


def _not_found(scenario_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")


def _require_scenario(scenario_id: str) -> None:
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)


def _allowed_route_ids_for_depot(scenario_id: str, depot_id: str) -> Optional[set[str]]:
    permissions = store.get_depot_route_permissions(scenario_id)
    matching_permissions = [
        permission
        for permission in permissions
        if permission.get("depotId") == depot_id
    ]
    if not matching_permissions:
        return None
    return {
        str(permission.get("routeId"))
        for permission in matching_permissions
        if permission.get("allowed") is True and permission.get("routeId") is not None
    }


def _resolve_dispatch_scope(
    scenario_id: str,
    *,
    service_id: Optional[str] = None,
    depot_id: Optional[str] = None,
    persist: bool = False,
) -> Dict[str, Any]:
    current = store.get_dispatch_scope(scenario_id)
    scope = {
        "serviceId": service_id or current.get("serviceId") or "WEEKDAY",
        "depotId": depot_id if depot_id is not None else current.get("depotId"),
    }
    if persist:
        return store.set_dispatch_scope(scenario_id, scope)
    return scope


def _allowed_vehicle_types_for_route(
    scenario_id: str,
    depot_id: str,
    route_id: str,
    vehicles: List[Dict[str, Any]],
) -> Optional[Set[str]]:
    """
    Resolve which vehicle types at the selected depot may serve the route.

    If no vehicles exist at the depot, return None so timetable-side allowed types
    remain unchanged. If explicit vehicle-route permissions exist, they are honored;
    otherwise a vehicle defaults to allowed for that route.
    """
    if not vehicles:
        return None

    permissions = store.get_vehicle_route_permissions(scenario_id)
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


def _build_deadhead_rules(
    scenario_id: str,
) -> Dict[Tuple[str, str], DeadheadRule]:
    rules: Dict[Tuple[str, str], DeadheadRule] = {}
    for item in store.get_deadhead_rules(scenario_id):
        from_stop = item.get("from_stop")
        to_stop = item.get("to_stop")
        if from_stop is None or to_stop is None:
            continue
        key = (str(from_stop), str(to_stop))
        rules[key] = DeadheadRule(
            from_stop=key[0],
            to_stop=key[1],
            travel_time_min=max(0, int(item.get("travel_time_min") or 0)),
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
    """
    if not depot_id:
        raise ValueError("No depot selected. Configure dispatch scope first.")

    raw_trips = store.get_field(scenario_id, "trips") or []
    timetable_rows = store.get_field(scenario_id, "timetable_rows") or []
    allowed_route_ids = _allowed_route_ids_for_depot(scenario_id, depot_id)

    # Filter by service_id when requested
    if service_id:
        timetable_rows = [
            r for r in timetable_rows if r.get("service_id", "WEEKDAY") == service_id
        ]

    if allowed_route_ids is not None:
        timetable_rows = [
            row for row in timetable_rows if row.get("route_id") in allowed_route_ids
        ]
        raw_trips = [
            trip for trip in raw_trips if trip.get("route_id") in allowed_route_ids
        ]

    if not raw_trips and not timetable_rows:
        raise ValueError(
            "No timetable rows found for the selected depot and service. "
            "Import ODPT or GTFS timetable data, or adjust the depot route selection."
        )

    vehicles = store.list_vehicles(scenario_id, depot_id=depot_id)

    # Convert raw trips to Trip objects
    trips: List[Trip] = []

    if raw_trips:
        for td in raw_trips:
            route_allowed_types = _allowed_vehicle_types_for_route(
                scenario_id,
                depot_id,
                str(td["route_id"]),
                vehicles,
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
            )
    else:
        # Build trips from timetable rows
        for i, row in enumerate(timetable_rows):
            trip_id = str(
                row.get("trip_id")
                or f"trip_{row['route_id']}_{row.get('direction', 'out')}_{i:03d}"
            )
            route_allowed_types = _allowed_vehicle_types_for_route(
                scenario_id,
                depot_id,
                str(row["route_id"]),
                vehicles,
            )
            trips.append(
                Trip(
                    trip_id=trip_id,
                    route_id=row["route_id"],
                    origin=row["origin"],
                    destination=row["destination"],
                    departure_time=row["departure"],
                    arrival_time=row["arrival"],
                    distance_km=float(row.get("distance_km", 0.0)),
                    allowed_vehicle_types=_normalize_allowed_types(
                        row.get("allowed_vehicle_types"),
                        route_allowed_types,
                    ),
                )
            )

    # Build turnaround and deadhead rules from scenario.
    turnaround_rules = _build_turnaround_rules(scenario_id)
    deadhead_rules = _build_deadhead_rules(scenario_id)

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
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    items = store.get_field(scenario_id, "trips") or []
    paged_items, page_limit = _paginate_items(items, limit, offset)
    return {"items": paged_items, "total": len(items), "limit": page_limit, "offset": offset}


@router.get("/scenarios/{scenario_id}/trips/summary")
def get_trips_summary(scenario_id: str) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    items = store.get_field(scenario_id, "trips") or []
    return {"item": _build_trips_summary(items)}


@router.post("/scenarios/{scenario_id}/build-trips")
def build_trips(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[BuildTripsBody] = None,
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
def get_graph(scenario_id: str) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    graph = store.get_field(scenario_id, "graph")
    if graph is None:
        raise HTTPException(
            status_code=404,
            detail="Graph has not been built yet. POST to /build-graph first.",
        )
    return graph


@router.get("/scenarios/{scenario_id}/graph/summary")
def get_graph_summary(scenario_id: str) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    graph = store.get_field(scenario_id, "graph")
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
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    graph = store.get_field(scenario_id, "graph")
    if graph is None:
        raise HTTPException(
            status_code=404,
            detail="Graph has not been built yet. POST to /build-graph first.",
        )
    arcs = list(graph.get("arcs") or [])
    if reason_code:
        arcs = [item for item in arcs if item.get("reason_code") == reason_code]
    paged_items, page_limit = _paginate_items(arcs, limit, offset)
    return {"items": paged_items, "total": len(arcs), "limit": page_limit, "offset": offset}


@router.post("/scenarios/{scenario_id}/build-graph")
def build_graph(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[BuildGraphBody] = None,
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
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    items = store.get_field(scenario_id, "duties") or []
    paged_items, page_limit = _paginate_items(items, limit, offset)
    return {"items": paged_items, "total": len(items), "limit": page_limit, "offset": offset}


@router.get("/scenarios/{scenario_id}/duties/summary")
def get_duties_summary(scenario_id: str) -> Dict[str, Any]:
    _require_scenario(scenario_id)
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
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    items = store.get_field(scenario_id, "blocks") or []
    paged_items, page_limit = _paginate_items(items, limit, offset)
    return {"items": paged_items, "total": len(items), "limit": page_limit, "offset": offset}


@router.get("/scenarios/{scenario_id}/dispatch-plan")
def get_dispatch_plan(scenario_id: str) -> Dict[str, Any]:
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
def validate_duties(scenario_id: str) -> Dict[str, Any]:
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
