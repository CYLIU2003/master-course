"""
bff/routers/optimization.py

Optimization endpoints:
  GET   /scenarios/{id}/optimization            → get optimization result
  POST  /scenarios/{id}/run-optimization        → async: run MILP/ALNS optimizer
"""

from __future__ import annotations

import subprocess
import traceback
import json
import threading
import multiprocessing
import os
from concurrent.futures import Executor, Future, ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from bff.dependencies import require_built
from bff.errors import AppErrorCode, make_error
from bff.mappers.scenario_to_problemdata import build_problem_data_from_scenario
from bff.mappers.solver_results import (
    serialize_milp_result,
    serialize_simulation_result,
)
from bff.routers.graph import (
    _build_blocks_payload,
    _build_dispatch_plan_payload,
    _build_duties_payload,
    _build_graph_payload,
    _build_trips_payload,
)
from bff.services.experiment_reports import log_optimization_experiment
from bff.services.run_preparation import (
    get_or_build_run_preparation,
    load_prepared_input,
    materialize_scenario_from_prepared_input,
)
from bff.store import job_store, scenario_store as store
from src.dispatch.models import hhmm_to_min
from src.optimization import (
    OptimizationConfig,
    OptimizationMode,
    ProblemBuilder,
    ResultSerializer,
)
from src.optimization.rolling.reoptimizer import RollingReoptimizer
from src.pipeline.solve import solve_problem_data

router = APIRouter(tags=["optimization"])
_OPTIMIZATION_EXECUTOR: Optional[Executor] = None
_OPTIMIZATION_FUTURE: Optional[Future[Any]] = None
_OPTIMIZATION_FUTURE_LOCK = threading.RLock()


def _require_nonempty_prepared_scope(prep, *, action: str) -> None:
    if int(prep.scope_summary.get("trip_count") or 0) > 0:
        return
    raise HTTPException(
        status_code=409,
        detail=make_error(
            AppErrorCode.SCENARIO_INCOMPLETE,
            f"{action} failed: no trips matched the current depot / route / day-type selection.",
            scopeSummary=prep.scope_summary,
        ),
    )


class RunOptimizationBody(BaseModel):
    mode: str = "mode_milp_only"
    time_limit_seconds: int = 300
    mip_gap: float = 0.01
    random_seed: int = 42
    prepared_input_id: Optional[str] = None
    service_id: Optional[str] = None
    depot_id: Optional[str] = None
    rebuild_dispatch: bool = True
    use_existing_duties: bool = False
    alns_iterations: int = 500
    no_improvement_limit: int = 100
    destroy_fraction: float = 0.25


class DelayEventBody(BaseModel):
    trip_id: str
    delay_min: float


class ReoptimizeBody(BaseModel):
    mode: str = "hybrid"
    current_time: str
    time_limit_seconds: int = 180
    mip_gap: float = 0.02
    random_seed: int = 42
    alns_iterations: int = 300
    no_improvement_limit: int = 100
    destroy_fraction: float = 0.25
    prepared_input_id: Optional[str] = None
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
        "supported_modes": [
            "milp",
            "alns",
            "hybrid",
            "ga",
            "abc",
            "mode_milp_only",
            "mode_alns_only",
            "mode_alns_milp",
        ],
        "supports_reoptimization": True,
        "max_concurrent_jobs": 1,
        "execution_model": f"{_executor_mode()}_pool",
        "notes": [
            "Optimization runs against canonical ProblemData built from the scenario snapshot.",
            "Dispatch artifacts can be rebuilt before solve when requested.",
            "Results are persisted to the scenario snapshot; job state is not.",
            "Optimization/re-optimization runs in a dedicated process pool so API polling stays responsive.",
            "Only one optimization/re-optimization job is allowed at a time in this BFF process.",
        ],
    }


