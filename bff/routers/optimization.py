"""
bff/routers/optimization.py

Optimization endpoints:
  GET   /scenarios/{id}/optimization            → get optimization result
  POST  /scenarios/{id}/run-optimization        → async: run MILP/ALNS optimizer
"""

from __future__ import annotations

import traceback
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from bff.store import job_store, scenario_store as store

router = APIRouter(tags=["optimization"])


class RunOptimizationBody(BaseModel):
    mode: str = "thesis_mode"
    time_limit_seconds: int = 300
    mip_gap: float = 0.01


def _not_found(scenario_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")


def _require_scenario(scenario_id: str) -> None:
    try:
        store.get_scenario(scenario_id)
    except KeyError:
        raise _not_found(scenario_id)


def _run_optimization(
    scenario_id: str,
    job_id: str,
    mode: str,
    time_limit_seconds: int,
    mip_gap: float,
) -> None:
    """
    Placeholder optimization runner.
    Real implementation: call src/pipeline/solve.py with the scenario config.
    Gurobi must be installed and licensed for real runs.
    """
    try:
        job_store.update_job(
            job_id,
            status="running",
            progress=10,
            message=f"Running optimizer (mode={mode})...",
        )

        duties = store.get_field(scenario_id, "duties") or []
        if not duties:
            raise ValueError("No duties found. Generate duties first.")

        # Stub result — real Gurobi integration is future work
        result: Dict[str, Any] = {
            "scenario_id": scenario_id,
            "solver_status": "stub_not_solved",
            "objective_value": 0.0,
            "solve_time_seconds": 0.0,
            "duties": duties,
            "charging_schedule": [],
            "cost_breakdown": {
                "energy_cost": 0.0,
                "peak_demand_cost": 0.0,
                "vehicle_cost": 0.0,
                "deadhead_cost": 0.0,
                "total_cost": 0.0,
            },
        }

        store.set_field(scenario_id, "optimization_result", result)
        store.update_scenario(scenario_id, status="optimized")
        job_store.update_job(
            job_id,
            status="completed",
            progress=100,
            message="Optimization complete (stub).",
            result_key="optimization_result",
        )
    except Exception:
        job_store.update_job(
            job_id,
            status="failed",
            message="Optimization failed.",
            error=traceback.format_exc(),
        )


@router.get("/scenarios/{scenario_id}/optimization")
def get_optimization_result(scenario_id: str) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    result = store.get_field(scenario_id, "optimization_result")
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Optimization has not been run yet. POST to /run-optimization first.",
        )
    return result


@router.post("/scenarios/{scenario_id}/run-optimization")
def run_optimization(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[RunOptimizationBody] = None,
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    mode = body.mode if body else "thesis_mode"
    tl = body.time_limit_seconds if body else 300
    gap = body.mip_gap if body else 0.01
    job = job_store.create_job()
    background_tasks.add_task(_run_optimization, scenario_id, job.job_id, mode, tl, gap)
    return job_store.job_to_dict(job)
