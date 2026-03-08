"""
bff/routers/optimization.py

Optimization endpoints:
  GET   /scenarios/{id}/optimization            → get optimization result
  POST  /scenarios/{id}/run-optimization        → async: run MILP/ALNS optimizer
"""

from __future__ import annotations

import subprocess
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from bff.mappers.scenario_to_problemdata import build_problem_data_from_scenario
from bff.mappers.solver_results import serialize_milp_result, serialize_simulation_result
from bff.routers.graph import (
    _build_blocks_payload,
    _build_dispatch_plan_payload,
    _build_duties_payload,
    _build_graph_payload,
    _build_trips_payload,
)
from bff.store import job_store, scenario_store as store
from src.dispatch.models import hhmm_to_min
from src.optimization import OptimizationConfig, OptimizationMode, ProblemBuilder, ResultSerializer
from src.optimization.rolling.reoptimizer import RollingReoptimizer
from src.pipeline.solve import solve_problem_data

router = APIRouter(tags=["optimization"])


class RunOptimizationBody(BaseModel):
    mode: str = "mode_milp_only"
    time_limit_seconds: int = 300
    mip_gap: float = 0.01
    service_id: Optional[str] = None
    depot_id: Optional[str] = None
    rebuild_dispatch: bool = True
    use_existing_duties: bool = False
    alns_iterations: int = 500


class DelayEventBody(BaseModel):
    trip_id: str
    delay_min: float


class ReoptimizeBody(BaseModel):
    mode: str = "hybrid"
    current_time: str
    time_limit_seconds: int = 180
    mip_gap: float = 0.02
    alns_iterations: int = 300
    service_id: Optional[str] = None
    depot_id: Optional[str] = None
    actual_soc: Dict[str, float] = {}
    actual_location_node_id: Dict[str, str] = {}
    delays: list[DelayEventBody] = []
    updated_pv_profile: list[Dict[str, Any]] = []


def _optimization_capabilities() -> Dict[str, Any]:
    return {
        "implemented": True,
        "async_job": True,
        "job_persistence": dict(job_store.JOB_PERSISTENCE_INFO),
        "supported_modes": ["milp", "alns", "hybrid", "mode_milp_only", "mode_alns_only", "mode_alns_milp"],
        "supports_reoptimization": True,
        "notes": [
            "Optimization runs against canonical ProblemData built from the scenario snapshot.",
            "Dispatch artifacts can be rebuilt before solve when requested.",
            "Results are persisted to the scenario snapshot; job state is not.",
        ],
    }


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


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                text=True,
            )
            .strip()
        )
    except Exception:
        return ""


def _rebuild_dispatch_artifacts(
    scenario_id: str,
    service_id: str,
    depot_id: str,
) -> None:
    trips = _build_trips_payload(scenario_id, service_id, depot_id)
    graph = _build_graph_payload(scenario_id, service_id, depot_id)
    blocks = _build_blocks_payload(scenario_id, None, "greedy", service_id, depot_id)
    duties = _build_duties_payload(scenario_id, None, "greedy", service_id, depot_id)
    dispatch_plan = _build_dispatch_plan_payload(
        scenario_id,
        None,
        "greedy",
        service_id,
        depot_id,
    )
    store.set_field(scenario_id, "trips", trips)
    store.set_field(scenario_id, "graph", graph)
    store.set_field(scenario_id, "blocks", blocks)
    store.set_field(scenario_id, "duties", duties)
    store.set_field(scenario_id, "dispatch_plan", dispatch_plan)


def _job_metadata(
    *,
    scenario_id: str,
    service_id: str,
    depot_id: Optional[str],
    stage: str,
    mode: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "scenario_id": scenario_id,
        "service_id": service_id,
        "depot_id": depot_id,
        "stage": stage,
        "mode": mode,
        **(extra or {}),
    }


