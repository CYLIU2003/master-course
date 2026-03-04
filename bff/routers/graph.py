"""
bff/routers/graph.py

Dispatch pipeline endpoints: trips, graph, duties.

Routes:
  GET   /scenarios/{id}/trips                   → get built trips
  POST  /scenarios/{id}/build-trips             → async: build Trip list from timetable
  GET   /scenarios/{id}/graph                   → get built connection graph
  POST  /scenarios/{id}/build-graph             → async: build feasibility graph
  GET   /scenarios/{id}/duties                  → get generated duties
  POST  /scenarios/{id}/generate-duties         → async: generate duties
  GET   /scenarios/{id}/duties/validate         → validate duties

All POST operations return a JobResponse immediately and execute in a
BackgroundTask. Poll GET /jobs/{job_id} for status.
"""

from __future__ import annotations

import traceback
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
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


# ── Pydantic models ────────────────────────────────────────────


class BuildTripsBody(BaseModel):
    force: bool = False


class BuildGraphBody(BaseModel):
    force: bool = False


class GenerateDutiesBody(BaseModel):
    vehicle_type: Optional[str] = None
    strategy: str = "greedy"


# ── Helpers ────────────────────────────────────────────────────


def _not_found(scenario_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")


def _require_scenario(scenario_id: str) -> None:
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)


def _build_dispatch_context(scenario_id: str) -> DispatchContext:
    """
    Build a DispatchContext from the scenario's timetable and stored trips.
    Uses timetable_rows if no trips have been built yet.
    """
    raw_trips = store.get_field(scenario_id, "trips") or []
    timetable_rows = store.get_field(scenario_id, "timetable_rows") or []

    # Convert raw trips to Trip objects
    trips: List[Trip] = []

    if raw_trips:
        for td in raw_trips:
            trips.append(dict_to_trip(td))
    else:
        # Build trips from timetable rows
        for i, row in enumerate(timetable_rows):
            trip_id = f"trip_{row['route_id']}_{row.get('direction', 'out')}_{i:03d}"
            trips.append(
                Trip(
                    trip_id=trip_id,
                    route_id=row["route_id"],
                    origin=row["origin"],
                    destination=row["destination"],
                    departure_time=row["departure"],
                    arrival_time=row["arrival"],
                    distance_km=float(row.get("distance_km", 0.0)),
                    allowed_vehicle_types=tuple(
                        row.get("allowed_vehicle_types", ["BEV", "ICE"])
                    ),
                )
            )

    # Build turnaround and deadhead rules from scenario (empty for now)
    turnaround_rules: Dict[str, TurnaroundRule] = {}
    deadhead_rules: Dict = {}

    # Build vehicle profiles from scenario vehicles
    vehicles = store.list_vehicles(scenario_id)
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


# ── Background task implementations ───────────────────────────


def _run_build_trips(scenario_id: str, job_id: str) -> None:
    try:
        job_store.update_job(
            job_id,
            status="running",
            progress=10,
            message="Building trips from timetable...",
        )
        context = _build_dispatch_context(scenario_id)
        trips_json = [trip_to_dict(t) for t in context.trips]
        store.set_field(scenario_id, "trips", trips_json)
        store.update_scenario(scenario_id, status="trips_built")
        job_store.update_job(
            job_id,
            status="completed",
            progress=100,
            message=f"Built {len(trips_json)} trips.",
            result_key="trips",
        )
    except Exception as e:
        job_store.update_job(
            job_id,
            status="failed",
            message="Build trips failed.",
            error=traceback.format_exc(),
        )


