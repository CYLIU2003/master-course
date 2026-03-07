"""
bff/routers/simulation.py

Simulation endpoints:
  GET   /scenarios/{id}/simulation          → get simulation result
  POST  /scenarios/{id}/run-simulation      → async: run simulation
"""

from __future__ import annotations

import traceback
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from bff.store import job_store, scenario_store as store

router = APIRouter(tags=["simulation"])


class RunSimulationBody(BaseModel):
    force: bool = False
    service_id: Optional[str] = None
    depot_id: Optional[str] = None


def _not_found(scenario_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")


def _require_scenario(scenario_id: str) -> None:
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)


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


def _run_simulation(
    scenario_id: str, job_id: str, service_id: Optional[str], depot_id: Optional[str]
) -> None:
    """
    Placeholder simulation runner.
    Real implementation: call src/pipeline/simulate.py with the scenario's
    duties, vehicle fleet, and simulation config.
    """
    try:
        job_store.update_job(
            job_id, status="running", progress=20, message="Running simulation..."
        )

        if not depot_id:
            raise ValueError("No depot selected. Configure dispatch scope first.")

        duties = store.get_field(scenario_id, "duties") or []
        if not duties:
            raise ValueError("No duties found. Generate duties first.")

        # Stub result — real pipeline integration is future work
        result: Dict[str, Any] = {
            "scenario_id": scenario_id,
            "scope": {
                "serviceId": service_id or "WEEKDAY",
                "depotId": depot_id,
            },
            "duties": duties,
            "energy_consumption": [],
            "soc_trace": [],
            "total_energy_kwh": 0.0,
            "total_distance_km": sum(d.get("total_distance_km", 0.0) for d in duties),
            "feasibility_violations": [],
        }

        store.set_field(scenario_id, "simulation_result", result)
        store.update_scenario(scenario_id, status="simulated")
        job_store.update_job(
            job_id,
            status="completed",
            progress=100,
            message="Simulation complete.",
            result_key="simulation_result",
        )
    except Exception:
        job_store.update_job(
            job_id,
            status="failed",
            message="Simulation failed.",
            error=traceback.format_exc(),
        )


@router.get("/scenarios/{scenario_id}/simulation")
def get_simulation_result(scenario_id: str) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    result = store.get_field(scenario_id, "simulation_result")
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Simulation has not been run yet. POST to /run-simulation first.",
        )
    return result


@router.post("/scenarios/{scenario_id}/run-simulation")
def run_simulation(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[RunSimulationBody] = None,
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
        _run_simulation,
        scenario_id,
        job.job_id,
        scope.get("serviceId"),
        scope.get("depotId"),
    )
    return job_store.job_to_dict(job)
