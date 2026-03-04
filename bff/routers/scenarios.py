"""
bff/routers/scenarios.py

Scenario CRUD + timetable + deadhead/turnaround rules endpoints.

Routes:
  GET    /scenarios                    → list
  POST   /scenarios                    → create
  GET    /scenarios/{id}               → get
  PUT    /scenarios/{id}               → update
  DELETE /scenarios/{id}               → delete

  GET    /scenarios/{id}/timetable     → get timetable rows
  PUT    /scenarios/{id}/timetable     → replace timetable rows

  GET    /scenarios/{id}/deadhead-rules    → list
  GET    /scenarios/{id}/turnaround-rules  → list
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from bff.store import scenario_store as store

router = APIRouter(tags=["scenarios"])


# ── Pydantic models ────────────────────────────────────────────


class CreateScenarioBody(BaseModel):
    name: str
    description: str = ""
    mode: str = "thesis_mode"


class UpdateScenarioBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    mode: Optional[str] = None


class TimetableRowBody(BaseModel):
    route_id: str
    direction: str = "outbound"
    trip_index: int = 0
    origin: str
    destination: str
    departure: str  # HH:MM
    arrival: str  # HH:MM
    distance_km: float = 0.0
    allowed_vehicle_types: List[str] = ["BEV", "ICE"]


class UpdateTimetableBody(BaseModel):
    rows: List[TimetableRowBody]


# ── Helpers ────────────────────────────────────────────────────


def _not_found(scenario_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")


# ── Scenario CRUD ──────────────────────────────────────────────


@router.get("/scenarios")
def list_scenarios() -> Dict[str, Any]:
    items = store.list_scenarios()
    return {"items": items, "total": len(items)}


@router.post("/scenarios", status_code=201)
def create_scenario(body: CreateScenarioBody) -> Dict[str, Any]:
    return store.create_scenario(
        name=body.name,
        description=body.description,
        mode=body.mode,
    )


@router.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: str) -> Dict[str, Any]:
    try:
        return store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)


@router.put("/scenarios/{scenario_id}")
def update_scenario(scenario_id: str, body: UpdateScenarioBody) -> Dict[str, Any]:
    try:
        return store.update_scenario(
            scenario_id,
            name=body.name,
            description=body.description,
            mode=body.mode,
        )
    except KeyError:
        raise _not_found(scenario_id)


@router.delete("/scenarios/{scenario_id}", status_code=204)
def delete_scenario(scenario_id: str) -> Response:
    try:
        store.delete_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    return Response(status_code=204)


# ── Timetable ──────────────────────────────────────────────────


@router.get("/scenarios/{scenario_id}/timetable")
def get_timetable(scenario_id: str) -> Dict[str, Any]:
    try:
        rows = store.get_field(scenario_id, "timetable_rows")
    except KeyError:
        raise _not_found(scenario_id)
    return {"items": rows or [], "total": len(rows or [])}


@router.put("/scenarios/{scenario_id}/timetable")
def update_timetable(scenario_id: str, body: UpdateTimetableBody) -> Dict[str, Any]:
    try:
        rows = [r.model_dump() for r in body.rows]
        store.set_field(scenario_id, "timetable_rows", rows)
        return {"items": rows, "total": len(rows)}
    except KeyError:
        raise _not_found(scenario_id)


# ── Rules (read-only from static data for now) ─────────────────


@router.get("/scenarios/{scenario_id}/deadhead-rules")
def get_deadhead_rules(scenario_id: str) -> Dict[str, Any]:
    """
    Returns deadhead rules stored in the scenario document.
    These are seeded from constant/ CSV data when a scenario is created
    (future work). For now returns empty list.
    """
    try:
        store.get_scenario(scenario_id)  # verify exists
    except KeyError:
        raise _not_found(scenario_id)
    items: List[Dict[str, Any]] = []
    return {"items": items, "total": 0}


@router.get("/scenarios/{scenario_id}/turnaround-rules")
def get_turnaround_rules(scenario_id: str) -> Dict[str, Any]:
    """
    Returns turnaround rules stored in the scenario document.
    These are seeded from constant/ CSV data when a scenario is created
    (future work). For now returns empty list.
    """
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)
    items: List[Dict[str, Any]] = []
    return {"items": items, "total": 0}
