"""
bff/routers/timetable.py

Calendar CRUD endpoints (service_id definitions + date exceptions).

Routes:
  GET    /scenarios/{id}/calendar                        → list service_id entries
  PUT    /scenarios/{id}/calendar                        → replace all entries
  POST   /scenarios/{id}/calendar/{service_id}           → upsert one entry
  DELETE /scenarios/{id}/calendar/{service_id}           → delete one entry

  GET    /scenarios/{id}/calendar-dates                  → list date exceptions
  PUT    /scenarios/{id}/calendar-dates                  → replace all exceptions
  POST   /scenarios/{id}/calendar-dates/{date}           → upsert one date exception
  DELETE /scenarios/{id}/calendar-dates/{date}           → delete one date exception
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from bff.store import scenario_store as store

router = APIRouter(tags=["timetable"])


# ── Pydantic models ────────────────────────────────────────────


class ServiceCalendarBody(BaseModel):
    service_id: str
    name: str = ""
    mon: int = 0
    tue: int = 0
    wed: int = 0
    thu: int = 0
    fri: int = 0
    sat: int = 0
    sun: int = 0
    start_date: str = "2026-01-01"
    end_date: str = "2026-12-31"


class UpdateCalendarBody(BaseModel):
    entries: List[ServiceCalendarBody]


class CalendarDateBody(BaseModel):
    date: str  # YYYY-MM-DD
    service_id: str
    exception_type: str = "ADD"  # "ADD" | "REMOVE"


class UpdateCalendarDatesBody(BaseModel):
    entries: List[CalendarDateBody]


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


# ── Calendar (service_id definitions) ─────────────────────────


@router.get("/scenarios/{scenario_id}/calendar")
def get_calendar(scenario_id: str) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    items = store.get_calendar(scenario_id)
    return {"items": items, "total": len(items)}


@router.put("/scenarios/{scenario_id}/calendar")
def update_calendar(scenario_id: str, body: UpdateCalendarBody) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    entries = [e.model_dump() for e in body.entries]
    store.set_calendar(scenario_id, entries)
    return {"items": entries, "total": len(entries)}


@router.post("/scenarios/{scenario_id}/calendar/{service_id}", status_code=201)
def upsert_calendar_entry(
    scenario_id: str, service_id: str, body: ServiceCalendarBody
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    # Enforce service_id consistency between URL param and body
    entry = body.model_dump()
    entry["service_id"] = service_id
    return store.upsert_calendar_entry(scenario_id, entry)


@router.delete("/scenarios/{scenario_id}/calendar/{service_id}", status_code=204)
def delete_calendar_entry(scenario_id: str, service_id: str) -> Response:
    _require_scenario(scenario_id)
    try:
        store.delete_calendar_entry(scenario_id, service_id)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Calendar entry '{service_id}' not found",
        )
    return Response(status_code=204)


# ── Calendar dates (exception overrides) ──────────────────────


@router.get("/scenarios/{scenario_id}/calendar-dates")
def get_calendar_dates(scenario_id: str) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    items = store.get_calendar_dates(scenario_id)
    return {"items": items, "total": len(items)}


@router.put("/scenarios/{scenario_id}/calendar-dates")
def update_calendar_dates(
    scenario_id: str, body: UpdateCalendarDatesBody
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    entries = [e.model_dump() for e in body.entries]
    store.set_calendar_dates(scenario_id, entries)
    return {"items": entries, "total": len(entries)}


@router.post("/scenarios/{scenario_id}/calendar-dates/{date}", status_code=201)
def upsert_calendar_date(
    scenario_id: str, date: str, body: CalendarDateBody
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    entry = body.model_dump()
    entry["date"] = date
    return store.upsert_calendar_date(scenario_id, entry)


@router.delete("/scenarios/{scenario_id}/calendar-dates/{date}", status_code=204)
def delete_calendar_date(scenario_id: str, date: str) -> Response:
    _require_scenario(scenario_id)
    try:
        store.delete_calendar_date(scenario_id, date)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Calendar date '{date}' not found",
        )
    return Response(status_code=204)