def _executor_mode() -> str:
    mode = (os.getenv("BFF_OPT_EXECUTOR") or "").strip().lower()
    if mode in {"process", "thread"}:
        return mode
    # Windows + spawn で worker が即死するケースがあるため既定は thread。
    return "thread" if os.name == "nt" else "process"


def _get_optimization_executor() -> Executor:
    global _OPTIMIZATION_EXECUTOR
    with _OPTIMIZATION_FUTURE_LOCK:
        if _OPTIMIZATION_EXECUTOR is None:
            if _executor_mode() == "thread":
                _OPTIMIZATION_EXECUTOR = ThreadPoolExecutor(max_workers=1)
            else:
                _OPTIMIZATION_EXECUTOR = ProcessPoolExecutor(
                    max_workers=1,
                    mp_context=multiprocessing.get_context("spawn"),
                )
    return _OPTIMIZATION_EXECUTOR


def shutdown_optimization_executor() -> None:
    global _OPTIMIZATION_EXECUTOR, _OPTIMIZATION_FUTURE
    with _OPTIMIZATION_FUTURE_LOCK:
        executor = _OPTIMIZATION_EXECUTOR
        _OPTIMIZATION_EXECUTOR = None
        _OPTIMIZATION_FUTURE = None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=True)


def _register_optimization_future(
    future: Future[Any],
    *,
    job_id: str,
    scenario_id: str,
    service_id: str,
    depot_id: Optional[str],
    mode: str,
    stage: str,
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
                message="Optimization worker crashed.",
                error=str(exc),
                metadata=_job_metadata(
                    scenario_id=scenario_id,
                    service_id=service_id,
                    depot_id=depot_id,
                    stage=stage,
                    mode=mode,
                    extra={"worker_failure": True},
                ),
            )
        except KeyError:
            return

    future.add_done_callback(_handle_completion)


def _submit_optimization_job(
    *,
    fn,
    args: tuple[Any, ...],
    job_id: str,
    scenario_id: str,
    service_id: str,
    depot_id: Optional[str],
    mode: str,
    stage: str,
) -> bool:
    global _OPTIMIZATION_FUTURE
    with _OPTIMIZATION_FUTURE_LOCK:
        if _OPTIMIZATION_FUTURE is not None and not _OPTIMIZATION_FUTURE.done():
            return False
        future = _get_optimization_executor().submit(fn, *args)
        _OPTIMIZATION_FUTURE = future
        _register_optimization_future(
            future,
            job_id=job_id,
            scenario_id=scenario_id,
            service_id=service_id,
            depot_id=depot_id,
            mode=mode,
            stage=stage,
        )
        return True



