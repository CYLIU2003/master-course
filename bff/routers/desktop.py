"""Small, paginated desktop projections over the existing scenario contracts."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from bff.desktop_models import DesktopPage, ScenarioOverview, ScenarioPage

from bff.store import desktop_store, scenario_store

router = APIRouter(prefix="/desktop", tags=["desktop"])


@router.get("/scenarios", response_model=ScenarioPage)
def scenarios(
    q: str = Query("", max_length=200),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=250),
):
    return desktop_store.scenario_page(q, offset, limit)


@router.get("/scenarios/{scenario_id}", response_model=ScenarioOverview)
def overview(scenario_id: str):
    try:
        meta, _ = scenario_store.get_desktop_context(scenario_id)
        return {
            "meta": meta.get("meta", {}),
            "stats": meta.get("stats", {}),
            "scope": desktop_store.collection(scenario_id, "dispatch_scope") or {},
            "settings": desktop_store.collection(scenario_id, "simulation_config")
            or {},
            "result": desktop_store.result_summary(scenario_id),
        }
    except KeyError as exc:
        raise HTTPException(404, "Scenario not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/scenarios/{scenario_id}/tables/{name}", response_model=DesktopPage)
def table(
    scenario_id: str,
    name: Literal[
        "routes",
        "depots",
        "vehicles",
        "stops",
        "chargers",
        "timetable_rows",
        "trips",
        "duties",
        "blocks",
    ],
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=250),
    service_id: str | None = None,
):
    try:
        return desktop_store.table_page(scenario_id, name, offset, limit, service_id)
    except KeyError as exc:
        raise HTTPException(404, "Scenario not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
