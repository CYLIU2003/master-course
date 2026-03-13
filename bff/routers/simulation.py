"""
bff/routers/simulation.py

Simulation endpoints:
  GET   /scenarios/{id}/simulation          → get simulation result
  POST  /scenarios/{id}/run-simulation      → async: run simulation
"""

from __future__ import annotations

import subprocess
import traceback
import json
import multiprocessing
import threading
from concurrent.futures import Future, ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from bff.dependencies import require_built
from bff.errors import AppErrorCode, make_error
from bff.mappers.scenario_to_problemdata import build_problem_data_from_scenario
from bff.mappers.solver_results import (
    deserialize_milp_result,
    serialize_simulation_result,
)
from bff.routers.graph import (
    _build_duties_payload,
    _build_graph_payload,
    _build_trips_payload,
)
from bff.store import job_store, scenario_store as store
from src.milp_model import MILPResult
from src.pipeline.simulate import simulate_problem_data

router = APIRouter(tags=["simulation"])
_SIMULATION_EXECUTOR: Optional[ProcessPoolExecutor] = None
_SIMULATION_FUTURE: Optional[Future[Any]] = None
_SIMULATION_FUTURE_LOCK = threading.Lock()


class RunSimulationBody(BaseModel):
    service_id: Optional[str] = None
    depot_id: Optional[str] = None
    source: str = "duties"


def _simulation_capabilities() -> Dict[str, Any]:
    return {
        "implemented": True,
        "async_job": True,
        "job_persistence": dict(job_store.JOB_PERSISTENCE_INFO),
        "primary_inputs": ["scenario", "dispatch_scope", "problem_data"],
        "supported_sources": ["duties", "optimization_result"],
        "execution_model": "process_pool",
        "notes": [
            "Simulation runs against scenario-derived ProblemData.",
            "Dispatch artifacts are auto-built when missing.",
            "Results are persisted to the scenario snapshot; job state is not.",
            "Simulation runs in a dedicated process pool so API polling stays responsive.",
        ],
    }


def _get_simulation_executor() -> ProcessPoolExecutor:
    global _SIMULATION_EXECUTOR
    with _SIMULATION_FUTURE_LOCK:
        if _SIMULATION_EXECUTOR is None:
            _SIMULATION_EXECUTOR = ProcessPoolExecutor(
                max_workers=1,
                mp_context=multiprocessing.get_context("spawn"),
            )
    return _SIMULATION_EXECUTOR


def shutdown_simulation_executor() -> None:
    global _SIMULATION_EXECUTOR, _SIMULATION_FUTURE
    with _SIMULATION_FUTURE_LOCK:
        executor = _SIMULATION_EXECUTOR
        _SIMULATION_EXECUTOR = None
        _SIMULATION_FUTURE = None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)


def _register_simulation_future(
    future: Future[Any],
    *,
    job_id: str,
    scenario_id: str,
    service_id: str,
    depot_id: Optional[str],
    source: str,
) -> None:
    def _handle_completion(done: Future[Any]) -> None:
        try:
            exc = done.exception()
        except Exception as callback_exc:  # pragma: no cover - defensive
            exc = callback_exc
        if exc is None:
            return
        try:
            job_store.update_job(
                job_id,
                status="failed",
                progress=100,
                message="Simulation worker crashed.",
                error=str(exc),
                metadata={
                    "scenario_id": scenario_id,
                    "service_id": service_id,
                    "depot_id": depot_id,
                    "source": source,
                    "worker_failure": True,
                },
            )
        except KeyError:
            return

    future.add_done_callback(_handle_completion)


def _submit_simulation_job(
    *,
    args: tuple[Any, ...],
    job_id: str,
    scenario_id: str,
    service_id: str,
    depot_id: Optional[str],
    source: str,
) -> bool:
    global _SIMULATION_FUTURE
    with _SIMULATION_FUTURE_LOCK:
        if _SIMULATION_FUTURE is not None and not _SIMULATION_FUTURE.done():
            return False
        future = _get_simulation_executor().submit(_run_simulation, *args)
        _SIMULATION_FUTURE = future
        _register_simulation_future(
            future,
            job_id=job_id,
            scenario_id=scenario_id,
            service_id=service_id,
            depot_id=depot_id,
            source=source,
        )
        return True


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
    doc = store._load(scenario_id)
    doc["dispatch_scope"] = {**current, **scope}
    return store._normalize_dispatch_scope(doc)

def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return ""


def _scenario_feed_context(scenario_id: str) -> Dict[str, Any]:
    return dict(store.get_feed_context(scenario_id) or {})