def _not_found(scenario_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Scenario '{scenario_id}' not found")


def _require_scenario(scenario_id: str) -> None:
    try:
        store.get_scenario(scenario_id)
        store.ensure_runtime_master_data(scenario_id)
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
    doc = store.get_scenario_document_shallow(scenario_id)
    doc["dispatch_scope"] = {**current, **scope}
    return store._normalize_dispatch_scope(doc)

def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except Exception:
        return ""


def _prepared_inputs_root() -> Path:
    return Path(__file__).resolve().parents[2] / "outputs" / "prepared_inputs"


def _persist_prepared_scope_artifacts(
    scenario_id: str,
    scenario_snapshot: Dict[str, Any],
    *,
    clear_stale_dispatch: bool = False,
) -> None:
    prepared_trips = list(scenario_snapshot.get("trips") or [])
    prepared_timetable_rows = list(
        scenario_snapshot.get("timetable_rows")
        or prepared_trips
    )
    prepared_stops = list(scenario_snapshot.get("stops") or [])
    prepared_stop_timetables = list(scenario_snapshot.get("stop_timetables") or [])
    if prepared_trips:
        store.set_field(scenario_id, "trips", prepared_trips)
    if prepared_timetable_rows:
        store.set_field(scenario_id, "timetable_rows", prepared_timetable_rows)
    if prepared_stops:
        store.set_field(scenario_id, "stops", prepared_stops)
    if prepared_stop_timetables:
        store.set_field(scenario_id, "stop_timetables", prepared_stop_timetables)
    if clear_stale_dispatch:
        store.set_field(scenario_id, "graph", {})
        store.set_field(scenario_id, "blocks", [])
        store.set_field(scenario_id, "duties", [])
        store.set_field(scenario_id, "dispatch_plan", {})


def _rebuild_dispatch_artifacts(
    scenario_id: str,
    service_id: str,
    depot_id: str,
) -> None:
    """Rebuild trips, graph, blocks, duties and dispatch_plan in one pass.

    Builds DispatchContext once and reuses it for all downstream steps,
    avoiding the O(n^2) graph analysis being repeated 4 times.
    """
    from src.dispatch.graph_builder import ConnectionGraphBuilder
    from src.dispatch.dispatcher import DispatchGenerator
    from src.dispatch.pipeline import TimetableDispatchPipeline
    from bff.routers.graph import (
        _build_dispatch_context,
        build_graph_response,
        trip_to_dict,
        vehicle_duty_to_dict,
    )

    context = _build_dispatch_context(scenario_id, service_id, depot_id)

    # Trips
    trips = [trip_to_dict(t) for t in context.trips]

    # Graph (O(n^2) — computed once)
    builder = ConnectionGraphBuilder()
    combined_graph: Dict[str, Any] = {
        "trips": trips,
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
        for rc, cnt in partial["reason_counts"].items():
            combined_graph["reason_counts"][rc] = (
                combined_graph["reason_counts"].get(rc, 0) + cnt
            )

    # Blocks (reuse context)
    generator = DispatchGenerator()
    vehicle_types = list(context.vehicle_profiles.keys())
    blocks: List[Dict[str, Any]] = []
    for vt in vehicle_types:
        for block in generator.generate_greedy_blocks(context, vt):
            blocks.append({
                "block_id": block.block_id,
                "vehicle_type": block.vehicle_type,
                "trip_ids": list(block.trip_ids),
            })

    # Duties (reuse context)
    pipeline = TimetableDispatchPipeline()
    duties: List[Dict[str, Any]] = []
    for vt in vehicle_types:
        result = pipeline.run(context, vt)
        for duty in result.duties:
            duties.append(vehicle_duty_to_dict(duty))

    # Dispatch plan (reuse blocks + duties)
    plan_blocks = [
        {
            "block_id": b["block_id"],
            "vehicle_type": b["vehicle_type"],
            "trip_ids": b["trip_ids"],
        }
        for b in blocks
    ]
    plan_duties = [
        {
            "duty_id": d["duty_id"],
            "vehicle_type": d.get("vehicle_type", "BEV"),
            "legs": d.get("legs", []),
        }
        for d in duties
    ]
    dispatch_plan = {
        "plans": [
            {
                "plan_id": f"plan_{vt}",
                "vehicle_type": vt,
                "blocks": [b for b in plan_blocks if b["vehicle_type"] == vt],
                "duties": [d for d in plan_duties if d["vehicle_type"] == vt],
                "charging_plan": [],
            }
            for vt in vehicle_types
        ],
        "total_plans": len(vehicle_types),
        "total_blocks": len(blocks),
        "total_duties": len(duties),
    }

    store.set_field(scenario_id, "trips", trips)
    store.set_field(scenario_id, "graph", combined_graph)
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


def _cost_breakdown(
    result_payload: Dict[str, Any], sim_payload: Dict[str, Any] | None
) -> Dict[str, float]:
    obj_breakdown = dict(result_payload.get("obj_breakdown") or {})
    provisional_energy = float(
        (sim_payload or {}).get("electricity_cost_provisional_jpy", 0.0)
        or 0.0
    )
    charged_energy = float(
        (sim_payload or {}).get("electricity_cost_charged_jpy", 0.0)
        or 0.0
    )
    final_energy_cost = float(
        (sim_payload or {}).get("total_energy_cost", obj_breakdown.get("electricity_cost_final"))
        or obj_breakdown.get("electricity_cost")
        or charged_energy
        or 0.0
    )
    provisional_leftover = float(
        (sim_payload or {}).get("electricity_cost_provisional_leftover_jpy", 0.0)
        or obj_breakdown.get("electricity_cost_provisional_leftover")
        or max(provisional_energy - final_energy_cost, 0.0)
    )
    return {
        "energy_cost": float(
            (sim_payload or {}).get("total_energy_cost", obj_breakdown.get("electricity_cost", 0.0))
            or 0.0
        ),
        "electricity_cost_final": final_energy_cost,
        "electricity_cost_provisional": provisional_energy,
        "electricity_cost_charged": charged_energy,
        "electricity_cost_provisional_leftover": provisional_leftover,
        "peak_demand_cost": float(
            (sim_payload or {}).get("total_demand_charge", obj_breakdown.get("demand_charge_cost", 0.0))
            or 0.0
        ),
        "vehicle_cost": float(
            (sim_payload or {}).get("total_vehicle_fixed_cost", obj_breakdown.get("vehicle_cost", 0.0))
            or 0.0
        ),
        "driver_cost": float(
            (sim_payload or {}).get("total_driver_cost", obj_breakdown.get("driver_cost", 0.0))
            or 0.0
        ),
        "deadhead_cost": float(obj_breakdown.get("deadhead_cost", 0.0) or 0.0),
        "fuel_cost": float(
            (sim_payload or {}).get("total_fuel_cost", obj_breakdown.get("fuel_cost", 0.0))
            or 0.0
        ),
        "battery_degradation_cost": float(
            (sim_payload or {}).get("total_degradation_cost", obj_breakdown.get("battery_degradation_cost", 0.0))
            or 0.0
        ),
        "grid_purchase_cost": float(obj_breakdown.get("grid_purchase_cost", 0.0) or 0.0),
        "bess_discharge_cost": float(obj_breakdown.get("bess_discharge_cost", 0.0) or 0.0),
        "grid_to_bus_kwh": float(obj_breakdown.get("grid_to_bus_kwh", 0.0) or 0.0),
        "bess_to_bus_kwh": float(obj_breakdown.get("bess_to_bus_kwh", 0.0) or 0.0),
        "pv_to_bess_kwh": float(obj_breakdown.get("pv_to_bess_kwh", 0.0) or 0.0),
        "grid_to_bess_kwh": float(obj_breakdown.get("grid_to_bess_kwh", 0.0) or 0.0),
        "stationary_battery_degradation_cost": float(
            obj_breakdown.get("stationary_battery_degradation_cost", 0.0) or 0.0
        ),
        "pv_asset_cost": float(obj_breakdown.get("pv_asset_cost", 0.0) or 0.0),
        "bess_asset_cost": float(obj_breakdown.get("bess_asset_cost", 0.0) or 0.0),
        "total_cost_with_assets": float(obj_breakdown.get("total_cost_with_assets", 0.0) or 0.0),
        "co2_cost": float(obj_breakdown.get("emission_cost", 0.0) or 0.0),
        "penalty_unserved": float(obj_breakdown.get("unserved_penalty", 0.0) or 0.0),
        "total_co2_kg": float((sim_payload or {}).get("total_co2_kg", 0.0) or 0.0),
        "total_cost": float(
            (sim_payload or {}).get("total_operating_cost", result_payload.get("objective_value", 0.0))
            or 0.0
        ),
    }


def _run_optimization(
    scenario_id: str,
    job_id: str,
    prepared_input_id: str,
    mode: str,
    time_limit_seconds: int,
    mip_gap: float,
    random_seed: int,
    service_id: str,
    depot_id: Optional[str],
    rebuild_dispatch: bool,
    use_existing_duties: bool,
    alns_iterations: int,
    no_improvement_limit: int,
    destroy_fraction: float,
) -> None:
    try:
        solver_mode = _normalize_solver_mode(mode)
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

        base_scenario = store.get_scenario_document_shallow(scenario_id)
        prepared_payload = load_prepared_input(
            scenario_id=scenario_id,
            prepared_input_id=prepared_input_id,
            scenarios_dir=_prepared_inputs_root(),
        )
        scenario = materialize_scenario_from_prepared_input(
            base_scenario,
            prepared_payload,
        )

        _persist_prepared_scope_artifacts(
            scenario_id,
            scenario,
            clear_stale_dispatch=not rebuild_dispatch and not use_existing_duties,
        )
        if rebuild_dispatch:
            _rebuild_dispatch_artifacts(scenario_id, service_id, depot_id)
        scenario["duties"] = store.get_field(scenario_id, "duties") or []
        scenario["blocks"] = store.get_field(scenario_id, "blocks") or []
        graph_meta = store.get_field(scenario_id, "graph")
        if isinstance(graph_meta, dict):
            scenario["graph"] = {k: v for k, v in graph_meta.items() if k != "arcs"}
            scenario["graph"]["arcs"] = []
        else:
            scenario["graph"] = {
                "source": "prepared_scope",
                "total_arcs": 0,
                "feasible_arcs": 0,
                "infeasible_arcs": 0,
            }
        feed_context = _scenario_feed_context(scenario_id)
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
            mode=solver_mode,
            use_existing_duties=use_existing_duties,
            analysis_scope=scenario.get("dispatch_scope") or store.get_dispatch_scope(scenario_id),
        )
        store.set_field(scenario_id, "problemdata_build_audit", build_report.to_dict())
        price_slots = list(getattr(data, "electricity_prices", []) or [])
        pv_slots = list(getattr(data, "pv_profiles", []) or [])

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
                        "trips": len(getattr(data, "tasks", []) or []),
                        "vehicles": len(getattr(data, "vehicles", []) or []),
                        "chargers": len(getattr(data, "chargers", []) or []),
                        "price_slots": len(price_slots),
                        "pv_slots": len(pv_slots),
                    }
                },
            ),
        )
        solve_output = solve_problem_data(
            data,
            mode=solver_mode,
            time_limit_seconds=time_limit_seconds,
            mip_gap=mip_gap,
            random_seed=random_seed,
            output_dir=_scoped_output_dir(
                root="outputs",
                feed_context=feed_context,
                scenario_id=scenario_id,
                stage="optimization",
                service_id=service_id,
                depot_id=depot_id,
            ),
            alns_iterations=alns_iterations,
            no_improvement_limit=no_improvement_limit,
            destroy_fraction=destroy_fraction,
        )
        output_dir = _scoped_output_dir(
            root="outputs",
            feed_context=feed_context,
            scenario_id=scenario_id,
            stage="optimization",
            service_id=service_id,
            depot_id=depot_id,
        )
        result_payload = serialize_milp_result(solve_output["result"])
        sim_payload = (
            serialize_simulation_result(solve_output["sim_result"])
            if solve_output.get("sim_result") is not None
            else None
        )
        vehicle_type_by_id = {
            vehicle.vehicle_id: vehicle.vehicle_type
            for vehicle in data.vehicles
        }
        vehicle_count_by_type: Dict[str, int] = {}
        trip_count_by_type: Dict[str, int] = {}
        for vehicle_id, task_ids in (result_payload.get("assignment") or {}).items():
            if not task_ids:
                continue
            vehicle_type = str(vehicle_type_by_id.get(vehicle_id) or "UNKNOWN")
            vehicle_count_by_type[vehicle_type] = vehicle_count_by_type.get(vehicle_type, 0) + 1
            trip_count_by_type[vehicle_type] = trip_count_by_type.get(vehicle_type, 0) + len(task_ids)
        objective_mode = str(
            (
                ((scenario.get("scenario_overlay") or {}).get("solver_config") or {}).get("objective_mode")
                or (scenario.get("simulation_config") or {}).get("objective_mode")
                or "total_cost"
            )
        )

        optimization_result: Dict[str, Any] = {
            "scenario_id": scenario_id,
            "feed_context": feed_context,
            "scope": {"serviceId": service_id, "depotId": depot_id},
            "prepared_input_id": prepared_input_id,
            "prepared_scope_summary": dict(scenario.get("prepared_scope_summary") or {}),
            "solver_status": result_payload["status"],
            "mode": mode,
            "solver_mode": solver_mode,
            "objective_mode": objective_mode,
            "objective_value": result_payload.get("objective_value"),
            "solve_time_seconds": result_payload.get("solve_time_seconds", 0.0),
            "mip_gap": result_payload.get("mip_gap"),
            "electricity_cost_basis": str(
                (sim_payload or {}).get("electricity_cost_basis") or "provisional_drive"
            ),
            "cost_breakdown": _cost_breakdown(result_payload, sim_payload),
            "dispatch_report": scenario.get("graph") or store.get_field(scenario_id, "graph") or {},
            "build_report": build_report.to_dict(),
            "summary": {
                "vehicle_count_used": sum(
                    1
                    for _vehicle_id, task_ids in (
                        result_payload.get("assignment") or {}
                    ).items()
                    if task_ids
                ),
                "vehicle_count_by_type": vehicle_count_by_type,
                "trip_count_by_type": trip_count_by_type,
                "trip_count_served": sum(
                    len(task_ids)
                    for task_ids in (result_payload.get("assignment") or {}).values()
                ),
                "trip_count_unserved": len(result_payload.get("unserved_tasks") or []),
            },
            "solver_result": result_payload,
            "canonical_problem_summary": {
                "trip_count": len(getattr(data, "tasks", []) or []),
                "vehicle_count": len(getattr(data, "vehicles", []) or []),
                "charger_count": len(getattr(data, "chargers", []) or []),
                "price_slot_count": len(price_slots),
                "pv_slot_count": len(pv_slots),
            },
        }
        if sim_payload is not None:
            optimization_result["simulation_summary"] = sim_payload

        optimization_audit = {
            "scenario_id": scenario_id,
            "feed_context": feed_context,
            "depot_id": depot_id,
            "service_id": service_id,
            "prepared_input_id": prepared_input_id,
            "prepared_scope_summary": dict(scenario.get("prepared_scope_summary") or {}),
            "case_type": scenario.get("experiment_case_type"),
            "input_counts": {
                "vehicles": build_report.vehicle_count,
                "tasks": build_report.task_count,
                "travel_connections": build_report.travel_connection_count,
            },
            "output_counts": {
                "assigned_vehicles": optimization_result["summary"][
                    "vehicle_count_used"
                ],
                "served_trips": optimization_result["summary"]["trip_count_served"],
                "unserved_trips": optimization_result["summary"]["trip_count_unserved"],
            },
            "warnings": build_report.warnings,
            "errors": build_report.errors,
            "solver_mode": mode,
            "solver_mode_effective": solver_mode,
            "time_limit": time_limit_seconds,
            "mip_gap": mip_gap,
            "random_seed": random_seed,
            "gurobi_seed": random_seed,
            "alns_iterations": alns_iterations,
            "no_improvement_limit": no_improvement_limit,
            "destroy_fraction": destroy_fraction,
            "git_sha": _git_sha(),
            "source_snapshot": store.get_field(scenario_id, "source_snapshot"),
            "output_dir": output_dir,
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            experiment_report = log_optimization_experiment(
                scenario_id=scenario_id,
                scenario_doc=scenario,
                optimization_result=optimization_result,
            )
            optimization_result["experiment_report"] = experiment_report
            optimization_audit["experiment_report"] = {
                "experiment_id": experiment_report.get("experiment_id"),
                "json_path": experiment_report.get("json_path"),
                "md_path": experiment_report.get("md_path"),
            }
        except Exception as exc:
            warnings = list(optimization_audit.get("warnings") or [])
            warnings.append(f"Experiment report generation failed: {exc}")
            optimization_audit["warnings"] = warnings
        optimization_result["audit"] = optimization_audit

        store.set_field(scenario_id, "optimization_result", optimization_result)
        store.set_field(scenario_id, "optimization_audit", optimization_audit)
        _persist_json_outputs(
            output_dir,
            {
                "optimization_result.json": optimization_result,
                "optimization_audit.json": optimization_audit,
            },
        )
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
                    "feed_context": feed_context,
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
    if normalized in {"ga", "mode_ga_only"}:
        return OptimizationMode.GA
    if normalized in {"abc", "mode_abc_only"}:
        return OptimizationMode.ABC
    return OptimizationMode.HYBRID


def _normalize_solver_mode(mode: str) -> str:
    normalized = (mode or "").strip().lower()
    alias_map = {
        "milp": "mode_milp_only",
        "exact": "mode_milp_only",
        "alns": "mode_alns_only",
        "heuristic": "mode_alns_only",
        "hybrid": "mode_alns_milp",
        "ga": "mode_ga_only",
        "abc": "mode_abc_only",
    }
    return alias_map.get(normalized, mode)


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
    body_payload: Dict[str, Any],
    prepared_input_id: str,
    service_id: str,
    depot_id: Optional[str],
) -> None:
    body = ReoptimizeBody(**body_payload)
    mode = body.mode
    try:
        if not depot_id:
            raise ValueError("No depot selected. Configure dispatch scope first.")

        base_scenario = store.get_scenario_document_shallow(scenario_id)
        prepared_payload = load_prepared_input(
            scenario_id=scenario_id,
            prepared_input_id=prepared_input_id,
            scenarios_dir=_prepared_inputs_root(),
        )
        scenario = _apply_reoptimization_inputs(
            materialize_scenario_from_prepared_input(base_scenario, prepared_payload),
            body,
        )
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
            random_seed=body.random_seed,
            alns_iterations=body.alns_iterations,
            no_improvement_limit=body.no_improvement_limit,
            destroy_fraction=body.destroy_fraction,
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
                "random_seed": body.random_seed,
                "gurobi_seed": body.random_seed,
                "executed_at": datetime.now(timezone.utc).isoformat(),
                "git_sha": _git_sha(),
                "source_snapshot": store.get_field(scenario_id, "source_snapshot"),
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
    if isinstance(result, dict) and "audit" not in result:
        audit = store.get_field(scenario_id, "optimization_audit")
        if audit is not None:
            result = {**result, "audit": audit}
    if isinstance(result, dict) and "electricity_cost_basis" not in result:
        simulation_summary = dict(result.get("simulation_summary") or {})
        result = {
            **result,
            "electricity_cost_basis": str(
                simulation_summary.get("electricity_cost_basis") or "provisional_drive"
            ),
        }
    return result