def _run_build_graph(scenario_id: str, job_id: str) -> None:
    try:
        job_store.update_job(
            job_id,
            status="running",
            progress=10,
            message="Building feasibility graph...",
        )
        context = _build_dispatch_context(scenario_id)
        builder = ConnectionGraphBuilder()

        all_types = list(context.vehicle_profiles.keys())
        combined_graph: Dict[str, Any] = {
            "trips": [trip_to_dict(t) for t in context.trips],
            "arcs": [],
            "total_arcs": 0,
            "feasible_arcs": 0,
            "infeasible_arcs": 0,
        }

        for vt in all_types:
            adjacency = builder.build(context, vt)
            partial = build_graph_response(context.trips, adjacency)
            combined_graph["arcs"].extend(partial["arcs"])
            combined_graph["feasible_arcs"] += partial["feasible_arcs"]
            combined_graph["total_arcs"] += partial["total_arcs"]

        store.set_field(scenario_id, "graph", combined_graph)
        store.update_scenario(scenario_id, status="graph_built")
        job_store.update_job(
            job_id,
            status="completed",
            progress=100,
            message=f"Graph built: {combined_graph['feasible_arcs']} feasible arcs.",
            result_key="graph",
        )
    except Exception as e:
        job_store.update_job(
            job_id,
            status="failed",
            message="Build graph failed.",
            error=traceback.format_exc(),
        )


def _run_generate_duties(
    scenario_id: str, job_id: str, vehicle_type: Optional[str], strategy: str
) -> None:
    try:
        job_store.update_job(
            job_id, status="running", progress=10, message="Generating duties..."
        )
        context = _build_dispatch_context(scenario_id)
        pipeline = TimetableDispatchPipeline()

        vehicle_types = (
            [vehicle_type] if vehicle_type else list(context.vehicle_profiles.keys())
        )

        all_duties_json = []
        for vt in vehicle_types:
            result = pipeline.run(context, vt)
            for duty in result.duties:
                all_duties_json.append(vehicle_duty_to_dict(duty))

        store.set_field(scenario_id, "duties", all_duties_json)
        store.update_scenario(scenario_id, status="duties_generated")
        job_store.update_job(
            job_id,
            status="completed",
            progress=100,
            message=f"Generated {len(all_duties_json)} duties.",
            result_key="duties",
        )
    except Exception as e:
        job_store.update_job(
            job_id,
            status="failed",
            message="Generate duties failed.",
            error=traceback.format_exc(),
        )


# ── Trips endpoints ────────────────────────────────────────────


@router.get("/scenarios/{scenario_id}/trips")
def get_trips(scenario_id: str) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    items = store.get_field(scenario_id, "trips") or []
    return {"items": items, "total": len(items)}


@router.post("/scenarios/{scenario_id}/build-trips")
def build_trips(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[BuildTripsBody] = None,
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    job = job_store.create_job()
    background_tasks.add_task(_run_build_trips, scenario_id, job.job_id)
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


@router.post("/scenarios/{scenario_id}/build-graph")
def build_graph(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[BuildGraphBody] = None,
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    job = job_store.create_job()
    background_tasks.add_task(_run_build_graph, scenario_id, job.job_id)
    return job_store.job_to_dict(job)


# ── Duties endpoints ───────────────────────────────────────────


@router.get("/scenarios/{scenario_id}/duties")
def get_duties(scenario_id: str) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    items = store.get_field(scenario_id, "duties") or []
    return {"items": items, "total": len(items)}


@router.post("/scenarios/{scenario_id}/generate-duties")
def generate_duties(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[GenerateDutiesBody] = None,
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    vt = body.vehicle_type if body else None
    strategy = body.strategy if body else "greedy"
    job = job_store.create_job()
    background_tasks.add_task(
        _run_generate_duties, scenario_id, job.job_id, vt, strategy
    )
    return job_store.job_to_dict(job)


@router.get("/scenarios/{scenario_id}/duties/validate")
def validate_duties(scenario_id: str) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    from src.dispatch.validator import DutyValidator
    from bff.mappers.dispatch_mappers import dict_to_trip
    from src.dispatch.models import DutyLeg as PyDutyLeg, VehicleDuty as PyVehicleDuty

    duties_raw = store.get_field(scenario_id, "duties") or []
    context = _build_dispatch_context(scenario_id)
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