def _scoped_output_dir(
    *,
    root: str,
    feed_context: Dict[str, Any],
    scenario_id: str,
    stage: str,
    service_id: Optional[str] = None,
    depot_id: Optional[str] = None,
) -> str:
    feed_id = str(feed_context.get("feedId") or "unscoped")
    snapshot_id = str(feed_context.get("snapshotId") or scenario_id)
    service_scope = str(service_id or "all_services")
    depot_scope = str(depot_id or "all_depots")
    return str(Path(root) / feed_id / snapshot_id / stage / scenario_id / depot_scope / service_scope)


def _persist_json_outputs(output_dir: str, payloads: Dict[str, Dict[str, Any]]) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (output_path / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _ensure_dispatch_artifacts(
    scenario_id: str, service_id: str, depot_id: str
) -> None:
    if not store.get_field(scenario_id, "trips"):
        store.set_field(
            scenario_id,
            "trips",
            _build_trips_payload(scenario_id, service_id, depot_id),
        )
    if not store.get_field(scenario_id, "graph"):
        store.set_field(
            scenario_id,
            "graph",
            _build_graph_payload(scenario_id, service_id, depot_id),
        )
    if not store.get_field(scenario_id, "duties"):
        store.set_field(
            scenario_id,
            "duties",
            _build_duties_payload(scenario_id, None, "greedy", service_id, depot_id),
        )


def _result_from_duties(data, duties_raw: list[dict]) -> MILPResult:
    task_lut = {task.task_id: task for task in data.tasks}
    vehicles_by_type: Dict[str, list] = {}
    for vehicle in data.vehicles:
        vehicles_by_type.setdefault(vehicle.vehicle_type, []).append(vehicle)

    result = MILPResult(status="FEASIBLE", objective_value=0.0)
    assigned_vehicle_ids: set[str] = set()
    duty_index_by_type: Dict[str, int] = {}

    for duty in duties_raw:
        vehicle_type = str(duty.get("vehicle_type") or "BEV")
        candidates = vehicles_by_type.get(vehicle_type) or data.vehicles
        if not candidates:
            continue
        idx = duty_index_by_type.get(vehicle_type, 0)
        vehicle = candidates[idx % len(candidates)]
        duty_index_by_type[vehicle_type] = idx + 1
        assigned_vehicle_ids.add(vehicle.vehicle_id)
        trip_ids = [
            str((leg.get("trip") or {}).get("trip_id"))
            for leg in duty.get("legs", [])
            if (leg.get("trip") or {}).get("trip_id") is not None
        ]
        result.assignment.setdefault(vehicle.vehicle_id, []).extend(trip_ids)

    for vehicle in data.vehicles:
        if vehicle.vehicle_type != "BEV":
            continue
        current_soc = (
            vehicle.soc_init or vehicle.soc_max or vehicle.battery_capacity or 0.0
        )
        series = [current_soc for _ in range(data.num_periods + 1)]
        for task_id in result.assignment.get(vehicle.vehicle_id, []):
            task = task_lut.get(task_id)
            if task is None:
                continue
            start = min(max(task.start_time_idx, 0), data.num_periods)
            energy = task.energy_required_kwh_bev
            for idx in range(start, data.num_periods + 1):
                series[idx] = max(0.0, series[idx] - energy)
        result.soc_series[vehicle.vehicle_id] = series

    return result


def _run_simulation(
    scenario_id: str,
    job_id: str,
    service_id: str,
    depot_id: Optional[str],
    source: str,
) -> None:
    try:
        job_store.update_job(
            job_id, status="running", progress=15, message="Preparing simulation..."
        )
        if not depot_id:
            raise ValueError("No depot selected. Configure dispatch scope first.")

        _ensure_dispatch_artifacts(scenario_id, service_id, depot_id)
        scenario = store._load(scenario_id)
        feed_context = _scenario_feed_context(scenario_id)
        output_dir = _scoped_output_dir(
            root="outputs",
            feed_context=feed_context,
            scenario_id=scenario_id,
            stage="simulation",
            service_id=service_id,
            depot_id=depot_id,
        )
        data, build_report = build_problem_data_from_scenario(
            scenario,
            depot_id=depot_id,
            service_id=service_id,
            mode="mode_milp_only",
            use_existing_duties=True,
            analysis_scope=store.get_dispatch_scope(scenario_id),
        )
        store.set_field(scenario_id, "problemdata_build_audit", build_report.to_dict())

        if source == "optimization_result":
            optimization_result = (
                store.get_field(scenario_id, "optimization_result") or {}
            )
            solver_result = optimization_result.get("solver_result")
            if not solver_result:
                raise ValueError(
                    "No optimization_result found. Run optimization first."
                )
            milp_result = deserialize_milp_result(solver_result)
        else:
            duties = store.get_field(scenario_id, "duties") or []
            if not duties:
                raise ValueError("No duties found. Generate duties first.")
            milp_result = _result_from_duties(data, duties)

        job_store.update_job(
            job_id, status="running", progress=60, message="Running simulator..."
        )
        sim_output = simulate_problem_data(data, milp_result)
        sim_payload = serialize_simulation_result(sim_output["sim"])

        total_distance_km = 0.0
        total_energy_kwh = 0.0
        task_lut = {task.task_id: task for task in data.tasks}
        for task_ids in milp_result.assignment.values():
            for task_id in task_ids:
                task = task_lut.get(task_id)
                if task is None:
                    continue
                total_distance_km += task.distance_km
                total_energy_kwh += task.energy_required_kwh_bev

        result: Dict[str, Any] = {
            "scenario_id": scenario_id,
            "feed_context": feed_context,
            "scope": {"serviceId": service_id, "depotId": depot_id},
            "source": source,
            "soc_trace": milp_result.soc_series,
            "charger_usage_timeline": milp_result.charge_schedule,
            "energy_consumption": milp_result.charge_power_kw,
            "total_energy_kwh": total_energy_kwh,
            "total_distance_km": total_distance_km,
            "feasibility_violations": sim_payload.get("feasibility_violations", []),
            "simulation_summary": sim_payload,
        }

        simulation_audit = {
            "scenario_id": scenario_id,
            "feed_context": feed_context,
            "depot_id": depot_id,
            "service_id": service_id,
            "case_type": scenario.get("experiment_case_type"),
            "input_counts": {
                "vehicles": build_report.vehicle_count,
                "tasks": build_report.task_count,
                "duties": len(store.get_field(scenario_id, "duties") or []),
            },
            "output_counts": {
                "soc_traces": len(milp_result.soc_series),
                "feasibility_violations": len(result["feasibility_violations"]),
            },
            "warnings": build_report.warnings,
            "errors": build_report.errors,
            "source": source,
            "git_sha": _git_sha(),
            "source_snapshot": store.get_field(scenario_id, "source_snapshot"),
            "output_dir": output_dir,
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }
        result["audit"] = simulation_audit

        store.set_field(scenario_id, "simulation_result", result)
        store.set_field(scenario_id, "simulation_audit", simulation_audit)
        _persist_json_outputs(
            output_dir,
            {
                "simulation_result.json": result,
                "simulation_audit.json": simulation_audit,
            },
        )
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
    if isinstance(result, dict) and "audit" not in result:
        audit = store.get_field(scenario_id, "simulation_audit")
        if audit is not None:
            result = {**result, "audit": audit}
    return result


@router.get("/scenarios/{scenario_id}/simulation/capabilities")
def get_simulation_capabilities(scenario_id: str) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    return _simulation_capabilities()


@router.post("/scenarios/{scenario_id}/run-simulation")
def run_simulation(
    scenario_id: str,
    body: Optional[RunSimulationBody] = None,
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    request = body or RunSimulationBody()
    scope = _resolve_dispatch_scope(
        scenario_id,
        service_id=request.service_id,
        depot_id=request.depot_id,
        persist=True,
    )
    job = job_store.create_job()
    job_store.update_job(
        job.job_id,
        metadata={
            "scenario_id": scenario_id,
            "feed_context": store.get_feed_context(scenario_id),
            "service_id": scope.get("serviceId") or "WEEKDAY",
            "depot_id": scope.get("depotId"),
            "stage": "queued",
            "source": request.source,
            "persistence": dict(job_store.JOB_PERSISTENCE_INFO),
        },
    )
    submitted = _submit_simulation_job(
        args=(
            scenario_id,
            job.job_id,
            scope.get("serviceId") or "WEEKDAY",
            scope.get("depotId"),
            request.source,
        ),
        job_id=job.job_id,
        scenario_id=scenario_id,
        service_id=scope.get("serviceId") or "WEEKDAY",
        depot_id=scope.get("depotId"),
        source=request.source,
    )
    if not submitted:
        job_store.update_job(
            job.job_id,
            status="failed",
            progress=100,
            message="Rejected because another simulation job is already running.",
            error="job_already_running",
        )
        raise HTTPException(
            status_code=503,
            detail=make_error(
                AppErrorCode.EXECUTION_IN_PROGRESS,
                "A simulation job is already running. Please retry after it completes.",
            ),
        )
    return job_store.job_to_dict(job)