def _cost_breakdown(result_payload: Dict[str, Any], sim_payload: Dict[str, Any] | None) -> Dict[str, float]:
    obj_breakdown = dict(result_payload.get("obj_breakdown") or {})
    return {
        "energy_cost": float(
            obj_breakdown.get(
                "electricity_cost",
                (sim_payload or {}).get("total_energy_cost", 0.0),
            )
            or 0.0
        ),
        "peak_demand_cost": float(
            obj_breakdown.get(
                "demand_charge_cost",
                (sim_payload or {}).get("total_demand_charge", 0.0),
            )
            or 0.0
        ),
        "vehicle_cost": float(obj_breakdown.get("vehicle_fixed_cost", 0.0) or 0.0),
        "deadhead_cost": float(obj_breakdown.get("deadhead_cost", 0.0) or 0.0),
        "battery_degradation_cost": float(
            obj_breakdown.get(
                "battery_degradation_cost",
                (sim_payload or {}).get("total_degradation_cost", 0.0),
            )
            or 0.0
        ),
        "penalty_unserved": float(
            obj_breakdown.get("unserved_penalty", 0.0) or 0.0
        ),
        "total_cost": float(
            result_payload.get("objective_value")
            or (sim_payload or {}).get("total_operating_cost", 0.0)
            or 0.0
        ),
    }


def _run_optimization(
    scenario_id: str,
    job_id: str,
    mode: str,
    time_limit_seconds: int,
    mip_gap: float,
    service_id: str,
    depot_id: str,
    rebuild_dispatch: bool,
    use_existing_duties: bool,
    alns_iterations: int,
) -> None:
    try:
        job_store.update_job(
            job_id,
            status="running",
            progress=5,
            message="Preparing optimization inputs...",
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="prepare",
                mode=mode,
            ),
        )

        if not depot_id:
            raise ValueError("No depot selected. Configure dispatch scope first.")

        if rebuild_dispatch:
            _rebuild_dispatch_artifacts(scenario_id, service_id, depot_id)
        elif not (store.get_field(scenario_id, "trips") and store.get_field(scenario_id, "duties")):
            _rebuild_dispatch_artifacts(scenario_id, service_id, depot_id)

        scenario = store._load(scenario_id)
        job_store.update_job(
            job_id,
            status="running",
            progress=25,
            message="Building ProblemData from scenario...",
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="build_problemdata",
                mode=mode,
                extra={
                    "rebuild_dispatch": rebuild_dispatch,
                    "use_existing_duties": use_existing_duties,
                },
            ),
        )
        data, build_report = build_problem_data_from_scenario(
            scenario,
            depot_id=depot_id,
            service_id=service_id,
            mode=mode,
            use_existing_duties=use_existing_duties,
        )
        store.set_field(scenario_id, "problemdata_build_audit", build_report.to_dict())
        canonical_problem = ProblemBuilder().build_from_scenario(
            scenario,
            depot_id=depot_id,
            service_id=service_id,
            config=OptimizationConfig(
                mode=_parse_optimization_mode(mode),
                time_limit_sec=time_limit_seconds,
                mip_gap=mip_gap,
                alns_iterations=alns_iterations,
            ),
        )

        job_store.update_job(
            job_id,
            status="running",
            progress=55,
            message=f"Running optimizer ({mode})...",
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="solve",
                mode=mode,
                extra={
                    "problem_summary": {
                        "trips": len(canonical_problem.trips),
                        "vehicles": len(canonical_problem.vehicles),
                        "chargers": len(canonical_problem.chargers),
                        "price_slots": len(canonical_problem.price_slots),
                        "pv_slots": len(canonical_problem.pv_slots),
                    }
                },
            ),
        )
        solve_output = solve_problem_data(
            data,
            mode=mode,
            time_limit_seconds=time_limit_seconds,
            mip_gap=mip_gap,
            output_dir="outputs",
        )
        result_payload = serialize_milp_result(solve_output["result"])
        sim_payload = (
            serialize_simulation_result(solve_output["sim_result"])
            if solve_output.get("sim_result") is not None
            else None
        )

        optimization_result: Dict[str, Any] = {
            "scenario_id": scenario_id,
            "solver_status": result_payload["status"],
            "mode": mode,
            "objective_value": result_payload.get("objective_value"),
            "solve_time_seconds": result_payload.get("solve_time_seconds", 0.0),
            "mip_gap": result_payload.get("mip_gap"),
            "cost_breakdown": _cost_breakdown(result_payload, sim_payload),
            "dispatch_report": store.get_field(scenario_id, "graph") or {},
            "build_report": build_report.to_dict(),
            "summary": {
                "vehicle_count_used": sum(
                    1
                    for _vehicle_id, task_ids in (result_payload.get("assignment") or {}).items()
                    if task_ids
                ),
                "trip_count_served": sum(
                    len(task_ids)
                    for task_ids in (result_payload.get("assignment") or {}).values()
                ),
                "trip_count_unserved": len(result_payload.get("unserved_tasks") or []),
            },
            "solver_result": result_payload,
            "canonical_problem_summary": {
                "trip_count": len(canonical_problem.trips),
                "vehicle_count": len(canonical_problem.vehicles),
                "charger_count": len(canonical_problem.chargers),
                "price_slot_count": len(canonical_problem.price_slots),
                "pv_slot_count": len(canonical_problem.pv_slots),
            },
        }
        if sim_payload is not None:
            optimization_result["simulation_summary"] = sim_payload

        optimization_audit = {
            "scenario_id": scenario_id,
            "depot_id": depot_id,
            "service_id": service_id,
            "case_type": scenario.get("experiment_case_type"),
            "input_counts": {
                "vehicles": build_report.vehicle_count,
                "tasks": build_report.task_count,
                "travel_connections": build_report.travel_connection_count,
            },
            "output_counts": {
                "assigned_vehicles": optimization_result["summary"]["vehicle_count_used"],
                "served_trips": optimization_result["summary"]["trip_count_served"],
                "unserved_trips": optimization_result["summary"]["trip_count_unserved"],
            },
            "warnings": build_report.warnings,
            "errors": build_report.errors,
            "solver_mode": mode,
            "time_limit": time_limit_seconds,
            "mip_gap": mip_gap,
            "alns_iterations": alns_iterations,
            "git_sha": _git_sha(),
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }

        store.set_field(scenario_id, "optimization_result", optimization_result)
        store.set_field(scenario_id, "optimization_audit", optimization_audit)
        store.update_scenario(scenario_id, status="optimized")
        job_store.update_job(
            job_id,
            status="completed",
            progress=100,
            message="Optimization complete.",
            result_key="optimization_result",
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="completed",
                mode=mode,
                extra={
                    "objective_value": optimization_result.get("objective_value"),
                    "solver_status": optimization_result.get("solver_status"),
                },
            ),
        )
    except Exception:
        job_store.update_job(
            job_id,
            status="failed",
            message="Optimization failed.",
            error=traceback.format_exc(),
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="failed",
                mode=mode,
            ),
        )