@router.get("/scenarios/{scenario_id}/optimization/capabilities")
def get_optimization_capabilities(scenario_id: str) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    return _optimization_capabilities()


@router.post("/scenarios/{scenario_id}/run-optimization")
def run_optimization(
    scenario_id: str,
    body: Optional[RunOptimizationBody] = None,
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    scenario = store.get_scenario_document_shallow(scenario_id)
    prep = get_or_build_run_preparation(
        scenario=scenario,
        built_dir=Path(_app_state.get("built_dir") or "data/built/tokyu_core"),
        scenarios_dir=_prepared_inputs_root(),
        routes_df=_app_state.get("routes_df"),
    )
    if not prep.is_valid:
        raise HTTPException(
            status_code=500,
            detail=make_error(
                AppErrorCode.SCENARIO_INCOMPLETE,
                f"Run preparation failed: {prep.error}",
            ),
        )
    _require_nonempty_prepared_scope(prep, action="Optimization preflight")
    request = body or RunOptimizationBody()
    if request.prepared_input_id and prep.prepared_input_id != request.prepared_input_id:
        raise HTTPException(
            status_code=409,
            detail=make_error(
                AppErrorCode.SCENARIO_INCOMPLETE,
                "Prepared input is stale. Run prepare again before starting optimization.",
                preparedInputId=request.prepared_input_id,
                currentPreparedInputId=prep.prepared_input_id,
            ),
        )
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
    submitted = _submit_optimization_job(
        fn=_run_optimization,
        args=(
            scenario_id,
            job.job_id,
            prep.prepared_input_id or "",
            request.mode,
            request.time_limit_seconds,
            request.mip_gap,
            request.random_seed,
            scope.get("serviceId") or "WEEKDAY",
            scope.get("depotId"),
            request.rebuild_dispatch,
            request.use_existing_duties,
            request.alns_iterations,
            request.no_improvement_limit,
            request.destroy_fraction,
        ),
        job_id=job.job_id,
        scenario_id=scenario_id,
        service_id=scope.get("serviceId") or "WEEKDAY",
        depot_id=scope.get("depotId"),
        mode=request.mode,
        stage="worker_crashed",
    )
    if not submitted:
        job_store.update_job(
            job.job_id,
            status="failed",
            progress=100,
            message="Rejected because another optimization job is already running.",
            error="job_already_running",
        )
        raise HTTPException(
            status_code=503,
            detail=make_error(
                AppErrorCode.EXECUTION_IN_PROGRESS,
                "An optimization job is already running. Please retry after it completes.",
            ),
        )
    return job_store.job_to_dict(job)


@router.post("/scenarios/{scenario_id}/reoptimize")
def reoptimize(
    scenario_id: str,
    body: ReoptimizeBody,
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    scenario = store.get_scenario_document_shallow(scenario_id)
    prep = get_or_build_run_preparation(
        scenario=scenario,
        built_dir=Path(_app_state.get("built_dir") or "data/built/tokyu_core"),
        scenarios_dir=_prepared_inputs_root(),
        routes_df=_app_state.get("routes_df"),
    )
    if not prep.is_valid:
        raise HTTPException(
            status_code=500,
            detail=make_error(
                AppErrorCode.SCENARIO_INCOMPLETE,
                f"Run preparation failed: {prep.error}",
            ),
        )
    _require_nonempty_prepared_scope(prep, action="Re-optimization preflight")
    if body.prepared_input_id and prep.prepared_input_id != body.prepared_input_id:
        raise HTTPException(
            status_code=409,
            detail=make_error(
                AppErrorCode.SCENARIO_INCOMPLETE,
                "Prepared input is stale. Run prepare again before starting re-optimization.",
                preparedInputId=body.prepared_input_id,
                currentPreparedInputId=prep.prepared_input_id,
            ),
        )
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
    submitted = _submit_optimization_job(
        fn=_run_reoptimization,
        args=(
            scenario_id,
            job.job_id,
            body.model_dump(),
            prep.prepared_input_id or "",
            scope.get("serviceId") or "WEEKDAY",
            scope.get("depotId"),
        ),
        job_id=job.job_id,
        scenario_id=scenario_id,
        service_id=scope.get("serviceId") or "WEEKDAY",
        depot_id=scope.get("depotId"),
        mode=body.mode,
        stage="reopt_worker_crashed",
    )
    if not submitted:
        job_store.update_job(
            job.job_id,
            status="failed",
            progress=100,
            message="Rejected because another optimization job is already running.",
            error="job_already_running",
        )
        raise HTTPException(
            status_code=503,
            detail=make_error(
                AppErrorCode.EXECUTION_IN_PROGRESS,
                "An optimization job is already running. Please retry after it completes.",
            ),
        )
    return job_store.job_to_dict(job)
