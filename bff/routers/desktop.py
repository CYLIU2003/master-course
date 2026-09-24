"""Small, paginated desktop projections over the existing scenario contracts."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from bff.desktop_models import (
    DesktopConfiguration, DesktopConfigurationEdit, DesktopPage, DesktopWeatherAction, DesktopTimetableImport, ScenarioOverview, ScenarioPage, ResultSummary, DesktopWeatherSource,
)

from bff.store import desktop_store, scenario_store
from bff.services import local_db_catalog

router = APIRouter(prefix="/desktop", tags=["desktop"])

from bff.services.scenario_periods import PeriodEdit, get_periods, save_periods


@router.get("/scenarios/{scenario_id}/periods")
def scenario_periods(scenario_id: str):
    try:
        return get_periods(scenario_id)
    except KeyError as exc:
        raise HTTPException(404, "Scenario not found") from exc


@router.put("/scenarios/{scenario_id}/periods")
def edit_scenario_periods(scenario_id: str, body: PeriodEdit):
    try:
        return save_periods(scenario_id, body)
    except KeyError as exc:
        raise HTTPException(404, "Scenario not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/route-catalog/full")
def full_route_catalog():
    try:
        return local_db_catalog.full_route_catalog()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/route-catalog/odpt")
def odpt_route_catalog():
    try:
        return desktop_store.odpt_route_catalog()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/scenarios/{scenario_id}/simulation-summary", response_model=ResultSummary)
def simulation_summary(scenario_id: str):
    try:
        return desktop_store.simulation_summary(scenario_id)
    except KeyError as exc:
        raise HTTPException(404, "Scenario not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/scenarios/{scenario_id}/artifacts")
def artifacts(scenario_id: str):
    try:
        return desktop_store.result_files(scenario_id)
    except KeyError as exc:
        raise HTTPException(404, "Scenario not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/scenarios/{scenario_id}/artifacts/file")
def artifact_file(scenario_id: str, name: str = Query(max_length=500)):
    try:
        path = desktop_store.result_file(scenario_id, name)
        return FileResponse(path, filename=path.name)
    except KeyError as exc:
        raise HTTPException(404, "Scenario not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/scenarios/{scenario_id}/timetable-import")
def timetable_import(scenario_id: str, body: DesktopTimetableImport):
    from bff.services.desktop_timetable import import_timetable
    try:
        return import_timetable(scenario_id, body.content, body.apply, body.revision)
    except KeyError as exc:
        raise HTTPException(404, "Scenario not found") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/scenarios/{scenario_id}/timetable-export")
def timetable_export(scenario_id: str):
    from bff.services.desktop_timetable import export_timetable
    try:
        return export_timetable(scenario_id)
    except KeyError as exc:
        raise HTTPException(404, "Scenario not found") from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/scenarios/{scenario_id}/result-data/{name}")
def result_data(scenario_id: str, name: str, owner: str = Query("", max_length=200), offset: int = Query(0, ge=0), limit: int = Query(250, ge=1, le=250)):
    try:
        return desktop_store.result_page(scenario_id, name, owner, offset, limit)
    except KeyError as exc:
        raise HTTPException(404, "Scenario not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/weather/action")
def weather_action(body: DesktopWeatherAction):
    from bff.services.desktop_weather import weather_action as run_action
    try:
        return run_action(body)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/weather/source")
def weather_source(body: DesktopWeatherSource):
    from bff.services.desktop_weather import import_source
    try:
        return import_source(body.filename, body.content)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/scenarios/{scenario_id}/configuration", response_model=DesktopConfiguration)
def configuration(scenario_id: str):
    from bff.services.desktop_configuration import configuration as read_configuration
    try:
        return read_configuration(scenario_id)
    except KeyError as exc:
        raise HTTPException(404, "Scenario not found") from exc


@router.put("/scenarios/{scenario_id}/configuration", response_model=DesktopConfiguration)
def edit_configuration(scenario_id: str, body: DesktopConfigurationEdit):
    from bff.services.desktop_configuration import save_configuration
    try:
        return save_configuration(scenario_id, body.changes, body.revision)
    except KeyError as exc:
        raise HTTPException(404, "Scenario not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/scenarios", response_model=ScenarioPage)
def scenarios(
    q: str = Query("", max_length=200),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=250),
    route_group: Literal["all", "shibu24", "shibu21_24", "shibu21_23", "other"] = Query("all"),
    period_kind: Literal["all", "reusable", "dated_history"] = Query("all"),
):
    return desktop_store.scenario_page(q, offset, limit, route_group, period_kind)


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


@router.get("/scenarios/{scenario_id}/route-catalog")
def route_catalog(scenario_id: str):
    try:
        return desktop_store.route_catalog(scenario_id)
    except KeyError as exc:
        raise HTTPException(404, "Scenario not found") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/scenarios/{scenario_id}/tables/{name}", response_model=DesktopPage)
def table(
    scenario_id: str,
    name: Literal[
        "routes",
        "depots",
        "vehicles",
        "vehicle_templates",
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