def _parse_optimization_mode(mode: str) -> OptimizationMode:
    normalized = (mode or "").strip().lower()
    if normalized in {"milp", "mode_milp_only", "exact"}:
        return OptimizationMode.MILP
    if normalized in {"alns", "mode_alns_only", "heuristic"}:
        return OptimizationMode.ALNS
    return OptimizationMode.HYBRID


def _parse_mode(mode: str) -> OptimizationMode:
    return _parse_optimization_mode(mode)


def _apply_reoptimization_inputs(
    scenario: Dict[str, Any],
    body: ReoptimizeBody,
) -> Dict[str, Any]:
    updated = dict(scenario)
    if body.updated_pv_profile:
        updated["pv_profiles"] = body.updated_pv_profile
    updated["reoptimization_request"] = {
        "current_time": body.current_time,
        "actual_soc": dict(body.actual_soc),
        "actual_location_node_id": dict(body.actual_location_node_id),
        "delays": [item.model_dump() for item in body.delays],
    }
    return updated


def _run_reoptimization(
    scenario_id: str,
    job_id: str,
    body: ReoptimizeBody,
    service_id: str,
    depot_id: Optional[str],
) -> None:
    mode = body.mode
    try:
        if not depot_id:
            raise ValueError("No depot selected. Configure dispatch scope first.")

        scenario = _apply_reoptimization_inputs(store._load(scenario_id), body)
        job_store.update_job(
            job_id,
            status="running",
            progress=15,
            message="Building canonical problem for re-optimization...",
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="reopt_build",
                mode=mode,
                extra={"current_time": body.current_time},
            ),
        )
        config = OptimizationConfig(
            mode=_parse_optimization_mode(mode),
            time_limit_sec=body.time_limit_seconds,
            mip_gap=body.mip_gap,
            alns_iterations=body.alns_iterations,
            rolling_current_min=hhmm_to_min(body.current_time),
        )
        problem = ProblemBuilder().build_from_scenario(
            scenario,
            depot_id=depot_id,
            service_id=service_id,
            config=config,
        )
        job_store.update_job(
            job_id,
            status="running",
            progress=55,
            message="Running rolling-horizon re-optimization...",
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="reopt_solve",
                mode=mode,
                extra={
                    "delay_count": len(body.delays),
                    "soc_updates": len(body.actual_soc),
                },
            ),
        )
        result = RollingReoptimizer().reoptimize(
            problem,
            config=config,
            current_min=hhmm_to_min(body.current_time),
        )
        payload = {
            "scenario_id": scenario_id,
            "reoptimized": True,
            "reoptimization_request": {
                "current_time": body.current_time,
                "actual_soc": dict(body.actual_soc),
                "actual_location_node_id": dict(body.actual_location_node_id),
                "delays": [item.model_dump() for item in body.delays],
            },
            **ResultSerializer.serialize_result(result),
        }
        store.set_field(scenario_id, "optimization_result", payload)
        store.set_field(
            scenario_id,
            "optimization_audit",
            {
                "scenario_id": scenario_id,
                "depot_id": depot_id,
                "service_id": service_id,
                "solver_mode": mode,
                "reoptimized": True,
                "current_time": body.current_time,
                "delay_count": len(body.delays),
                "actual_soc_count": len(body.actual_soc),
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "git_sha": _git_sha(),
            },
        )
        job_store.update_job(
            job_id,
            status="completed",
            progress=100,
            message="Re-optimization complete.",
            result_key="optimization_result",
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="reopt_completed",
                mode=mode,
                extra={"objective_value": payload.get("objective_value")},
            ),
        )
    except Exception:
        job_store.update_job(
            job_id,
            status="failed",
            message="Re-optimization failed.",
            error=traceback.format_exc(),
            metadata=_job_metadata(
                scenario_id=scenario_id,
                service_id=service_id,
                depot_id=depot_id,
                stage="reopt_failed",
                mode=mode,
            ),
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


@router.get("/scenarios/{scenario_id}/optimization/capabilities")
def get_optimization_capabilities(scenario_id: str) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    return _optimization_capabilities()


@router.post("/scenarios/{scenario_id}/run-optimization")
def run_optimization(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    body: Optional[RunOptimizationBody] = None,
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    request = body or RunOptimizationBody()
    scope = _resolve_dispatch_scope(
        scenario_id,
        service_id=request.service_id,
        depot_id=request.depot_id,
        persist=True,
    )
    job = job_store.create_job()
    job_store.update_job(
        job.job_id,
        metadata=_job_metadata(
            scenario_id=scenario_id,
            service_id=scope.get("serviceId") or "WEEKDAY",
            depot_id=scope.get("depotId"),
            stage="queued",
            mode=request.mode,
            extra={"persistence": dict(job_store.JOB_PERSISTENCE_INFO)},
        ),
    )
    background_tasks.add_task(
        _run_optimization,
        scenario_id,
        job.job_id,
        request.mode,
        request.time_limit_seconds,
        request.mip_gap,
        scope.get("serviceId") or "WEEKDAY",
        scope.get("depotId"),
        request.rebuild_dispatch,
        request.use_existing_duties,
        request.alns_iterations,
    )
    return job_store.job_to_dict(job)


@router.post("/scenarios/{scenario_id}/reoptimize")
def reoptimize(
    scenario_id: str,
    background_tasks: BackgroundTasks,
    body: ReoptimizeBody,
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    scope = _resolve_dispatch_scope(
        scenario_id,
        service_id=body.service_id,
        depot_id=body.depot_id,
        persist=True,
    )
    job = job_store.create_job()
    job_store.update_job(
        job.job_id,
        metadata=_job_metadata(
            scenario_id=scenario_id,
            service_id=scope.get("serviceId") or "WEEKDAY",
            depot_id=scope.get("depotId"),
            stage="queued",
            mode=body.mode,
            extra={"persistence": dict(job_store.JOB_PERSISTENCE_INFO)},
        ),
    )
    background_tasks.add_task(
        _run_reoptimization,
        scenario_id,
        job.job_id,
        body,
        scope.get("serviceId") or "WEEKDAY",
        scope.get("depotId"),
    )
    return job_store.job_to_dict(job)
