"""
bff/routers/optimization.py

Optimization endpoints:
  GET   /scenarios/{id}/optimization            → get optimization result
  POST  /scenarios/{id}/run-optimization        → async: run MILP/ALNS optimizer
"""

from __future__ import annotations

import traceback
import json
import csv
import math
import shutil
from dataclasses import is_dataclass, replace
from collections import Counter, defaultdict
import threading
import multiprocessing
import os
import time
from concurrent.futures import Executor, Future, ProcessPoolExecutor, ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from bff.dependencies import require_built
from bff.errors import AppErrorCode, make_error
from bff.mappers.scenario_to_problemdata import (
    ScenarioBuildReport,
    build_problem_data_from_scenario,
)
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
from bff.services.optimization_run.canonical_graph import (
    canonical_datetime_from_min as _canonical_datetime_from_min,
    canonical_deadhead_distance_km as _canonical_deadhead_distance_km,
    canonical_estimated_deadhead_energy_kwh as _canonical_estimated_deadhead_energy_kwh,
    canonical_horizon_start_min as _canonical_horizon_start_min,
    canonical_output_base_date as _canonical_output_base_date,
    canonical_slot_datetime as _canonical_slot_datetime,
    canonical_vehicle_initial_soc_kwh as _canonical_vehicle_initial_soc_kwh,
)
from bff.services.optimization_run.cost_breakdown import (
    canonical_cost_breakdown_json as _canonical_cost_breakdown_json,
    cost_breakdown as _cost_breakdown,
)
from bff.services.optimization_run.execute import (
    normalize_solver_mode as _normalize_solver_mode,
    parse_optimization_mode as _parse_optimization_mode,
    phase_from_solver_mode as _phase_from_solver_mode,
)
from bff.services.optimization_run.input_provenance import (
    MANIFEST_FILE as RUN_INPUT_MANIFEST_FILE,
    collect_git_state,
    persist_run_input_provenance,
)
from bff.services.optimization_run.rich_outputs import (
    persist_json_outputs as _persist_json_outputs,
    run_stamp as _run_stamp,
    service_date_for_output as _service_date_for_output,
    write_csv_rows as _write_csv_rows,
)
from bff.services.optimization_run.weather import (
    configured_service_date as _configured_service_date,
    load_weather_proxy_for_bff as _load_weather_proxy_for_bff,
    preflight_weather_proxy_request as _preflight_weather_proxy_request,
    prepare_weather_policy_for_scenario as _prepare_weather_policy_for_scenario,
    resolve_weather_proxy_path as _resolve_weather_proxy_path,
    weather_policy_payload_from_problem_metadata as _weather_policy_payload_from_problem_metadata,
    weather_policy_requested as _weather_policy_requested,
    weather_proxy_http_error as _weather_proxy_http_error,
)
from bff.services.run_preparation import (
    get_or_build_run_preparation,
    load_prepared_input,
    materialize_scenario_from_prepared_input,
)
from bff.services.optimization_run.vehicle_timeline import vehicle_ids_with_timeline_activity
from bff.store import job_store, output_paths, scenario_store as store
from src.dispatch.models import hhmm_to_min
from src.optimization import (
    OptimizationConfig,
    OptimizationEngine,
    ProblemBuilder,
    ResultSerializer,
)
from src.optimization.common.energy_flow_accounting import (
    compute_pv_curtail_kwh,
    compute_pv_utilization_rate,
    normalize_pv_energy_breakdown,
)
from src.optimization.common.time_axis import normalize_timestep_min
from src.optimization.rolling.reoptimizer import (
    RollingReoptimizer,
    assignment_plan_from_serialized_result,
)
from src.optimization.common.bess_terminal_policy import (
    resolve_bess_terminal_soc_target_kwh,
)
from src.preprocess.weather.operation_policy import apply_weather_policy_to_problem
from src.run_output_layout import allocate_run_dir
from src.pipeline.solve import solve_problem_data

router = APIRouter(tags=["optimization"])
_OPTIMIZATION_EXECUTOR: Optional[Executor] = None

# Interactive BFF/Tk launches are used for comparable research runs.  Keep
# this policy at the BFF boundary so a stale client payload cannot silently
# re-enable the Stage 1 early-stop rule or vary Gurobi parallelism.  The formal
# CLI runner remains independently configurable for non-interactive studies.
INTERACTIVE_RUNTIME_POLICY_VERSION = "interactive_runtime_controls_v1"
INTERACTIVE_STAGE1_BEST_OBJ_STOP_ENABLED = False
INTERACTIVE_GUROBI_THREADS = 1
INTERACTIVE_TERMINAL_SOC_POLICY_VERSION = "interactive_terminal_soc_controls_v1"
INTERACTIVE_BEV_TERMINAL_SOC_POLICY = "return_to_initial"
INTERACTIVE_OPERATION_TIME_WINDOW_CONTROLS_VERSION = (
    "interactive_operation_time_window_controls_v1"
)
FULL_DAY_OPERATION_START_TIME = "00:00"
FULL_DAY_OPERATION_END_TIME = "23:59"


def _interactive_runtime_controls_payload(
    *,
    requested_stage1_best_obj_stop_enabled: Any,
    requested_gurobi_threads: Any,
) -> Dict[str, Any]:
    """Describe the server-enforced solver controls for an interactive run."""

    requested = {
        "stage1_best_obj_stop_enabled": bool(
            requested_stage1_best_obj_stop_enabled
        ),
        "gurobi_threads": requested_gurobi_threads,
    }
    effective = {
        "stage1_best_obj_stop_enabled": INTERACTIVE_STAGE1_BEST_OBJ_STOP_ENABLED,
        "gurobi_threads": INTERACTIVE_GUROBI_THREADS,
    }
    return {
        "policy_version": INTERACTIVE_RUNTIME_POLICY_VERSION,
        "scope": "interactive_bff_run_optimization",
        "enforced": True,
        "requested": requested,
        "effective": effective,
        "override_applied": requested != effective,
        "reason": (
            "Interactive runs disable Stage 1 BestObjStop and use one Gurobi "
            "thread so their solver controls are recorded consistently."
        ),
    }


def _apply_interactive_bev_terminal_soc_policy(
    scenario: Dict[str, Any],
) -> Dict[str, Any]:
    """Enforce energy-neutral BEV terminal SOC for interactive day-ahead runs.

    A fixed percentage terminal target lets vehicles with heterogeneous initial
    SOC contribute or retain inventory across the representative day.  That
    makes a daily high-PV/low-PV cost comparison non-neutral.  The interactive
    path therefore applies the per-vehicle ``return_to_initial`` policy after
    all scenario/weather overlays and before ``ProblemBuilder`` is called.
    The formal CLI remains explicit and independently configurable.
    """

    simulation_config = scenario.get("simulation_config")
    if not isinstance(simulation_config, dict):
        simulation_config = {}
        scenario["simulation_config"] = simulation_config

    scenario_overlay = scenario.get("scenario_overlay")
    charging_constraints: Dict[str, Any] = {}
    if isinstance(scenario_overlay, dict):
        candidate = scenario_overlay.get("charging_constraints")
        if isinstance(candidate, dict):
            charging_constraints = candidate

    terminal_fields = (
        "bev_terminal_soc_policy",
        "terminal_soc_policy",
        "final_soc_target_percent",
        "final_soc_target_tolerance_percent",
    )
    requested = {
        "simulation_config": {
            field: simulation_config.get(field) for field in terminal_fields
        },
        "charging_constraints": {
            field: charging_constraints.get(field) for field in terminal_fields
        },
    }

    # Set the policy in the source with builder precedence and clear legacy
    # fixed-target inputs.  ``None`` deliberately masks an inherited overlay
    # because ProblemBuilder's _first_present treats it as the explicit value.
    simulation_config["bev_terminal_soc_policy"] = INTERACTIVE_BEV_TERMINAL_SOC_POLICY
    simulation_config["terminal_soc_policy"] = INTERACTIVE_BEV_TERMINAL_SOC_POLICY
    simulation_config["final_soc_target_percent"] = None
    simulation_config["final_soc_target_tolerance_percent"] = None
    if charging_constraints:
        charging_constraints["bev_terminal_soc_policy"] = INTERACTIVE_BEV_TERMINAL_SOC_POLICY
        charging_constraints["terminal_soc_policy"] = INTERACTIVE_BEV_TERMINAL_SOC_POLICY
        charging_constraints["final_soc_target_percent"] = None
        charging_constraints["final_soc_target_tolerance_percent"] = None

    effective = {
        "bev_terminal_soc_policy": INTERACTIVE_BEV_TERMINAL_SOC_POLICY,
        "terminal_soc_policy": INTERACTIVE_BEV_TERMINAL_SOC_POLICY,
        "final_soc_target_percent": None,
        "final_soc_target_tolerance_percent": None,
    }
    requested_policy = requested["simulation_config"].get(
        "bev_terminal_soc_policy"
    ) or requested["charging_constraints"].get("bev_terminal_soc_policy")
    requested_target = requested["simulation_config"].get(
        "final_soc_target_percent"
    )
    if requested_target is None:
        requested_target = requested["charging_constraints"].get(
            "final_soc_target_percent"
        )
    requested_tolerance = requested["simulation_config"].get(
        "final_soc_target_tolerance_percent"
    )
    if requested_tolerance is None:
        requested_tolerance = requested["charging_constraints"].get(
            "final_soc_target_tolerance_percent"
        )
    return {
        "policy_version": INTERACTIVE_TERMINAL_SOC_POLICY_VERSION,
        "scope": "interactive_bff_run_optimization",
        "enforced": True,
        "requested": requested,
        "effective": effective,
        "override_applied": bool(
            requested_policy != INTERACTIVE_BEV_TERMINAL_SOC_POLICY
            or requested_target is not None
            or requested_tolerance is not None
        ),
        "reason": (
            "Interactive day-ahead runs enforce per-vehicle return_to_initial "
            "BEV terminal SOC so representative-day energy and cost comparisons "
            "do not consume or create BEV inventory."
        ),
    }


def _coerce_bool(value: Any, *, default: bool) -> bool:
    """Parse persisted/UI booleans without treating an invalid string as true."""

    if value is None:
        return bool(default)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return bool(default)
    return bool(value)


def _apply_interactive_operation_time_window_controls(
    scenario: Dict[str, Any],
) -> Dict[str, Any]:
    """Materialize the front-end time-window intent before canonical build.

    The start/end pair is retained as the user's requested pair even when the
    checkbox is disabled.  In that case this function writes separate effective
    fields and a 24-hour horizon, while ``ProblemBuilder`` independently enforces
    the same full-day semantics.  Keeping both representations makes a later
    artifact review distinguish user input from solver input.
    """

    simulation_config = scenario.get("simulation_config")
    if not isinstance(simulation_config, dict):
        simulation_config = {}
        scenario["simulation_config"] = simulation_config

    requested_enabled = simulation_config.get("operation_time_window_enabled")
    if requested_enabled is None:
        requested_enabled = simulation_config.get("operationTimeWindowEnabled")
    # Prepared inputs created before this feature retain their established
    # scoped-time behavior.  Tk Prepare writes the flag explicitly.
    enabled = _coerce_bool(requested_enabled, default=True)
    requested_start_time = str(
        simulation_config.get("start_time") or "05:00"
    )
    requested_end_time = str(
        simulation_config.get("end_time") or "23:00"
    )
    planning_days = max(int(simulation_config.get("planning_days") or 1), 1)
    effective_start_time = (
        requested_start_time if enabled else FULL_DAY_OPERATION_START_TIME
    )
    effective_end_time = (
        requested_end_time if enabled else FULL_DAY_OPERATION_END_TIME
    )

    simulation_config["operation_time_window_enabled"] = enabled
    simulation_config["operation_time_window_effective_start_time"] = (
        effective_start_time
    )
    simulation_config["operation_time_window_effective_end_time"] = (
        effective_end_time
    )
    if not enabled:
        simulation_config["planning_horizon_hours"] = 24.0 * float(planning_days)

    return {
        "schema_version": INTERACTIVE_OPERATION_TIME_WINDOW_CONTROLS_VERSION,
        "scope": "interactive_bff_run_optimization",
        "requested": {
            "operation_time_window_enabled": requested_enabled,
            "start_time": requested_start_time,
            "end_time": requested_end_time,
        },
        "effective": {
            "operation_time_window_enabled": enabled,
            "start_time": effective_start_time,
            "end_time": effective_end_time,
            "planning_horizon_hours": (
                24.0 * float(planning_days)
                if not enabled
                else simulation_config.get("planning_horizon_hours")
            ),
        },
        "full_day_horizon_forced": not enabled,
        "reason": (
            "The start/end pair is inactive; canonical optimization uses the "
            "complete 00:00-23:59 calendar day."
            if not enabled
            else "The explicitly enabled start/end pair scopes the optimization horizon."
        ),
    }
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


def _request_timestep_min(*values: Any) -> Optional[int]:
    raw = next((value for value in values if value is not None), None)
    if raw is None:
        return None
    try:
        return normalize_timestep_min(raw, default=30)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=make_error(
                AppErrorCode.SCHEMA_VALIDATION_ERROR,
                str(exc),
                field="timestep_min",
                allowed=[30, 60],
            ),
        ) from exc


def _apply_timestep_min_to_scenario(scenario: Dict[str, Any], timestep_min: Optional[int]) -> None:
    if timestep_min is None:
        return
    sim_cfg = scenario.get("simulation_config")
    if not isinstance(sim_cfg, dict):
        sim_cfg = {}
        scenario["simulation_config"] = sim_cfg
    sim_cfg["time_step_min"] = timestep_min
    sim_cfg["timestep_min"] = timestep_min


class RunOptimizationBody(BaseModel):
    mode: str = "thesis_mode"
    research_run: bool = False
    time_step_min: Optional[int] = None
    timestep_min: Optional[int] = None
    time_limit_seconds: int = 300
    stage1_time_limit_seconds: Optional[int] = None
    stage2_time_limit_seconds: Optional[int] = None
    # These interactive defaults are also enforced by _run_optimization so an
    # older client cannot restore the early stop or a machine-dependent thread
    # count through a request body.
    stage1_best_obj_stop_enabled: bool = INTERACTIVE_STAGE1_BEST_OBJ_STOP_ENABLED
    gurobi_threads: Optional[int] = Field(
        default=INTERACTIVE_GUROBI_THREADS,
        ge=1,
    )
    mip_gap: float = 0.01
    random_seed: int = 42
    prepared_input_id: Optional[str] = None
    service_id: Optional[str] = None
    depot_id: Optional[str] = None
    rebuild_dispatch: bool = True
    force_reprepare: bool = False
    use_existing_duties: bool = False
    alns_iterations: int = 500
    no_improvement_limit: int = 100
    destroy_fraction: float = 0.25
    weatherProxyForecastPath: Optional[str] = None
    enableWeatherOperationPolicy: Optional[bool] = None


class DelayEventBody(BaseModel):
    trip_id: str
    delay_min: float


class ReoptimizeBody(BaseModel):
    mode: str = "hybrid"
    research_run: bool = False
    current_time: str
    time_step_min: Optional[int] = None
    timestep_min: Optional[int] = None
    time_limit_seconds: int = 180
    mip_gap: float = 0.02
    random_seed: int = 42
    alns_iterations: int = 300
    no_improvement_limit: int = 100
    destroy_fraction: float = 0.25
    prepared_input_id: Optional[str] = None
    service_id: Optional[str] = None
    depot_id: Optional[str] = None
    actual_soc: Dict[str, float] = Field(default_factory=dict)
    actual_bess_soc_kwh: Dict[str, float] = Field(default_factory=dict)
    observed_on_peak_kw_by_depot: Dict[str, float] = Field(default_factory=dict)
    observed_off_peak_kw_by_depot: Dict[str, float] = Field(default_factory=dict)
    actual_location_node_id: Dict[str, str] = Field(default_factory=dict)
    delays: list[DelayEventBody] = Field(default_factory=list)
    updated_pv_profile: list[Dict[str, Any]] = Field(default_factory=list)
    reoptimization_strategy: str = "generic"
    execution_minutes: int = Field(default=60, ge=1)
    bess_terminal_policy: str = "scenario"


def _optimization_capabilities() -> Dict[str, Any]:
    return {
        "implemented": True,
        "async_job": True,
        "job_persistence": dict(job_store.JOB_PERSISTENCE_INFO),
        "supported_modes": [
            "thesis_mode",
            "debug_mode",
            "mode_milp_only",
            "mode_alns_only",
            "mode_ga_only",
            "mode_abc_only",
            "mode_hybrid",
            "phase1_charging_only",
            "phase2_assignment_only",
            "phase3_two_stage",
            "phase4_integrated",
            "diagnostic",
        ],
        "mode_aliases": {
            "milp": "mode_milp_only",
            "exact": "mode_milp_only",
            "thesis": "thesis_mode",
            "debug": "debug_mode",
            "alns": "mode_alns_only",
            "heuristic": "mode_alns_only",
            "ga": "mode_ga_only",
            "genetic": "mode_ga_only",
            "abc": "mode_abc_only",
            "colony": "mode_abc_only",
            "hybrid": "mode_hybrid",
            "phase1": "phase1_charging_only",
            "phase2": "phase2_assignment_only",
            "phase3": "phase3_two_stage",
            "phase4": "phase4_integrated",
            "diagnostic_mode": "diagnostic",
        },
        "deprecated_modes": {
            "mode_alns_milp": "mode_hybrid (auto-routed)",
            "mode_a_journey_charge": "BLOCKED - no longer supported",
            "mode_b_optimistic": "BLOCKED - no longer supported",
        },
        "default_mode": "thesis_mode",
        "interactive_runtime_controls": {
            "policy_version": INTERACTIVE_RUNTIME_POLICY_VERSION,
            "stage1_best_obj_stop_enabled": INTERACTIVE_STAGE1_BEST_OBJ_STOP_ENABLED,
            "gurobi_threads": INTERACTIVE_GUROBI_THREADS,
            "enforced_server_side": True,
        },
        "interactive_terminal_soc_controls": {
            "policy_version": INTERACTIVE_TERMINAL_SOC_POLICY_VERSION,
            "bev_terminal_soc_policy": INTERACTIVE_BEV_TERMINAL_SOC_POLICY,
            "enforced_server_side": True,
        },
        "authoritative_engine": "canonical (src/optimization/)",
        "supports_reoptimization": True,
        "max_concurrent_jobs": 1,
        "execution_model": f"{_executor_mode()}_pool",
        "notes": [
            "All supported modes use the canonical optimization engine (src/optimization/).",
            "thesis_mode runs the canonical two-stage MILP without unserved decision variables or postsolve repair.",
            "debug_mode keeps diagnostic unserved variables and is not eligible for research KPI claims.",
            "Phase 1 requires a concrete fixed assignment with duties before charging/PV/BESS optimization.",
            "Phase 2 returns assignment-only MILP results; charging/SOC feasibility is explicitly not evaluated.",
            "diagnostic is diagnostic-only and is never eligible for research KPI claims.",
            "mode_alns_milp is auto-routed to mode_hybrid (ALNS+MILP hybrid).",
            "Optimization runs against canonical CanonicalOptimizationProblem built from scenario.",
            "Dispatch artifacts can be rebuilt before solve when requested.",
            "Results are persisted to the scenario snapshot; job state is not.",
            "Optimization/re-optimization runs in a dedicated executor so API polling stays responsive.",
            "Only one optimization/re-optimization job is allowed at a time in this BFF process.",
            "Interactive /run-optimization enforces Stage 1 BestObjStop=OFF and Gurobi Threads=1; the formal CLI runner remains explicit.",
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
        future = _OPTIMIZATION_FUTURE
        _OPTIMIZATION_EXECUTOR = None
        _OPTIMIZATION_FUTURE = None
    if future is not None and not future.done():
        future.cancel()
    if executor is not None:
        executor.shutdown(wait=True, cancel_futures=True)


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
            import logging
            logging.getLogger("bff.optimization").error(
                "Failed to update job %s status to failed (job may have been cleaned up). "
                "Worker error: %s",
                job_id, exc,
            )
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
    """Return the current SHA when provenance collection succeeds.

    Legacy call sites consume a string, while rich artifacts additionally emit
    the full explicit state through :func:`collect_git_state`.
    """

    return str(collect_git_state().get("git_sha") or "")


def _prepared_inputs_root() -> Path:
    return output_paths.outputs_root() / "prepared_inputs"


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
    return str(allocate_run_dir(root))


def _dated_scenario_run_dir(
    *,
    scenario: Dict[str, Any],
    scenario_id: str,
    mode: str,
    service_id: str,
    depot_id: Optional[str],
) -> Path:
    root = output_paths.outputs_root()
    return allocate_run_dir(root)


def _normalize_depot_slot_mapping(raw: Any) -> Dict[str, Dict[int, float]]:
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[int, float]] = {}
    for depot_id, slot_map in raw.items():
        if isinstance(slot_map, dict):
            out[str(depot_id)] = {
                int(slot_idx): float(value or 0.0)
                for slot_idx, value in slot_map.items()
            }
        elif isinstance(slot_map, list):
            out[str(depot_id)] = {
                int(slot_idx): float(value or 0.0)
                for slot_idx, value in enumerate(slot_map)
            }
    return out


def _mapping_has_positive_flow(mapping: Dict[str, Dict[int, float]]) -> bool:
    return any(
        max(float(value or 0.0), 0.0) > 0.0
        for slot_map in mapping.values()
        for value in slot_map.values()
    )


def _depot_mapping_has_positive_flow(
    mapping: Dict[str, Dict[int, float]],
    depot_id: str,
) -> bool:
    return any(max(float(value or 0.0), 0.0) > 0.0 for value in (mapping.get(str(depot_id)) or {}).values())


def _canonical_vehicle_home_depot_map(problem) -> Dict[str, str]:
    return {
        str(getattr(vehicle, "vehicle_id", "") or ""): str(getattr(vehicle, "home_depot_id", "") or "")
        for vehicle in list(getattr(problem, "vehicles", ()) or ())
    }


def _canonical_charging_source_and_depot(
    problem,
    charging_slot,
) -> tuple[str, str]:
    vehicle_home_depot = _canonical_vehicle_home_depot_map(problem)
    fallback_depot = str(
        getattr(charging_slot, "charging_depot_id", "") or vehicle_home_depot.get(str(getattr(charging_slot, "vehicle_id", "") or ""), "")
    ).strip()
    raw = str(getattr(charging_slot, "charger_id", "") or "")
    if ":" in raw:
        source, depot_id = raw.split(":", 1)
        normalized_source = source.strip().lower()
        if normalized_source in {"grid", "pv", "bess"}:
            return normalized_source, depot_id.strip() or fallback_depot or "depot_default"
    return "grid", fallback_depot or "depot_default"


def _canonical_charging_slot_signature(charging_slot) -> tuple[str, int, str, str]:
    return (
        str(getattr(charging_slot, "vehicle_id", "") or ""),
        int(getattr(charging_slot, "slot_index", 0) or 0),
        str(getattr(charging_slot, "charger_id", "") or ""),
        str(getattr(charging_slot, "charging_depot_id", "") or ""),
    )


def _merge_depot_slot_flow_maps(
    base: Dict[str, Dict[int, float]],
    additions: Dict[str, Dict[int, float]],
) -> Dict[str, Dict[int, float]]:
    merged = {depot_id: dict(slot_map) for depot_id, slot_map in base.items()}
    for depot_id, slot_map in additions.items():
        if not slot_map:
            continue
        target = merged.setdefault(depot_id, {})
        for slot_idx, value in slot_map.items():
            target[slot_idx] = float(target.get(slot_idx, 0.0) or 0.0) + float(value or 0.0)
    return merged


def _bess_soc_bounds_for_asset(asset: Any) -> tuple[float, float, float] | None:
    capacity = max(float(getattr(asset, "bess_energy_kwh", 0.0) or 0.0), 0.0)
    configured_max = max(float(getattr(asset, "bess_soc_max_kwh", 0.0) or 0.0), 0.0)
    if configured_max > 0.0:
        max_soc = min(configured_max, capacity) if capacity > 0.0 else configured_max
    else:
        max_soc = capacity
    if max_soc <= 1.0e-9:
        return None
    min_soc = min(max(float(getattr(asset, "bess_soc_min_kwh", 0.0) or 0.0), 0.0), max_soc)
    initial_soc = min(max(float(getattr(asset, "bess_initial_soc_kwh", 0.0) or 0.0), min_soc), max_soc)
    return min_soc, max_soc, initial_soc


def _resolved_bess_terminal_target_kwh(asset: Any) -> float | None:
    bounds = _bess_soc_bounds_for_asset(asset)
    if bounds is None:
        return None
    min_soc, max_soc, initial_soc = bounds
    terminal_floor = min(
        max(
            float(getattr(asset, "bess_terminal_soc_min_kwh", 0.0) or 0.0),
            min_soc,
        ),
        max_soc,
    )
    return resolve_bess_terminal_soc_target_kwh(
        policy=getattr(asset, "bess_terminal_soc_policy", ""),
        initial_soc_kwh=initial_soc,
        configured_target_kwh=float(
            getattr(asset, "bess_terminal_soc_target_kwh", 0.0) or 0.0
        ),
        terminal_soc_floor_kwh=terminal_floor,
        maximum_soc_kwh=max_soc,
    )


def _complete_bess_soc_flow_context(problem: Any, flow_ctx: Dict[str, Any]) -> Dict[str, Any]:
    assets = dict(getattr(problem, "depot_energy_assets", {}) or {})
    if not assets:
        return flow_ctx

    completed = dict(flow_ctx)
    bess_soc = _normalize_depot_slot_mapping(completed.get("bess_soc_kwh_by_depot_slot", {}))
    bess_soc_start = _normalize_depot_slot_mapping(completed.get("bess_soc_start_kwh_by_depot_slot", {}))
    bess_soc_end = _normalize_depot_slot_mapping(completed.get("bess_soc_end_kwh_by_depot_slot", {}))
    slot_count = len(list(getattr(problem, "price_slots", ()) or ()))

    flow_keys = (
        "grid_to_bus_kwh_by_depot_slot",
        "pv_to_bus_kwh_by_depot_slot",
        "bess_to_bus_kwh_by_depot_slot",
        "pv_to_bess_kwh_by_depot_slot",
        "grid_to_bess_kwh_by_depot_slot",
        "pv_curtail_kwh_by_depot_slot",
        "contract_over_limit_kwh_by_depot_slot",
    )
    for asset in assets.values():
        slot_count = max(slot_count, len(tuple(getattr(asset, "pv_generation_kwh_by_slot", ()) or ())))
    for key in flow_keys:
        for slot_map in dict(completed.get(key) or {}).values():
            slot_count = max(slot_count, max((int(slot_idx) + 1 for slot_idx in dict(slot_map or {}).keys()), default=slot_count))
    for mapping in (bess_soc, bess_soc_start, bess_soc_end):
        for slot_map in mapping.values():
            slot_count = max(slot_count, max((int(slot_idx) + 1 for slot_idx in dict(slot_map or {}).keys()), default=slot_count))

    for depot_id, asset in assets.items():
        depot_key = str(depot_id or "")
        if not depot_key or not bool(getattr(asset, "bess_enabled", False)):
            continue
        bounds = _bess_soc_bounds_for_asset(asset)
        if bounds is None:
            continue
        min_soc, max_soc, initial_soc = bounds
        charge_eff = min(max(float(getattr(asset, "bess_charge_efficiency", 0.95) or 0.95), 1.0e-9), 1.0)
        discharge_eff = min(max(float(getattr(asset, "bess_discharge_efficiency", 0.95) or 0.95), 1.0e-9), 1.0)
        slot_indices = set(range(slot_count))
        for key in flow_keys:
            slot_indices.update(int(slot_idx) for slot_idx in dict((completed.get(key) or {}).get(depot_key, {}) or {}).keys())
        slot_indices.update(int(slot_idx) for slot_idx in dict(bess_soc.get(depot_key, {}) or {}).keys())
        slot_indices.update(int(slot_idx) for slot_idx in dict(bess_soc_start.get(depot_key, {}) or {}).keys())
        slot_indices.update(int(slot_idx) for slot_idx in dict(bess_soc_end.get(depot_key, {}) or {}).keys())
        if not slot_indices:
            continue

        soc = initial_soc
        start_map = bess_soc_start.setdefault(depot_key, {})
        end_map = bess_soc_end.setdefault(depot_key, {})
        soc_map = bess_soc.setdefault(depot_key, {})
        for slot_idx in sorted(slot_indices):
            explicit_start = start_map.get(slot_idx)
            start = min(max(float(explicit_start if explicit_start is not None else soc), min_soc), max_soc)
            explicit_end = end_map.get(slot_idx)
            if explicit_end is None:
                explicit_end = soc_map.get(slot_idx)
            if explicit_end is None:
                pv_to_bess = max(float(((completed.get("pv_to_bess_kwh_by_depot_slot") or {}).get(depot_key, {}) or {}).get(slot_idx, 0.0) or 0.0), 0.0)
                grid_to_bess = max(float(((completed.get("grid_to_bess_kwh_by_depot_slot") or {}).get(depot_key, {}) or {}).get(slot_idx, 0.0) or 0.0), 0.0)
                bess_to_bus = max(float(((completed.get("bess_to_bus_kwh_by_depot_slot") or {}).get(depot_key, {}) or {}).get(slot_idx, 0.0) or 0.0), 0.0)
                end = start + ((pv_to_bess + grid_to_bess) * charge_eff) - (bess_to_bus / discharge_eff)
            else:
                end = float(explicit_end or 0.0)
            end = min(max(end, min_soc), max_soc)
            start_map[slot_idx] = start
            end_map[slot_idx] = end
            soc_map[slot_idx] = end
            soc = end

    completed["bess_soc_kwh_by_depot_slot"] = bess_soc
    completed["bess_soc_start_kwh_by_depot_slot"] = bess_soc_start
    completed["bess_soc_end_kwh_by_depot_slot"] = bess_soc_end or bess_soc
    completed["bess_soc_kwh_semantics"] = "slot_end"
    return completed


def _canonical_energy_flow_context_from_snapshot(problem, plan, preserved_context) -> Dict[str, Any]:
    timestep_min = max(int(getattr(problem.scenario, "timestep_min", 0) or 0), 1)
    timestep_h = timestep_min / 60.0

    raw_grid_to_bus = _normalize_depot_slot_mapping(
        preserved_context.get("grid_to_bus_kwh_by_depot_slot", {})
    )
    raw_pv_to_bus = _normalize_depot_slot_mapping(
        preserved_context.get("pv_to_bus_kwh_by_depot_slot", {})
    )
    raw_bess_to_bus = _normalize_depot_slot_mapping(
        preserved_context.get("bess_to_bus_kwh_by_depot_slot", {})
    )
    raw_pv_to_bess = _normalize_depot_slot_mapping(
        preserved_context.get("pv_to_bess_kwh_by_depot_slot", {})
    )
    raw_grid_to_bess = _normalize_depot_slot_mapping(
        preserved_context.get("grid_to_bess_kwh_by_depot_slot", {})
    )
    raw_pv_curtail = _normalize_depot_slot_mapping(
        preserved_context.get("pv_curtail_kwh_by_depot_slot", {})
    )
    raw_bess_soc = _normalize_depot_slot_mapping(
        preserved_context.get("bess_soc_kwh_by_depot_slot", {})
    )
    raw_bess_soc_start = _normalize_depot_slot_mapping(
        preserved_context.get("bess_soc_start_kwh_by_depot_slot", {})
    )
    raw_bess_soc_end = _normalize_depot_slot_mapping(
        preserved_context.get("bess_soc_end_kwh_by_depot_slot", {})
    )
    raw_contract_over_limit = _normalize_depot_slot_mapping(
        preserved_context.get("contract_over_limit_kwh_by_depot_slot", {})
    )

    preserved_slot_signatures = {
        tuple(item)
        for item in list(preserved_context.get("charging_slot_signatures") or [])
        if isinstance(item, (list, tuple)) and len(item) >= 4
    }

    derived_grid_to_bus: Dict[str, Dict[int, float]] = {}
    derived_pv_to_bus: Dict[str, Dict[int, float]] = {}
    derived_bess_to_bus: Dict[str, Dict[int, float]] = {}
    derived_depots: set[str] = set()
    for charging_slot in list(getattr(plan, "charging_slots", ()) or ()):
        if _canonical_charging_slot_signature(charging_slot) in preserved_slot_signatures:
            continue
        charge_kw = max(float(getattr(charging_slot, "charge_kw", 0.0) or 0.0), 0.0)
        discharge_kw = max(float(getattr(charging_slot, "discharge_kw", 0.0) or 0.0), 0.0)
        net_charge_kwh = max(charge_kw - discharge_kw, 0.0) * timestep_h
        if net_charge_kwh <= 0.0:
            continue
        source, depot_id = _canonical_charging_source_and_depot(problem, charging_slot)
        if source == "pv":
            target = derived_pv_to_bus
        elif source == "bess":
            target = derived_bess_to_bus
        else:
            target = derived_grid_to_bus
        slot_map = target.setdefault(str(depot_id), {})
        slot_idx = int(getattr(charging_slot, "slot_index", 0) or 0)
        slot_map[slot_idx] = slot_map.get(slot_idx, 0.0) + net_charge_kwh
        derived_depots.add(str(depot_id))

    effective_grid_to_bus = _merge_depot_slot_flow_maps(raw_grid_to_bus, derived_grid_to_bus)
    effective_pv_to_bus = _merge_depot_slot_flow_maps(raw_pv_to_bus, derived_pv_to_bus)
    effective_bess_to_bus = _merge_depot_slot_flow_maps(raw_bess_to_bus, derived_bess_to_bus)

    depot_limit_kw = {
        str(getattr(depot, "depot_id", "") or ""): float(getattr(depot, "import_limit_kw", 0.0) or 0.0)
        for depot in list(getattr(problem, "depots", ()) or ())
        if str(getattr(depot, "depot_id", "") or "")
    }
    depot_ids = set(depot_limit_kw.keys())
    for mapping in (
        effective_grid_to_bus,
        effective_pv_to_bus,
        effective_bess_to_bus,
        raw_pv_to_bess,
        raw_grid_to_bess,
        raw_pv_curtail,
        raw_bess_soc,
        raw_bess_soc_start,
        raw_bess_soc_end,
        raw_contract_over_limit,
    ):
        depot_ids.update(mapping.keys())
    depot_ids.update(
        str(getattr(vehicle, "home_depot_id", "") or "")
        for vehicle in list(getattr(problem, "vehicles", ()) or ())
        if str(getattr(vehicle, "home_depot_id", "") or "")
    )
    depot_ids.update(str(key) for key in dict(getattr(problem, "depot_energy_assets", {}) or {}).keys())

    pv_generation_kwh_by_depot_slot: Dict[str, Dict[int, float]] = {}
    for depot_id, asset in dict(getattr(problem, "depot_energy_assets", {}) or {}).items():
        generation = {}
        for slot_idx, value in enumerate(list(getattr(asset, "pv_generation_kwh_by_slot", ()) or ())):
            generation[int(slot_idx)] = max(float(value or 0.0), 0.0)
        pv_generation_kwh_by_depot_slot[str(depot_id)] = generation

    price_by_slot = {
        int(getattr(slot, "slot_index", 0) or 0): float(getattr(slot, "grid_buy_yen_per_kwh", 0.0) or 0.0)
        for slot in list(getattr(problem, "price_slots", ()) or ())
    }
    demand_flag_by_slot = {
        int(getattr(slot, "slot_index", 0) or 0): bool(float(getattr(slot, "demand_charge_weight", 0.0) or 0.0) > 0.0)
        for slot in list(getattr(problem, "price_slots", ()) or ())
    }

    derived_from_charging_slots = any(
        _mapping_has_positive_flow(mapping)
        for mapping in (derived_grid_to_bus, derived_pv_to_bus, derived_bess_to_bus)
    )
    provenance_note = str(preserved_context.get("source_provenance_note") or "").strip()
    if not provenance_note:
        provenance_note = (
            "Preserved per-source depot/slot energy-flow maps from the pre-postsolve plan; added postsolve charging slots were derived from the current charging slots."
            if derived_from_charging_slots
            else "Preserved per-source depot/slot energy-flow maps are present in the assignment plan."
        )

    flow_ctx = {
        "timestep_min": timestep_min,
        "timestep_h": timestep_h,
        "depot_ids": sorted(item for item in depot_ids if item),
        "grid_to_bus_kwh_by_depot_slot": effective_grid_to_bus,
        "pv_to_bus_kwh_by_depot_slot": effective_pv_to_bus,
        "bess_to_bus_kwh_by_depot_slot": effective_bess_to_bus,
        "pv_to_bess_kwh_by_depot_slot": raw_pv_to_bess,
        "grid_to_bess_kwh_by_depot_slot": raw_grid_to_bess,
        "pv_curtail_kwh_by_depot_slot": raw_pv_curtail,
        "bess_soc_kwh_by_depot_slot": raw_bess_soc,
        "bess_soc_start_kwh_by_depot_slot": raw_bess_soc_start,
        "bess_soc_end_kwh_by_depot_slot": raw_bess_soc_end or raw_bess_soc,
        "contract_over_limit_kwh_by_depot_slot": raw_contract_over_limit,
        "pv_generation_kwh_by_depot_slot": pv_generation_kwh_by_depot_slot,
        "bess_terminal_soc_target_kwh_by_depot": dict(
            preserved_context.get("bess_terminal_soc_target_kwh_by_depot") or {}
        ),
        "bess_terminal_soc_deviation_kwh_by_depot": dict(
            preserved_context.get("bess_terminal_soc_deviation_kwh_by_depot") or {}
        ),
        "depot_limit_kw": depot_limit_kw,
        "price_by_slot": price_by_slot,
        "demand_flag_by_slot": demand_flag_by_slot,
        "source_provenance_exact": bool(preserved_context.get("source_provenance_exact")) and not derived_from_charging_slots,
        "source_provenance_note": provenance_note,
        "derived_from_charging_slots": derived_from_charging_slots,
        "derived_depots": sorted(derived_depots),
    }
    return _complete_bess_soc_flow_context(problem, flow_ctx)


def _canonical_energy_flow_context(problem, plan) -> Dict[str, Any]:
    metadata = dict(getattr(plan, "metadata", {}) or {})
    preserved_context = dict(metadata.get("canonical_source_flow_context") or {})
    if preserved_context:
        return _canonical_energy_flow_context_from_snapshot(problem, plan, preserved_context)

    timestep_min = max(int(getattr(problem.scenario, "timestep_min", 0) or 0), 1)
    timestep_h = timestep_min / 60.0

    raw_grid_to_bus = _normalize_depot_slot_mapping(getattr(plan, "grid_to_bus_kwh_by_depot_slot", {}))
    raw_pv_to_bus = _normalize_depot_slot_mapping(getattr(plan, "pv_to_bus_kwh_by_depot_slot", {}))
    raw_bess_to_bus = _normalize_depot_slot_mapping(getattr(plan, "bess_to_bus_kwh_by_depot_slot", {}))
    raw_pv_to_bess = _normalize_depot_slot_mapping(getattr(plan, "pv_to_bess_kwh_by_depot_slot", {}))
    raw_grid_to_bess = _normalize_depot_slot_mapping(getattr(plan, "grid_to_bess_kwh_by_depot_slot", {}))
    raw_pv_curtail = _normalize_depot_slot_mapping(getattr(plan, "pv_curtail_kwh_by_depot_slot", {}))
    raw_bess_soc = _normalize_depot_slot_mapping(getattr(plan, "bess_soc_kwh_by_depot_slot", {}))
    raw_bess_soc_start = _normalize_depot_slot_mapping(metadata.get("bess_soc_start_kwh_by_depot_slot", {}))
    raw_bess_soc_end = _normalize_depot_slot_mapping(metadata.get("bess_soc_end_kwh_by_depot_slot", {}))
    raw_contract_over_limit = _normalize_depot_slot_mapping(getattr(plan, "contract_over_limit_kwh_by_depot_slot", {}))

    derived_grid_to_bus: Dict[str, Dict[int, float]] = {}
    derived_pv_to_bus: Dict[str, Dict[int, float]] = {}
    derived_bess_to_bus: Dict[str, Dict[int, float]] = {}
    derived_depots: set[str] = set()
    for charging_slot in list(getattr(plan, "charging_slots", ()) or ()):
        charge_kw = max(float(getattr(charging_slot, "charge_kw", 0.0) or 0.0), 0.0)
        discharge_kw = max(float(getattr(charging_slot, "discharge_kw", 0.0) or 0.0), 0.0)
        net_charge_kwh = max(charge_kw - discharge_kw, 0.0) * timestep_h
        if net_charge_kwh <= 0.0:
            continue
        source, depot_id = _canonical_charging_source_and_depot(problem, charging_slot)
        if source == "pv":
            target = derived_pv_to_bus
        elif source == "bess":
            target = derived_bess_to_bus
        else:
            target = derived_grid_to_bus
        slot_map = target.setdefault(str(depot_id), {})
        slot_idx = int(getattr(charging_slot, "slot_index", 0) or 0)
        slot_map[slot_idx] = slot_map.get(slot_idx, 0.0) + net_charge_kwh
        derived_depots.add(str(depot_id))

    effective_grid_to_bus = dict(raw_grid_to_bus)
    effective_pv_to_bus = dict(raw_pv_to_bus)
    effective_bess_to_bus = dict(raw_bess_to_bus)
    for depot_id, slot_map in derived_grid_to_bus.items():
        if not _depot_mapping_has_positive_flow(raw_grid_to_bus, depot_id):
            effective_grid_to_bus[depot_id] = dict(slot_map)
    for depot_id, slot_map in derived_pv_to_bus.items():
        if not _depot_mapping_has_positive_flow(raw_pv_to_bus, depot_id):
            effective_pv_to_bus[depot_id] = dict(slot_map)
    for depot_id, slot_map in derived_bess_to_bus.items():
        if not _depot_mapping_has_positive_flow(raw_bess_to_bus, depot_id):
            effective_bess_to_bus[depot_id] = dict(slot_map)

    depot_limit_kw = {
        str(getattr(depot, "depot_id", "") or ""): float(getattr(depot, "import_limit_kw", 0.0) or 0.0)
        for depot in list(getattr(problem, "depots", ()) or ())
        if str(getattr(depot, "depot_id", "") or "")
    }
    depot_ids = set(depot_limit_kw.keys())
    for mapping in (
        effective_grid_to_bus,
        effective_pv_to_bus,
        effective_bess_to_bus,
        raw_pv_to_bess,
        raw_grid_to_bess,
        raw_pv_curtail,
        raw_bess_soc,
        raw_bess_soc_start,
        raw_bess_soc_end,
        raw_contract_over_limit,
    ):
        depot_ids.update(mapping.keys())
    depot_ids.update(
        str(getattr(vehicle, "home_depot_id", "") or "")
        for vehicle in list(getattr(problem, "vehicles", ()) or ())
        if str(getattr(vehicle, "home_depot_id", "") or "")
    )
    depot_ids.update(str(key) for key in dict(getattr(problem, "depot_energy_assets", {}) or {}).keys())

    pv_generation_kwh_by_depot_slot: Dict[str, Dict[int, float]] = {}
    for depot_id, asset in dict(getattr(problem, "depot_energy_assets", {}) or {}).items():
        generation = {}
        for slot_idx, value in enumerate(list(getattr(asset, "pv_generation_kwh_by_slot", ()) or ())):
            generation[int(slot_idx)] = max(float(value or 0.0), 0.0)
        pv_generation_kwh_by_depot_slot[str(depot_id)] = generation

    price_by_slot = {
        int(getattr(slot, "slot_index", 0) or 0): float(getattr(slot, "grid_buy_yen_per_kwh", 0.0) or 0.0)
        for slot in list(getattr(problem, "price_slots", ()) or ())
    }
    demand_flag_by_slot = {
        int(getattr(slot, "slot_index", 0) or 0): bool(float(getattr(slot, "demand_charge_weight", 0.0) or 0.0) > 0.0)
        for slot in list(getattr(problem, "price_slots", ()) or ())
    }

    explicit_source_split = any(
        _mapping_has_positive_flow(mapping)
        for mapping in (
            raw_grid_to_bus,
            raw_pv_to_bus,
            raw_bess_to_bus,
            raw_pv_to_bess,
            raw_grid_to_bess,
            raw_pv_curtail,
        )
    )
    derived_from_charging_slots = any(
        _mapping_has_positive_flow(mapping)
        for mapping in (derived_grid_to_bus, derived_pv_to_bus, derived_bess_to_bus)
    ) and not explicit_source_split

    if explicit_source_split:
        provenance_note = "Explicit per-source depot/slot energy-flow maps are present in the assignment plan."
    elif derived_from_charging_slots:
        provenance_note = (
            "Per-source depot/slot energy-flow maps are not present; grid-origin charging was derived from charging slots. "
            "PV/BESS source split remains zero unless the plan encodes it explicitly."
        )
    else:
        provenance_note = "No charging energy flow was recorded for this plan."

    flow_ctx = {
        "timestep_min": timestep_min,
        "timestep_h": timestep_h,
        "depot_ids": sorted(item for item in depot_ids if item),
        "grid_to_bus_kwh_by_depot_slot": effective_grid_to_bus,
        "pv_to_bus_kwh_by_depot_slot": effective_pv_to_bus,
        "bess_to_bus_kwh_by_depot_slot": effective_bess_to_bus,
        "pv_to_bess_kwh_by_depot_slot": raw_pv_to_bess,
        "grid_to_bess_kwh_by_depot_slot": raw_grid_to_bess,
        "pv_curtail_kwh_by_depot_slot": raw_pv_curtail,
        "bess_soc_kwh_by_depot_slot": raw_bess_soc,
        "bess_soc_start_kwh_by_depot_slot": raw_bess_soc_start,
        "bess_soc_end_kwh_by_depot_slot": raw_bess_soc_end or raw_bess_soc,
        "contract_over_limit_kwh_by_depot_slot": raw_contract_over_limit,
        "pv_generation_kwh_by_depot_slot": pv_generation_kwh_by_depot_slot,
        "bess_terminal_soc_target_kwh_by_depot": dict(
            metadata.get("bess_terminal_soc_target_kwh_by_depot") or {}
        ),
        "bess_terminal_soc_deviation_kwh_by_depot": dict(
            metadata.get("bess_terminal_soc_deviation_kwh_by_depot") or {}
        ),
        "depot_limit_kw": depot_limit_kw,
        "price_by_slot": price_by_slot,
        "demand_flag_by_slot": demand_flag_by_slot,
        "source_provenance_exact": not derived_from_charging_slots,
        "source_provenance_note": provenance_note,
        "derived_from_charging_slots": derived_from_charging_slots,
        "derived_depots": sorted(derived_depots),
    }
    return _complete_bess_soc_flow_context(problem, flow_ctx)


def _canonical_charging_output_payload(problem, engine_result) -> Dict[str, Any]:
    plan = engine_result.plan
    flow_ctx = _canonical_energy_flow_context(problem, plan)
    timestep_h = float(flow_ctx["timestep_h"] or 1.0)
    breakdown = dict(engine_result.cost_breakdown or {})
    plan_metadata = dict(getattr(plan, "metadata", {}) or {})
    solver_metadata = dict(engine_result.solver_metadata or {})
    # The source-flow variables are exact at depot × time-slot scope.  Unless
    # the solver carried vehicle/source/slot variables, a vehicle ledger is a
    # transparent post-allocation rather than another exact decision trace.
    depot_source_provenance_exact = bool(flow_ctx["source_provenance_exact"])
    vehicle_source_provenance_exact = bool(
        depot_source_provenance_exact
        and plan_metadata.get("vehicle_source_provenance_exact", False)
    )
    vehicle_source_allocation_method = (
        "solver_native"
        if vehicle_source_provenance_exact
        else "proportional_by_depot_timestep"
    )
    vehicle_source_precision_note = (
        "Vehicle source split is an exact MILP vehicle/source/slot decision trace."
        if vehicle_source_provenance_exact
        else (
            "Vehicle source split is inferred by proportional allocation of exact "
            "depot/time-slot source totals; it is not solver-native."
        )
    )
    penalty_enabled = bool(
        plan_metadata.get(
            "enable_contract_overage_penalty",
            solver_metadata.get("enable_contract_overage_penalty", True),
        )
    )
    raw_penalty_yen_per_kwh = plan_metadata.get(
        "contract_overage_penalty_yen_per_kwh",
        solver_metadata.get("contract_overage_penalty_yen_per_kwh", 0.0),
    )
    penalty_yen_per_kwh = float(raw_penalty_yen_per_kwh or 0.0)
    contract_overage_policy = "soft_penalty" if penalty_enabled and penalty_yen_per_kwh > 0.0 else "warning_only"

    rows: List[Dict[str, Any]] = []
    per_depot: List[Dict[str, Any]] = []
    all_slot_indices: set[int] = set()
    overall_peak_grid_kw = 0.0
    overall_peak_total_charge_kw = 0.0

    for depot_id in list(flow_ctx["depot_ids"]):
        depot_slots = set()
        for key in (
            "grid_to_bus_kwh_by_depot_slot",
            "pv_to_bus_kwh_by_depot_slot",
            "bess_to_bus_kwh_by_depot_slot",
            "pv_to_bess_kwh_by_depot_slot",
            "grid_to_bess_kwh_by_depot_slot",
            "pv_curtail_kwh_by_depot_slot",
            "bess_soc_kwh_by_depot_slot",
            "bess_soc_start_kwh_by_depot_slot",
            "bess_soc_end_kwh_by_depot_slot",
            "contract_over_limit_kwh_by_depot_slot",
            "pv_generation_kwh_by_depot_slot",
        ):
            depot_slots.update(dict(flow_ctx.get(key) or {}).get(depot_id, {}).keys())
        peak_grid_kw = 0.0
        peak_total_charge_kw = 0.0
        peak_contract_over_kw = 0.0
        grid_to_bus_total = 0.0
        pv_to_bus_total = 0.0
        bess_to_bus_total = 0.0
        pv_to_bess_total = 0.0
        grid_to_bess_total = 0.0
        pv_curtail_total = 0.0
        contract_over_total = 0.0
        contract_slot_count = 0

        for slot_idx in sorted(int(idx) for idx in depot_slots):
            all_slot_indices.add(slot_idx)
            grid_to_bus = float((flow_ctx["grid_to_bus_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            pv_to_bus = float((flow_ctx["pv_to_bus_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            bess_to_bus = float((flow_ctx["bess_to_bus_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            pv_to_bess = float((flow_ctx["pv_to_bess_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            grid_to_bess = float((flow_ctx["grid_to_bess_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            raw_pv_curtail = float((flow_ctx["pv_curtail_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            bess_soc = float((flow_ctx["bess_soc_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            bess_soc_start = float((flow_ctx["bess_soc_start_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            bess_soc_end = float((flow_ctx["bess_soc_end_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, bess_soc) or 0.0)
            if bess_soc <= 0.0 and bess_soc_end > 0.0:
                bess_soc = bess_soc_end
            contract_over_limit_kwh = float((flow_ctx["contract_over_limit_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            pv_generation_kwh = float((flow_ctx["pv_generation_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            if pv_generation_kwh > 0.0:
                pv_curtail = compute_pv_curtail_kwh(pv_generation_kwh, pv_to_bus, pv_to_bess)
            else:
                pv_curtail = max(raw_pv_curtail, 0.0)
            pv_balance_residual_kwh = pv_generation_kwh - pv_to_bus - pv_to_bess - pv_curtail
            contract_limit_kw = float((flow_ctx["depot_limit_kw"].get(depot_id, 0.0)) or 0.0)
            grid_import_total_kwh = grid_to_bus + grid_to_bess
            grid_import_for_contract_kwh = grid_import_total_kwh
            total_bus_charge_kwh = grid_to_bus + pv_to_bus + bess_to_bus
            total_bess_charge_kwh = pv_to_bess + grid_to_bess
            grid_import_kw = grid_import_total_kwh / timestep_h if timestep_h > 0.0 else 0.0
            total_charge_kw = total_bus_charge_kwh / timestep_h if timestep_h > 0.0 else 0.0
            if contract_limit_kw > 0.0:
                contract_limit_kwh = contract_limit_kw * timestep_h
                contract_over_limit_kwh = max(
                    contract_over_limit_kwh,
                    grid_import_total_kwh - contract_limit_kwh,
                    0.0,
                )
            contract_over_limit_kw = contract_over_limit_kwh / timestep_h if timestep_h > 0.0 else 0.0
            peak_grid_kw = max(peak_grid_kw, grid_import_kw)
            peak_total_charge_kw = max(peak_total_charge_kw, total_charge_kw)
            peak_contract_over_kw = max(peak_contract_over_kw, contract_over_limit_kw)
            overall_peak_grid_kw = max(overall_peak_grid_kw, grid_import_kw)
            overall_peak_total_charge_kw = max(overall_peak_total_charge_kw, total_charge_kw)
            grid_to_bus_total += grid_to_bus
            pv_to_bus_total += pv_to_bus
            bess_to_bus_total += bess_to_bus
            pv_to_bess_total += pv_to_bess
            grid_to_bess_total += grid_to_bess
            pv_curtail_total += pv_curtail
            contract_over_total += contract_over_limit_kwh
            if contract_over_limit_kwh > 1.0e-9:
                contract_slot_count += 1
            rows.append(
                {
                    "depot_id": depot_id,
                    "slot_index": slot_idx,
                    "grid_to_bus_kwh": grid_to_bus,
                    "pv_to_bus_kwh": pv_to_bus,
                    "bess_to_bus_kwh": bess_to_bus,
                    "pv_to_bess_kwh": pv_to_bess,
                    "grid_to_bess_kwh": grid_to_bess,
                    "pv_curtail_kwh": pv_curtail,
                    "pv_curtail_raw_kwh": raw_pv_curtail,
                    "pv_generation_kwh": pv_generation_kwh,
                    "pv_balance_residual_kwh": pv_balance_residual_kwh,
                    "bess_soc_kwh": bess_soc,
                    "bess_soc_start_kwh": bess_soc_start,
                    "bess_soc_end_kwh": bess_soc_end,
                    "grid_import_total_kwh": grid_import_total_kwh,
                    "grid_import_for_contract_kwh": grid_import_for_contract_kwh,
                    "grid_import_kw": grid_import_kw,
                    "grid_import_for_contract_kw": grid_import_kw,
                    "bus_charge_from_grid_kwh": grid_to_bus,
                    "bus_charge_from_bess_kwh": bess_to_bus,
                    "total_bus_charge_kwh": total_bus_charge_kwh,
                    "total_bess_charge_kwh": total_bess_charge_kwh,
                    "total_charge_kw": total_charge_kw,
                    "contract_limit_kw": contract_limit_kw,
                    "contract_over_limit_kwh": contract_over_limit_kwh,
                    "contract_over_limit_kw": contract_over_limit_kw,
                    "contract_limit_exceeded": contract_over_limit_kwh > 1.0e-9,
                    "energy_price_yen_per_kwh": float((flow_ctx["price_by_slot"].get(slot_idx, 0.0)) or 0.0),
                    "demand_charge_window_flag": bool(flow_ctx["demand_flag_by_slot"].get(slot_idx, False)),
                    # Legacy field retains its depot/time-slot meaning.
                    "source_provenance_exact": depot_source_provenance_exact,
                    "depot_source_provenance_exact": depot_source_provenance_exact,
                }
            )

        contract_overage_cost = contract_over_total * penalty_yen_per_kwh if penalty_enabled else 0.0
        asset = dict(getattr(problem, "depot_energy_assets", {}) or {}).get(depot_id)
        bess_initial_soc = float(getattr(asset, "bess_initial_soc_kwh", 0.0) or 0.0) if asset is not None else 0.0
        bess_terminal_min = float(getattr(asset, "bess_terminal_soc_min_kwh", 0.0) or 0.0) if asset is not None else 0.0
        raw_terminal_target = (flow_ctx.get("bess_terminal_soc_target_kwh_by_depot", {}) or {}).get(depot_id)
        if raw_terminal_target is None and asset is not None:
            raw_terminal_target = _resolved_bess_terminal_target_kwh(asset)
        bess_terminal_target = float(raw_terminal_target or 0.0) if asset is not None else 0.0
        depot_bess_soc_map = dict(flow_ctx["bess_soc_kwh_by_depot_slot"].get(depot_id, {}) or {})
        depot_bess_soc_end_map = dict(flow_ctx["bess_soc_end_kwh_by_depot_slot"].get(depot_id, {}) or {})
        bess_final_soc = (
            float(depot_bess_soc_end_map[max(depot_bess_soc_end_map.keys())])
            if depot_bess_soc_end_map
            else float(depot_bess_soc_map[max(depot_bess_soc_map.keys())])
            if depot_bess_soc_map
            else bess_initial_soc
        )
        bess_terminal_deviation = abs(bess_final_soc - bess_terminal_target) if asset is not None and bess_terminal_target > 0.0 else 0.0
        pv_generation_total = sum(
            float(value or 0.0)
            for value in dict(flow_ctx["pv_generation_kwh_by_depot_slot"].get(depot_id, {}) or {}).values()
        )
        pv_used_total = pv_to_bus_total + pv_to_bess_total
        per_depot.append(
            {
                "depot_id": depot_id,
                # Legacy field retains its depot/time-slot meaning.
                "source_provenance_exact": depot_source_provenance_exact and depot_id not in set(flow_ctx["derived_depots"]),
                "depot_source_provenance_exact": depot_source_provenance_exact and depot_id not in set(flow_ctx["derived_depots"]),
                "grid_to_bus_kwh": grid_to_bus_total,
                "pv_to_bus_kwh": pv_to_bus_total,
                "bess_to_bus_kwh": bess_to_bus_total,
                "pv_to_bess_kwh": pv_to_bess_total,
                "grid_to_bess_kwh": grid_to_bess_total,
                "pv_curtail_kwh": pv_curtail_total,
                "pv_generation_kwh": pv_generation_total,
                "pv_utilization_rate": compute_pv_utilization_rate(
                    pv_generation_total,
                    pv_to_bus_total,
                    pv_to_bess_total,
                ),
                "grid_import_total_kwh": grid_to_bus_total + grid_to_bess_total,
                "grid_import_for_contract_kwh": grid_to_bus_total + grid_to_bess_total,
                "total_bus_charge_kwh": grid_to_bus_total + pv_to_bus_total + bess_to_bus_total,
                "bus_charge_from_grid_kwh": grid_to_bus_total,
                "bus_charge_from_bess_kwh": bess_to_bus_total,
                "total_bess_charge_kwh": pv_to_bess_total + grid_to_bess_total,
                "bess_initial_soc_kwh": bess_initial_soc,
                "bess_final_soc_kwh": bess_final_soc,
                "bess_terminal_soc_delta_kwh": bess_final_soc - bess_initial_soc,
                "bess_terminal_soc_min_kwh": bess_terminal_min,
                "bess_terminal_soc_target_kwh": bess_terminal_target,
                "bess_terminal_soc_deviation_kwh": bess_terminal_deviation,
                "bess_terminal_soc_violation_kwh": max(bess_terminal_min - bess_final_soc, 0.0),
                "peak_grid_import_kw": peak_grid_kw,
                "peak_total_charge_kw": peak_total_charge_kw,
                "contract_limit_kw": float((flow_ctx["depot_limit_kw"].get(depot_id, 0.0)) or 0.0),
                "contract_over_limit_kwh": contract_over_total,
                "contract_over_limit_kw_peak": peak_contract_over_kw,
                "contract_over_limit_slot_count": contract_slot_count,
                "contract_limit_exceeded": contract_over_total > 1.0e-9,
                "contract_overage_penalty_enabled": penalty_enabled,
                "contract_overage_penalty_yen_per_kwh": penalty_yen_per_kwh,
                "contract_overage_cost_jpy": contract_overage_cost,
                "contract_overage_policy": contract_overage_policy,
            }
        )

    overall_grid_import_total_kwh = sum(float(row["grid_import_total_kwh"]) for row in per_depot)
    overall_contract_over_kwh = sum(float(row["contract_over_limit_kwh"]) for row in per_depot)
    expected_contract_over_cost = overall_contract_over_kwh * penalty_yen_per_kwh if penalty_enabled else 0.0
    overall_contract_over_cost = float(breakdown.get("contract_overage_cost", expected_contract_over_cost) or 0.0)
    if abs(overall_contract_over_cost - expected_contract_over_cost) <= 1.0e-6:
        overall_contract_over_cost = expected_contract_over_cost
    fuel_cost_jpy = float(breakdown.get("fuel_cost", 0.0) or 0.0)
    aggregate_energy_cost_jpy = float(breakdown.get("energy_cost", 0.0) or 0.0)
    if breakdown.get("electricity_cost") is not None:
        electricity_cost_jpy = float(breakdown.get("electricity_cost") or 0.0)
    elif breakdown.get("electricity_cost_final") is not None:
        electricity_cost_jpy = float(breakdown.get("electricity_cost_final") or 0.0)
    else:
        electricity_cost_jpy = (
            max(aggregate_energy_cost_jpy - fuel_cost_jpy, 0.0)
            if fuel_cost_jpy > 0.0
            else aggregate_energy_cost_jpy
        )
    overall_by_slot_grid_peak = 0.0
    overall_by_slot_charge_peak = 0.0
    for slot_idx in sorted(all_slot_indices):
        total_grid_import_kwh = 0.0
        total_charge_kwh = 0.0
        for depot_id in list(flow_ctx["depot_ids"]):
            total_grid_import_kwh += float((flow_ctx["grid_to_bus_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            total_grid_import_kwh += float((flow_ctx["grid_to_bess_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            total_charge_kwh += float((flow_ctx["grid_to_bus_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            total_charge_kwh += float((flow_ctx["pv_to_bus_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            total_charge_kwh += float((flow_ctx["bess_to_bus_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
        overall_by_slot_grid_peak = max(overall_by_slot_grid_peak, total_grid_import_kwh / timestep_h if timestep_h > 0.0 else 0.0)
        overall_by_slot_charge_peak = max(overall_by_slot_charge_peak, total_charge_kwh / timestep_h if timestep_h > 0.0 else 0.0)

    return {
        "summary": {
            "timestep_min": int(flow_ctx["timestep_min"]),
            # ``source_provenance_exact`` is retained for older consumers and
            # explicitly means depot × time-slot source-flow exactness.
            "source_provenance_exact": depot_source_provenance_exact,
            "source_provenance_scope": "depot_timestep",
            "depot_source_provenance_exact": depot_source_provenance_exact,
            "vehicle_source_provenance_exact": vehicle_source_provenance_exact,
            "vehicle_source_allocation_method": vehicle_source_allocation_method,
            "vehicle_source_precision_note": vehicle_source_precision_note,
            "source_provenance_note": str(flow_ctx["source_provenance_note"] or ""),
            "depots": per_depot,
            "totals": {
                "source_provenance_exact": depot_source_provenance_exact,
                "source_provenance_scope": "depot_timestep",
                "depot_source_provenance_exact": depot_source_provenance_exact,
                "vehicle_source_provenance_exact": vehicle_source_provenance_exact,
                "vehicle_source_allocation_method": vehicle_source_allocation_method,
                "grid_to_bus_kwh": sum(float(row["grid_to_bus_kwh"]) for row in per_depot),
                "pv_to_bus_kwh": sum(float(row["pv_to_bus_kwh"]) for row in per_depot),
                "bess_to_bus_kwh": sum(float(row["bess_to_bus_kwh"]) for row in per_depot),
                "pv_to_bess_kwh": sum(float(row["pv_to_bess_kwh"]) for row in per_depot),
                "grid_to_bess_kwh": sum(float(row["grid_to_bess_kwh"]) for row in per_depot),
                "pv_curtail_kwh": sum(float(row["pv_curtail_kwh"]) for row in per_depot),
                "pv_generation_kwh": sum(float(row["pv_generation_kwh"]) for row in per_depot),
                "pv_utilization_rate": compute_pv_utilization_rate(
                    sum(float(row["pv_generation_kwh"]) for row in per_depot),
                    sum(float(row["pv_to_bus_kwh"]) for row in per_depot),
                    sum(float(row["pv_to_bess_kwh"]) for row in per_depot),
                ),
                "grid_import_total_kwh": overall_grid_import_total_kwh,
                "grid_import_for_contract_kwh": overall_grid_import_total_kwh,
                "total_bus_charge_kwh": sum(float(row["total_bus_charge_kwh"]) for row in per_depot),
                "bus_charge_from_grid_kwh": sum(float(row["bus_charge_from_grid_kwh"]) for row in per_depot),
                "bus_charge_from_bess_kwh": sum(float(row["bus_charge_from_bess_kwh"]) for row in per_depot),
                "total_bess_charge_kwh": sum(float(row["total_bess_charge_kwh"]) for row in per_depot),
                "bess_initial_soc_kwh": sum(float(row["bess_initial_soc_kwh"]) for row in per_depot),
                "bess_final_soc_kwh": sum(float(row["bess_final_soc_kwh"]) for row in per_depot),
                "bess_terminal_soc_delta_kwh": sum(float(row["bess_terminal_soc_delta_kwh"]) for row in per_depot),
                "bess_terminal_soc_target_kwh": sum(float(row["bess_terminal_soc_target_kwh"]) for row in per_depot),
                "peak_grid_import_kw_any_depot": overall_peak_grid_kw,
                "peak_grid_import_kw_all_depots": overall_by_slot_grid_peak,
                "peak_total_charge_kw_any_depot": overall_peak_total_charge_kw,
                "peak_total_charge_kw_all_depots": overall_by_slot_charge_peak,
                "contract_over_limit_kwh": overall_contract_over_kwh,
                "contract_limit_exceeded": overall_contract_over_kwh > 1.0e-9,
                "contract_overage_penalty_enabled": penalty_enabled,
                "contract_overage_penalty_yen_per_kwh": penalty_yen_per_kwh,
                "contract_overage_cost_jpy": overall_contract_over_cost,
                "contract_overage_policy": contract_overage_policy,
                "contract_overage_warning": (
                    "Contract limit exceeded but no overage cost was applied; policy is warning_only."
                    if overall_contract_over_kwh > 1.0e-9 and contract_overage_policy == "warning_only"
                    else ""
                ),
                "bess_terminal_soc_violation_kwh": float(
                    solver_metadata.get(
                        "bess_terminal_soc_violation_kwh",
                        plan_metadata.get("bess_terminal_soc_violation_kwh", 0.0),
                    )
                    or 0.0
                ),
                "bess_terminal_soc_deviation_kwh": float(
                    solver_metadata.get(
                        "bess_terminal_soc_deviation_kwh",
                        plan_metadata.get(
                            "bess_terminal_soc_deviation_kwh",
                            sum(float(row.get("bess_terminal_soc_deviation_kwh", 0.0) or 0.0) for row in per_depot),
                        ),
                    )
                    or 0.0
                ),
                "readiness_topup_policy": {
                    "status": "metadata_only",
                    "warning": False,
                    "bess_terminal_soc_min_enforced": True,
                },
                "demand_charge_cost_jpy": float(breakdown.get("demand_cost", 0.0) or 0.0),
                "grid_purchase_cost_jpy": float(breakdown.get("grid_purchase_cost", 0.0) or 0.0),
                "bess_discharge_cost_jpy": float(breakdown.get("bess_discharge_cost", 0.0) or 0.0),
                "pv_self_consumption_cost_jpy": float(breakdown.get("pv_self_consumption_cost_jpy", 0.0) or 0.0),
                "electricity_cost_jpy": electricity_cost_jpy,
                "objective_value_jpy": float(engine_result.objective_value or 0.0),
                "objective_is_actual_cost": bool(breakdown.get("objective_is_actual_cost", False)),
                "supports_exact_milp": bool((engine_result.solver_metadata or {}).get("supports_exact_milp", False)),
            },
        },
        "rows": rows,
    }


def _canonical_simulation_condition_tables(
    canonical_problem: Optional[Any],
) -> Optional[tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]]:
    """Build condition tables from the canonical model actually solved.

    ``simulation_config`` is a frontend-facing editable document and can omit
    values inherited from a tariff CSV or the selected depot. These output
    tables are evidence artifacts, so their prices and import limits must be
    taken from the already-built canonical problem instead of that stale UI
    payload.
    """

    if canonical_problem is None:
        return None
    price_slots = sorted(
        list(getattr(canonical_problem, "price_slots", ()) or ()),
        key=lambda slot: int(getattr(slot, "slot_index", 0) or 0),
    )
    depots = list(getattr(canonical_problem, "depots", ()) or ())
    if not price_slots or not depots:
        return None

    tou_rows: List[Dict[str, Any]] = []
    contract_rows: List[Dict[str, Any]] = []
    depot_ids: List[str] = []
    metadata = dict(getattr(canonical_problem, "metadata", {}) or {})
    base_load_by_depot_slot = metadata.get("base_load_kw_by_depot_slot")
    base_load_by_slot = metadata.get("base_load_kw_by_slot")

    def canonical_base_load_kw(depot_id: str, slot_index: int) -> Any:
        """Return an explicitly represented base load, never infer one."""

        if isinstance(base_load_by_depot_slot, dict):
            per_depot = base_load_by_depot_slot.get(depot_id)
            if isinstance(per_depot, dict):
                if slot_index in per_depot:
                    return per_depot[slot_index]
                if str(slot_index) in per_depot:
                    return per_depot[str(slot_index)]
        if isinstance(base_load_by_slot, dict):
            if slot_index in base_load_by_slot:
                return base_load_by_slot[slot_index]
            if str(slot_index) in base_load_by_slot:
                return base_load_by_slot[str(slot_index)]
        if isinstance(base_load_by_slot, (list, tuple)) and 0 <= slot_index < len(
            base_load_by_slot
        ):
            return base_load_by_slot[slot_index]
        return None

    for depot in depots:
        depot_id = str(getattr(depot, "depot_id", "") or "").strip()
        if not depot_id:
            continue
        depot_ids.append(depot_id)
        import_limit_kw = float(getattr(depot, "import_limit_kw", 0.0) or 0.0)
        for slot in price_slots:
            slot_index = int(getattr(slot, "slot_index", 0) or 0)
            tou_rows.append(
                {
                    "site_id": depot_id,
                    "time_idx": slot_index,
                    "grid_energy_price_yen_per_kwh": float(
                        getattr(slot, "grid_buy_yen_per_kwh", 0.0) or 0.0
                    ),
                    "sell_back_price_yen_per_kwh": float(
                        getattr(slot, "grid_sell_yen_per_kwh", 0.0) or 0.0
                    ),
                    # A demand-charge weight is not generally a physical base
                    # load. Export a base load only when the canonical model
                    # represents one explicitly; otherwise leave it blank.
                    "base_load_kw": canonical_base_load_kw(depot_id, slot_index),
                    "demand_charge_weight": float(
                        getattr(slot, "demand_charge_weight", 0.0) or 0.0
                    ),
                    "grid_co2_factor_kg_per_kwh": float(
                        getattr(slot, "co2_factor", 0.0) or 0.0
                    ),
                }
            )
        contract_rows.append(
            {
                "site_id": depot_id,
                "site_type": "depot",
                # The canonical model represents one grid-import limit. It is
                # the operative contract limit; no separate transformer value
                # is invented when the input did not provide one.
                "contract_demand_limit_kw": import_limit_kw,
                "grid_import_limit_kw": import_limit_kw,
                "site_transformer_limit_kw": None,
            }
        )
    if not depot_ids:
        return None
    return (
        tou_rows,
        contract_rows,
        {
            "schema_version": "simulation_conditions_provenance_v1",
            "source": "canonical_problem",
            "price_source": "canonical_problem.price_slots",
            "contract_limit_source": "canonical_problem.depots[].import_limit_kw",
            "base_load_source": (
                "canonical_problem.metadata.base_load_kw_by_depot_slot_or_by_slot; "
                "blank_when_not_represented"
            ),
            "demand_charge_weight_source": (
                "canonical_problem.price_slots[].demand_charge_weight"
            ),
            "site_transformer_limit_semantics": "not_modeled_blank_in_csv",
            "depot_ids": sorted(depot_ids),
            "price_slot_count": len(price_slots),
        },
    )


def _persist_rich_run_outputs(
    *,
    run_dir: Path,
    scenario: Dict[str, Any],
    optimization_result: Dict[str, Any],
    optimization_audit: Dict[str, Any],
    result_payload: Dict[str, Any],
    sim_payload: Optional[Dict[str, Any]],
    canonical_solver_result: Optional[Dict[str, Any]],
    canonical_problem: Optional[Any] = None,
    graph_source_dir: Optional[Path] = None,
    charging_summary: Optional[Dict[str, Any]] = None,
    charging_flow_payload: Optional[Dict[str, Any]] = None,
    finalize_reporting: bool = False,
) -> Optional[Dict[str, Any]]:
    run_dir.mkdir(parents=True, exist_ok=True)

    unit_map = {
        "objective_value": "JPY",
        "solve_time_seconds": "s",
        "energy_cost": "JPY",
        "electricity_cost": "JPY",
        "pv_self_consumption_cost_jpy": "JPY",
        "pv_marginal_charge_cost_yen_per_kwh": "JPY/kWh",
        "pv_curtail_penalty_yen_per_kwh": "JPY/kWh",
        "demand_charge": "JPY",
        "vehicle_cost": "JPY",
        "vehicle_usage_cost": "JPY",
        "vehicle_usage_cost_jpy": "JPY",
        "vehicle_usage_cost_jpy_per_used_bus": "JPY/vehicle-day",
        "used_vehicle_day_count": "vehicle-day",
        "driver_cost": "JPY",
        "fuel_cost": "JPY",
        "fuel_cost_final": "JPY",
        "fuel_cost_provisional": "JPY",
        "fuel_cost_refueled": "JPY",
        "fuel_cost_realized": "JPY",
        "fuel_cost_provisional_leftover": "JPY",
        "penalty_unserved": "JPY",
        "return_leg_bonus": "JPY",
        "weather_strategy_objective_term_jpy_equivalent": "JPY-equivalent",
        "total_cost": "JPY",
        "accounting_total_cost_jpy": "JPY",
        "solver_objective_value": "JPY",
        "validated_operating_cost_jpy": "JPY",
        "co2_cost": "JPY",
        "total_co2_kg": "kg-CO2",
        "grid_to_bus_kwh": "kWh",
        "pv_to_bus_kwh": "kWh",
        "grid_to_bess_kwh": "kWh",
        "bess_to_bus_kwh": "kWh",
        "pv_to_bess_kwh": "kWh",
        "pv_curtail_kwh": "kWh",
        "grid_import_total_kwh": "kWh",
        "grid_import_for_contract_kwh": "kWh",
        "bus_charge_from_grid_kwh": "kWh",
        "bus_charge_from_bess_kwh": "kWh",
        "contract_over_limit_kwh": "kWh",
        "contract_overage_cost": "JPY",
        "peak_grid_kw": "kW",
    }

    (run_dir / "optimization_result.json").write_text(
        json.dumps(optimization_result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "optimization_audit.json").write_text(
        json.dumps(optimization_audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "solver_result.json").write_text(
        json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if canonical_solver_result is not None:
        (run_dir / "canonical_solver_result.json").write_text(
            json.dumps(canonical_solver_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    accounting_summary = dict((optimization_result.get("graph_artifacts") or {}).get("accounting_summary") or {})
    solution_validity = dict(
        optimization_result.get("solution_validity")
        or (optimization_result.get("summary") or {}).get("solution_validity")
        or {}
    )
    if "validated_feasible" in solution_validity:
        evaluation_valid = bool(solution_validity.get("validated_feasible"))
    elif isinstance(canonical_solver_result, dict) and "feasible" in canonical_solver_result:
        evaluation_valid = bool(canonical_solver_result.get("feasible"))
    else:
        evaluation_valid = str(optimization_result.get("solver_status") or "").lower() in {
            "optimal",
            "feasible",
            "solved_feasible",
        }

    def _evaluation_float(value: Any) -> Optional[float]:
        if not evaluation_valid or value in (None, ""):
            return None
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None

    result_summary = dict(optimization_result.get("summary") or {})
    # Older/alternative solver paths do not necessarily provide settings.  Keep
    # rich-output persistence backward compatible and emit null telemetry in
    # that case rather than failing after a feasible solve.
    solver_settings = dict(optimization_result.get("solver_settings") or {})
    solver_metadata = dict(optimization_result.get("solver_metadata") or {})
    summary = {
        "scenario_id": optimization_result.get("scenario_id"),
        "mode": optimization_result.get("mode"),
        "solver_status": optimization_result.get("solver_status"),
        "objective_mode": optimization_result.get("objective_mode"),
        "objective_value": optimization_result.get("objective_value"),
        "objective_value_unit": "JPY",
        "objective_value_jpy": _evaluation_float(
            accounting_summary.get("objective_value_jpy", optimization_result.get("objective_value"))
        ),
        "total_cost_jpy": _evaluation_float(
            accounting_summary.get(
                "total_cost_jpy",
                (optimization_result.get("cost_breakdown") or {}).get(
                    "total_cost",
                    optimization_result.get("objective_value"),
                ),
            )
        ),
        "accounting_total_cost_jpy": _evaluation_float(
            accounting_summary.get(
                "accounting_total_cost_jpy",
                accounting_summary.get("total_cost_jpy"),
            )
        ),
        "solver_objective_value": _evaluation_float(
            accounting_summary.get(
                "solver_objective_value",
                accounting_summary.get(
                    "objective_value_jpy", optimization_result.get("objective_value")
                ),
            )
        ),
        "validated_operating_cost_jpy": _evaluation_float(
            accounting_summary.get("validated_operating_cost_jpy")
        ),
        "objective_is_actual_cost": bool(
            evaluation_valid
            and (optimization_result.get("cost_breakdown") or {}).get(
                "objective_is_actual_cost", False
            )
        ),
        "supports_exact_milp": bool((optimization_result.get("solver_metadata") or {}).get("supports_exact_milp", False)),
        "stage1_solver_status": solver_settings.get("stage1_solver_status"),
        "stage1_termination_reason": solver_settings.get(
            "stage1_termination_reason"
        ),
        "stage1_best_obj_stop_enabled": solver_settings.get(
            "stage1_best_obj_stop_enabled"
        ),
        "stage1_best_obj_stop_applied": solver_settings.get(
            "stage1_best_obj_stop_applied"
        ),
        "stage1_best_obj_stop_threshold": solver_settings.get(
            "stage1_best_obj_stop_threshold"
        ),
        "stage1_gurobi_raw_mip_gap_ratio": solver_settings.get(
            "stage1_gurobi_raw_mip_gap_ratio"
        ),
        "stage1_certified_mip_gap_ratio": solver_settings.get(
            "stage1_certified_mip_gap_ratio"
        ),
        "runtime_comparison_eligible": solver_settings.get(
            "runtime_comparison_eligible"
        ),
        "gurobi_threads": solver_settings.get("gurobi_threads"),
        "interactive_runtime_controls": dict(
            solver_settings.get("interactive_runtime_controls") or {}
        ),
        "interactive_operation_time_window_controls": dict(
            solver_settings.get("interactive_operation_time_window_controls") or {}
        ),
        "interactive_terminal_soc_controls": dict(
            solver_settings.get("interactive_terminal_soc_controls") or {}
        ),
        "bev_terminal_soc_policy": solver_metadata.get("bev_terminal_soc_policy"),
        "bev_terminal_soc_balance_satisfied": solver_metadata.get(
            "bev_terminal_soc_balance_satisfied"
        ),
        "bev_terminal_soc_total_drawdown_kwh": solver_metadata.get(
            "bev_terminal_soc_total_drawdown_kwh"
        ),
        "solve_time_seconds": optimization_result.get("solve_time_seconds"),
        "solve_time_unit": "s",
        "trip_count_served": (
            accounting_summary.get("served_trip_count", result_summary.get("trip_count_served"))
            if evaluation_valid
            else result_summary.get("trip_count_served")
        ),
        "trip_count_unserved": (
            accounting_summary.get("unserved_trip_count", result_summary.get("trip_count_unserved"))
            if evaluation_valid
            else result_summary.get("trip_count_unserved")
        ),
        "vehicle_count_used": accounting_summary.get("used_vehicle_count", (optimization_result.get("summary") or {}).get("vehicle_count_used")),
        "same_day_depot_cycles_enabled": (optimization_result.get("summary") or {}).get("same_day_depot_cycles_enabled"),
        "max_depot_cycles_per_vehicle_per_day": (optimization_result.get("summary") or {}).get("max_depot_cycles_per_vehicle_per_day"),
        "vehicle_fragment_counts": (optimization_result.get("summary") or {}).get("vehicle_fragment_counts"),
        "vehicles_with_multiple_fragments": (optimization_result.get("summary") or {}).get("vehicles_with_multiple_fragments"),
        "max_fragments_observed": (optimization_result.get("summary") or {}).get("max_fragments_observed"),
        "solution_validity": solution_validity,
        "result_status": optimization_result.get("result_status"),
        "failure_stage": optimization_result.get("failure_stage"),
        "research_kpi_eligible": bool(
            optimization_result.get("research_kpi_eligible", False)
        ),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "solver_settings.json").write_text(
        json.dumps(solver_settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    cost_breakdown = dict(optimization_result.get("cost_breakdown") or {})
    cost_rows = [
        {
            "key": key,
            "value": value,
            "unit": unit_map.get(key, ""),
        }
        for key, value in cost_breakdown.items()
    ]
    (run_dir / "cost_breakdown_detail.json").write_text(
        json.dumps({"rows": cost_rows}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_csv_rows(
        run_dir / "cost_breakdown_detail.csv",
        cost_rows,
        ["key", "value", "unit"],
    )

    objective_rows = [
        {"key": key, "value": value, "unit": unit_map.get(key, "")}
        for key, value in dict(result_payload.get("obj_breakdown") or {}).items()
    ]
    solution_validity = dict(
        optimization_result.get("solution_validity")
        or (optimization_result.get("summary") or {}).get("solution_validity")
        or {}
    )
    if solution_validity:
        objective_rows = [
            row for row in objective_rows if row.get("key") != "evaluation_feasible"
        ]
        objective_rows.append(
            {
                "key": "evaluation_feasible",
                "value": 1.0 if bool(solution_validity.get("validated_feasible")) else 0.0,
                "unit": "",
            }
        )
    (run_dir / "objective_breakdown.json").write_text(
        json.dumps({"rows": objective_rows}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_csv_rows(
        run_dir / "objective_breakdown.csv",
        objective_rows,
        ["key", "value", "unit"],
    )

    assignment = dict(result_payload.get("assignment") or {})
    vehicle_schedule_rows: List[Dict[str, Any]] = []
    for vehicle_id, trip_ids in assignment.items():
        for order, trip_id in enumerate(list(trip_ids or []), start=1):
            vehicle_schedule_rows.append(
                {
                    "vehicle_id": vehicle_id,
                    "sequence": order,
                    "trip_id": trip_id,
                }
            )
    _write_csv_rows(
        run_dir / "vehicle_schedule.csv",
        vehicle_schedule_rows,
        ["vehicle_id", "sequence", "trip_id"],
    )

    summary_payload = dict(optimization_result.get("summary") or {})
    trip_type_rows = [
        {
            "vehicle_type": vehicle_type,
            "trip_count": trip_count,
            "unit": "trips",
        }
        for vehicle_type, trip_count in dict(summary_payload.get("trip_count_by_type") or {}).items()
    ]
    (run_dir / "trip_type_counts.json").write_text(
        json.dumps({"rows": trip_type_rows}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_csv_rows(
        run_dir / "trip_type_counts.csv",
        trip_type_rows,
        ["vehicle_type", "trip_count", "unit"],
    )

    targeted_rows = [
        {"trip_id": trip_id, "status": "unserved"}
        for trip_id in list(result_payload.get("unserved_tasks") or [])
    ]
    (run_dir / "targeted_trips.json").write_text(
        json.dumps({"rows": targeted_rows}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_csv_rows(
        run_dir / "targeted_trips.csv",
        targeted_rows,
        ["trip_id", "status"],
    )

    sim_cfg = dict(scenario.get("simulation_config") or {})
    cost_cfg = dict(((scenario.get("scenario_overlay") or {}).get("cost_coefficients") or {}))
    (run_dir / "simulation_conditions.json").write_text(
        json.dumps(sim_cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    weather_policy = dict(optimization_result.get("weather_policy") or {})
    if weather_policy.get("enabled"):
        forecast_payload = dict(weather_policy.get("forecast") or {})
        profile_payload = dict(weather_policy.get("operation_profile") or {})
        audit_payload = dict(weather_policy.get("audit") or {})
        representative_curve_payload = dict(weather_policy.get("representative_curve") or {})
        (run_dir / "weather_proxy_forecast.json").write_text(
            json.dumps(forecast_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (run_dir / "weather_operation_policy.json").write_text(
            json.dumps(profile_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (run_dir / "weather_policy_audit.json").write_text(
            json.dumps(audit_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if representative_curve_payload:
            (run_dir / "weather_pv_representative_curve.json").write_text(
                json.dumps(representative_curve_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    # Legacy-compatible simulation condition tables.
    vehicles = list(scenario.get("vehicles") or [])
    vehicle_cost_rows: List[Dict[str, Any]] = []
    for vehicle in vehicles:
        if not isinstance(vehicle, dict):
            continue
        vehicle_type = str(vehicle.get("vehicle_type") or vehicle.get("type") or "").upper()
        fuel_unit_price = (
            vehicle.get("fuel_cost_coeff_yen_per_liter")
            or vehicle.get("fuelCostPerL")
            or vehicle.get("fuel_price_yen_per_liter")
            or vehicle.get("fuelPriceYenPerLiter")
        )
        if fuel_unit_price in (None, "") and vehicle_type not in {"BEV", "PHEV", "FCEV"}:
            fuel_unit_price = cost_cfg.get("diesel_price_per_l") or sim_cfg.get("diesel_price_per_l") or 0.0
        vehicle_cost_rows.append(
            {
                "vehicle_id": vehicle.get("vehicle_id") or vehicle.get("id") or vehicle.get("name") or "",
                "vehicle_type": vehicle_type,
                "fixed_use_cost_yen": vehicle.get("fixed_use_cost_yen") or vehicle.get("fixed_cost_yen") or 0.0,
                "fuel_cost_coeff_yen_per_liter": fuel_unit_price or 0.0,
                "battery_degradation_cost_coeff_yen_per_kwh": vehicle.get("battery_degradation_cost_coeff_yen_per_kwh") or 0.0,
                "co2_emission_coeff_kg_per_liter": vehicle.get("co2_emission_coeff_kg_per_liter") or vehicle.get("co2EmissionKgPerL") or 0.0,
            }
        )
    _write_csv_rows(
        run_dir / "simulation_conditions_vehicle_costs.csv",
        vehicle_cost_rows,
        [
            "vehicle_id",
            "vehicle_type",
            "fixed_use_cost_yen",
            "fuel_cost_coeff_yen_per_liter",
            "battery_degradation_cost_coeff_yen_per_kwh",
            "co2_emission_coeff_kg_per_liter",
        ],
    )

    canonical_condition_tables = _canonical_simulation_condition_tables(
        canonical_problem
    )
    if canonical_condition_tables is not None:
        tou_rows, contract_rows, condition_provenance = canonical_condition_tables
    else:
        # Retain a clearly-labelled legacy fallback for direct callers that do
        # not provide a canonical problem. The interactive BFF execution path
        # always supplies one, so formal evidence is generated from the model.
        slot_count = int(sim_cfg.get("planning_horizon_hours") or 24)
        timestep = int(
            sim_cfg.get("time_step_min") or sim_cfg.get("timestep_min") or 60
        )
        if timestep > 0:
            slot_count = max(slot_count * 60 // timestep, 1)
        tou_price_series = list(sim_cfg.get("tou_prices_yen_per_kwh") or [])
        default_price = float(sim_cfg.get("grid_energy_price_yen_per_kwh") or 0.0)
        grid_co2_series = list(sim_cfg.get("grid_co2_factor_kg_per_kwh") or [])
        base_load_series = list(sim_cfg.get("base_load_kw") or [])
        site_id = str(sim_cfg.get("depot_id") or "depot_A")
        tou_rows = []
        for time_idx in range(slot_count):
            tou_rows.append(
                {
                    "site_id": site_id,
                    "time_idx": time_idx,
                    "grid_energy_price_yen_per_kwh": (
                        tou_price_series[time_idx]
                        if time_idx < len(tou_price_series)
                        else default_price
                    ),
                    "sell_back_price_yen_per_kwh": 0.0,
                    "base_load_kw": (
                        base_load_series[time_idx]
                        if time_idx < len(base_load_series)
                        else 0.0
                    ),
                    "demand_charge_weight": None,
                    "grid_co2_factor_kg_per_kwh": (
                        grid_co2_series[time_idx]
                        if time_idx < len(grid_co2_series)
                        else 0.0
                    ),
                }
            )
        contract_rows = [
            {
                "site_id": site_id,
                "site_type": "depot",
                "contract_demand_limit_kw": float(
                    sim_cfg.get("contract_demand_limit_kw") or 0.0
                ),
                "grid_import_limit_kw": float(
                    sim_cfg.get("grid_import_limit_kw") or 0.0
                ),
                "site_transformer_limit_kw": float(
                    sim_cfg.get("site_transformer_limit_kw") or 0.0
                ),
            }
        ]
        condition_provenance = {
            "schema_version": "simulation_conditions_provenance_v1",
            "source": "legacy_scenario_payload_fallback",
            "reason": "canonical_problem_not_supplied_to_rich_output_writer",
            "price_source": "scenario.simulation_config",
            "contract_limit_source": "scenario.simulation_config",
        }
    _write_csv_rows(
        run_dir / "simulation_conditions_tou_prices.csv",
        tou_rows,
        [
            "site_id",
            "time_idx",
            "grid_energy_price_yen_per_kwh",
            "sell_back_price_yen_per_kwh",
            "base_load_kw",
            "demand_charge_weight",
            "grid_co2_factor_kg_per_kwh",
        ],
    )

    _write_csv_rows(
        run_dir / "simulation_conditions_contract_limits.csv",
        contract_rows,
        [
            "site_id",
            "site_type",
            "contract_demand_limit_kw",
            "grid_import_limit_kw",
            "site_transformer_limit_kw",
        ],
    )
    (run_dir / "simulation_conditions_provenance.json").write_text(
        json.dumps(condition_provenance, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    ice_co2_kg = float(
        cost_breakdown.get("ice_bus_co2_kg", cost_breakdown.get("ice_co2_kg", cost_breakdown.get("engine_bus_co2_kg", 0.0))) or 0.0
    )
    grid_co2_kg = float(
        cost_breakdown.get("grid_electricity_co2_kg", cost_breakdown.get("power_generation_co2_kg", 0.0)) or 0.0
    )
    pv_co2_kg = float(cost_breakdown.get("pv_operational_co2_kg", cost_breakdown.get("pv_co2_kg", 0.0)) or 0.0)
    bess_storage_co2_kg = float(cost_breakdown.get("bess_storage_operational_co2_kg", 0.0) or 0.0)
    total_components_co2_kg = ice_co2_kg + grid_co2_kg + pv_co2_kg + bess_storage_co2_kg
    total_co2_kg = float(cost_breakdown.get("total_co2_kg", total_components_co2_kg) or 0.0)
    if abs(total_co2_kg - total_components_co2_kg) > 1.0e-6 and ice_co2_kg == 0.0 and grid_co2_kg == 0.0 and pv_co2_kg == 0.0 and bess_storage_co2_kg == 0.0:
        grid_co2_kg = total_co2_kg
        total_components_co2_kg = total_co2_kg
    co2_rows = [
        {"component": "ice_bus_co2_kg", "value": ice_co2_kg},
        {"component": "grid_electricity_co2_kg", "value": grid_co2_kg},
        {"component": "pv_operational_co2_kg", "value": pv_co2_kg},
        {"component": "bess_storage_operational_co2_kg", "value": bess_storage_co2_kg},
        {"component": "total_co2_kg", "value": total_components_co2_kg},
    ]
    (run_dir / "co2_breakdown.json").write_text(
        json.dumps({"rows": co2_rows}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_csv_rows(
        run_dir / "co2_breakdown.csv",
        co2_rows,
        ["component", "value"],
    )

    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "optimization_result.json").write_text(
        json.dumps(optimization_result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (raw_dir / "optimization_audit.json").write_text(
        json.dumps(optimization_audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (raw_dir / "solver_result.json").write_text(
        json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if canonical_solver_result is not None:
        (raw_dir / "canonical_solver_result.json").write_text(
            json.dumps(canonical_solver_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    raw_assignment_rows: List[Dict[str, Any]] = []
    for vehicle_id, trip_ids in assignment.items():
        for order, trip_id in enumerate(list(trip_ids or []), start=1):
            raw_assignment_rows.append(
                {
                    "vehicle_id": vehicle_id,
                    "sequence": order,
                    "trip_id": trip_id,
                }
            )
    _write_csv_rows(
        raw_dir / "assignment.csv",
        raw_assignment_rows,
        ["vehicle_id", "sequence", "trip_id"],
    )
    raw_unserved_rows = [
        {"trip_id": trip_id, "status": "unserved"}
        for trip_id in list(result_payload.get("unserved_tasks") or [])
    ]
    _write_csv_rows(
        raw_dir / "unserved_trips.csv",
        raw_unserved_rows,
        ["trip_id", "status"],
    )

    graph_artifacts = dict(optimization_result.get("graph_artifacts") or {})
    timeline_candidates: List[Path] = []
    if graph_artifacts.get("vehicle_timeline_path"):
        rel = Path(str(graph_artifacts.get("vehicle_timeline_path")))
        timeline_candidates.append(run_dir / rel)
        if graph_source_dir is not None:
            timeline_candidates.append(graph_source_dir / rel.name)
            timeline_candidates.append(graph_source_dir / rel)
    timeline_candidates.append(run_dir / "graph" / "vehicle_timeline.csv")
    if graph_source_dir is not None:
        timeline_candidates.append(graph_source_dir / "vehicle_timeline.csv")
    copied_timeline_src: Optional[Path] = None
    for src in timeline_candidates:
        if src.exists():
            shutil.copy2(src, run_dir / "vehicle_timeline_gantt.csv")
            shutil.copy2(src, run_dir / "vehicle_timelines.csv")
            copied_timeline_src = src
            break
    if copied_timeline_src is not None:
        try:
            with copied_timeline_src.open("r", encoding="utf-8", newline="") as handle:
                timeline_rows = list(csv.DictReader(handle))
            (run_dir / "vehicle_timelines.json").write_text(
                json.dumps(_canonical_vehicle_timelines_payload(timeline_rows), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    refuel_rows = []
    charging_rows = []
    if canonical_solver_result is not None:
        for item in list((canonical_solver_result.get("charging_schedule") or [])):
            if not isinstance(item, dict):
                continue
            charge_kw = float(item.get("charge_kw") or 0.0)
            discharge_kw = float(item.get("discharge_kw") or 0.0)
            charging_rows.append(
                {
                    "vehicle_id": item.get("vehicle_id"),
                    "charger_id": item.get("charger_id"),
                    "time_idx": item.get("slot_index"),
                    "z_charge": 1 if charge_kw > 1.0e-9 else 0,
                    "p_charge_kw": charge_kw,
                    "p_discharge_kw": discharge_kw,
                    "soc_kwh": "",
                    "charging_depot_id": item.get("charging_depot_id"),
                }
            )
        for item in list((canonical_solver_result.get("refueling_schedule") or [])):
            if not isinstance(item, dict):
                continue
            refuel_rows.append(
                {
                    "vehicle_id": item.get("vehicle_id"),
                    "slot_index": item.get("slot_index"),
                    "time_hhmm": item.get("time_hhmm"),
                    "refuel_liters": item.get("refuel_liters"),
                    "unit": "L",
                }
            )
    _write_csv_rows(
        run_dir / "charging_schedule.csv",
        charging_rows,
        [
            "vehicle_id",
            "charger_id",
            "time_idx",
            "z_charge",
            "p_charge_kw",
            "p_discharge_kw",
            "soc_kwh",
            "charging_depot_id",
        ],
    )
    _write_csv_rows(
        run_dir / "refuel_events.csv",
        refuel_rows,
        ["vehicle_id", "slot_index", "time_hhmm", "refuel_liters", "unit"],
    )

    charging_summary_payload = dict(charging_summary or optimization_result.get("charging_summary") or {})
    charging_flow_rows = list((charging_flow_payload or {}).get("rows") or [])
    if charging_summary_payload:
        (run_dir / "charging_summary.json").write_text(
            json.dumps(charging_summary_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        charging_source_provenance = {
            "schema_version": "charging_source_provenance_v1",
            "site_depot_timestep": {
                "exact": bool(
                    charging_summary_payload.get(
                        "depot_source_provenance_exact",
                        charging_summary_payload.get("source_provenance_exact", False),
                    )
                ),
                "scope": str(
                    charging_summary_payload.get(
                        "source_provenance_scope", "depot_timestep"
                    )
                ),
                "note": charging_summary_payload.get("source_provenance_note"),
            },
            "vehicle_timestep": {
                "exact": bool(
                    charging_summary_payload.get(
                        "vehicle_source_provenance_exact", False
                    )
                ),
                "allocation_method": str(
                    charging_summary_payload.get(
                        "vehicle_source_allocation_method",
                        "proportional_by_depot_timestep",
                    )
                ),
                "note": charging_summary_payload.get(
                    "vehicle_source_precision_note"
                ),
            },
            "interpretation": (
                "Site/depot source totals and vehicle source allocations have "
                "different precision scopes and must not be conflated."
            ),
        }
        (run_dir / "charging_source_provenance.json").write_text(
            json.dumps(charging_source_provenance, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        charging_summary_rows: List[Dict[str, Any]] = []
        for depot_row in list(charging_summary_payload.get("depots") or []):
            if isinstance(depot_row, dict):
                charging_summary_rows.append({"scope": "depot", **dict(depot_row)})
        totals_row = dict(charging_summary_payload.get("totals") or {})
        if totals_row:
            charging_summary_rows.append({"scope": "total", "depot_id": "", **totals_row})
        _write_csv_rows(
            run_dir / "charging_summary.csv",
            charging_summary_rows,
            [
                "scope",
                "depot_id",
                "source_provenance_exact",
                "source_provenance_scope",
                "depot_source_provenance_exact",
                "vehicle_source_provenance_exact",
                "vehicle_source_allocation_method",
                "grid_to_bus_kwh",
                "pv_to_bus_kwh",
                "bess_to_bus_kwh",
                "pv_to_bess_kwh",
                "grid_to_bess_kwh",
                "pv_curtail_kwh",
                "pv_generation_kwh",
                "pv_utilization_rate",
                "grid_import_total_kwh",
                "total_bus_charge_kwh",
                "total_bess_charge_kwh",
                "bess_initial_soc_kwh",
                "bess_final_soc_kwh",
                "bess_terminal_soc_min_kwh",
                "bess_terminal_soc_violation_kwh",
                "peak_grid_import_kw",
                "peak_grid_import_kw_any_depot",
                "peak_grid_import_kw_all_depots",
                "peak_total_charge_kw",
                "peak_total_charge_kw_any_depot",
                "peak_total_charge_kw_all_depots",
                "contract_limit_kw",
                "contract_over_limit_kwh",
                "contract_over_limit_kw_peak",
                "contract_over_limit_slot_count",
                "contract_limit_exceeded",
                "contract_overage_penalty_enabled",
                "contract_overage_penalty_yen_per_kwh",
                "contract_overage_cost_jpy",
                "demand_charge_cost_jpy",
                "grid_purchase_cost_jpy",
                "bess_discharge_cost_jpy",
                "electricity_cost_jpy",
            ],
        )

    if charging_flow_rows:
        (run_dir / "depot_energy_flows.json").write_text(
            json.dumps(
                {
                    "rows": charging_flow_rows,
                    "summary": charging_summary_payload,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        _write_csv_rows(
            run_dir / "depot_energy_flows.csv",
            charging_flow_rows,
            [
                "depot_id",
                "slot_index",
                "grid_to_bus_kwh",
                "pv_to_bus_kwh",
                "bess_to_bus_kwh",
                "pv_to_bess_kwh",
                "grid_to_bess_kwh",
                "pv_curtail_kwh",
                "pv_curtail_raw_kwh",
                "pv_generation_kwh",
                "pv_balance_residual_kwh",
                "bess_soc_kwh",
                "bess_soc_start_kwh",
                "bess_soc_end_kwh",
                "bess_terminal_soc_target_kwh",
                "bess_terminal_soc_deviation_kwh",
                "bess_terminal_soc_delta_kwh",
                "grid_import_total_kwh",
                "grid_import_for_contract_kwh",
                "grid_import_kw",
                "grid_import_for_contract_kw",
                "bus_charge_from_grid_kwh",
                "bus_charge_from_bess_kwh",
                "total_bus_charge_kwh",
                "total_bess_charge_kwh",
                "total_charge_kw",
                "contract_limit_kw",
                "contract_over_limit_kwh",
                "contract_over_limit_kw",
                "contract_limit_exceeded",
                "energy_price_yen_per_kwh",
                "demand_charge_window_flag",
                "source_provenance_exact",
                "depot_source_provenance_exact",
            ],
        )
    else:
        grid_to_bus_kwh = _evaluation_float(cost_breakdown.get("grid_to_bus_kwh"))
        bess_to_bus_kwh = _evaluation_float(cost_breakdown.get("bess_to_bus_kwh"))
        grid_to_bess_kwh = _evaluation_float(cost_breakdown.get("grid_to_bess_kwh"))
        grid_import_total_kwh = (
            grid_to_bus_kwh + grid_to_bess_kwh
            if grid_to_bus_kwh is not None and grid_to_bess_kwh is not None
            else None
        )
        fallback_rows = [
            {"metric": "grid_to_bus_kwh", "value": grid_to_bus_kwh, "unit": "kWh"},
            {"metric": "grid_to_bess_kwh", "value": grid_to_bess_kwh, "unit": "kWh"},
            {"metric": "grid_import_total_kwh", "value": grid_import_total_kwh, "unit": "kWh"},
            {"metric": "grid_import_for_contract_kwh", "value": grid_import_total_kwh, "unit": "kWh"},
            {"metric": "bus_charge_from_grid_kwh", "value": grid_to_bus_kwh, "unit": "kWh"},
            {"metric": "bus_charge_from_bess_kwh", "value": bess_to_bus_kwh, "unit": "kWh"},
        ]
        (run_dir / "depot_energy_flows.json").write_text(
            json.dumps({"rows": fallback_rows}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        _write_csv_rows(
            run_dir / "depot_energy_flows.csv",
            fallback_rows,
            ["metric", "value", "unit"],
        )

    if charging_summary_payload:
        totals = dict(charging_summary_payload.get("totals") or {})

        def _site_result_value(key: str, *fallback_keys: str) -> Optional[float]:
            for candidate in (key, *fallback_keys):
                if candidate in totals:
                    return _evaluation_float(totals.get(candidate))
            return None

        site_rows = [
            {"metric": "grid_to_bus_kwh", "value": _site_result_value("grid_to_bus_kwh"), "unit": "kWh"},
            {"metric": "pv_to_bus_kwh", "value": _site_result_value("pv_to_bus_kwh"), "unit": "kWh"},
            {"metric": "bess_to_bus_kwh", "value": _site_result_value("bess_to_bus_kwh"), "unit": "kWh"},
            {"metric": "pv_to_bess_kwh", "value": _site_result_value("pv_to_bess_kwh"), "unit": "kWh"},
            {"metric": "grid_to_bess_kwh", "value": _site_result_value("grid_to_bess_kwh"), "unit": "kWh"},
            {"metric": "pv_curtail_kwh", "value": _site_result_value("pv_curtail_kwh"), "unit": "kWh"},
            {"metric": "pv_generation_kwh", "value": _site_result_value("pv_generation_kwh"), "unit": "kWh"},
            {"metric": "pv_utilization_rate", "value": _site_result_value("pv_utilization_rate"), "unit": "ratio"},
            {"metric": "bess_terminal_soc_violation_kwh", "value": _site_result_value("bess_terminal_soc_violation_kwh"), "unit": "kWh"},
            {"metric": "grid_import_total_kwh", "value": _site_result_value("grid_import_total_kwh"), "unit": "kWh"},
            {"metric": "grid_import_for_contract_kwh", "value": _site_result_value("grid_import_for_contract_kwh", "grid_import_total_kwh"), "unit": "kWh"},
            {"metric": "bus_charge_from_grid_kwh", "value": _site_result_value("bus_charge_from_grid_kwh", "grid_to_bus_kwh"), "unit": "kWh"},
            {"metric": "bus_charge_from_bess_kwh", "value": _site_result_value("bus_charge_from_bess_kwh", "bess_to_bus_kwh"), "unit": "kWh"},
            {"metric": "peak_grid_import_kw_all_depots", "value": _site_result_value("peak_grid_import_kw_all_depots"), "unit": "kW"},
            {"metric": "contract_over_limit_kwh", "value": _site_result_value("contract_over_limit_kwh"), "unit": "kWh"},
            {"metric": "contract_overage_cost_jpy", "value": _site_result_value("contract_overage_cost_jpy"), "unit": "JPY"},
            {"metric": "demand_charge_cost_jpy", "value": _site_result_value("demand_charge_cost_jpy"), "unit": "JPY"},
            {"metric": "grid_purchase_cost_jpy", "value": _site_result_value("grid_purchase_cost_jpy"), "unit": "JPY"},
            {"metric": "bess_discharge_cost_jpy", "value": _site_result_value("bess_discharge_cost_jpy"), "unit": "JPY"},
            {"metric": "electricity_cost_jpy", "value": _site_result_value("electricity_cost_jpy"), "unit": "JPY"},
            {"metric": "contract_limit_exceeded", "value": bool(totals.get("contract_limit_exceeded")) if evaluation_valid else None, "unit": "flag"},
        ]
    else:
        grid_to_bus_kwh = _evaluation_float(cost_breakdown.get("grid_to_bus_kwh"))
        bess_to_bus_kwh = _evaluation_float(cost_breakdown.get("bess_to_bus_kwh"))
        grid_to_bess_kwh = _evaluation_float(cost_breakdown.get("grid_to_bess_kwh"))
        grid_import_total_kwh = (
            grid_to_bus_kwh + grid_to_bess_kwh
            if grid_to_bus_kwh is not None and grid_to_bess_kwh is not None
            else None
        )
        site_rows = [
            {"metric": "grid_to_bus_kwh", "value": grid_to_bus_kwh, "unit": "kWh"},
            {"metric": "grid_to_bess_kwh", "value": grid_to_bess_kwh, "unit": "kWh"},
            {"metric": "grid_import_total_kwh", "value": grid_import_total_kwh, "unit": "kWh"},
            {"metric": "grid_import_for_contract_kwh", "value": grid_import_total_kwh, "unit": "kWh"},
            {"metric": "bus_charge_from_grid_kwh", "value": grid_to_bus_kwh, "unit": "kWh"},
            {"metric": "bus_charge_from_bess_kwh", "value": bess_to_bus_kwh, "unit": "kWh"},
        ]
    _write_csv_rows(run_dir / "site_power_balance.csv", site_rows, ["metric", "value", "unit"])

    kpi_summary = {
        "total_cost_jpy": float(cost_breakdown.get("total_cost", 0.0) or 0.0),
        "objective_value_jpy": float(optimization_result.get("objective_value", 0.0) or 0.0),
        "objective_is_actual_cost": bool(cost_breakdown.get("objective_is_actual_cost", False)),
        "supports_exact_milp": bool((optimization_result.get("solver_metadata") or {}).get("supports_exact_milp", False)),
        "electricity_cost_jpy": float(
            cost_breakdown.get("electricity_cost", cost_breakdown.get("electricity_cost_final", 0.0))
            or 0.0
        ),
        "fuel_cost_jpy": float(cost_breakdown.get("fuel_cost", 0.0) or 0.0),
        "fuel_cost_final_jpy": float(cost_breakdown.get("fuel_cost_final", cost_breakdown.get("fuel_cost", 0.0)) or 0.0),
        "fuel_cost_final_source": str(cost_breakdown.get("fuel_cost_final_source", "provisional_distance_based") or "provisional_distance_based"),
        "fuel_cost_provisional_jpy": float(cost_breakdown.get("fuel_cost_provisional", cost_breakdown.get("provisional_ice_drive_cost", 0.0)) or 0.0),
        "fuel_cost_refueled_jpy": float(cost_breakdown.get("fuel_cost_refueled", cost_breakdown.get("realized_ice_refuel_cost", 0.0)) or 0.0),
        "fuel_cost_provisional_leftover_jpy": float(cost_breakdown.get("fuel_cost_provisional_leftover", cost_breakdown.get("leftover_ice_provisional_cost", 0.0)) or 0.0),
        "propulsion_energy_cost_jpy": float(cost_breakdown.get("energy_cost", 0.0) or 0.0),
        "pv_self_consumption_cost_jpy": float(cost_breakdown.get("pv_self_consumption_cost_jpy", 0.0) or 0.0),
        "pv_marginal_charge_cost_yen_per_kwh": float(
            cost_breakdown.get("pv_marginal_charge_cost_yen_per_kwh", 0.0) or 0.0
        ),
        "weather_strategy_objective_term_jpy_equivalent": float(
            cost_breakdown.get("weather_strategy_objective_term_jpy_equivalent", 0.0) or 0.0
        ),
        "grid_import_total_kwh": float(
            dict((charging_summary_payload or {}).get("totals") or {}).get("grid_import_total_kwh", 0.0)
            or (float(cost_breakdown.get("grid_to_bus_kwh", 0.0) or 0.0) + float(cost_breakdown.get("grid_to_bess_kwh", 0.0) or 0.0))
        ),
        "grid_import_for_contract_kwh": float(
            dict((charging_summary_payload or {}).get("totals") or {}).get("grid_import_for_contract_kwh", 0.0)
            or dict((charging_summary_payload or {}).get("totals") or {}).get("grid_import_total_kwh", 0.0)
            or (float(cost_breakdown.get("grid_to_bus_kwh", 0.0) or 0.0) + float(cost_breakdown.get("grid_to_bess_kwh", 0.0) or 0.0))
        ),
        "bus_charge_from_grid_kwh": float(
            dict((charging_summary_payload or {}).get("totals") or {}).get("bus_charge_from_grid_kwh", 0.0)
            or float(cost_breakdown.get("grid_to_bus_kwh", 0.0) or 0.0)
        ),
        "bus_charge_from_bess_kwh": float(
            dict((charging_summary_payload or {}).get("totals") or {}).get("bus_charge_from_bess_kwh", 0.0)
            or float(cost_breakdown.get("bess_to_bus_kwh", 0.0) or 0.0)
        ),
        "served_trip_count": int(summary_payload.get("trip_count_served") or 0),
        "unserved_trip_count": int(summary_payload.get("trip_count_unserved") or 0),
        "solver_runtime_sec": float(optimization_result.get("solve_time_seconds") or 0.0),
        "time_limit_seconds_requested": solver_settings.get("time_limit_seconds_requested"),
        "time_limit_seconds_effective": solver_settings.get("time_limit_seconds_effective"),
        "mip_gap_requested_ratio": solver_settings.get("mip_gap_requested_ratio"),
        "mip_gap_requested_percent": solver_settings.get("mip_gap_requested_percent"),
        "mip_gap_achieved_ratio": solver_settings.get("mip_gap_achieved_ratio"),
        "mip_gap_achieved_percent": solver_settings.get("mip_gap_achieved_percent"),
        "stage1_solver_status": solver_settings.get("stage1_solver_status"),
        "stage1_termination_reason": solver_settings.get(
            "stage1_termination_reason"
        ),
        "stage1_best_obj_stop_enabled": solver_settings.get(
            "stage1_best_obj_stop_enabled"
        ),
        "stage1_best_obj_stop_applied": solver_settings.get(
            "stage1_best_obj_stop_applied"
        ),
        "stage1_best_obj_stop_threshold": solver_settings.get(
            "stage1_best_obj_stop_threshold"
        ),
        "stage1_gurobi_raw_mip_gap_ratio": solver_settings.get(
            "stage1_gurobi_raw_mip_gap_ratio"
        ),
        "stage1_certified_mip_gap_ratio": solver_settings.get(
            "stage1_certified_mip_gap_ratio"
        ),
        "runtime_comparison_eligible": solver_settings.get(
            "runtime_comparison_eligible"
        ),
        "gurobi_threads": solver_settings.get("gurobi_threads"),
    }
    if accounting_summary:
        def _prefer_accounting_value(key: str, fallback: Any) -> Any:
            value = accounting_summary.get(key, None)
            if value in (None, "", 0, 0.0):
                return fallback
            return value

        kpi_summary.update(
            {
                "total_cost_jpy": float(accounting_summary.get("total_cost_jpy", kpi_summary["total_cost_jpy"]) or 0.0),
                "accounting_total_cost_jpy": accounting_summary.get(
                    "accounting_total_cost_jpy", accounting_summary.get("total_cost_jpy")
                ),
                "objective_value_jpy": float(accounting_summary.get("objective_value_jpy", kpi_summary["objective_value_jpy"]) or 0.0),
                "solver_objective_value": accounting_summary.get(
                    "solver_objective_value", accounting_summary.get("objective_value_jpy")
                ),
                "validated_operating_cost_jpy": accounting_summary.get(
                    "validated_operating_cost_jpy"
                ),
                "energy_cost_jpy": float(accounting_summary.get("energy_cost_jpy", kpi_summary["electricity_cost_jpy"]) or 0.0),
                "demand_cost_jpy": float(
                    accounting_summary.get(
                        "demand_cost_jpy",
                        kpi_summary.get("demand_charge_cost_jpy", kpi_summary.get("demand_cost_jpy", 0.0)),
                    )
                    or 0.0
                ),
                "fuel_cost_jpy": float(_prefer_accounting_value("fuel_cost_jpy", kpi_summary["fuel_cost_jpy"]) or 0.0),
                "co2_cost_jpy": float(_prefer_accounting_value("co2_cost_jpy", kpi_summary.get("co2_cost_jpy", 0.0)) or 0.0),
                "battery_degradation_cost_jpy": float(_prefer_accounting_value("battery_degradation_cost_jpy", kpi_summary.get("battery_degradation_cost_jpy", 0.0)) or 0.0),
                "contract_overage_cost_jpy": float(_prefer_accounting_value("contract_overage_cost_jpy", kpi_summary.get("contract_overage_cost_jpy", 0.0)) or 0.0),
                "served_trip_count": int(accounting_summary.get("served_trip_count", kpi_summary["served_trip_count"]) or 0),
                "unserved_trip_count": int(accounting_summary.get("unserved_trip_count", kpi_summary["unserved_trip_count"]) or 0),
                "bev_trip_count": int(accounting_summary.get("bev_trip_count", kpi_summary.get("bev_trip_count", 0)) or 0),
                "ice_trip_count": int(accounting_summary.get("ice_trip_count", kpi_summary.get("ice_trip_count", 0)) or 0),
                "used_vehicle_count": int(accounting_summary.get("used_vehicle_count", kpi_summary.get("used_vehicle_count", 0)) or 0),
                "available_vehicle_count": int(accounting_summary.get("available_vehicle_count", kpi_summary.get("available_vehicle_count", 0)) or 0),
                "vehicle_utilization_ratio": float(accounting_summary.get("vehicle_utilization_ratio", kpi_summary.get("vehicle_utilization_ratio", 0.0)) or 0.0),
                "service_km": float(accounting_summary.get("service_km", kpi_summary.get("service_km", 0.0)) or 0.0),
                "deadhead_before_km": float(accounting_summary.get("deadhead_before_km", kpi_summary.get("deadhead_before_km", 0.0)) or 0.0),
                "deadhead_after_km": float(accounting_summary.get("deadhead_after_km", kpi_summary.get("deadhead_after_km", 0.0)) or 0.0),
                "deadhead_total_km": float(accounting_summary.get("deadhead_total_km", kpi_summary.get("deadhead_total_km", 0.0)) or 0.0),
                "pv_generation_kwh": float(accounting_summary.get("pv_generation_kwh", kpi_summary.get("pv_generation_total_kwh", 0.0)) or 0.0),
                "pv_to_bus_kwh": float(accounting_summary.get("pv_to_bus_kwh", kpi_summary.get("pv_to_bus_kwh", 0.0)) or 0.0),
                "pv_to_bess_kwh": float(accounting_summary.get("pv_to_bess_kwh", kpi_summary.get("pv_to_bess_kwh", 0.0)) or 0.0),
                "bess_to_bus_kwh": float(accounting_summary.get("bess_to_bus_kwh", kpi_summary.get("bess_to_bus_kwh", 0.0)) or 0.0),
                "pv_curtailed_kwh": float(accounting_summary.get("pv_curtailed_kwh", kpi_summary.get("pv_curtail_kwh", 0.0)) or 0.0),
                "pv_utilization_ratio": float(accounting_summary.get("pv_utilization_ratio", kpi_summary.get("pv_utilization_ratio", 0.0)) or 0.0),
                "grid_to_bus_kwh": float(accounting_summary.get("grid_to_bus_kwh", kpi_summary.get("grid_to_bus_kwh", 0.0)) or 0.0),
                "grid_to_bess_kwh": float(accounting_summary.get("grid_to_bess_kwh", kpi_summary.get("grid_to_bess_kwh", 0.0)) or 0.0),
                "grid_total_kwh": float(accounting_summary.get("grid_total_kwh", kpi_summary.get("grid_import_total_kwh", 0.0)) or 0.0),
                "peak_grid_kw": float(accounting_summary.get("peak_grid_kw", kpi_summary.get("peak_grid_import_kw_all_depots", 0.0)) or 0.0),
                "total_charge_input_kwh": float(accounting_summary.get("total_charge_input_kwh", kpi_summary.get("total_charge_input_kwh", 0.0)) or 0.0),
                "min_soc_ratio": float(accounting_summary.get("min_soc_ratio", kpi_summary.get("min_soc_pct", 0.0)) or 0.0),
                "mean_soc_ratio": float(accounting_summary.get("mean_soc_ratio", kpi_summary.get("average_soc_pct", 0.0)) or 0.0),
                "final_min_soc_ratio": float(accounting_summary.get("final_min_soc_ratio", kpi_summary.get("min_soc_pct", 0.0)) or 0.0),
                "final_mean_soc_ratio": float(accounting_summary.get("final_mean_soc_ratio", kpi_summary.get("average_soc_pct", 0.0)) or 0.0),
                "objective_is_actual_cost": bool(accounting_summary.get("objective_is_actual_cost", kpi_summary.get("objective_is_actual_cost", False))),
                "supports_exact_milp": bool(accounting_summary.get("supports_exact_milp", kpi_summary.get("supports_exact_milp", False))),
                "fallback_applied": bool(accounting_summary.get("fallback_applied", kpi_summary.get("fallback_applied", False))),
                # Accounting's legacy flag is vehicle-level: it is false for
                # proportional post-allocation even when the site flow is exact.
                "vehicle_source_provenance_exact": bool(
                    accounting_summary.get(
                        "vehicle_source_provenance_exact",
                        accounting_summary.get(
                            "charging_source_provenance_exact",
                            kpi_summary.get("vehicle_source_provenance_exact", False),
                        ),
                    )
                ),
                "vehicle_source_allocation_method": str(
                    accounting_summary.get(
                        "vehicle_charging_source_allocation_method",
                        kpi_summary.get(
                            "vehicle_source_allocation_method",
                            "proportional_by_depot_timestep",
                        ),
                    )
                    or "proportional_by_depot_timestep"
                ),
                "contract_power_kw": float(accounting_summary.get("contract_power_kw", kpi_summary.get("contract_power_kw", 0.0)) or 0.0),
                "contract_power_exceeded": bool(accounting_summary.get("contract_power_exceeded", kpi_summary.get("contract_power_exceeded", False))),
                "contract_overage_kw": float(accounting_summary.get("contract_overage_kw", kpi_summary.get("contract_overage_kw", 0.0)) or 0.0),
                "contract_power_mode": str(accounting_summary.get("contract_power_mode", kpi_summary.get("contract_power_mode", "report_only")) or "report_only"),
            }
        )
    if charging_summary_payload:
        totals = dict(charging_summary_payload.get("totals") or {})
        depot_source_provenance_exact = bool(
            charging_summary_payload.get(
                "depot_source_provenance_exact",
                charging_summary_payload.get("source_provenance_exact", False),
            )
        )
        vehicle_source_provenance_exact = bool(
            charging_summary_payload.get(
                "vehicle_source_provenance_exact",
                kpi_summary.get("vehicle_source_provenance_exact", False),
            )
        )
        kpi_summary.update(
            {
                "pv_to_bus_kwh": float(totals.get("pv_to_bus_kwh", 0.0) or 0.0),
                "bess_to_bus_kwh": float(totals.get("bess_to_bus_kwh", 0.0) or 0.0),
                "grid_to_bess_kwh": float(totals.get("grid_to_bess_kwh", 0.0) or 0.0),
                "grid_import_for_contract_kwh": float(totals.get("grid_import_for_contract_kwh", totals.get("grid_import_total_kwh", 0.0)) or 0.0),
                "bus_charge_from_grid_kwh": float(totals.get("bus_charge_from_grid_kwh", totals.get("grid_to_bus_kwh", 0.0)) or 0.0),
                "bus_charge_from_bess_kwh": float(totals.get("bus_charge_from_bess_kwh", totals.get("bess_to_bus_kwh", 0.0)) or 0.0),
                "pv_to_bess_kwh": float(totals.get("pv_to_bess_kwh", 0.0) or 0.0),
                "contract_over_limit_kwh": float(totals.get("contract_over_limit_kwh", 0.0) or 0.0),
                "contract_overage_cost_jpy": float(totals.get("contract_overage_cost_jpy", 0.0) or 0.0),
                "demand_charge_cost_jpy": float(totals.get("demand_charge_cost_jpy", 0.0) or 0.0),
                "peak_grid_import_kw_all_depots": float(totals.get("peak_grid_import_kw_all_depots", 0.0) or 0.0),
                "contract_limit_exceeded": bool(totals.get("contract_limit_exceeded", False)),
                "depot_source_provenance_exact": depot_source_provenance_exact,
                "vehicle_source_provenance_exact": vehicle_source_provenance_exact,
                "vehicle_source_allocation_method": str(
                    charging_summary_payload.get(
                        "vehicle_source_allocation_method",
                        kpi_summary.get(
                            "vehicle_source_allocation_method",
                            "proportional_by_depot_timestep",
                        ),
                    )
                    or "proportional_by_depot_timestep"
                ),
                # This combined flag is only true when neither the site nor
                # per-vehicle source breakdown is inferred.
                "charging_source_provenance_exact": bool(
                    depot_source_provenance_exact
                    and vehicle_source_provenance_exact
                ),
                "charging_source_provenance_scope": "site_and_vehicle",
            }
        )
    if not evaluation_valid:
        _invalidate_mapping_metrics(kpi_summary)
        kpi_summary.update(
            {
                "served_trip_count": int(result_summary.get("trip_count_served") or 0),
                "unserved_trip_count": int(result_summary.get("trip_count_unserved") or 0),
                "result_status": optimization_result.get("result_status") or "INVALID",
                "failure_stage": optimization_result.get("failure_stage")
                or "result_validation",
                "research_kpi_eligible": False,
            }
        )
    (run_dir / "kpi_summary.json").write_text(
        json.dumps(kpi_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    reporting_finalizer_result: Optional[Dict[str, Any]] = None
    optimization_audit["experiment_report"] = {
        "status": "not_requested",
        "reason": "Reporting finalization was not requested for this run.",
    }
    if finalize_reporting:
        reporting_finalizer_result = _run_reporting_finalizer(run_dir)
        graph_artifacts = dict(optimization_result.get("graph_artifacts") or {})
        graph_artifacts["reporting_finalizer"] = reporting_finalizer_result
        optimization_result["graph_artifacts"] = graph_artifacts
        if reporting_finalizer_result.get("status") != "completed":
            warning = (
                "Reporting artifact finalization failed after optimization outputs were written: "
                f"{reporting_finalizer_result.get('error') or 'unknown error'}"
            )
            optimization_result["warnings"] = list(
                dict.fromkeys([*list(optimization_result.get("warnings") or []), warning])
            )
            optimization_audit["warnings"] = list(
                dict.fromkeys([*list(optimization_audit.get("warnings") or []), warning])
            )
        (run_dir / "optimization_result.json").write_text(
            json.dumps(optimization_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (run_dir / "optimization_audit.json").write_text(
            json.dumps(optimization_audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (raw_dir / "optimization_result.json").write_text(
            json.dumps(optimization_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (raw_dir / "optimization_audit.json").write_text(
            json.dumps(optimization_audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        if reporting_finalizer_result.get("status") == "completed":
            try:
                finalized_accounting = _finalized_accounting_summary_for_experiment_report(
                    run_dir
                )
                experiment_report = log_optimization_experiment(
                    scenario_id=str(optimization_result.get("scenario_id") or ""),
                    scenario_doc=scenario,
                    optimization_result=optimization_result,
                    accounting_summary_override=finalized_accounting,
                    git_commit_override=str(optimization_audit.get("git_sha") or "")
                    or None,
                )
                optimization_result["experiment_report"] = experiment_report
                source_json_path = experiment_report.get("json_path")
                source_md_path = experiment_report.get("md_path")
                local_json_path = None
                local_md_path = None
                if isinstance(source_json_path, str) and source_json_path.strip():
                    src_json = Path(source_json_path)
                    if src_json.exists():
                        local_json_path = "experiment_report.json"
                        shutil.copy2(src_json, run_dir / local_json_path)
                if isinstance(source_md_path, str) and source_md_path.strip():
                    src_md = Path(source_md_path)
                    if src_md.exists():
                        local_md_path = "experiment_report.md"
                        shutil.copy2(src_md, run_dir / local_md_path)
                optimization_audit["experiment_report"] = {
                    "status": "generated",
                    "experiment_id": experiment_report.get("experiment_id"),
                    "source_json_path": source_json_path,
                    "source_md_path": source_md_path,
                    "run_json_path": local_json_path,
                    "run_md_path": local_md_path,
                    "accounting_source": finalized_accounting.get(
                        "experiment_report_accounting_source"
                    ),
                    "accounting_reconciled": bool(
                        finalized_accounting.get("experiment_report_accounting_reconciled")
                    ),
                    "accounting_residual_jpy": finalized_accounting.get(
                        "experiment_report_accounting_residual_jpy"
                    ),
                }
            except Exception as exc:
                warning = f"Canonical experiment report generation failed: {exc}"
                optimization_result["warnings"] = list(
                    dict.fromkeys([*list(optimization_result.get("warnings") or []), warning])
                )
                optimization_audit["warnings"] = list(
                    dict.fromkeys([*list(optimization_audit.get("warnings") or []), warning])
                )
                optimization_audit["experiment_report"] = {
                    "status": "failed",
                    "error": str(exc),
                }
        else:
            optimization_audit["experiment_report"] = {
                "status": "not_generated",
                "reason": "Canonical reporting finalization failed.",
                "reporting_finalizer_status": reporting_finalizer_result.get("status"),
            }

        (run_dir / "optimization_result.json").write_text(
            json.dumps(optimization_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (run_dir / "optimization_audit.json").write_text(
            json.dumps(optimization_audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (raw_dir / "optimization_result.json").write_text(
            json.dumps(optimization_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (raw_dir / "optimization_audit.json").write_text(
            json.dumps(optimization_audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    try:
        from openpyxl import Workbook

        wb = Workbook()
        ws_summary = wb.active
        ws_summary.title = "summary"
        ws_summary.append(["key", "value", "unit"])
        ws_summary.append(["objective_value", summary.get("objective_value"), "JPY"])
        ws_summary.append(["solve_time_seconds", summary.get("solve_time_seconds"), "s"])
        ws_summary.append(["trip_count_served", summary.get("trip_count_served"), "trips"])
        ws_summary.append(["trip_count_unserved", summary.get("trip_count_unserved"), "trips"])

        ws_cost = wb.create_sheet("cost_breakdown")
        ws_cost.append(["key", "value", "unit"])
        for row in cost_rows:
            ws_cost.append([row.get("key"), row.get("value"), row.get("unit")])

        wb.save(run_dir / "results.xlsx")
    except Exception:
        pass

    run_input_manifest_path = run_dir / RUN_INPUT_MANIFEST_FILE
    run_input_manifest = {}
    if run_input_manifest_path.is_file():
        run_input_manifest = json.loads(
            run_input_manifest_path.read_text(encoding="utf-8")
        )
    solver_metadata = dict(optimization_result.get("solver_metadata") or {})
    input_git_provenance = dict(run_input_manifest.get("code_provenance") or {})
    git_provenance = {
        "git_sha": solver_metadata.get("git_sha", input_git_provenance.get("git_sha")),
        "git_dirty": solver_metadata.get("git_dirty", input_git_provenance.get("git_dirty")),
        "git_state_available": bool(
            solver_metadata.get(
                "git_state_available",
                input_git_provenance.get("git_state_available", False),
            )
        ),
        "git_state_error": solver_metadata.get(
            "git_state_error",
            input_git_provenance.get("git_state_error"),
        ),
    }
    rolling_execution_minutes = solver_metadata.get("rolling_execution_minutes")
    rolling_policy = str(solver_metadata.get("rolling_horizon_policy") or "").strip()
    rolling_execution = {
        "status": (
            "executed"
            if rolling_execution_minutes is not None or rolling_policy
            else "not_executed"
        ),
        "rolling_horizon_policy": rolling_policy or None,
        "rolling_execution_minutes": rolling_execution_minutes,
        "semantics": (
            "This manual frontend artifact is a day-ahead optimization result. "
            "Hourly rolling evidence is a separate execution chain."
        ),
    }
    research_claim_scope = _research_claim_scope_payload(
        optimization_result=optimization_result,
        solver_settings=solver_settings,
        weather_policy=weather_policy,
        rolling_execution=rolling_execution,
    )
    optimization_result["research_claim_scope"] = research_claim_scope
    optimization_audit["research_claim_scope"] = research_claim_scope
    (run_dir / "research_claim_scope.json").write_text(
        json.dumps(research_claim_scope, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (run_dir / "optimization_result.json").write_text(
        json.dumps(optimization_result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "optimization_audit.json").write_text(
        json.dumps(optimization_audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (raw_dir / "optimization_result.json").write_text(
        json.dumps(optimization_result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (raw_dir / "optimization_audit.json").write_text(
        json.dumps(optimization_audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    run_manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scenario_id": optimization_result.get("scenario_id"),
        "service_date": (
            (optimization_result.get("graph_artifacts") or {}).get("accounting_summary") or {}
        ).get("service_date")
        or ((scenario.get("simulation_config") or {}).get("service_date") or ""),
        **git_provenance,
        "research_run": bool(solver_metadata.get("research_run", False)),
        "research_run_accepted": bool(solver_metadata.get("research_run_accepted", False)),
        "research_submission_git_provenance_eligible": bool(
            solver_metadata.get("research_submission_git_provenance_eligible", False)
        ),
        "requested_phase": solver_metadata.get("requested_phase"),
        "resolved_phase": solver_metadata.get("resolved_phase"),
        "executed_phase": solver_metadata.get("executed_phase"),
        "files": sorted(
            [p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*") if p.is_file()]
        ),
        "units": unit_map,
        "weather_proxy_enabled": bool(weather_policy.get("enabled")),
        "weather_proxy_version": (
            (weather_policy.get("forecast") or {}).get("version")
            if weather_policy.get("enabled")
            else None
        ),
        "weather_operation_mode": (
            (weather_policy.get("operation_profile") or {}).get("operation_mode")
            if weather_policy.get("enabled")
            else None
        ),
        "weather_analog_date": (
            (weather_policy.get("forecast") or {}).get("analog_date")
            if weather_policy.get("enabled")
            else None
        ),
        "weather_typical_class": (
            (weather_policy.get("representative_curve") or {}).get("typical_weather_class")
            if weather_policy.get("enabled")
            else None
        ),
        "weather_pv_curve_applied": (
            bool((weather_policy.get("audit") or {}).get("weather_pv_forecast_applied"))
            if weather_policy.get("enabled")
            else False
        ),
        "weather_pv_source_dates": (
            list((weather_policy.get("representative_curve") or {}).get("source_dates") or ())
            if weather_policy.get("enabled")
            else []
        ),
        "solver_settings": solver_settings,
        "simulation_conditions": condition_provenance,
        "run_input_provenance": {
            "status": "OK" if run_input_manifest else "MISSING",
            "manifest_path": (
                RUN_INPUT_MANIFEST_FILE if run_input_manifest else None
            ),
            "schema_version": run_input_manifest.get("schema_version"),
            "prepared_input_id": run_input_manifest.get("prepared_input_id"),
            "prepared_source_sha256": run_input_manifest.get(
                "prepared_source_sha256"
            ),
            "artifacts": dict(run_input_manifest.get("artifacts") or {}),
            "git_state_available": bool(
                input_git_provenance.get("git_state_available", False)
            ),
            "git_sha": input_git_provenance.get("git_sha"),
        },
        "rolling_execution": rolling_execution,
        "research_claim_scope": research_claim_scope,
        "experiment_report": dict(optimization_audit.get("experiment_report") or {}),
        "formal_phase3_weather_submission_readiness": {
            "ready": False,
            "reason": (
                "This is a manual frontend day-ahead artifact. Formal Phase 3 "
                "weather submission additionally requires the strict CLI runner, "
                "an accepted same-service-date comparison, and a completed hourly "
                "rolling chain."
            ),
            "day_ahead_research_run_accepted": bool(
                solver_metadata.get("research_run_accepted", False)
            ),
            "git_provenance_eligible": bool(
                solver_metadata.get("research_submission_git_provenance_eligible", False)
            ),
            "rolling_execution_status": rolling_execution["status"],
        },
        "graph": {
            "manifest_path": "graph/manifest.json",
            "route_band_diagrams_manifest": str(
                graph_artifacts.get("manifest_path") or "graph/route_band_diagrams/manifest.json"
            ),
            "route_band_diagram_count": int(graph_artifacts.get("diagram_count") or 0),
            "vehicle_operation_diagrams_manifest": str(
                graph_artifacts.get("vehicle_operation_diagram_manifest_path") or ""
            ),
            "vehicle_operation_diagram_count": int(
                graph_artifacts.get("vehicle_operation_diagram_count") or 0
            ),
            "reporting_finalizer": reporting_finalizer_result
            or graph_artifacts.get("reporting_finalizer")
            or {},
        },
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return reporting_finalizer_result


def _run_reporting_finalizer(run_dir: Path) -> Dict[str, Any]:
    try:
        from src.reporting import rebuild_reporting_artifacts_in_place

        result = rebuild_reporting_artifacts_in_place(run_dir)
        return {
            "status": "completed",
            "updated_files": list(result.updated_files),
            "validation_status": dict(result.validation_status),
            "warnings": list(result.warnings),
        }
    except Exception as exc:
        return {
            "status": "failed",
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }


def _finalized_accounting_summary_for_experiment_report(run_dir: Path) -> Dict[str, Any]:
    """Load the final accounting ledger used by the human experiment report.

    The reporting finalizer can rebuild the canonical ledger after the solver
    result is first assembled.  Reading its sidecar artifacts here prevents an
    early, provisional objective breakdown from being presented as the final
    accounting cost.
    """

    def _read_mapping(path: Path) -> Dict[str, Any]:
        if not path.is_file():
            return {}
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return dict(loaded) if isinstance(loaded, dict) else {}

    kpi_summary = _read_mapping(run_dir / "kpi_summary.json")
    summary = _read_mapping(run_dir / "summary.json")
    if not summary:
        raise ValueError("Finalized summary.json is missing")

    canonical = dict(kpi_summary)
    # summary.json is the finalizer's canonical source for the values that a
    # reviewer compares across runs.  It intentionally overrides the older
    # provisional values in kpi_summary.json.
    for key in (
        "total_cost_jpy",
        "accounting_total_cost_jpy",
        "objective_value_jpy",
        "energy_cost_jpy",
        "grid_purchase_cost_jpy",
        "demand_charge_cost_jpy",
        "fuel_cost_jpy",
        "co2_cost_jpy",
        "vehicle_usage_cost_jpy",
        "total_co2_kg",
        "served_trip_count",
        "unserved_trip_count",
        "bev_trip_count",
        "ice_trip_count",
        "used_vehicle_count",
        "bus_charging_total_kwh",
        "peak_grid_import_kw",
        "objective_is_actual_cost",
    ):
        if key in summary:
            canonical[key] = summary[key]

    required_cost_keys = (
        "accounting_total_cost_jpy",
        "grid_purchase_cost_jpy",
        "demand_charge_cost_jpy",
        "fuel_cost_jpy",
        "co2_cost_jpy",
        "vehicle_usage_cost_jpy",
    )
    missing = [key for key in required_cost_keys if canonical.get(key) is None]
    if missing:
        raise ValueError(
            "Finalized accounting ledger is missing required cost fields: "
            + ", ".join(missing)
        )
    accounting_total = float(canonical["accounting_total_cost_jpy"])
    reconciled_components = sum(
        float(canonical[key]) for key in required_cost_keys[1:]
    )
    residual = accounting_total - reconciled_components
    if not math.isclose(residual, 0.0, abs_tol=1.0e-6):
        raise ValueError(
            "Finalized accounting ledger does not reconcile: "
            f"total={accounting_total}, components={reconciled_components}, "
            f"residual={residual}"
        )
    canonical["experiment_report_accounting_reconciled"] = True
    canonical["experiment_report_accounting_residual_jpy"] = residual
    canonical["experiment_report_accounting_source"] = (
        "finalized_summary_and_kpi_sidecars"
    )
    return canonical


def _research_claim_scope_payload(
    *,
    optimization_result: Dict[str, Any],
    solver_settings: Dict[str, Any],
    weather_policy: Dict[str, Any],
    rolling_execution: Dict[str, Any],
) -> Dict[str, Any]:
    """State what a manual frontend run may, and may not, support.

    This is deliberately a claim gate rather than a score.  It prevents a
    PV-only manual day-ahead artifact from being relabelled later as a formal
    weather-adaptive dispatch result, a runtime benchmark, or an integrated
    global optimum.
    """

    metadata = dict(optimization_result.get("solver_metadata") or {})
    solution_validity = dict(optimization_result.get("solution_validity") or {})
    decision_policy = dict(
        (weather_policy.get("audit") or {}).get("decision_policy")
        or weather_policy.get("decision_policy")
        or {}
    )
    weather_enabled = bool(weather_policy.get("enabled", False))
    policy_scope = str(decision_policy.get("policy_scope") or "not_enabled")
    physically_feasible = bool(solution_validity.get("validated_feasible", False))
    is_integrated_exact = bool(metadata.get("supports_integrated_exact_milp", False))
    is_manual_unaccepted = not bool(metadata.get("research_run_accepted", False))
    if weather_enabled and policy_scope == "pv_curve_only":
        result_label = "exploratory_pv_supply_sensitivity_not_weather_adaptive_dispatch"
    elif weather_enabled:
        result_label = "manual_weather_policy_day_ahead_result_not_formal_comparison"
    else:
        result_label = "manual_day_ahead_feasibility_result"

    allowed_claims: list[str] = []
    if physically_feasible:
        allowed_claims.append("physical_schedule_feasibility_under_recorded_inputs")
    if weather_enabled:
        allowed_claims.append("recorded_pv_supply_effect_on_depot_energy_flows")
    disallowed_claims = [
        "integrated_global_total_cost_optimum",
        "actual_monthly_demand_charge_savings",
        "pv_or_bess_investment_economics",
    ]
    if policy_scope != "weather_dispatch_policy":
        disallowed_claims.append("weather_adaptive_dispatch_or_charging_policy")
    if is_manual_unaccepted:
        disallowed_claims.append("formal_research_weather_comparison")
    if rolling_execution.get("status") != "executed":
        disallowed_claims.append("hourly_rolling_reoptimization_performance")
    # A single manually initiated run can record whether BestObjStop was out of
    # the way, but it cannot itself establish a runtime comparison.  That also
    # needs matched cross-case controls and repeated measurements.
    disallowed_claims.append("wall_clock_runtime_comparison")

    return {
        "schema_version": "research_claim_scope_v1",
        "result_label": result_label,
        "physical_feasibility_claim_eligible": physically_feasible,
        "weather_policy_scope": policy_scope,
        "weather_adaptive_dispatch_claim_eligible": (
            weather_enabled
            and policy_scope == "weather_dispatch_policy"
            and not is_manual_unaccepted
        ),
        "formal_weather_comparison_claim_eligible": False,
        "integrated_global_optimality_claim_eligible": is_integrated_exact,
        "runtime_comparison_claim_eligible": False,
        "demand_charge_claim_scope": (
            "planning_horizon_allocation_proxy_not_actual_monthly_bill_savings"
        ),
        "asset_economics_claim_eligible": False,
        "allowed_claims": allowed_claims,
        "disallowed_claims": sorted(set(disallowed_claims)),
        "evidence": {
            "research_run": bool(metadata.get("research_run", False)),
            "research_run_accepted": bool(
                metadata.get("research_run_accepted", False)
            ),
            "optimization_structure": metadata.get("optimization_structure"),
            "supports_integrated_exact_milp": is_integrated_exact,
            "weather_policy_scope": policy_scope,
            "rolling_execution_status": rolling_execution.get("status"),
            "stage1_best_obj_stop_applied": solver_settings.get(
                "stage1_best_obj_stop_applied"
            ),
            "stage1_stop_rule_runtime_control_eligible": solver_settings.get(
                "runtime_comparison_eligible"
            ),
            "runtime_comparison_claim_requires": [
                "matched_cross_case_solver_controls",
                "fixed_explicit_gurobi_threads",
                "multiple_repetitions",
            ],
        },
    }


def _canonical_vehicle_timeline_rows(
    *,
    problem,
    engine_result,
    scenario_id: str,
    graph_context: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    from src.result_exporter import _route_band_key

    rows: List[Dict[str, Any]] = []
    problem_trip_by_id = problem.trip_by_id()
    vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
    band_labels_by_band_id = dict((graph_context or {}).get("band_labels_by_band_id") or {})
    base_date = _canonical_output_base_date(problem, graph_context)
    depot_name_by_id = {
        str(depot.depot_id): str(getattr(depot, "name", "") or getattr(depot, "depot_id", "") or "")
        for depot in problem.depots
    }
    duties_by_vehicle = engine_result.plan.duties_by_vehicle()
    charge_slots_by_vehicle: Dict[str, List[Any]] = defaultdict(list)
    for slot in engine_result.plan.charging_slots:
        charge_slots_by_vehicle[str(slot.vehicle_id)].append(slot)
    refuel_slots_by_vehicle: Dict[str, List[Any]] = defaultdict(list)
    for slot in engine_result.plan.refuel_slots:
        refuel_slots_by_vehicle[str(slot.vehicle_id)].append(slot)

    active_vehicle_ids = vehicle_ids_with_timeline_activity(
        duties_by_vehicle,
        engine_result.plan.charging_slots,
        engine_result.plan.refuel_slots,
    )
    for vehicle_id in active_vehicle_ids:
        duties = list(duties_by_vehicle.get(str(vehicle_id), []))
        vehicle = vehicle_by_id.get(str(vehicle_id))
        depot_id = str(getattr(vehicle, "home_depot_id", "") or "")
        depot_label = depot_name_by_id.get(depot_id) or depot_id
        vehicle_type = str(getattr(vehicle, "vehicle_type", "") or (duties[0].vehicle_type if duties else ""))
        band_counter: Counter[str] = Counter()
        for duty in duties:
            for leg in duty.legs:
                trip_id = str(getattr(leg.trip, "trip_id", "") or "")
                problem_trip = problem_trip_by_id.get(trip_id)
                if problem_trip is None:
                    continue
                route_family_code = str(getattr(leg.trip, "route_family_code", "") or "")
                route_id = str(getattr(leg.trip, "route_id", problem_trip.route_id) or problem_trip.route_id)
                band_id = _route_band_key(route_family_code, route_id)
                if band_id:
                    band_counter[band_id] += 1
        primary_band_id = ""
        primary_band_label = ""
        if band_counter:
            primary_band_id = sorted(
                band_counter.items(),
                key=lambda item: (-item[1], item[0]),
            )[0][0]
            primary_band_label = str(band_labels_by_band_id.get(primary_band_id) or primary_band_id)

        for duty in duties:
            prev_trip = None
            prev_band_id = ""
            for leg in duty.legs:
                dispatch_trip = leg.trip
                trip_id = str(dispatch_trip.trip_id or "")
                problem_trip = problem_trip_by_id.get(trip_id)
                if problem_trip is None:
                    continue
                route_family_code = str(getattr(dispatch_trip, "route_family_code", "") or "")
                route_id = str(getattr(dispatch_trip, "route_id", problem_trip.route_id) or problem_trip.route_id)
                band_id = _route_band_key(route_family_code, route_id)
                band_label = str(band_labels_by_band_id.get(band_id) or band_id)
                start_dt = _canonical_datetime_from_min(base_date, int(dispatch_trip.departure_min))
                end_min = int(dispatch_trip.arrival_min)
                if end_min <= int(dispatch_trip.departure_min):
                    end_min += 24 * 60
                end_dt = _canonical_datetime_from_min(base_date, end_min)
                variant = str(getattr(dispatch_trip, "route_variant_type", "") or "")
                deadhead_min = max(int(getattr(leg, "deadhead_from_prev_min", 0) or 0), 0)
                if deadhead_min > 0:
                    deadhead_start = _canonical_datetime_from_min(
                        base_date,
                        int(dispatch_trip.departure_min) - deadhead_min,
                    )
                    deadhead_band_id = band_id if prev_trip is None or prev_band_id == band_id else ""
                    rows.append(
                        {
                            "scenario_id": scenario_id,
                            "depot_id": depot_id,
                            "vehicle_id": str(vehicle_id),
                            "vehicle_type": vehicle_type,
                            "band_id": deadhead_band_id,
                            "band_label": str(band_labels_by_band_id.get(deadhead_band_id) or deadhead_band_id),
                            "vehicle_primary_band_id": primary_band_id,
                            "vehicle_primary_band_label": primary_band_label,
                            "start_time": deadhead_start.isoformat(),
                            "end_time": start_dt.isoformat(),
                            "state": "deadhead",
                            "route_id": "",
                            "route_family_code": route_family_code,
                            "route_series_code": deadhead_band_id,
                            "event_route_band_id": deadhead_band_id,
                            "trip_id": "",
                            "from_location_id": (
                                depot_label
                                if prev_trip is None
                                else str(getattr(prev_trip, "destination", "") or "")
                            ),
                            "to_location_id": str(dispatch_trip.origin or ""),
                            "from_location_type": "depot" if prev_trip is None else "terminal",
                            "to_location_type": "terminal",
                            "direction": "",
                            "route_variant_type": "",
                            "energy_delta_kwh": -_canonical_estimated_deadhead_energy_kwh(
                                problem,
                                deadhead_min=deadhead_min,
                                trip_energy_kwh=float(getattr(problem_trip, "energy_kwh", 0.0) or 0.0),
                                trip_distance_km=float(getattr(problem_trip, "distance_km", 0.0) or 0.0),
                            ),
                            "distance_km": _canonical_deadhead_distance_km(problem, deadhead_min),
                            "duration_min": float(deadhead_min),
                            "is_deadhead": True,
                            "is_charge": False,
                            "is_service": False,
                            "is_idle": False,
                            "is_depot_move": prev_trip is None,
                            "is_short_turn": False,
                            "charger_id": "",
                            "charge_power_kw": "",
                            "refuel_liters": "",
                        }
                    )

                rows.append(
                    {
                        "scenario_id": scenario_id,
                        "depot_id": depot_id,
                        "vehicle_id": str(vehicle_id),
                        "vehicle_type": vehicle_type,
                        "band_id": band_id,
                        "band_label": band_label,
                        "vehicle_primary_band_id": primary_band_id,
                        "vehicle_primary_band_label": primary_band_label,
                        "start_time": start_dt.isoformat(),
                        "end_time": end_dt.isoformat(),
                        "state": "service",
                        "route_id": route_id,
                        "route_family_code": route_family_code,
                        "route_series_code": band_id,
                        "event_route_band_id": band_id,
                        "trip_id": trip_id,
                        "from_location_id": str(dispatch_trip.origin or ""),
                        "to_location_id": str(dispatch_trip.destination or ""),
                        "from_location_type": "terminal",
                        "to_location_type": "terminal",
                        "direction": str(getattr(dispatch_trip, "direction", "") or ""),
                        "route_variant_type": variant,
                        "energy_delta_kwh": -max(float(getattr(problem_trip, "energy_kwh", 0.0) or 0.0), 0.0),
                        "distance_km": max(float(getattr(problem_trip, "distance_km", 0.0) or 0.0), 0.0),
                        "duration_min": max((end_dt - start_dt).total_seconds() / 60.0, 0.0),
                        "is_deadhead": False,
                        "is_charge": False,
                        "is_service": True,
                        "is_idle": False,
                        "is_depot_move": variant in {"depot_move", "depot_in", "depot_out"},
                        "is_short_turn": variant == "short_turn",
                        "charger_id": "",
                        "charge_power_kw": "",
                        "refuel_liters": "",
                    }
                )
                prev_trip = dispatch_trip
                prev_band_id = band_id

        for start_slot, end_slot, charger_id, avg_charge_kw, avg_discharge_kw, location_id in _canonical_charge_segments(
            problem,
            charge_slots_by_vehicle.get(str(vehicle_id), []),
            fallback_location_id=depot_id,
        ):
            charge_start = _canonical_slot_datetime(problem, base_date, start_slot)
            charge_end = _canonical_slot_datetime(problem, base_date, end_slot)
            duration_min = max((charge_end - charge_start).total_seconds() / 60.0, 0.0)
            net_power_kw = avg_charge_kw - avg_discharge_kw
            rows.append(
                {
                    "scenario_id": scenario_id,
                    "depot_id": depot_id,
                    "vehicle_id": str(vehicle_id),
                    "vehicle_type": vehicle_type,
                    "band_id": "",
                    "band_label": "",
                    "vehicle_primary_band_id": primary_band_id,
                    "vehicle_primary_band_label": primary_band_label,
                    "start_time": charge_start.isoformat(),
                    "end_time": charge_end.isoformat(),
                    "state": "charge",
                    "route_id": "",
                    "route_family_code": "",
                    "route_series_code": "",
                    "event_route_band_id": "",
                    "trip_id": "",
                    "from_location_id": location_id,
                    "to_location_id": location_id,
                    "from_location_type": "charger",
                    "to_location_type": "charger",
                    "direction": "",
                    "route_variant_type": "",
                    "energy_delta_kwh": net_power_kw * duration_min / 60.0,
                    "distance_km": 0.0,
                    "duration_min": duration_min,
                    "is_deadhead": False,
                    "is_charge": True,
                    "is_service": False,
                    "is_idle": False,
                    "is_depot_move": False,
                    "is_short_turn": False,
                    "charger_id": charger_id,
                    "charge_power_kw": net_power_kw,
                    "refuel_liters": "",
                }
            )

        for refuel_slot in sorted(
            refuel_slots_by_vehicle.get(str(vehicle_id), []),
            key=lambda slot: (int(getattr(slot, "slot_index", 0) or 0), str(getattr(slot, "vehicle_id", "") or "")),
        ):
            liters = max(float(getattr(refuel_slot, "refuel_liters", 0.0) or 0.0), 0.0)
            if liters <= 0.0:
                continue
            slot_index = int(getattr(refuel_slot, "slot_index", 0) or 0)
            refuel_start = _canonical_slot_datetime(problem, base_date, slot_index)
            refuel_end = _canonical_slot_datetime(problem, base_date, slot_index + 1)
            location_id = str(getattr(refuel_slot, "location_id", "") or depot_id or depot_label)
            rows.append(
                {
                    "scenario_id": scenario_id,
                    "depot_id": depot_id,
                    "vehicle_id": str(vehicle_id),
                    "vehicle_type": vehicle_type,
                    "band_id": "",
                    "band_label": "",
                    "vehicle_primary_band_id": primary_band_id,
                    "vehicle_primary_band_label": primary_band_label,
                    "start_time": refuel_start.isoformat(),
                    "end_time": refuel_end.isoformat(),
                    "state": "refuel",
                    "route_id": "",
                    "route_family_code": "",
                    "route_series_code": "",
                    "event_route_band_id": "",
                    "trip_id": "",
                    "from_location_id": location_id,
                    "to_location_id": location_id,
                    "from_location_type": "depot",
                    "to_location_type": "depot",
                    "direction": "",
                    "route_variant_type": "depot_refuel",
                    "energy_delta_kwh": "",
                    "distance_km": 0.0,
                    "duration_min": max((refuel_end - refuel_start).total_seconds() / 60.0, 0.0),
                    "is_deadhead": False,
                    "is_charge": False,
                    "is_service": False,
                    "is_idle": False,
                    "is_depot_move": True,
                    "is_short_turn": False,
                    "charger_id": "",
                    "charge_power_kw": "",
                    "refuel_liters": round(liters, 4),
                }
            )
    rows.sort(key=lambda row: (str(row.get("vehicle_id") or ""), str(row.get("start_time") or ""), str(row.get("trip_id") or "")))
    return rows


def _canonical_charge_segments(
    problem,
    charging_slots: List[Any],
    *,
    fallback_location_id: str,
) -> List[tuple[int, int, str, float, float, str]]:
    del problem
    grouped: Dict[tuple[str, str], Dict[int, tuple[float, float, str]]] = defaultdict(dict)
    for slot in charging_slots:
        slot_index = int(getattr(slot, "slot_index", 0) or 0)
        charger_id = str(getattr(slot, "charger_id", "") or "")
        location_id = str(getattr(slot, "charging_depot_id", "") or fallback_location_id)
        grouped[(charger_id, location_id)][slot_index] = (
            max(float(getattr(slot, "charge_kw", 0.0) or 0.0), 0.0),
            max(float(getattr(slot, "discharge_kw", 0.0) or 0.0), 0.0),
            location_id,
        )

    segments: List[tuple[int, int, str, float, float, str]] = []
    for (charger_id, location_id), slot_map in grouped.items():
        ordered_slots = sorted(slot_map)
        if not ordered_slots:
            continue
        seg_start = ordered_slots[0]
        seg_end = seg_start + 1
        charge_values = [slot_map[seg_start][0]]
        discharge_values = [slot_map[seg_start][1]]
        for slot_index in ordered_slots[1:]:
            if slot_index == seg_end:
                seg_end += 1
                charge_values.append(slot_map[slot_index][0])
                discharge_values.append(slot_map[slot_index][1])
                continue
            segments.append(
                (
                    seg_start,
                    seg_end,
                    charger_id,
                    sum(charge_values) / len(charge_values),
                    sum(discharge_values) / len(discharge_values),
                    location_id,
                )
            )
            seg_start = slot_index
            seg_end = slot_index + 1
            charge_values = [slot_map[slot_index][0]]
            discharge_values = [slot_map[slot_index][1]]
        segments.append(
            (
                seg_start,
                seg_end,
                charger_id,
                sum(charge_values) / len(charge_values),
                sum(discharge_values) / len(discharge_values),
                location_id,
            )
        )
    return sorted(segments, key=lambda item: (item[0], item[2], item[5]))


def _canonical_trip_assignment_rows(
    *,
    problem,
    engine_result,
    scenario_id: str,
    base_date: date,
    timeline_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    primary_band_by_vehicle = {
        str(row.get("vehicle_id") or ""): {
            "band_id": str(row.get("vehicle_primary_band_id") or ""),
            "band_label": str(row.get("vehicle_primary_band_label") or ""),
        }
        for row in timeline_rows
        if str(row.get("vehicle_id") or "").strip() and str(row.get("vehicle_primary_band_id") or "").strip()
    }
    problem_trip_by_id = problem.trip_by_id()
    vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
    rows: List[Dict[str, Any]] = []
    sequence_by_vehicle: Dict[str, int] = defaultdict(int)
    for vehicle_id, duties in sorted(engine_result.plan.duties_by_vehicle().items()):
        for duty in duties:
            vehicle_id = str(vehicle_id)
            # ``duties_by_vehicle`` is the canonical chronological order.  Do
            # not sort by trip_id: lexical IDs can reverse the actual service
            # order and make downstream timeline validation meaningless.
            vehicle = vehicle_by_id.get(vehicle_id)
            duty_legs = list(duty.legs)
            for index, leg in enumerate(duty_legs):
                sequence_by_vehicle[vehicle_id] += 1
                sequence = sequence_by_vehicle[vehicle_id]
                dispatch_trip = leg.trip
                trip_id = str(dispatch_trip.trip_id or "")
                problem_trip = problem_trip_by_id.get(trip_id)
                if problem_trip is None:
                    continue
                next_deadhead_min = 0
                if index + 1 < len(duty_legs):
                    next_deadhead_min = max(int(getattr(duty_legs[index + 1], "deadhead_from_prev_min", 0) or 0), 0)
                route_family_code = str(getattr(dispatch_trip, "route_family_code", "") or "")
                departure_dt = _canonical_datetime_from_min(base_date, int(getattr(dispatch_trip, "departure_min", 0) or 0))
                arrival_dt = _canonical_datetime_from_min(base_date, int(getattr(dispatch_trip, "arrival_min", 0) or 0))
                rows.append(
                    {
                        "scenario_id": scenario_id,
                        "trip_id": trip_id,
                        "route_id": str(getattr(dispatch_trip, "route_id", problem_trip.route_id) or problem_trip.route_id),
                        "route_family_code": route_family_code,
                        "route_series_code": route_family_code or str(getattr(dispatch_trip, "route_id", problem_trip.route_id) or problem_trip.route_id),
                        "band_id": route_family_code or str(getattr(dispatch_trip, "route_id", problem_trip.route_id) or problem_trip.route_id),
                        "direction": str(getattr(dispatch_trip, "direction", "") or ""),
                        "route_variant_type": str(getattr(dispatch_trip, "route_variant_type", "unknown") or "unknown"),
                        "scheduled_departure": departure_dt.isoformat(),
                        "scheduled_arrival": arrival_dt.isoformat(),
                        "actual_departure": departure_dt.isoformat(),
                        "actual_arrival": arrival_dt.isoformat(),
                        "assigned_vehicle_id": vehicle_id,
                        "vehicle_sequence": sequence,
                        "assigned_vehicle_type": str(getattr(vehicle, "vehicle_type", "") or ""),
                        "assigned_depot_id": str(getattr(vehicle, "home_depot_id", "") or ""),
                        "assigned_vehicle_band_id": str((primary_band_by_vehicle.get(vehicle_id) or {}).get("band_id") or ""),
                        "served_flag": True,
                        "unserved_reason": "",
                        "energy_used_kwh": float(getattr(problem_trip, "energy_kwh", 0.0) or 0.0),
                        "distance_km": float(getattr(problem_trip, "distance_km", 0.0) or 0.0),
                        "delay_departure_min": 0.0,
                        "delay_arrival_min": 0.0,
                        "deadhead_before_km": _canonical_deadhead_distance_km(problem, int(getattr(leg, "deadhead_from_prev_min", 0) or 0)),
                        "deadhead_after_km": _canonical_deadhead_distance_km(problem, next_deadhead_min),
                        "swap_type": "none",
                    }
                )
    rows.sort(key=lambda row: (str(row.get("assigned_vehicle_id") or ""), int(row.get("vehicle_sequence", 0) or 0), str(row.get("scheduled_departure") or ""), str(row.get("trip_id") or "")))
    return rows


def _canonical_soc_event_rows(
    *,
    problem,
    engine_result,
    scenario_id: str,
    base_date: date,
) -> List[Dict[str, Any]]:
    problem_trip_by_id = problem.trip_by_id()
    vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
    charge_slots_by_vehicle: Dict[str, List[Any]] = defaultdict(list)
    for slot in engine_result.plan.charging_slots:
        charge_slots_by_vehicle[str(slot.vehicle_id)].append(slot)

    rows: List[Dict[str, Any]] = []
    duties_by_vehicle = engine_result.plan.duties_by_vehicle()
    for vehicle_id, duties in duties_by_vehicle.items():
        vehicle = vehicle_by_id.get(vehicle_id)
        if vehicle is None or str(getattr(vehicle, "vehicle_type", "") or "").upper() not in {"BEV", "PHEV", "FCEV"}:
            continue
        battery_kwh = max(float(getattr(vehicle, "battery_capacity_kwh", 0.0) or 0.0), 0.0)
        min_soc = max(float(getattr(vehicle, "reserve_soc", 0.0) or 0.0), 0.0)
        max_soc = battery_kwh if battery_kwh > 0.0 else 0.0
        current_soc = _canonical_vehicle_initial_soc_kwh(vehicle)
        events: List[tuple[int, int, Dict[str, Any]]] = []
        for duty in duties:
            prev_trip = None
            for leg in duty.legs:
                dispatch_trip = leg.trip
                trip_id = str(dispatch_trip.trip_id or "")
                problem_trip = problem_trip_by_id.get(trip_id)
                if problem_trip is None:
                    continue
                deadhead_min = max(int(getattr(leg, "deadhead_from_prev_min", 0) or 0), 0)
                if deadhead_min > 0:
                    events.append(
                        (
                            int(dispatch_trip.departure_min) - deadhead_min,
                            0,
                            {
                                "event_type": "deadhead",
                                "trip_id": "",
                                "route_id": "",
                                "location_id": str(getattr(prev_trip, "destination", "") or getattr(vehicle, "home_depot_id", "") or ""),
                                "delta_kwh": -_canonical_estimated_deadhead_energy_kwh(
                                    problem,
                                    deadhead_min=deadhead_min,
                                    trip_energy_kwh=float(getattr(problem_trip, "energy_kwh", 0.0) or 0.0),
                                    trip_distance_km=float(getattr(problem_trip, "distance_km", 0.0) or 0.0),
                                ),
                            },
                        )
                    )
                events.append(
                    (
                        int(dispatch_trip.departure_min),
                        1,
                        {
                            "event_type": "service_trip",
                            "trip_id": trip_id,
                            "route_id": str(getattr(dispatch_trip, "route_id", problem_trip.route_id) or problem_trip.route_id),
                            "location_id": str(getattr(dispatch_trip, "origin_stop_id", "") or dispatch_trip.origin or ""),
                            "delta_kwh": -max(float(getattr(problem_trip, "energy_kwh", 0.0) or 0.0), 0.0),
                        },
                    )
                )
                prev_trip = dispatch_trip
        for start_slot, end_slot, _charger_id, avg_charge_kw, avg_discharge_kw, location_id in _canonical_charge_segments(
            problem,
            charge_slots_by_vehicle.get(vehicle_id, []),
            fallback_location_id=str(getattr(vehicle, "home_depot_id", "") or ""),
        ):
            duration_h = max(end_slot - start_slot, 0) * max(int(getattr(problem.scenario, "timestep_min", 0) or 0), 1) / 60.0
            events.append(
                (
                    _canonical_horizon_start_min(problem) + start_slot * max(int(getattr(problem.scenario, "timestep_min", 0) or 0), 1),
                    2,
                    {
                        "event_type": "charge_segment",
                        "trip_id": "",
                        "route_id": "",
                        "location_id": location_id,
                        "delta_kwh": (avg_charge_kw - avg_discharge_kw) * duration_h,
                    },
                )
            )
        events.sort(key=lambda item: (item[0], item[1]))
        for minute_from_midnight, _order, payload in events:
            before = current_soc
            delta_kwh = float(payload.get("delta_kwh", 0.0) or 0.0)
            after = current_soc + delta_kwh
            current_soc = after
            rows.append(
                {
                    "scenario_id": scenario_id,
                    "vehicle_id": vehicle_id,
                    "event_time": _canonical_datetime_from_min(base_date, minute_from_midnight).isoformat(),
                    "event_type": str(payload.get("event_type") or ""),
                    "trip_id": str(payload.get("trip_id") or ""),
                    "route_id": str(payload.get("route_id") or ""),
                    "location_id": str(payload.get("location_id") or ""),
                    "soc_kwh_before": before,
                    "soc_kwh_after": after,
                    "soc_pct_before": (before / battery_kwh * 100.0) if battery_kwh > 0.0 else 0.0,
                    "soc_pct_after": (after / battery_kwh * 100.0) if battery_kwh > 0.0 else 0.0,
                    "delta_kwh": delta_kwh,
                    "battery_capacity_kwh": battery_kwh,
                    "energy_consumed_kwh": max(-delta_kwh, 0.0),
                    "energy_charged_kwh": max(delta_kwh, 0.0),
                    "reserve_margin_kwh": after - min_soc,
                    "min_soc_constraint_kwh": min_soc,
                    "max_soc_constraint_kwh": max_soc,
                }
            )
    rows.sort(key=lambda row: (str(row.get("vehicle_id", "")), str(row.get("event_time", ""))))
    return rows


def _canonical_depot_power_rows_5min(
    *,
    problem,
    engine_result,
    scenario_id: str,
    base_date: date,
    operator_id: str = "UNKNOWN_OPERATOR",
) -> List[Dict[str, Any]]:
    plan = engine_result.plan
    flow_ctx = _canonical_energy_flow_context(problem, plan)
    slot_count = max(
        len(problem.price_slots),
        max((int(getattr(slot, "slot_index", 0) or 0) + 1 for slot in plan.charging_slots), default=0),
        max(
            (
                int(slot_idx) + 1
                for key in (
                    "grid_to_bus_kwh_by_depot_slot",
                    "pv_to_bus_kwh_by_depot_slot",
                    "bess_to_bus_kwh_by_depot_slot",
                    "pv_to_bess_kwh_by_depot_slot",
                    "grid_to_bess_kwh_by_depot_slot",
                    "pv_curtail_kwh_by_depot_slot",
                    "bess_soc_kwh_by_depot_slot",
                    "bess_soc_start_kwh_by_depot_slot",
                    "bess_soc_end_kwh_by_depot_slot",
                    "contract_over_limit_kwh_by_depot_slot",
                )
                for slot_map in dict(flow_ctx.get(key) or {}).values()
                for slot_idx in dict(slot_map or {}).keys()
            ),
            default=0,
        ),
    )
    if slot_count <= 0:
        return []
    timestep_min = max(int(getattr(problem.scenario, "timestep_min", 0) or 0), 1)
    timestep_h = timestep_min / 60.0
    output_slot_min = float(timestep_min)
    output_slot_h = output_slot_min / 60.0
    slot_scale = output_slot_min / float(timestep_min)

    slot_values_by_depot: Dict[str, Dict[int, Dict[str, float]]] = defaultdict(dict)
    for depot_id in list(flow_ctx["depot_ids"]):
        for slot_idx in range(slot_count):
            grid_to_bus = float((flow_ctx["grid_to_bus_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            pv_to_bus = float((flow_ctx["pv_to_bus_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            bess_to_bus = float((flow_ctx["bess_to_bus_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            pv_to_bess = float((flow_ctx["pv_to_bess_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            grid_to_bess = float((flow_ctx["grid_to_bess_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            raw_pv_curtail = float((flow_ctx["pv_curtail_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            pv_generation = float((flow_ctx["pv_generation_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            pv_curtail = compute_pv_curtail_kwh(pv_generation, pv_to_bus, pv_to_bess) if pv_generation > 0.0 else max(raw_pv_curtail, 0.0)
            bess_soc_kwh = float((flow_ctx["bess_soc_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            bess_soc_start_kwh = float((flow_ctx["bess_soc_start_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, bess_soc_kwh) or 0.0)
            bess_soc_end_kwh = float((flow_ctx["bess_soc_end_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, bess_soc_kwh) or 0.0)
            contract_over_limit_kwh = float((flow_ctx["contract_over_limit_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            contract_limit_kw = float((flow_ctx["depot_limit_kw"].get(depot_id, 0.0)) or 0.0)
            grid_import_for_contract_kwh = grid_to_bus + grid_to_bess
            if contract_limit_kw > 0.0:
                contract_over_limit_kwh = max(
                    contract_over_limit_kwh,
                    grid_import_for_contract_kwh - (contract_limit_kw * timestep_h),
                    0.0,
                )
            slot_values_by_depot[depot_id][slot_idx] = {
                "grid_import_kw": grid_import_for_contract_kwh / timestep_h,
                "grid_import_for_contract_kwh": grid_import_for_contract_kwh,
                "grid_import_for_contract_kw": grid_import_for_contract_kwh / timestep_h,
                "pv_generation_kw": pv_generation / timestep_h,
                "pv_used_for_charging_kw": pv_to_bus / timestep_h,
                "pv_used_for_building_kw": 0.0,
                "pv_curtailed_kw": pv_curtail / timestep_h,
                "building_load_kw": 0.0,
                "battery_storage_charge_kw": (pv_to_bess + grid_to_bess) / timestep_h,
                "battery_storage_discharge_kw": bess_to_bus / timestep_h,
                "total_charge_kw": (grid_to_bus + pv_to_bus + bess_to_bus) / timestep_h,
                "net_load_kw": (grid_to_bus + grid_to_bess) / timestep_h,
                "grid_to_bus_kwh": grid_to_bus,
                "pv_to_bus_kwh": pv_to_bus,
                "bess_to_bus_kwh": bess_to_bus,
                "pv_to_bess_kwh": pv_to_bess,
                "grid_to_bess_kwh": grid_to_bess,
                "bus_charge_from_grid_kwh": grid_to_bus,
                "bus_charge_from_bess_kwh": bess_to_bus,
                "bess_soc_kwh": bess_soc_kwh,
                "bess_soc_start_kwh": bess_soc_start_kwh,
                "bess_soc_end_kwh": bess_soc_end_kwh,
                "contract_limit_kw": contract_limit_kw,
                "contract_over_limit_kwh": contract_over_limit_kwh,
                "contract_over_limit_kw": contract_over_limit_kwh / timestep_h if timestep_h > 0.0 else 0.0,
            }

    rows: List[Dict[str, Any]] = []
    for depot_id, slot_map in slot_values_by_depot.items():
        peak_grid = max((values.get("grid_import_kw", 0.0) for values in slot_map.values()), default=0.0)
        cumulative_grid_kwh = 0.0
        cumulative_grid_cost = 0.0
        for slot_idx in range(slot_count):
            minute = slot_idx * timestep_min
            slot_idx = min(int(minute // timestep_min), max(slot_count - 1, 0))
            values = slot_map.get(slot_idx, {})
            grid_import_kw = float(values.get("grid_import_kw", 0.0) or 0.0)
            pv_generation_kw = float(values.get("pv_generation_kw", 0.0) or 0.0)
            pv_curtailed_kw = float(values.get("pv_curtailed_kw", 0.0) or 0.0)
            grid_to_bus_hourly_source_kwh = float(values.get("grid_to_bus_kwh", 0.0) or 0.0)
            pv_to_bus_hourly_source_kwh = float(values.get("pv_to_bus_kwh", 0.0) or 0.0)
            bess_to_bus_hourly_source_kwh = float(values.get("bess_to_bus_kwh", 0.0) or 0.0)
            pv_to_bess_hourly_source_kwh = float(values.get("pv_to_bess_kwh", 0.0) or 0.0)
            grid_to_bess_hourly_source_kwh = float(values.get("grid_to_bess_kwh", 0.0) or 0.0)
            grid_import_for_contract_hourly_source_kwh = float(values.get("grid_import_for_contract_kwh", 0.0) or 0.0)
            bus_charge_from_grid_hourly_source_kwh = float(values.get("bus_charge_from_grid_kwh", 0.0) or 0.0)
            bus_charge_from_bess_hourly_source_kwh = float(values.get("bus_charge_from_bess_kwh", 0.0) or 0.0)
            contract_over_limit_hourly_source_kwh = float(values.get("contract_over_limit_kwh", 0.0) or 0.0)
            bess_soc_kwh = float(values.get("bess_soc_kwh", 0.0) or 0.0)
            bess_soc_start_kwh = float(values.get("bess_soc_start_kwh", bess_soc_kwh) or 0.0)
            bess_soc_end_kwh = float(values.get("bess_soc_end_kwh", bess_soc_kwh) or 0.0)
            grid_to_bus_slot_kwh = grid_to_bus_hourly_source_kwh * slot_scale
            pv_to_bus_slot_kwh = pv_to_bus_hourly_source_kwh * slot_scale
            bess_to_bus_slot_kwh = bess_to_bus_hourly_source_kwh * slot_scale
            pv_to_bess_slot_kwh = pv_to_bess_hourly_source_kwh * slot_scale
            grid_to_bess_slot_kwh = grid_to_bess_hourly_source_kwh * slot_scale
            grid_import_for_contract_slot_kwh = grid_import_for_contract_hourly_source_kwh * slot_scale
            bus_charge_from_grid_slot_kwh = bus_charge_from_grid_hourly_source_kwh * slot_scale
            bus_charge_from_bess_slot_kwh = bus_charge_from_bess_hourly_source_kwh * slot_scale
            contract_over_limit_slot_kwh = contract_over_limit_hourly_source_kwh * slot_scale
            grid_import_kwh = grid_to_bus_slot_kwh + grid_to_bess_slot_kwh
            pv_generation_kwh = pv_generation_kw * output_slot_h
            pv_curtail_kwh = pv_curtailed_kw * output_slot_h
            bus_charge_total_kwh = grid_to_bus_slot_kwh + pv_to_bus_slot_kwh + bess_to_bus_slot_kwh
            price = float(flow_ctx["price_by_slot"].get(slot_idx, 0.0) or 0.0)
            grid_purchase_cost = grid_import_kwh * price
            cumulative_grid_kwh += grid_import_kwh
            cumulative_grid_cost += grid_purchase_cost
            power_balance_error = grid_import_kwh - grid_to_bus_slot_kwh - grid_to_bess_slot_kwh
            pv_balance_error = pv_generation_kwh - pv_to_bus_slot_kwh - pv_to_bess_slot_kwh - pv_curtail_kwh
            timestamp = (
                datetime.combine(base_date, datetime.min.time(), timezone(timedelta(hours=9)))
                + timedelta(minutes=_canonical_horizon_start_min(problem) + minute)
            ).isoformat()
            rows.append(
                {
                    "scenario_id": scenario_id,
                    "run_id": str(getattr(engine_result, "run_id", "") or ""),
                    "operator_id": str(operator_id or "UNKNOWN_OPERATOR"),
                    "timestamp": timestamp,
                    "depot_id": depot_id,
                    "slot_index": slot_idx,
                    "slot_minutes": output_slot_min,
                    "total_charge_kw": float(values.get("total_charge_kw", 0.0) or 0.0),
                    "grid_import_kw": grid_import_kw,
                    "grid_import_kwh": grid_import_kwh,
                    "grid_import_cumulative_kwh": cumulative_grid_kwh,
                    "grid_import_for_contract_kw": float(values.get("grid_import_for_contract_kw", grid_import_kw) or 0.0),
                    "grid_import_slot_kwh": grid_import_kw * output_slot_h,
                    "grid_import_for_contract_slot_kwh": grid_import_for_contract_slot_kwh,
                    "grid_import_hourly_source_kwh": grid_to_bus_hourly_source_kwh + grid_to_bess_hourly_source_kwh,
                    "grid_import_for_contract_hourly_source_kwh": grid_import_for_contract_hourly_source_kwh,
                    "bus_charge_from_grid_kwh": bus_charge_from_grid_slot_kwh,
                    "bus_charge_from_grid_slot_kwh": bus_charge_from_grid_slot_kwh,
                    "bus_charge_from_grid_hourly_source_kwh": bus_charge_from_grid_hourly_source_kwh,
                    "bus_charge_from_bess_kwh": bus_charge_from_bess_slot_kwh,
                    "bus_charge_from_bess_slot_kwh": bus_charge_from_bess_slot_kwh,
                    "bus_charge_from_bess_hourly_source_kwh": bus_charge_from_bess_hourly_source_kwh,
                    "grid_to_bus_kwh": grid_to_bus_slot_kwh,
                    "grid_to_bus_slot_kwh": grid_to_bus_slot_kwh,
                    "grid_to_bus_hourly_source_kwh": grid_to_bus_hourly_source_kwh,
                    "pv_to_bus_kwh": pv_to_bus_slot_kwh,
                    "pv_to_bus_slot_kwh": pv_to_bus_slot_kwh,
                    "pv_to_bus_hourly_source_kwh": pv_to_bus_hourly_source_kwh,
                    "bess_to_bus_kwh": bess_to_bus_slot_kwh,
                    "bess_to_bus_slot_kwh": bess_to_bus_slot_kwh,
                    "bess_to_bus_hourly_source_kwh": bess_to_bus_hourly_source_kwh,
                    "pv_to_bess_kwh": pv_to_bess_slot_kwh,
                    "pv_to_bess_slot_kwh": pv_to_bess_slot_kwh,
                    "pv_to_bess_hourly_source_kwh": pv_to_bess_hourly_source_kwh,
                    "grid_to_bess_kwh": grid_to_bess_slot_kwh,
                    "grid_import_total_kwh": grid_import_kwh,
                    "grid_to_bess_slot_kwh": grid_to_bess_slot_kwh,
                    "grid_to_bess_hourly_source_kwh": grid_to_bess_hourly_source_kwh,
                    "bess_soc_kwh": bess_soc_end_kwh,
                    "bess_soc_start_kwh": bess_soc_start_kwh,
                    "bess_soc_end_kwh": bess_soc_end_kwh,
                    "pv_generation_kw": pv_generation_kw,
                    "pv_generation_kwh": pv_generation_kwh,
                    "pv_generation_slot_kwh": pv_generation_kw * output_slot_h,
                    "pv_used_for_charging_kw": float(values.get("pv_used_for_charging_kw", 0.0) or 0.0),
                    "pv_used_for_building_kw": float(values.get("pv_used_for_building_kw", 0.0) or 0.0),
                    "pv_curtailed_kw": pv_curtailed_kw,
                    "pv_curtail_kwh": pv_curtail_kwh,
                    "pv_curtailed_slot_kwh": pv_curtailed_kw * output_slot_h,
                    "building_load_kw": float(values.get("building_load_kw", 0.0) or 0.0),
                    "battery_storage_charge_kw": float(values.get("battery_storage_charge_kw", 0.0) or 0.0),
                    "battery_storage_discharge_kw": float(values.get("battery_storage_discharge_kw", 0.0) or 0.0),
                    "net_load_kw": float(values.get("net_load_kw", 0.0) or 0.0),
                    "contract_limit_kw": float(values.get("contract_limit_kw", 0.0) or 0.0),
                    "contract_over_limit_kwh": contract_over_limit_slot_kwh,
                    "contract_over_limit_slot_kwh": contract_over_limit_slot_kwh,
                    "contract_over_limit_hourly_source_kwh": contract_over_limit_hourly_source_kwh,
                    "contract_over_limit_kw": float(values.get("contract_over_limit_kw", 0.0) or 0.0),
                    "contract_limit_exceeded": float(values.get("contract_over_limit_kwh", 0.0) or 0.0) > 1.0e-9,
                    "demand_peak_candidate": abs(float(values.get("grid_import_kw", 0.0) or 0.0) - peak_grid) <= 1.0e-9,
                    "bus_charge_total_kwh": bus_charge_total_kwh,
                    "energy_price_yen_per_kwh": price,
                    "grid_purchase_cost_jpy": grid_purchase_cost,
                    "grid_purchase_cumulative_cost_jpy": cumulative_grid_cost,
                    "power_balance_error_kwh": power_balance_error,
                    "pv_balance_error_kwh": pv_balance_error,
                    "demand_charge_window_flag": bool(flow_ctx["demand_flag_by_slot"].get(slot_idx, False)),
                    "source_provenance_exact": bool(flow_ctx["source_provenance_exact"]),
                }
            )
    rows.sort(key=lambda row: (str(row.get("depot_id", "")), str(row.get("timestamp", ""))))
    return rows


def _research_timestamp_parts(timestamp: Any) -> tuple[str, str]:
    try:
        parsed = datetime.fromisoformat(str(timestamp))
        return parsed.date().isoformat(), parsed.strftime("%H:%M")
    except ValueError:
        text = str(timestamp or "")
        return text[:10], text[11:16]


def _research_rows_from_depot_power(
    depot_power_rows: List[Dict[str, Any]],
    *,
    base_date: date,
) -> Dict[str, List[Dict[str, Any]]]:
    rows_by_depot_time: Dict[tuple[str, str], Dict[str, Any]] = {}
    depot_ids = sorted({str(row.get("depot_id") or "") for row in depot_power_rows if str(row.get("depot_id") or "")})
    slot_minutes = int(float(depot_power_rows[0].get("slot_minutes", 30) or 30)) if depot_power_rows else 30
    for row in depot_power_rows:
        _out_date, out_time = _research_timestamp_parts(row.get("timestamp"))
        depot_id = str(row.get("depot_id") or "")
        if depot_id:
            rows_by_depot_time[(depot_id, out_time)] = row
    initial_bess_soc_by_depot: Dict[str, float] = {}
    for row in depot_power_rows:
        depot_id = str(row.get("depot_id") or "")
        if depot_id and depot_id not in initial_bess_soc_by_depot:
            initial_bess_soc_by_depot[depot_id] = float(
                row.get("bess_soc_start_kwh", row.get("bess_soc_end_kwh", row.get("bess_soc_kwh", 0.0))) or 0.0
            )
    grid_rows: List[Dict[str, Any]] = []
    pv_rows: List[Dict[str, Any]] = []
    flow_rows: List[Dict[str, Any]] = []
    charge_rows: List[Dict[str, Any]] = []
    for depot_id in depot_ids:
        bess_soc_carry = float(initial_bess_soc_by_depot.get(depot_id, 0.0) or 0.0)
        for minute in range(0, 24 * 60, slot_minutes):
            out_time = f"{minute // 60:02d}:{minute % 60:02d}"
            row = rows_by_depot_time.get((depot_id, out_time), {})
            if row:
                bess_soc_start_kwh = float(row.get("bess_soc_start_kwh", row.get("bess_soc_kwh", bess_soc_carry)) or 0.0)
                bess_soc_end_kwh = float(row.get("bess_soc_end_kwh", row.get("bess_soc_kwh", bess_soc_start_kwh)) or 0.0)
            else:
                bess_soc_start_kwh = bess_soc_carry
                bess_soc_end_kwh = bess_soc_carry
            bess_soc_kwh = bess_soc_end_kwh
            bess_soc_carry = bess_soc_end_kwh
            out_date = base_date.isoformat()
            energy_price = float(
                row.get(
                    "energy_price_yen_per_kwh",
                    row.get("grid_energy_price_yen_per_kwh", 0.0),
                )
                or 0.0
            )
            base = {
                "date": out_date,
                "time": out_time,
                "depot_id": depot_id,
            }
            grid_import_kw = float(row.get("grid_import_kw", 0.0) or 0.0)
            grid_import_for_contract_kw = float(row.get("grid_import_for_contract_kw", grid_import_kw) or 0.0)
            contract_limit_kw = float(row.get("contract_limit_kw", 0.0) or 0.0)
            grid_rows.append(
                {
                    **base,
                    "grid_import_kw": grid_import_kw,
                    "grid_import_for_contract_kw": grid_import_for_contract_kw,
                    "grid_import_slot_kwh": float(row.get("grid_import_slot_kwh", 0.0) or 0.0),
                    "grid_import_for_contract_slot_kwh": float(row.get("grid_import_for_contract_slot_kwh", row.get("grid_import_slot_kwh", 0.0)) or 0.0),
                    "contract_limit_kw": contract_limit_kw,
                    "contract_over_limit_slot_kwh": float(row.get("contract_over_limit_slot_kwh", 0.0) or 0.0),
                }
            )
            pv_rows.append(
                {
                    **base,
                    "pv_generation_kw": float(row.get("pv_generation_kw", 0.0) or 0.0),
                    "pv_generation_slot_kwh": float(row.get("pv_generation_slot_kwh", 0.0) or 0.0),
                    "pv_curtailed_slot_kwh": float(row.get("pv_curtailed_slot_kwh", 0.0) or 0.0),
                }
            )
            flow_rows.append(
                {
                    **base,
                    "pv_generation_kwh": float(row.get("pv_generation_slot_kwh", row.get("pv_generation_kwh", 0.0)) or 0.0),
                    "pv_generation_slot_kwh": float(row.get("pv_generation_slot_kwh", row.get("pv_generation_kwh", 0.0)) or 0.0),
                    "pv_curtailed_kwh": float(row.get("pv_curtailed_slot_kwh", row.get("pv_curtail_kwh", 0.0)) or 0.0),
                    "pv_curtailed_slot_kwh": float(row.get("pv_curtailed_slot_kwh", row.get("pv_curtail_kwh", 0.0)) or 0.0),
                    "grid_to_bus_slot_kwh": float(row.get("grid_to_bus_slot_kwh", 0.0) or 0.0),
                    "pv_to_bus_slot_kwh": float(row.get("pv_to_bus_slot_kwh", 0.0) or 0.0),
                    "pv_to_bess_slot_kwh": float(row.get("pv_to_bess_slot_kwh", 0.0) or 0.0),
                    "bess_to_bus_slot_kwh": float(row.get("bess_to_bus_slot_kwh", 0.0) or 0.0),
                    "grid_to_bess_slot_kwh": float(row.get("grid_to_bess_slot_kwh", 0.0) or 0.0),
                    "grid_import_for_contract_slot_kwh": float(row.get("grid_import_for_contract_slot_kwh", row.get("grid_import_slot_kwh", 0.0)) or 0.0),
                    "bus_charge_from_grid_slot_kwh": float(row.get("bus_charge_from_grid_slot_kwh", row.get("grid_to_bus_slot_kwh", 0.0)) or 0.0),
                    "bus_charge_from_bess_slot_kwh": float(row.get("bus_charge_from_bess_slot_kwh", row.get("bess_to_bus_slot_kwh", 0.0)) or 0.0),
                    "bess_soc_kwh": bess_soc_kwh,
                    "bess_soc_start_kwh": bess_soc_start_kwh,
                    "bess_soc_end_kwh": bess_soc_end_kwh,
                    "energy_price_yen_per_kwh": energy_price,
                    "grid_purchase_cost_jpy": float(row.get("grid_purchase_cost_jpy", 0.0) or 0.0),
                    "contract_limit_kw": float(row.get("contract_limit_kw", 0.0) or 0.0),
                    "contract_over_limit_kwh": float(row.get("contract_over_limit_kwh", 0.0) or 0.0),
                    "contract_over_limit_slot_kwh": float(row.get("contract_over_limit_slot_kwh", 0.0) or 0.0),
                    "contract_over_limit_kw": float(row.get("contract_over_limit_kw", 0.0) or 0.0),
                    "contract_limit_exceeded": bool(row.get("contract_limit_exceeded", False)),
                    "demand_charge_window_flag": bool(row.get("demand_charge_window_flag", False)),
                }
            )
            total_charge_kw = float(row.get("total_charge_kw", 0.0) or 0.0)
            charge_rows.append(
                {
                    **base,
                    "total_bus_charge_kw": total_charge_kw,
                    "total_bus_charge_slot_kwh": total_charge_kw * (float(row.get("slot_minutes", slot_minutes) or slot_minutes) / 60.0),
                }
            )
    return {
        "grid_import_timeseries.csv": grid_rows,
        "pv_generation_timeseries.csv": pv_rows,
        "energy_flow_timeseries.csv": flow_rows,
        "bus_charging_total_timeseries.csv": charge_rows,
    }


def _hhmm_to_minute(value: str) -> int:
    hour, minute = str(value or "00:00").split(":", 1)
    return (int(hour) % 24) * 60 + (int(minute) % 60)


def _research_depot_time_index(
    depot_power_rows: List[Dict[str, Any]],
) -> tuple[List[str], Dict[tuple[str, str], Dict[str, Any]]]:
    rows_by_depot_time: Dict[tuple[str, str], Dict[str, Any]] = {}
    depot_ids = sorted({str(row.get("depot_id") or "") for row in depot_power_rows if str(row.get("depot_id") or "")})
    for row in depot_power_rows:
        _out_date, out_time = _research_timestamp_parts(row.get("timestamp"))
        depot_id = str(row.get("depot_id") or "")
        if depot_id:
            rows_by_depot_time[(depot_id, out_time)] = row
    return depot_ids, rows_by_depot_time


def _research_slot_index_for_time(problem, time_hhmm: str) -> int:
    timestep_min = max(int(getattr(problem.scenario, "timestep_min", 0) or 0), 1)
    minute = _hhmm_to_minute(time_hhmm)
    horizon_start = _canonical_horizon_start_min(problem)
    if minute < horizon_start:
        minute += 24 * 60
    return max((minute - horizon_start) // timestep_min, 0)


def _research_vehicle_maps(problem) -> tuple[Dict[str, Any], Dict[str, Any]]:
    vehicle_by_id = {str(getattr(vehicle, "vehicle_id", "") or ""): vehicle for vehicle in list(getattr(problem, "vehicles", ()) or ())}
    vehicle_type_by_id = {
        str(getattr(vehicle_type, "vehicle_type_id", "") or ""): vehicle_type
        for vehicle_type in list(getattr(problem, "vehicle_types", ()) or ())
    }
    return vehicle_by_id, vehicle_type_by_id


def _research_vehicle_fuel_rate_l_per_km(vehicle: Any, vehicle_type: Any) -> float:
    for source in (vehicle, vehicle_type):
        value = getattr(source, "fuel_consumption_l_per_km", None) if source is not None else None
        if value is not None:
            parsed = max(float(value or 0.0), 0.0)
            if parsed > 0.0:
                return parsed
    return 0.0


def _research_vehicle_co2_kg_per_l(problem, vehicle_type: Any) -> float:
    value = getattr(vehicle_type, "co2_emission_kg_per_l", None) if vehicle_type is not None else None
    parsed = max(float(value or 0.0), 0.0) if value is not None else 0.0
    return parsed if parsed > 0.0 else max(float(getattr(problem.scenario, "ice_co2_kg_per_l", 0.0) or 0.0), 0.0)


def _research_is_electric_vehicle(vehicle: Any, vehicle_type: Any) -> bool:
    powertrain = str(getattr(vehicle_type, "powertrain_type", "") or getattr(vehicle, "vehicle_type", "") or "").upper()
    return powertrain in {"BEV", "PHEV", "FCEV"}


def _research_spread_event_to_5min(
    bucket: Dict[tuple[str, str], Dict[str, float]],
    *,
    base_date: date,
    depot_id: str,
    start_time: Any,
    end_time: Any,
    values: Dict[str, float],
    slot_minutes: int = 30,
) -> None:
    try:
        start = datetime.fromisoformat(str(start_time))
        end = datetime.fromisoformat(str(end_time))
    except ValueError:
        return
    if end <= start:
        return
    base_midnight = datetime.combine(base_date, datetime.min.time(), tzinfo=start.tzinfo)
    start_min = (start - base_midnight).total_seconds() / 60.0
    end_min = (end - base_midnight).total_seconds() / 60.0
    duration = max(end_min - start_min, 1.0e-9)
    bucket_start = int(start_min // slot_minutes) * slot_minutes
    while bucket_start < end_min:
        bucket_end = bucket_start + slot_minutes
        overlap = max(min(bucket_end, end_min) - max(bucket_start, start_min), 0.0)
        if overlap > 0.0:
            out_minute = int(bucket_start % (24 * 60))
            out_time = f"{out_minute // 60:02d}:{out_minute % 60:02d}"
            target = bucket.setdefault((str(depot_id), out_time), defaultdict(float))
            for key, value in values.items():
                target[key] += float(value or 0.0) * overlap / duration
        bucket_start += slot_minutes


def _research_fuel_time_bucket(
    *,
    problem,
    timeline_rows: List[Dict[str, Any]],
    refuel_rows: List[Dict[str, Any]],
    base_date: date,
    slot_minutes: int,
) -> Dict[tuple[str, str], Dict[str, float]]:
    vehicle_by_id, vehicle_type_by_id = _research_vehicle_maps(problem)
    bucket: Dict[tuple[str, str], Dict[str, float]] = {}
    for row in timeline_rows:
        vehicle_id = str(row.get("vehicle_id") or "")
        vehicle = vehicle_by_id.get(vehicle_id)
        vehicle_type = vehicle_type_by_id.get(str(getattr(vehicle, "vehicle_type", "") or row.get("vehicle_type") or ""))
        if vehicle is None or _research_is_electric_vehicle(vehicle, vehicle_type):
            continue
        fuel_rate = _research_vehicle_fuel_rate_l_per_km(vehicle, vehicle_type)
        if fuel_rate <= 0.0:
            continue
        distance_km = max(float(row.get("distance_km", 0.0) or 0.0), 0.0)
        fuel_l = distance_km * fuel_rate
        if fuel_l <= 0.0:
            continue
        co2 = fuel_l * _research_vehicle_co2_kg_per_l(problem, vehicle_type)
        state = str(row.get("state") or "")
        trip_fuel = fuel_l if state == "service" or bool(row.get("is_service")) else 0.0
        deadhead_fuel = fuel_l if state == "deadhead" or bool(row.get("is_deadhead")) else 0.0
        _research_spread_event_to_5min(
            bucket,
            base_date=base_date,
            depot_id=str(row.get("depot_id") or getattr(vehicle, "home_depot_id", "") or "depot_default"),
            start_time=row.get("start_time"),
            end_time=row.get("end_time"),
            values={
                "trip_fuel_liters": trip_fuel,
                "deadhead_fuel_liters": deadhead_fuel,
                "fuel_liters": fuel_l,
                "ice_bus_co2_kg": co2,
            },
            slot_minutes=slot_minutes,
        )
    vehicle_home = _canonical_vehicle_home_depot_map(problem)
    for row in refuel_rows:
        liters = max(float(row.get("refuel_liters", 0.0) or 0.0), 0.0)
        if liters <= 0.0:
            continue
        vehicle_id = str(row.get("vehicle_id") or "")
        depot_id = str(row.get("location_id") or vehicle_home.get(vehicle_id) or "depot_default")
        time_hhmm = str(row.get("time_hhmm") or "00:00")[:5]
        target = bucket.setdefault((depot_id, time_hhmm), defaultdict(float))
        target["refuel_liters"] += liters
    return bucket


def _research_extended_timeseries_exports(
    *,
    problem,
    engine_result,
    depot_power_rows: List[Dict[str, Any]],
    timeline_rows: List[Dict[str, Any]],
    refuel_rows: List[Dict[str, Any]],
    base_date: date,
) -> Dict[str, List[Dict[str, Any]]]:
    depot_ids, rows_by_depot_time = _research_depot_time_index(depot_power_rows)
    depot_ids = sorted(set(depot_ids) | {str(getattr(depot, "depot_id", "") or "") for depot in list(getattr(problem, "depots", ()) or ()) if str(getattr(depot, "depot_id", "") or "")})
    if not depot_ids:
        depot_ids = ["depot_default"]
    price_by_slot = {
        int(getattr(slot, "slot_index", 0) or 0): float(getattr(slot, "grid_buy_yen_per_kwh", 0.0) or 0.0)
        for slot in list(getattr(problem, "price_slots", ()) or ())
    }
    co2_by_slot = {
        int(getattr(slot, "slot_index", 0) or 0): float(getattr(slot, "co2_factor", 0.0) or 0.0)
        for slot in list(getattr(problem, "price_slots", ()) or ())
    }
    demand_flag_by_slot = {
        int(getattr(slot, "slot_index", 0) or 0): bool(float(getattr(slot, "demand_charge_weight", 0.0) or 0.0) > 0.0)
        for slot in list(getattr(problem, "price_slots", ()) or ())
    }
    assets = dict(getattr(problem, "depot_energy_assets", {}) or {})
    breakdown = dict(getattr(engine_result, "cost_breakdown", {}) or {})
    plan_metadata = dict(getattr(engine_result.plan, "metadata", {}) or {})
    solver_metadata = dict(getattr(engine_result, "solver_metadata", {}) or {})
    timestep_min = max(int(getattr(problem.scenario, "timestep_min", 0) or 0), 1)
    pv_unit = max(float(breakdown.get("pv_marginal_charge_cost_yen_per_kwh", getattr(problem, "metadata", {}).get("pv_marginal_charge_cost_yen_per_kwh", 0.0)) or 0.0), 0.0)
    contract_penalty = max(float(plan_metadata.get("contract_overage_penalty_yen_per_kwh", solver_metadata.get("contract_overage_penalty_yen_per_kwh", getattr(problem, "metadata", {}).get("contract_overage_penalty_yen_per_kwh", 0.0))) or 0.0), 0.0)
    fuel_bucket = _research_fuel_time_bucket(
        problem=problem,
        timeline_rows=timeline_rows,
        refuel_rows=refuel_rows,
        base_date=base_date,
        slot_minutes=timestep_min,
    )
    flow_ctx = _canonical_energy_flow_context(problem, engine_result.plan)
    depot_source_exact = bool(flow_ctx.get("source_provenance_exact", False))
    vehicle_source_exact = bool(
        depot_source_exact
        and dict(getattr(engine_result.plan, "metadata", {}) or {}).get("vehicle_source_provenance_exact", False)
    )

    co2_rows: List[Dict[str, Any]] = []
    cost_rows: List[Dict[str, Any]] = []
    contract_rows: List[Dict[str, Any]] = []
    bess_rows: List[Dict[str, Any]] = []
    fuel_rows: List[Dict[str, Any]] = []
    for depot_id in depot_ids:
        asset = assets.get(depot_id)
        bess_capacity = max(float(getattr(asset, "bess_energy_kwh", 0.0) or 0.0), 0.0) if asset is not None else 0.0
        bess_bounds = _bess_soc_bounds_for_asset(asset) if asset is not None else None
        if bess_bounds is not None:
            bess_min, bess_max, bess_initial_soc = bess_bounds
        else:
            bess_min = 0.0
            bess_max = bess_capacity
            bess_initial_soc = max(float(getattr(asset, "bess_initial_soc_kwh", 0.0) or 0.0), 0.0) if asset is not None else 0.0
        bess_terminal_min = min(max(float(getattr(asset, "bess_terminal_soc_min_kwh", 0.0) or 0.0), bess_min), bess_max) if asset is not None else 0.0
        resolved_terminal_target = (
            _resolved_bess_terminal_target_kwh(asset) if asset is not None else None
        )
        has_terminal_target = resolved_terminal_target is not None
        bess_terminal_target = float(resolved_terminal_target or 0.0)
        bess_cycle_unit = max(float(getattr(asset, "bess_cycle_cost_yen_per_kwh", 0.0) or 0.0), 0.0) if asset is not None else 0.0
        carried_bess_soc = bess_initial_soc
        for minute in range(0, 24 * 60, timestep_min):
            time_hhmm = f"{minute // 60:02d}:{minute % 60:02d}"
            base = {"date": base_date.isoformat(), "time": time_hhmm, "depot_id": depot_id}
            row = rows_by_depot_time.get((depot_id, time_hhmm), {})
            slot_idx = _research_slot_index_for_time(problem, time_hhmm)
            price = float(row.get("energy_price_yen_per_kwh", price_by_slot.get(slot_idx, 0.0)) or 0.0)
            co2_factor = float(co2_by_slot.get(slot_idx, 0.0) or 0.0)
            grid_contract_kwh = float(row.get("grid_import_for_contract_slot_kwh", row.get("grid_import_slot_kwh", 0.0)) or 0.0)
            grid_to_bus_kwh = float(row.get("grid_to_bus_slot_kwh", row.get("grid_to_bus_kwh", 0.0)) or 0.0)
            grid_to_bess_kwh = float(row.get("grid_to_bess_slot_kwh", row.get("grid_to_bess_kwh", 0.0)) or 0.0)
            pv_to_bus_kwh = float(row.get("pv_to_bus_slot_kwh", row.get("pv_to_bus_kwh", 0.0)) or 0.0)
            pv_to_bess_kwh = float(row.get("pv_to_bess_slot_kwh", row.get("pv_to_bess_kwh", 0.0)) or 0.0)
            bess_to_bus_kwh = float(row.get("bess_to_bus_slot_kwh", row.get("bess_to_bus_kwh", 0.0)) or 0.0)
            contract_limit_kw = float(row.get("contract_limit_kw", 0.0) or 0.0)
            grid_contract_kw = float(row.get("grid_import_for_contract_kw", row.get("grid_import_kw", 0.0)) or 0.0)
            contract_over_kwh = float(row.get("contract_over_limit_slot_kwh", row.get("contract_over_limit_kwh", 0.0)) or 0.0)
            contract_over_cost = contract_over_kwh * contract_penalty
            pv_used_kwh = pv_to_bus_kwh + pv_to_bess_kwh
            pv_generation_kwh = float(row.get("pv_generation_slot_kwh", 0.0) or 0.0)
            pv_curtail_kwh = float(row.get("pv_curtailed_slot_kwh", 0.0) or 0.0)
            grid_co2 = grid_contract_kwh * co2_factor
            fuel_values = fuel_bucket.get((depot_id, time_hhmm), {})
            ice_co2 = float(fuel_values.get("ice_bus_co2_kg", 0.0) or 0.0)
            co2_rows.append(
                {
                    **base,
                    "grid_import_for_contract_kwh": grid_contract_kwh,
                    "grid_co2_factor_kg_per_kwh": co2_factor,
                    "grid_electricity_co2_kg": grid_co2,
                    "ice_bus_co2_kg": ice_co2,
                    "pv_operational_co2_kg": 0.0,
                    "bess_storage_operational_co2_kg": 0.0,
                    "total_co2_kg": grid_co2 + ice_co2,
                    "source_provenance_exact": depot_source_exact,
                }
            )
            cost_rows.append(
                {
                    **base,
                    "grid_energy_price_yen_per_kwh": price,
                    "grid_purchase_cost_jpy": (grid_to_bus_kwh + grid_to_bess_kwh) * price,
                    "bess_discharge_cost_jpy": bess_to_bus_kwh * bess_cycle_unit,
                    "pv_self_consumption_cost_jpy": pv_used_kwh * pv_unit,
                    "contract_overage_cost_jpy": contract_over_cost,
                    "electricity_energy_cost_jpy": ((grid_to_bus_kwh + grid_to_bess_kwh) * price) + (bess_to_bus_kwh * bess_cycle_unit) + (pv_used_kwh * pv_unit),
                    "demand_charge_window_flag": bool(row.get("demand_charge_window_flag", demand_flag_by_slot.get(slot_idx, False))),
                    "demand_peak_candidate": bool(row.get("demand_peak_candidate", False)),
                    "demand_charge_is_peak_based_not_time_additive": True,
                    "source_provenance_exact": depot_source_exact,
                }
            )
            contract_rows.append(
                {
                    **base,
                    "grid_import_for_contract_kw": grid_contract_kw,
                    "grid_import_for_contract_kwh": grid_contract_kwh,
                    "contract_limit_kw": contract_limit_kw,
                    "contract_margin_kw": contract_limit_kw - grid_contract_kw if contract_limit_kw > 0.0 else 0.0,
                    "contract_over_limit_kw": float(row.get("contract_over_limit_kw", 0.0) or 0.0),
                    "contract_over_limit_kwh": contract_over_kwh,
                    "contract_limit_exceeded": bool(row.get("contract_limit_exceeded", contract_over_kwh > 1.0e-9)),
                    "contract_overage_cost_jpy": contract_over_cost,
                    "bess_to_bus_excluded_from_contract_kwh": bess_to_bus_kwh,
                    "source_provenance_exact": depot_source_exact,
                }
            )
            if row:
                bess_soc_start = float(row.get("bess_soc_start_kwh", row.get("bess_soc_kwh", carried_bess_soc)) or 0.0)
                bess_soc_end = float(row.get("bess_soc_end_kwh", row.get("bess_soc_kwh", bess_soc_start)) or 0.0)
            else:
                bess_soc_start = carried_bess_soc
                bess_soc_end = carried_bess_soc
            if bess_bounds is not None:
                bess_soc_start = min(max(bess_soc_start, bess_min), bess_max)
                bess_soc_end = min(max(bess_soc_end, bess_min), bess_max)
            bess_soc = bess_soc_end
            carried_bess_soc = bess_soc_end
            bess_charge_kwh = pv_to_bess_kwh + grid_to_bess_kwh
            bess_rows.append(
                {
                    **base,
                    "bess_charge_kwh": bess_charge_kwh,
                    "bess_charge_kw": bess_charge_kwh / (timestep_min / 60.0),
                    "bess_discharge_kwh": bess_to_bus_kwh,
                    "bess_discharge_kw": bess_to_bus_kwh / (timestep_min / 60.0),
                    "bess_net_charge_kwh": bess_charge_kwh - bess_to_bus_kwh,
                    "pv_to_bess_kwh": pv_to_bess_kwh,
                    "grid_to_bess_kwh": grid_to_bess_kwh,
                    "bess_to_bus_kwh": bess_to_bus_kwh,
                    "bess_soc_kwh": bess_soc,
                    "bess_soc_start_kwh": bess_soc_start,
                    "bess_soc_end_kwh": bess_soc_end,
                    "bess_soc_percent": (bess_soc / bess_capacity * 100.0) if bess_capacity > 0.0 else 0.0,
                    "bess_soc_min_kwh": bess_min,
                    "bess_soc_max_kwh": bess_max,
                    "bess_terminal_soc_min_kwh": bess_terminal_min,
                    "bess_terminal_soc_target_kwh": bess_terminal_target,
                    "bess_terminal_soc_deviation_kwh": abs(bess_soc - bess_terminal_target) if has_terminal_target and minute >= 24 * 60 - timestep_min else 0.0,
                    "bess_terminal_soc_delta_kwh": bess_soc - bess_initial_soc if minute >= 24 * 60 - timestep_min else 0.0,
                    "bess_terminal_soc_violation_kwh": max(bess_terminal_min - bess_soc, 0.0) if minute >= 24 * 60 - timestep_min else 0.0,
                    "bess_cycle_cost_jpy": bess_to_bus_kwh * bess_cycle_unit,
                    "source_provenance_exact": depot_source_exact,
                }
            )
            fuel_rows.append(
                {
                    **base,
                    "trip_fuel_liters": float(fuel_values.get("trip_fuel_liters", 0.0) or 0.0),
                    "deadhead_fuel_liters": float(fuel_values.get("deadhead_fuel_liters", 0.0) or 0.0),
                    "fuel_liters": float(fuel_values.get("fuel_liters", 0.0) or 0.0),
                    "refuel_liters": float(fuel_values.get("refuel_liters", 0.0) or 0.0),
                    "net_fuel_inventory_delta_liters": float(fuel_values.get("refuel_liters", 0.0) or 0.0) - float(fuel_values.get("fuel_liters", 0.0) or 0.0),
                    "ice_bus_co2_kg": ice_co2,
                }
            )
    return {
        "co2_timeseries.csv": co2_rows,
        "cost_timeseries.csv": cost_rows,
        "contract_limit_timeseries.csv": contract_rows,
        "bess_timeseries.csv": bess_rows,
        "fuel_timeseries.csv": fuel_rows,
    }


def _research_vehicle_charging_source_timeseries_rows(
    *,
    problem,
    engine_result,
    base_date: date,
    operator_id: str = "UNKNOWN_OPERATOR",
) -> List[Dict[str, Any]]:
    timestep_min = max(int(getattr(problem.scenario, "timestep_min", 0) or 0), 1)
    timestep_h = timestep_min / 60.0
    horizon_start = _canonical_horizon_start_min(problem)
    vehicle_by_id, _vehicle_type_by_id = _research_vehicle_maps(problem)
    active_vehicle_ids = sorted({str(getattr(slot, "vehicle_id", "") or "") for slot in list(getattr(engine_result.plan, "charging_slots", ()) or ()) if str(getattr(slot, "vehicle_id", "") or "")})
    if not active_vehicle_ids:
        return []
    flow_ctx = _canonical_energy_flow_context(problem, engine_result.plan)
    depot_source_exact = bool(flow_ctx.get("source_provenance_exact", False))
    vehicle_source_exact = bool(
        depot_source_exact
        and dict(getattr(engine_result.plan, "metadata", {}) or {}).get("vehicle_source_provenance_exact", False)
    )
    allocation_method = "solver_native" if vehicle_source_exact else "proportional_by_timestep"
    values: Dict[tuple[str, str], Dict[str, Any]] = {}
    charge_rows_by_depot_slot: Dict[tuple[str, int], List[Dict[str, Any]]] = defaultdict(list)
    for slot in list(getattr(engine_result.plan, "charging_slots", ()) or ()):
        vehicle_id = str(getattr(slot, "vehicle_id", "") or "")
        if not vehicle_id:
            continue
        source, depot_id = _canonical_charging_source_and_depot(problem, slot)
        charge_kw = max(float(getattr(slot, "charge_kw", 0.0) or 0.0), 0.0)
        discharge_kw = max(float(getattr(slot, "discharge_kw", 0.0) or 0.0), 0.0)
        net_kw = max(charge_kw - discharge_kw, 0.0)
        if net_kw <= 0.0:
            continue
        slot_idx = int(getattr(slot, "slot_index", 0) or 0)
        start_minute = horizon_start + int(getattr(slot, "slot_index", 0) or 0) * timestep_min
        out_minute = start_minute % (24 * 60)
        out_time = f"{out_minute // 60:02d}:{out_minute % 60:02d}"
        charge_kwh = net_kw * timestep_h
        if vehicle_source_exact:
            target = values.setdefault((vehicle_id, out_time), defaultdict(float))
            target[f"{source}_to_vehicle_kwh"] += charge_kwh
            target["total_charge_kwh"] += charge_kwh
            target["charge_kw"] += net_kw
            target[f"{source}_charge_kw"] += net_kw
            target["_depot_id"] = depot_id
            target["_charger_id"] = str(getattr(slot, "charger_id", "") or "")
        else:
            charge_rows_by_depot_slot[(depot_id, slot_idx)].append(
                {
                    "vehicle_id": vehicle_id,
                    "time": out_time,
                    "depot_id": depot_id,
                    "charger_id": str(getattr(slot, "charger_id", "") or ""),
                    "source": source,
                    "charge_kwh": charge_kwh,
                    "charge_kw": net_kw,
                }
            )

    if not vehicle_source_exact:
        for (depot_id, slot_idx), slot_rows in sorted(charge_rows_by_depot_slot.items(), key=lambda item: (item[0][0], item[0][1])):
            total_charge_kwh = sum(float(row.get("charge_kwh", 0.0) or 0.0) for row in slot_rows)
            if total_charge_kwh <= 0.0:
                continue
            grid_total = float((flow_ctx["grid_to_bus_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            pv_total = float((flow_ctx["pv_to_bus_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            bess_total = float((flow_ctx["bess_to_bus_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            if grid_total + pv_total + bess_total <= 1.0e-9:
                source = str(slot_rows[0].get("source") or "grid") if slot_rows else "grid"
                if source == "pv":
                    pv_total = total_charge_kwh
                elif source == "bess":
                    bess_total = total_charge_kwh
                else:
                    grid_total = total_charge_kwh
            remaining_grid = grid_total
            remaining_pv = pv_total
            remaining_bess = bess_total
            ordered = sorted(slot_rows, key=lambda row: (str(row.get("vehicle_id") or ""), str(row.get("charger_id") or "")))
            for index, row in enumerate(ordered):
                charge_kwh = float(row.get("charge_kwh", 0.0) or 0.0)
                share = charge_kwh / total_charge_kwh if total_charge_kwh > 0.0 else 0.0
                is_last = index == len(ordered) - 1
                if is_last:
                    grid_kwh = remaining_grid
                    pv_kwh = remaining_pv
                    bess_kwh = remaining_bess
                else:
                    grid_kwh = grid_total * share
                    pv_kwh = pv_total * share
                    bess_kwh = bess_total * share
                    remaining_grid -= grid_kwh
                    remaining_pv -= pv_kwh
                    remaining_bess -= bess_kwh
                vehicle_id = str(row.get("vehicle_id") or "")
                out_time = str(row.get("time") or "00:00")
                target = values.setdefault((vehicle_id, out_time), defaultdict(float))
                target["grid_to_vehicle_kwh"] += grid_kwh
                target["pv_to_vehicle_kwh"] += pv_kwh
                target["bess_to_vehicle_kwh"] += bess_kwh
                target["total_charge_kwh"] += grid_kwh + pv_kwh + bess_kwh
                target["charge_kw"] += float(row.get("charge_kw", 0.0) or 0.0)
                target["grid_charge_kw"] += grid_kwh / timestep_h if timestep_h > 0.0 else 0.0
                target["pv_charge_kw"] += pv_kwh / timestep_h if timestep_h > 0.0 else 0.0
                target["bess_charge_kw"] += bess_kwh / timestep_h if timestep_h > 0.0 else 0.0
                target["_depot_id"] = depot_id
                target["_charger_id"] = str(row.get("charger_id") or "")
    rows: List[Dict[str, Any]] = []
    for vehicle_id in active_vehicle_ids:
        vehicle = vehicle_by_id.get(vehicle_id)
        fallback_depot = str(getattr(vehicle, "home_depot_id", "") or "") if vehicle is not None else ""
        for minute in range(0, 24 * 60, timestep_min):
            time_hhmm = f"{minute // 60:02d}:{minute % 60:02d}"
            item = values.get((vehicle_id, time_hhmm), {})
            depot_id = str(item.get("_depot_id") or fallback_depot)
            grid_kwh = float(item.get("grid_to_vehicle_kwh", 0.0) or 0.0)
            pv_kwh = float(item.get("pv_to_vehicle_kwh", 0.0) or 0.0)
            bess_kwh = float(item.get("bess_to_vehicle_kwh", 0.0) or 0.0)
            rows.append(
                {
                    "date": base_date.isoformat(),
                    "time": time_hhmm,
                    "timestamp": datetime.combine(base_date, datetime.min.time()).replace(hour=minute // 60, minute=minute % 60).isoformat(),
                    "slot_minutes": timestep_min,
                    "vehicle_id": vehicle_id,
                    "operator_id": operator_id,
                    "depot_id": depot_id,
                    "route_id": "",
                    "charger_id": str(item.get("_charger_id") or ""),
                    "grid_to_vehicle_kwh": grid_kwh,
                    "pv_to_vehicle_kwh": pv_kwh,
                    "bess_to_vehicle_kwh": bess_kwh,
                    "total_charge_kwh": grid_kwh + pv_kwh + bess_kwh,
                    "charge_kw": float(item.get("charge_kw", 0.0) or 0.0),
                    "grid_charge_kw": float(item.get("grid_charge_kw", 0.0) or 0.0),
                    "pv_charge_kw": float(item.get("pv_charge_kw", 0.0) or 0.0),
                    "bess_charge_kw": float(item.get("bess_charge_kw", 0.0) or 0.0),
                    "source_provenance_exact": vehicle_source_exact,
                    "depot_source_provenance_exact": depot_source_exact,
                    "vehicle_charging_source_allocation_method": allocation_method,
                    "vehicle_charging_source_is_solver_native": vehicle_source_exact,
                    "vehicle_source_split_note": (
                        "Vehicle source split is an exact MILP vehicle/source/slot decision trace."
                        if vehicle_source_exact
                        else "Vehicle source split is post-allocated by depot/timestep site source ratios because per-vehicle source decision variables are not present."
                    ),
                }
            )
    return rows


def _research_vehicle_soc_timeseries_rows(
    *,
    problem,
    engine_result,
    base_date: date,
    timeline_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    soc_by_vehicle = _normalize_depot_slot_mapping(
        getattr(engine_result.plan, "vehicle_soc_kwh_by_vehicle_slot", {})
    )
    if not soc_by_vehicle:
        return []
    vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
    timeline_by_vehicle: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in timeline_rows:
        timeline_by_vehicle[str(item.get("vehicle_id") or "")].append(item)

    timestep_min = max(int(getattr(problem.scenario, "timestep_min", 0) or 0), 1)
    points = list(range(0, 24 * 60, timestep_min))
    rows: List[Dict[str, Any]] = []
    for vehicle_id, slot_map in sorted(soc_by_vehicle.items()):
        vehicle = vehicle_by_id.get(vehicle_id)
        capacity = max(float(getattr(vehicle, "battery_capacity_kwh", 0.0) or 0.0), 0.0) if vehicle is not None else 0.0
        depot_id = str(getattr(vehicle, "home_depot_id", "") or "") if vehicle is not None else ""
        max_slot = max(slot_map.keys(), default=0)
        for minute in points:
            slot_idx = min(int(minute // timestep_min), max_slot)
            soc_kwh = float(slot_map.get(slot_idx, 0.0) or 0.0)
            timestamp = datetime.combine(base_date, datetime.min.time()) + timedelta(minutes=minute)
            state = "idle"
            for event in timeline_by_vehicle.get(vehicle_id, []):
                try:
                    start = datetime.fromisoformat(str(event.get("start_time")))
                    end = datetime.fromisoformat(str(event.get("end_time")))
                except ValueError:
                    continue
                if start <= timestamp < end:
                    state = str(event.get("state") or "idle")
                    break
            rows.append(
                {
                    "date": base_date.isoformat(),
                    "time": timestamp.strftime("%H:%M"),
                    "vehicle_id": vehicle_id,
                    "soc_kwh": soc_kwh,
                    "soc_percent": (soc_kwh / capacity * 100.0) if capacity > 0.0 else 0.0,
                    "state": state,
                    "depot_id": depot_id,
                }
            )
    return rows


def _research_fuel_summary_rows(
    *,
    problem,
    timeline_rows: List[Dict[str, Any]],
    refuel_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    vehicle_by_id = {str(vehicle.vehicle_id): vehicle for vehicle in problem.vehicles}
    refuel_by_vehicle: Dict[str, float] = defaultdict(float)
    for row in refuel_rows:
        refuel_by_vehicle[str(row.get("vehicle_id") or "")] += float(row.get("refuel_liters", 0.0) or 0.0)

    accum: Dict[str, Dict[str, float]] = defaultdict(lambda: {"trip_fuel_liters": 0.0, "deadhead_fuel_liters": 0.0})
    for row in timeline_rows:
        vehicle_id = str(row.get("vehicle_id") or "")
        vehicle = vehicle_by_id.get(vehicle_id)
        if vehicle is None or str(getattr(vehicle, "vehicle_type", "") or "").upper() in {"BEV", "PHEV", "FCEV"}:
            continue
        fuel_rate = max(float(getattr(vehicle, "fuel_consumption_l_per_km", 0.0) or 0.0), 0.0)
        if fuel_rate <= 0.0:
            continue
        liters = max(float(row.get("distance_km", 0.0) or 0.0), 0.0) * fuel_rate
        if bool(row.get("is_service")):
            accum[vehicle_id]["trip_fuel_liters"] += liters
        elif bool(row.get("is_deadhead")):
            accum[vehicle_id]["deadhead_fuel_liters"] += liters

    rows: List[Dict[str, Any]] = []
    totals = {"trip_fuel_liters": 0.0, "deadhead_fuel_liters": 0.0, "refuel_liters": 0.0}
    for vehicle_id in sorted(set(accum.keys()) | set(refuel_by_vehicle.keys())):
        vehicle = vehicle_by_id.get(vehicle_id)
        vehicle_type = str(getattr(vehicle, "vehicle_type", "UNKNOWN") or "UNKNOWN") if vehicle is not None else "UNKNOWN"
        trip_l = float(accum.get(vehicle_id, {}).get("trip_fuel_liters", 0.0) or 0.0)
        deadhead_l = float(accum.get(vehicle_id, {}).get("deadhead_fuel_liters", 0.0) or 0.0)
        refuel_l = float(refuel_by_vehicle.get(vehicle_id, 0.0) or 0.0)
        fuel_l = trip_l + deadhead_l
        rows.append(
            {
                "vehicle_id": vehicle_id,
                "vehicle_type": vehicle_type,
                "fuel_liters": fuel_l,
                "trip_fuel_liters": trip_l,
                "deadhead_fuel_liters": deadhead_l,
                "refuel_liters": refuel_l,
                "unit": "L",
            }
        )
        totals["trip_fuel_liters"] += trip_l
        totals["deadhead_fuel_liters"] += deadhead_l
        totals["refuel_liters"] += refuel_l
    if rows:
        rows.append(
            {
                "vehicle_id": "TOTAL",
                "vehicle_type": "ALL_ICE",
                "fuel_liters": totals["trip_fuel_liters"] + totals["deadhead_fuel_liters"],
                "trip_fuel_liters": totals["trip_fuel_liters"],
                "deadhead_fuel_liters": totals["deadhead_fuel_liters"],
                "refuel_liters": totals["refuel_liters"],
                "unit": "L",
            }
        )
    return rows


def _canonical_vehicle_timelines_payload(timeline_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in timeline_rows:
        grouped[str(row.get("vehicle_id") or "")].append(row)
    for vehicle_id in list(grouped):
        grouped[vehicle_id] = sorted(
            grouped[vehicle_id],
            key=lambda item: (str(item.get("start_time") or ""), str(item.get("state") or "")),
        )
    return {
        "timeline_schema_version": "canonical_v1",
        "vehicle_timelines": dict(grouped),
        "vehicle_gantt_rows": list(timeline_rows),
    }


def _canonical_kpi_summary_json(
    *,
    problem,
    engine_result,
    scenario_id: str,
    soc_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    plan = engine_result.plan
    served_trip_count = len(plan.served_trip_ids)
    total_trip_count = len(problem.trips)
    served_distance = 0.0
    served_energy = 0.0
    deadhead_distance = 0.0
    for duty in plan.duties:
        for leg in duty.legs:
            trip_info = problem.trip_by_id().get(str(leg.trip.trip_id))
            if trip_info is None:
                continue
            served_distance += float(getattr(trip_info, "distance_km", 0.0) or 0.0)
            served_energy += float(getattr(trip_info, "energy_kwh", 0.0) or 0.0)
            deadhead_distance += _canonical_deadhead_distance_km(problem, int(getattr(leg, "deadhead_from_prev_min", 0) or 0))
    total_charge_energy = sum(
        max(float(getattr(slot, "charge_kw", 0.0) or 0.0) - float(getattr(slot, "discharge_kw", 0.0) or 0.0), 0.0)
        * max(int(getattr(problem.scenario, "timestep_min", 0) or 0), 1)
        / 60.0
        for slot in plan.charging_slots
    )
    grid_import_total_kwh = sum(
        float(value or 0.0)
        for depot_map in (plan.grid_to_bus_kwh_by_depot_slot or {}).values()
        for value in (depot_map or {}).values()
    ) + sum(
        float(value or 0.0)
        for depot_map in (plan.grid_to_bess_kwh_by_depot_slot or {}).values()
        for value in (depot_map or {}).values()
    )
    timestep_h = max(int(getattr(problem.scenario, "timestep_min", 0) or 0), 1) / 60.0
    peak_grid_import_kw = 0.0
    for depot_id, depot_map in (plan.grid_to_bus_kwh_by_depot_slot or {}).items():
        bess_map = (plan.grid_to_bess_kwh_by_depot_slot or {}).get(depot_id, {})
        for slot_idx, value in (depot_map or {}).items():
            peak_grid_import_kw = max(
                peak_grid_import_kw,
                (float(value or 0.0) + float((bess_map or {}).get(slot_idx, 0.0) or 0.0)) / timestep_h,
            )
    soc_pct_values = [float(row.get("soc_pct_after", 0.0) or 0.0) for row in soc_rows]
    charger_usage: Dict[str, set[int]] = defaultdict(set)
    for slot in plan.charging_slots:
        charger_id = str(getattr(slot, "charger_id", "") or "")
        if charger_id:
            charger_usage[charger_id].add(int(getattr(slot, "slot_index", 0) or 0))
    slot_count = max(len(problem.price_slots), 1)
    utilization_values = [len(slot_indices) / slot_count for slot_indices in charger_usage.values()]
    pv_generated_total_kwh = sum(
        float(value or 0.0)
        for asset in (problem.depot_energy_assets or {}).values()
        for value in getattr(asset, "pv_generation_kwh_by_slot", ())
    )
    pv_self_consumption_kwh = sum(
        float(value or 0.0)
        for depot_map in (plan.pv_to_bus_kwh_by_depot_slot or {}).values()
        for value in (depot_map or {}).values()
    ) + sum(
        float(value or 0.0)
        for depot_map in (plan.pv_to_bess_kwh_by_depot_slot or {}).values()
        for value in (depot_map or {}).values()
    )
    breakdown = dict(engine_result.cost_breakdown or {})
    return {
        "scenario_id": scenario_id,
        "fleet_size": len(problem.vehicles),
        "served_trip_count": served_trip_count,
        "unserved_trip_count": len(plan.unserved_trip_ids),
        "served_trip_rate": float(served_trip_count / total_trip_count) if total_trip_count > 0 else 0.0,
        "total_distance_km": served_distance,
        "total_deadhead_km": deadhead_distance,
        "deadhead_ratio": float(deadhead_distance / served_distance) if served_distance > 0 else 0.0,
        "total_energy_consumption_kwh": served_energy,
        "total_charging_energy_kwh": total_charge_energy,
        "peak_grid_import_kw": peak_grid_import_kw,
        "peak_charge_kw": max((float(getattr(slot, "charge_kw", 0.0) or 0.0) for slot in plan.charging_slots), default=0.0),
        "pv_generation_total_kwh": pv_generated_total_kwh,
        "pv_self_consumption_kwh": pv_self_consumption_kwh,
        "pv_utilization_ratio": float(pv_self_consumption_kwh / pv_generated_total_kwh) if pv_generated_total_kwh > 0 else 0.0,
        "min_soc_pct": min(soc_pct_values) if soc_pct_values else 0.0,
        "average_soc_pct": (sum(soc_pct_values) / len(soc_pct_values)) if soc_pct_values else 0.0,
        "charger_utilization_avg": (sum(utilization_values) / len(utilization_values)) if utilization_values else 0.0,
        "charger_utilization_max": max(utilization_values) if utilization_values else 0.0,
        "total_cost_jpy": float(
            breakdown.get("total_cost")
            if breakdown.get("total_cost") is not None
            else engine_result.objective_value
            or 0.0
        ),
        "accounting_total_cost_jpy": float(
            breakdown.get("total_cost")
            if breakdown.get("total_cost") is not None
            else 0.0
        ),
        "objective_value_jpy": float(engine_result.objective_value or 0.0),
        "solver_objective_value": float(engine_result.objective_value or 0.0),
        "validated_operating_cost_jpy": (
            float(breakdown.get("total_cost") or 0.0)
            if bool(engine_result.feasible)
            and str(engine_result.solver_status or "").upper()
            in {"OPTIMAL", "FEASIBLE", "SOLVED_FEASIBLE", "PHASE2_ASSIGNMENT_FEASIBLE"}
            and (
                not bool((engine_result.solver_metadata or {}).get("research_run", False))
                or bool(
                    (engine_result.solver_metadata or {}).get(
                        "research_accounting_cost_eligible", False
                    )
                )
            )
            else None
        ),
        "objective_is_actual_cost": bool(breakdown.get("objective_is_actual_cost", False)),
        "supports_exact_milp": bool((engine_result.solver_metadata or {}).get("supports_exact_milp", False)),
        "electricity_cost_jpy": float(
            breakdown.get("electricity_cost", breakdown.get("electricity_cost_final", 0.0))
            or 0.0
        ),
        "fuel_cost_jpy": float(breakdown.get("fuel_cost", 0.0) or 0.0),
        "vehicle_usage_cost_jpy": float(breakdown.get("vehicle_usage_cost", breakdown.get("vehicle_usage_cost_jpy", 0.0)) or 0.0),
        "used_vehicle_day_count": int(breakdown.get("used_vehicle_day_count", 0) or 0),
        "vehicle_usage_cost_jpy_per_used_bus": float(breakdown.get("vehicle_usage_cost_jpy_per_used_bus", 0.0) or 0.0),
        "fuel_cost_final_jpy": float(breakdown.get("fuel_cost_final", breakdown.get("fuel_cost", 0.0)) or 0.0),
        "fuel_cost_final_source": str(breakdown.get("fuel_cost_final_source", "provisional_distance_based") or "provisional_distance_based"),
        "fuel_cost_provisional_jpy": float(breakdown.get("fuel_cost_provisional", breakdown.get("provisional_ice_drive_cost", 0.0)) or 0.0),
        "fuel_cost_refueled_jpy": float(breakdown.get("fuel_cost_refueled", breakdown.get("realized_ice_refuel_cost", 0.0)) or 0.0),
        "fuel_cost_provisional_leftover_jpy": float(breakdown.get("fuel_cost_provisional_leftover", breakdown.get("leftover_ice_provisional_cost", 0.0)) or 0.0),
        "pv_self_consumption_cost_jpy": float(breakdown.get("pv_self_consumption_cost_jpy", 0.0) or 0.0),
        "pv_marginal_charge_cost_yen_per_kwh": float(
            breakdown.get("pv_marginal_charge_cost_yen_per_kwh", 0.0)
            or getattr(problem, "metadata", {}).get("pv_marginal_charge_cost_yen_per_kwh", 0.0)
            or 0.0
        ),
        "propulsion_energy_cost_jpy": float(breakdown.get("energy_cost", 0.0) or 0.0),
        "electricity_cost_basis": str(
            breakdown.get("energy_cost_basis")
            or "realized_supply_plus_inventory_valuation"
        ),
        "energy_cash_purchase_cost_jpy": float(
            breakdown.get("energy_cash_purchase_cost_jpy", 0.0) or 0.0
        ),
        "energy_inventory_valuation_cost_jpy": float(
            breakdown.get("energy_inventory_valuation_cost_jpy", 0.0) or 0.0
        ),
        "ev_unreplenished_drive_energy_kwh": float(
            breakdown.get("ev_unreplenished_drive_energy_kwh", 0.0) or 0.0
        ),
        "ev_energy_inventory_balanced": bool(
            breakdown.get("ev_energy_inventory_balanced", False)
        ),
        "bev_terminal_soc_policy": str(
            (engine_result.solver_metadata or {}).get("bev_terminal_soc_policy")
            or getattr(problem, "metadata", {}).get("bev_terminal_soc_policy")
            or "minimum_only"
        ),
        "bev_terminal_soc_total_drawdown_kwh": float(
            (engine_result.solver_metadata or {}).get(
                "bev_terminal_soc_total_drawdown_kwh", 0.0
            )
            or 0.0
        ),
        "bev_terminal_soc_balance_satisfied": bool(
            (engine_result.solver_metadata or {}).get(
                "bev_terminal_soc_balance_satisfied", False
            )
        ),
        "research_accounting_cost_eligible": bool(
            (engine_result.solver_metadata or {}).get(
                "research_accounting_cost_eligible", False
            )
        ),
        "research_cost_optimality_eligible": bool(
            (engine_result.solver_metadata or {}).get(
                "research_cost_optimality_eligible", False
            )
        ),
        "electricity_cost_provisional_jpy": float(breakdown.get("provisional_ev_drive_cost", 0.0) or 0.0),
        "electricity_cost_charged_jpy": float(
            breakdown.get(
                "realized_ev_charge_cost",
                breakdown.get("electricity_cost", breakdown.get("electricity_cost_final", 0.0)),
            )
            or 0.0
        ),
        "grid_energy_provisional_kwh": float(sum(float(value or 0.0) for depot_map in (plan.grid_to_bus_kwh_by_depot_slot or {}).values() for value in (depot_map or {}).values())),
        "grid_energy_charged_kwh": grid_import_total_kwh,
        "pv_to_bus_kwh": float(breakdown.get("pv_to_bus_kwh", 0.0) or 0.0),
        "bess_to_bus_kwh": float(breakdown.get("bess_to_bus_kwh", 0.0) or 0.0),
        "pv_to_bess_kwh": float(breakdown.get("pv_to_bess_kwh", 0.0) or 0.0),
        "grid_to_bess_kwh": float(breakdown.get("grid_to_bess_kwh", 0.0) or 0.0),
        "contract_over_limit_kwh": float(breakdown.get("contract_over_limit_kwh", 0.0) or 0.0),
        "contract_overage_cost_jpy": float(breakdown.get("contract_overage_cost", 0.0) or 0.0),
        "demand_charge_cost_jpy": float(breakdown.get("demand_cost", 0.0) or 0.0),
        "co2_kg": float(breakdown.get("total_co2_kg", 0.0) or 0.0),
        "solver_runtime_sec": float((engine_result.solver_metadata or {}).get("solve_time_sec", 0.0) or 0.0),
        "solution_status": str(getattr(engine_result, "solver_status", "") or "").lower(),
    }


def _canonical_deadhead_ratio_by_band(timeline_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    accum: Dict[str, Dict[str, float]] = {}
    for row in timeline_rows:
        band_id = str(row.get("band_id") or row.get("event_route_band_id") or "").strip()
        if not band_id:
            continue
        item = accum.setdefault(
            band_id,
            {
                "service_events": 0.0,
                "deadhead_events": 0.0,
                "service_km": 0.0,
                "deadhead_km": 0.0,
                "service_min": 0.0,
                "deadhead_min": 0.0,
            },
        )
        distance_km = float(row.get("distance_km") or 0.0)
        duration_min = float(row.get("duration_min") or 0.0)
        if bool(row.get("is_service")) or str(row.get("state") or "") == "service":
            item["service_events"] += 1.0
            item["service_km"] += distance_km
            item["service_min"] += duration_min
        if bool(row.get("is_deadhead")) or str(row.get("state") or "") == "deadhead":
            item["deadhead_events"] += 1.0
            item["deadhead_km"] += distance_km
            item["deadhead_min"] += duration_min
    rows: List[Dict[str, Any]] = []
    for band_id, values in sorted(accum.items()):
        service_km = float(values.get("service_km") or 0.0)
        deadhead_km = float(values.get("deadhead_km") or 0.0)
        rows.append(
            {
                "band_id": band_id,
                "service_events": int(values.get("service_events") or 0),
                "deadhead_events": int(values.get("deadhead_events") or 0),
                "service_km": service_km,
                "deadhead_km": deadhead_km,
                "service_min": float(values.get("service_min") or 0.0),
                "deadhead_min": float(values.get("deadhead_min") or 0.0),
                "deadhead_service_km_ratio": deadhead_km / service_km if service_km > 0 else 0.0,
            }
        )
    return rows


def _persist_canonical_graph_exports(
    *,
    scenario: Dict[str, Any],
    problem,
    engine_result,
    scenario_id: str,
    output_dir: str,
) -> Dict[str, Any]:
    from bff.mappers.scenario_to_problemdata import _build_graph_export_context
    from src.result_exporter import (
        _build_route_band_diagram_assets,
        _build_vehicle_operation_diagram_assets,
        _write_csv,
        _write_route_band_diagram_assets,
        _write_vehicle_operation_diagram_assets,
        _filter_timeline_rows_for_day,
    )

    trips = [
        dict(item)
        for item in list(scenario.get("trips") or scenario.get("timetable_rows") or [])
        if isinstance(item, dict)
    ]
    tasks = [SimpleNamespace(task_id=str(trip.get("trip_id") or "")) for trip in trips]
    graph_context = _build_graph_export_context(scenario, trips, tasks)
    base_date = _canonical_output_base_date(problem, graph_context)
    operator_id = str(
        scenario.get("operator_id")
        or scenario.get("operatorId")
        or (problem.metadata or {}).get("operator_id")
        or ""
    ).strip()
    if not operator_id:
        observed_operator_ids = sorted(
            {
                str(getattr(trip, "operator_id", "") or "").strip()
                for trip in tuple(getattr(getattr(problem, "dispatch_context", None), "trips", ()) or ())
                if str(getattr(trip, "operator_id", "") or "").strip()
            }
        )
        operator_id = observed_operator_ids[0] if len(observed_operator_ids) == 1 else "UNKNOWN_OPERATOR"
    timeline_rows = _canonical_vehicle_timeline_rows(
        problem=problem,
        engine_result=engine_result,
        scenario_id=scenario_id,
        graph_context=graph_context,
    )
    for row in timeline_rows:
        row["operator_id"] = operator_id
    trip_assignment_rows = _canonical_trip_assignment_rows(
        problem=problem,
        engine_result=engine_result,
        scenario_id=scenario_id,
        base_date=base_date,
        timeline_rows=timeline_rows,
    )
    for row in trip_assignment_rows:
        row["operator_id"] = operator_id
    soc_rows = _canonical_soc_event_rows(
        problem=problem,
        engine_result=engine_result,
        scenario_id=scenario_id,
        base_date=base_date,
    )
    depot_power_rows = _canonical_depot_power_rows_5min(
        problem=problem,
        engine_result=engine_result,
        scenario_id=scenario_id,
        base_date=base_date,
        operator_id=operator_id,
    )
    cost_breakdown = _canonical_cost_breakdown_json(
        problem=problem,
        engine_result=engine_result,
        scenario_id=scenario_id,
    )
    kpi_summary = _canonical_kpi_summary_json(
        problem=problem,
        engine_result=engine_result,
        scenario_id=scenario_id,
        soc_rows=soc_rows,
    )
    source_flow_context = _canonical_energy_flow_context(problem, engine_result.plan)
    depot_source_provenance_exact = bool(
        source_flow_context.get("source_provenance_exact", False)
    )
    vehicle_source_provenance_exact = bool(
        depot_source_provenance_exact
        and dict(getattr(engine_result.plan, "metadata", {}) or {}).get(
            "vehicle_source_provenance_exact", False
        )
    )
    vehicle_source_allocation_method = (
        "solver_native"
        if vehicle_source_provenance_exact
        else "proportional_by_depot_timestep"
    )
    try:
        from src.optimization.accounting import build_accounting_artifacts
    except Exception:
        build_accounting_artifacts = None
    accounting_artifacts = None
    if build_accounting_artifacts is not None:
        vehicle_charging_source_rows = _research_vehicle_charging_source_timeseries_rows(
            problem=problem,
            engine_result=engine_result,
            base_date=base_date,
            operator_id=operator_id,
        )
        vehicle_soc_timeseries_rows = _research_vehicle_soc_timeseries_rows(
            problem=problem,
            engine_result=engine_result,
            base_date=base_date,
            timeline_rows=timeline_rows,
        )
        research_energy_exports = _research_rows_from_depot_power(
            depot_power_rows,
            base_date=base_date,
        )
        energy_flow_export_rows = list(research_energy_exports.get("energy_flow_timeseries.csv") or [])
        pv_generation_timeseries_total = sum(
            float(row.get("pv_generation_slot_kwh", row.get("pv_generation_kwh", 0.0)) or 0.0)
            for row in list(research_energy_exports.get("pv_generation_timeseries.csv") or [])
        )
        depot_energy_flows_pv_total = sum(
            float(row.get("pv_generation_slot_kwh", row.get("pv_generation_kwh", 0.0)) or 0.0)
            for row in energy_flow_export_rows
        )
        grid_co2_factor_by_slot = {
            int(getattr(slot, "slot_index", 0) or 0): float(getattr(slot, "co2_factor", 0.0) or 0.0)
            for slot in list(getattr(problem, "price_slots", ()) or ())
        }
        problem_metadata = dict(getattr(problem, "metadata", {}) or {})
        raw_initial_soc_policy = problem_metadata.get("weather_initial_soc_policy") or {}
        if isinstance(raw_initial_soc_policy, dict):
            initial_soc_policy = str(problem_metadata.get("initial_soc_policy") or raw_initial_soc_policy.get("mode") or "scenario_file")
        else:
            initial_soc_policy = str(problem_metadata.get("initial_soc_policy") or raw_initial_soc_policy or "scenario_file")
        available_vehicle_count = sum(
            1 for vehicle in list(getattr(problem, "vehicles", ()) or []) if bool(getattr(vehicle, "available", True))
        )
        demand_rate = 0.0
        peak_grid_kw = float(kpi_summary.get("peak_grid_import_kw_all_depots", 0.0) or 0.0)
        demand_cost = float(kpi_summary.get("demand_charge_cost_jpy", 0.0) or 0.0)
        if peak_grid_kw > 0.0:
            demand_rate = demand_cost / peak_grid_kw
        scenario_cost_coeffs = dict(((scenario.get("scenario_overlay") or {}).get("cost_coefficients") or {}))
        generated_at = datetime.now(timezone.utc).isoformat()
        weather_reference_date = str(
            ((scenario.get("simulation_config") or {}).get("weather_reference_date"))
            or ((scenario.get("simulation_config") or {}).get("service_date"))
            or base_date.isoformat()
        )[:10]
        accounting_artifacts = build_accounting_artifacts(
            problem=problem,
            scenario_id=scenario_id,
            run_id=str(Path(output_dir).name),
            service_date=base_date,
            weather_date=base_date,
            operator_id=operator_id,
            trip_assignment_rows=trip_assignment_rows,
            vehicle_soc_timeseries_rows=vehicle_soc_timeseries_rows,
            vehicle_charging_source_rows=vehicle_charging_source_rows,
            energy_flow_rows=energy_flow_export_rows,
            metadata={
                "scenario_id": scenario_id,
                "run_id": str(Path(output_dir).name),
                "service_date": base_date.isoformat(),
                "weather_date": base_date.isoformat(),
                "weather_reference_date": weather_reference_date,
                "weather_profile": str(((scenario.get("simulation_config") or {}).get("weather_profile") or "") or ""),
                "operation_mode": str(((scenario.get("simulation_config") or {}).get("operation_mode") or getattr(problem.scenario, "objective_mode", "")) or ""),
                "run_created_at": str((engine_result.solver_metadata or {}).get("started_at") or generated_at),
                "output_generated_at": generated_at,
                "pv_generation_timeseries_total_kwh": pv_generation_timeseries_total,
                "depot_energy_flows_pv_generation_total_kwh": depot_energy_flows_pv_total,
                "grid_co2_factor_by_slot": grid_co2_factor_by_slot,
                "initial_soc_policy": initial_soc_policy,
                "initial_soc_min_ratio": problem_metadata.get("initial_soc_min_ratio"),
                "initial_soc_max_ratio": problem_metadata.get("initial_soc_max_ratio"),
                "initial_soc_random_seed": problem_metadata.get("initial_soc_random_seed", (engine_result.solver_metadata or {}).get("random_seed", "")),
                "operator_id": operator_id,
                "slot_minutes": int(getattr(problem.scenario, "timestep_min", 30) or 30),
                "num_periods": len(getattr(problem, "price_slots", ()) or ()),
                "planning_horizon_hours": float(getattr(problem.scenario, "planning_horizon_hours", 0.0) or 0.0),
                "vehicle_usage_cost_jpy_per_used_bus": float((engine_result.cost_breakdown or {}).get("vehicle_usage_cost_jpy_per_used_bus", getattr(problem, "metadata", {}).get("vehicle_usage_cost_jpy_per_used_bus", 0.0)) or 0.0),
                "cost_component_flags": dict(getattr(problem, "metadata", {}).get("cost_component_flags", {}) or {}),
                "available_vehicle_count": available_vehicle_count,
                "objective_value": float(engine_result.objective_value or 0.0),
                "objective_is_actual_cost": bool(kpi_summary.get("objective_is_actual_cost", False)),
                "solver_objective_matches_accounting_total": bool(
                    (engine_result.solver_metadata or {}).get(
                        "solver_objective_matches_accounting_total", False
                    )
                ),
                "objective_semantics": str(
                    (engine_result.solver_metadata or {}).get("objective_semantics")
                    or "single_solver_objective"
                ),
                "supports_exact_milp": bool((engine_result.solver_metadata or {}).get("supports_exact_milp", False)),
                "fallback_applied": bool((engine_result.solver_metadata or {}).get("fallback_applied", False)),
                "charging_source_provenance_exact": bool(
                    vehicle_charging_source_rows
                    and all(bool(row.get("source_provenance_exact", False)) for row in vehicle_charging_source_rows)
                ),
                "vehicle_source_provenance_exact": vehicle_source_provenance_exact,
                "depot_source_provenance_exact": depot_source_provenance_exact,
                "vehicle_charging_source_allocation_method": str(
                    (
                        vehicle_charging_source_rows[0].get(
                            "vehicle_charging_source_allocation_method"
                        )
                        if vehicle_charging_source_rows
                        else vehicle_source_allocation_method
                    )
                    or vehicle_source_allocation_method
                ),
                "vehicle_charging_source_is_solver_native": bool(
                    vehicle_charging_source_rows
                    and all(bool(row.get("vehicle_charging_source_is_solver_native", False)) for row in vehicle_charging_source_rows)
                ),
                "fuel_price_jpy_per_liter": float(
                    scenario_cost_coeffs.get("diesel_price_per_l", scenario_cost_coeffs.get("fuel_price_yen_per_liter", 0.0)) or 0.0
                ),
                "co2_price_jpy_per_kg": float(
                    scenario_cost_coeffs.get("co2_price_per_kg", scenario_cost_coeffs.get("carbon_price_jpy_per_kg", 0.0)) or 0.0
                ),
                "battery_degradation_price_jpy_per_kwh": float(
                    scenario_cost_coeffs.get("battery_degradation_cost_coeff_yen_per_kwh", 0.0) or 0.0
                ),
                "demand_rate_jpy_per_kw": demand_rate,
                "contract_power_kw": float(
                    max(
                        (
                            float(getattr(depot, "import_limit_kw", 0.0) or 0.0)
                            for depot in list(getattr(problem, "depots", ()) or [])
                        ),
                        default=0.0,
                    )
                ),
                "contract_power_exceeded": bool(kpi_summary.get("contract_limit_exceeded", False)),
                "contract_overage_kw": float(
                    kpi_summary.get("contract_over_limit_kwh", 0.0) or 0.0
                )
                / max(float(getattr(problem.scenario, "timestep_min", 5) or 5) / 60.0, 1.0e-9),
                "contract_power_mode": str(
                    kpi_summary.get("contract_overage_policy", "report_only") or "report_only"
                ),
                "solver_status": str(engine_result.solver_status or ""),
                "phase": (engine_result.solver_metadata or {}).get("phase"),
                "research_run": bool((engine_result.solver_metadata or {}).get("research_run", False)),
                "research_run_accepted": bool((engine_result.solver_metadata or {}).get("research_run_accepted", False)),
                "full_operational_validation": bool(
                    str((engine_result.solver_metadata or {}).get("phase") or "")
                    != "phase2_assignment_only"
                    and bool(engine_result.feasible)
                ),
                "validated_feasible": bool(engine_result.feasible),
                "requested_phase": (engine_result.solver_metadata or {}).get("requested_phase"),
                "resolved_phase": (engine_result.solver_metadata or {}).get("resolved_phase"),
                "executed_phase": (engine_result.solver_metadata or {}).get("executed_phase"),
                "mip_gap_requested_ratio": float((engine_result.solver_metadata or {}).get("requested_mip_gap", (engine_result.solver_metadata or {}).get("mip_gap", 0.0)) or 0.0),
                "mip_gap_requested_percent": float((engine_result.solver_metadata or {}).get("requested_mip_gap", (engine_result.solver_metadata or {}).get("mip_gap", 0.0)) or 0.0) * 100.0,
                "mip_gap_achieved_ratio": (engine_result.solver_metadata or {}).get("achieved_mip_gap", (engine_result.solver_metadata or {}).get("final_gap")),
"mip_gap_achieved_percent": (
                    None
                    if (engine_result.solver_metadata or {}).get("achieved_mip_gap", (engine_result.solver_metadata or {}).get("final_gap")) is None
                    else float((engine_result.solver_metadata or {}).get("achieved_mip_gap", (engine_result.solver_metadata or {}).get("final_gap")) or 0.0) * 100.0
                ),
                "stage1_mip_gap": (engine_result.solver_metadata or {}).get("stage1_mip_gap"),
                "stage2_mip_gap": (engine_result.solver_metadata or {}).get("stage2_mip_gap"),
                "supports_two_stage_milp": (engine_result.solver_metadata or {}).get("supports_two_stage_milp"),
                "supports_integrated_exact_milp": (engine_result.solver_metadata or {}).get("supports_integrated_exact_milp"),
                "optimization_structure": (engine_result.solver_metadata or {}).get("optimization_structure"),
            },
        )
        kpi_summary = dict(accounting_artifacts.summary)
    refuel_rows = [
        {
            "vehicle_id": str(getattr(slot, "vehicle_id", "") or ""),
            "slot_index": int(getattr(slot, "slot_index", 0) or 0),
            "time_hhmm": _canonical_slot_datetime(problem, base_date, int(getattr(slot, "slot_index", 0) or 0)).strftime("%H:%M"),
            "refuel_liters": float(getattr(slot, "refuel_liters", 0.0) or 0.0),
            "location_id": str(getattr(slot, "location_id", "") or ""),
        }
        for slot in engine_result.plan.refuel_slots
    ]
    research_energy_exports = _research_rows_from_depot_power(
        depot_power_rows,
        base_date=base_date,
    )
    research_extended_exports = _research_extended_timeseries_exports(
        problem=problem,
        engine_result=engine_result,
        depot_power_rows=depot_power_rows,
        timeline_rows=timeline_rows,
        refuel_rows=refuel_rows,
        base_date=base_date,
    )
    vehicle_charging_source_rows = _research_vehicle_charging_source_timeseries_rows(
        problem=problem,
        engine_result=engine_result,
        base_date=base_date,
        operator_id=operator_id,
    )
    vehicle_soc_timeseries_rows = _research_vehicle_soc_timeseries_rows(
        problem=problem,
        engine_result=engine_result,
        base_date=base_date,
        timeline_rows=timeline_rows,
    )
    fuel_summary_rows = _research_fuel_summary_rows(
        problem=problem,
        timeline_rows=timeline_rows,
        refuel_rows=refuel_rows,
    )
    graph_dir = Path(output_dir) / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    if accounting_artifacts is not None:
        try:
            from src.optimization.accounting import export_accounting_outputs

            accounting_paths = export_accounting_outputs(graph_dir, accounting_artifacts)
            kpi_summary = dict(accounting_artifacts.summary)
            research_extended_exports["co2_timeseries.csv"] = [dict(row) for row in accounting_artifacts.co2_timeseries]
            research_extended_exports["fuel_timeseries.csv"] = [dict(row) for row in accounting_artifacts.fuel_timeseries]
        except Exception:
            accounting_paths = {}
    else:
        accounting_paths = {}
    _write_csv(graph_dir / "vehicle_timeline.csv", timeline_rows)
    _write_csv(graph_dir / "soc_events.csv", soc_rows)
    _write_csv(graph_dir / "depot_power_timeseries.csv", depot_power_rows)
    for filename, rows in research_energy_exports.items():
        _write_csv(graph_dir / filename, rows)
    for filename, rows in research_extended_exports.items():
        _write_csv(graph_dir / filename, rows)
    _write_csv(graph_dir / "vehicle_charging_source_timeseries.csv", vehicle_charging_source_rows)
    _write_csv(graph_dir / "vehicle_soc_timeseries.csv", vehicle_soc_timeseries_rows)
    _write_csv(graph_dir / "fuel_summary.csv", fuel_summary_rows)
    _write_csv(graph_dir / "trip_assignment.csv", trip_assignment_rows)
    _write_csv(graph_dir / "refuel_events.csv", refuel_rows)
    deadhead_ratio_rows = _canonical_deadhead_ratio_by_band(timeline_rows)
    _write_csv(graph_dir / "deadhead_ratio_by_band.csv", deadhead_ratio_rows)
    (graph_dir / "deadhead_ratio_by_band.json").write_text(
        json.dumps({"rows": deadhead_ratio_rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    accounting_summary = dict(getattr(accounting_artifacts, "summary", {}) or {})
    if accounting_summary:
        # Keep the three cost meanings explicit in every canonical graph
        # export.  Infeasible results retain diagnostic ledger totals, but the
        # validated operating cost is deliberately null.
        cost_breakdown["accounting_total_cost_jpy"] = accounting_summary.get(
            "accounting_total_cost_jpy", accounting_summary.get("total_cost_jpy")
        )
        cost_breakdown["solver_objective_value"] = accounting_summary.get(
            "solver_objective_value", accounting_summary.get("objective_value_jpy")
        )
        cost_breakdown["validated_operating_cost_jpy"] = accounting_summary.get(
            "validated_operating_cost_jpy"
        )
    kpi_summary.update(
        {
            "depot_source_provenance_exact": depot_source_provenance_exact,
            "vehicle_source_provenance_exact": vehicle_source_provenance_exact,
            "vehicle_source_allocation_method": vehicle_source_allocation_method,
            "charging_source_provenance_exact": bool(
                depot_source_provenance_exact and vehicle_source_provenance_exact
            ),
            "charging_source_provenance_scope": "site_and_vehicle",
        }
    )
    charging_source_provenance = {
        "schema_version": "charging_source_provenance_v1",
        "site_depot_timestep": {
            "exact": depot_source_provenance_exact,
            "scope": "depot_timestep",
            "note": source_flow_context.get("source_provenance_note"),
        },
        "vehicle_timestep": {
            "exact": vehicle_source_provenance_exact,
            "allocation_method": vehicle_source_allocation_method,
            "note": (
                "Vehicle source split is solver-native."
                if vehicle_source_provenance_exact
                else (
                    "Vehicle source split is inferred by proportional allocation "
                    "of exact depot/time-slot source totals."
                )
            ),
        },
    }
    (graph_dir / "charging_source_provenance.json").write_text(
        json.dumps(charging_source_provenance, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (graph_dir / "cost_breakdown.json").write_text(
        json.dumps(cost_breakdown, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (graph_dir / "kpi_summary.json").write_text(
        json.dumps(kpi_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Multi-day diagram support
    planning_days = int(problem.scenario.planning_days or 1)
    simulation_cfg = scenario.get("simulation_config") or {}
    solver_cfg = ((scenario.get("scenario_overlay") or {}).get("solver_config") or {})
    assets: Dict[str, Any] = {"entries": [], "svgs": {}}
    vehicle_operation_assets: Dict[str, Any] = {"entries": [], "svgs": {}}
    if planning_days > 1:
        all_vehicle_operation_assets: Dict[str, Any] = {"entries": [], "svgs": {}}
        all_route_band_assets: Dict[str, Any] = {"entries": [], "svgs": {}}
        timestep_min = int(problem.scenario.timestep_min or 30)
        for day_idx in range(planning_days):
            day_rows = _filter_timeline_rows_for_day(timeline_rows, day_idx, timestep_min)
            day_vehicle_operation_assets = _build_vehicle_operation_diagram_assets(
                day_rows,
                f"{scenario_id}_d{day_idx}",
            )
            day_route_band_assets = _build_route_band_diagram_assets(
                day_rows,
                f"{scenario_id}_d{day_idx}",
                graph_context=graph_context,
                trip_assignment_rows=trip_assignment_rows,
            )
            for entry in day_vehicle_operation_assets.get("entries", []):
                entry["day_index"] = day_idx
                entry["diagram_file"] = f"day_{day_idx}/{entry.get('diagram_file', '')}"
                all_vehicle_operation_assets["entries"].append(entry)
            for svg_key, svg_content in (day_vehicle_operation_assets.get("svg_payloads") or day_vehicle_operation_assets.get("svgs") or {}).items():
                all_vehicle_operation_assets["svgs"][f"day_{day_idx}/{svg_key}"] = svg_content
            for entry in day_route_band_assets.get("entries", []):
                entry["day_index"] = day_idx
                entry["diagram_file"] = f"day_{day_idx}/{entry.get('diagram_file', '')}"
                all_route_band_assets["entries"].append(entry)
            for svg_key, svg_content in (day_route_band_assets.get("svg_payloads") or day_route_band_assets.get("svgs") or {}).items():
                all_route_band_assets["svgs"][f"day_{day_idx}/{svg_key}"] = svg_content
        vehicle_operation_assets = all_vehicle_operation_assets
        assets = all_route_band_assets
    else:
        vehicle_operation_assets = _build_vehicle_operation_diagram_assets(
            timeline_rows,
            scenario_id,
        )
        assets = _build_route_band_diagram_assets(
            timeline_rows,
            scenario_id,
            graph_context=graph_context,
            trip_assignment_rows=trip_assignment_rows,
        )
    route_band_dir = graph_dir / "route_band_diagrams"
    if route_band_dir.exists():
        shutil.rmtree(route_band_dir)
    _write_route_band_diagram_assets(graph_dir, assets, planning_days=planning_days)
    _write_vehicle_operation_diagram_assets(
        graph_dir,
        vehicle_operation_assets,
        planning_days=planning_days,
    )

    graph_manifest = {
        "schema_version": "canonical_graph_v1",
        "scenario_id": scenario_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "time_resolution_minutes": int(getattr(problem.scenario, "timestep_min", 30) or 30),
        "timezone": "Asia/Tokyo",
        "source": "canonical_assignment_plan",
        "bess_soc_kwh_semantics": "slot_end",
        "files": [
            "vehicle_timeline.csv",
            "soc_events.csv",
            "depot_power_timeseries.csv",
            "grid_import_timeseries.csv",
            "pv_generation_timeseries.csv",
            "energy_flow_timeseries.csv",
            "bus_charging_total_timeseries.csv",
            "co2_timeseries.csv",
            "cost_timeseries.csv",
            "contract_limit_timeseries.csv",
            "bess_timeseries.csv",
            "charging_source_provenance.json",
            "vehicle_charging_source_timeseries.csv",
            "fuel_timeseries.csv",
            "vehicle_soc_timeseries.csv",
            "vehicle_slot_ledger.csv",
            "vehicle_slot_ledger.json",
            "vehicle_energy_ledger.csv",
            "vehicle_energy_ledger.json",
            "energy_flow_ledger.csv",
            "energy_flow_ledger.json",
            "fuel_canonical_ledger.csv",
            "initial_soc_ledger.csv",
            "initial_soc_precheck.csv",
            "data_flow_validation.csv",
            "fuel_summary.csv",
            "trip_assignment.csv",
            "refuel_events.csv",
            "deadhead_ratio_by_band.csv",
            "deadhead_ratio_by_band.json",
            "cost_breakdown.json",
            "kpi_summary.json",
        ],
        "optional_exports": {
            "route_band_diagrams": {
                "enabled": bool(assets.get("entries")),
                "grouping_key": "band_id",
                "diagram_format": "svg",
                "manifest_file": "route_band_diagrams/manifest.json",
                "diagram_count": len(list(assets.get("entries") or [])),
            },
            "vehicle_operation_diagrams": {
                "enabled": bool(vehicle_operation_assets.get("entries")),
                "grouping_key": "vehicle_id",
                "diagram_format": "svg",
                "manifest_file": (
                    "vehicle_operation_diagrams/manifest.json"
                    if vehicle_operation_assets.get("entries")
                    else ""
                ),
                "diagram_count": len(list(vehicle_operation_assets.get("entries") or [])),
            }
        },
    }
    (graph_dir / "manifest.json").write_text(
        json.dumps(graph_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest_relpath = None
    manifest_relpath = "graph/route_band_diagrams/manifest.json"
    return {
        "enabled": bool(assets.get("entries")),
        "diagram_count": len(list(assets.get("entries") or [])),
        "manifest_path": manifest_relpath,
        "vehicle_operation_diagram_manifest_path": (
            "graph/vehicle_operation_diagrams/manifest.json"
            if vehicle_operation_assets.get("entries")
            else None
        ),
        "vehicle_timeline_path": "graph/vehicle_timeline.csv",
        "graph_manifest_path": "graph/manifest.json",
        "trip_assignment_path": "graph/trip_assignment.csv",
        "deadhead_ratio_by_band_path": "graph/deadhead_ratio_by_band.csv",
        "soc_events_path": "graph/soc_events.csv",
        "depot_power_timeseries_path": "graph/depot_power_timeseries.csv",
        "grid_import_timeseries_path": "graph/grid_import_timeseries.csv",
        "pv_generation_timeseries_path": "graph/pv_generation_timeseries.csv",
        "energy_flow_timeseries_path": "graph/energy_flow_timeseries.csv",
        "bus_charging_total_timeseries_path": "graph/bus_charging_total_timeseries.csv",
        "co2_timeseries_path": "graph/co2_timeseries.csv",
        "cost_timeseries_path": "graph/cost_timeseries.csv",
        "contract_limit_timeseries_path": "graph/contract_limit_timeseries.csv",
        "bess_timeseries_path": "graph/bess_timeseries.csv",
        "charging_source_provenance_path": "graph/charging_source_provenance.json",
        "vehicle_charging_source_timeseries_path": "graph/vehicle_charging_source_timeseries.csv",
        "fuel_timeseries_path": "graph/fuel_timeseries.csv",
        "vehicle_soc_timeseries_path": "graph/vehicle_soc_timeseries.csv",
        "fuel_summary_path": "graph/fuel_summary.csv",
        "cost_breakdown_path": "graph/cost_breakdown.json",
        "kpi_summary_path": "graph/kpi_summary.json",
        "vehicle_slot_ledger_path": accounting_paths.get("vehicle_slot_ledger_csv", "graph/vehicle_slot_ledger.csv"),
        "vehicle_energy_ledger_path": accounting_paths.get("vehicle_energy_ledger_csv", "graph/vehicle_energy_ledger.csv"),
        "energy_flow_ledger_path": accounting_paths.get("energy_flow_ledger_csv", "graph/energy_flow_ledger.csv"),
        "fuel_canonical_ledger_path": accounting_paths.get("fuel_canonical_ledger_csv", "graph/fuel_canonical_ledger.csv"),
        "initial_soc_ledger_path": accounting_paths.get("initial_soc_ledger_csv", "graph/initial_soc_ledger.csv"),
        "initial_soc_precheck_path": accounting_paths.get("initial_soc_precheck_csv", "graph/initial_soc_precheck.csv"),
        "data_flow_validation_path": accounting_paths.get("data_flow_validation_csv", "graph/data_flow_validation.csv"),
        "accounting_summary": getattr(accounting_artifacts, "summary", {}),
        "reporting_finalizer": {
            "status": "deferred",
            "reason": "requires top-level rich run outputs before canonical reporting rebuild",
        },
        "refuel_events_path": "graph/refuel_events.csv",
        "planning_days": planning_days,
    }


def _solution_validity_payload(
    *,
    solver_status: Any,
    feasible: Any,
    trip_count_unserved: Any,
    infeasibility_reasons: List[Any],
    solver_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    status = str(solver_status or "").strip()
    status_upper = status.upper()
    reasons = [str(item) for item in list(infeasibility_reasons or []) if str(item).strip()]
    blocking_reasons: List[str] = []
    meta = dict(solver_metadata or {})

    is_fallback_status = (
        "FALLBACK" in status_upper
        or "BASELINE" in status_upper
        or "UNAVAILABLE" in status_upper
        or "GUARDRAIL" in status_upper
    )
    if is_fallback_status:
        blocking_reasons.append("baseline_fallback")
    if status_upper in {"REPAIRED_HEURISTIC", "POSTSOLVE_REPAIRED"}:
        blocking_reasons.append("repaired_heuristic")
    if status_upper == "DEBUG_RESULT" or meta.get("debug_mode") or meta.get("result_class") == "debug_result":
        blocking_reasons.append("debug_result")
    if meta.get("result_class") == "assignment_only_result" or meta.get("phase") == "phase2_assignment_only":
        blocking_reasons.append("assignment_only_result")
    if status_upper == "PARTIAL_BASELINE_FALLBACK":
        blocking_reasons.append("partial_baseline_fallback")
    if status_upper == "TRUTHFUL_BASELINE_GUARDRAIL":
        blocking_reasons.append("truthful_baseline_guardrail")
    if status_upper == "POSTSOLVE_REPAIRED":
        blocking_reasons.append("postsolve_repaired")
    if meta.get("postsolve_soc_repair_applied"):
        blocking_reasons.append("repaired_heuristic")
    if meta.get("postsolve_charging_recomputed"):
        blocking_reasons.append("repaired_heuristic")
    if meta.get("postsolve_modified_solution"):
        blocking_reasons.append("repaired_heuristic")
    if bool(meta.get("research_run", False)) and not bool(
        meta.get("research_run_accepted", False)
    ):
        blocking_reasons.append("research_acceptance_failed")
    if not bool(feasible):
        blocking_reasons.append("postsolve_infeasible")
    if reasons:
        blocking_reasons.append("infeasibility_reasons_present")
    try:
        unserved = int(trip_count_unserved or 0)
    except (TypeError, ValueError):
        unserved = 0
    if unserved > 0:
        blocking_reasons.append("unserved_trips_present")
    blocking_reasons = sorted(set(blocking_reasons))
    supports_exact = bool(meta.get("supports_exact_milp", False))
    fallback_applied = bool(meta.get("fallback_applied", False) or meta.get("fallback_reason"))
    result_class: str
    status_reason: str
    if not blocking_reasons and status_upper in {"SOLVED_FEASIBLE", "OPTIMAL", "FEASIBLE"}:
        if supports_exact and not fallback_applied:
            status_reason = "validated_feasible_no_cancellation" if unserved == 0 else "validated_feasible"
            result_class = "exact_or_validated"
        else:
            status_reason = "validated_feasible_non_exact"
            result_class = "validated_non_exact"
    elif "partial_baseline_fallback" in blocking_reasons:
        status_reason = "partial_baseline_fallback"
        result_class = "baseline_fallback"
    elif "truthful_baseline_guardrail" in blocking_reasons:
        status_reason = "truthful_baseline_guardrail"
        result_class = "baseline_fallback"
    elif "debug_result" in blocking_reasons:
        status_reason = "debug_result_not_research_kpi"
        result_class = "debug_result"
    elif "assignment_only_result" in blocking_reasons:
        status_reason = "assignment_only_no_charging_soc_validation"
        result_class = "assignment_only_result"
    elif "research_acceptance_failed" in blocking_reasons:
        status_reason = "research_acceptance_failed"
        result_class = "research_invalid"
    elif "repaired_heuristic" in blocking_reasons or "postsolve_repaired" in blocking_reasons:
        status_reason = "repaired_heuristic"
        result_class = "repaired_heuristic"
    elif "baseline_fallback" in blocking_reasons:
        status_reason = "baseline_fallback_or_postsolve_infeasible"
        result_class = "baseline_fallback"
    elif "postsolve_infeasible" in blocking_reasons:
        status_reason = "postsolve_infeasible"
        result_class = "postsolve_infeasible"
    elif "unserved_trips_present" in blocking_reasons:
        status_reason = "unserved_trips_present"
        result_class = "postsolve_infeasible"
    else:
        status_reason = "infeasibility_reasons_present"
        result_class = "postsolve_infeasible"
    validated_feasible = not blocking_reasons and status_upper in {"SOLVED_FEASIBLE", "OPTIMAL", "FEASIBLE"}
    validated_no_cancellation = bool(validated_feasible and unserved == 0)
    research_assignment_eligible = bool(
        str(meta.get("phase") or "") == "phase2_assignment_only"
        and bool(meta.get("research_run", False))
        and bool(meta.get("research_run_accepted", False))
        and bool(meta.get("research_feasibility_eligible", False))
    )
    return {
        "validated_no_cancellation": validated_no_cancellation,
        "validated_feasible": bool(validated_feasible),
        "status_reason": status_reason,
        "result_class": result_class,
        "blocking_reasons": blocking_reasons,
        "research_kpi_eligible": bool(
            validated_feasible
            and result_class == "exact_or_validated"
            and bool(meta.get("research_run", False))
            and bool(meta.get("research_run_accepted", False))
            and bool(meta.get("research_cost_kpi_eligible", False))
        ),
        "research_feasibility_eligible": bool(
            validated_feasible
            and bool(meta.get("research_run", False))
            and bool(meta.get("research_run_accepted", False))
            and bool(meta.get("research_feasibility_eligible", False))
        ),
        # Phase 2 validates vehicle-trip assignment only.  Keep it distinct
        # from full operational/SOC feasibility so callers cannot infer that
        # charging feasibility was evaluated.
        "research_assignment_eligible": research_assignment_eligible,
        "research_cost_kpi_eligible": bool(
            meta.get("research_cost_kpi_eligible", False)
        ),
        "validation_metrics": dict(meta.get("validation_metrics") or {}),
        "research_acceptance_checks": dict(meta.get("research_acceptance_checks") or {}),
    }


_INVALID_RESULT_METRIC_KEYS = {
    "total_cost",
    "total_cost_jpy",
    "objective_value",
    "objective_value_jpy",
    "accounting_total_cost_jpy",
    "gross_operating_cost_jpy",
    "reported_total_cost_jpy",
    "solver_objective_value",
    "validated_operating_cost_jpy",
    "energy_cost",
    "energy_cost_jpy",
    "electricity_cost",
    "electricity_cost_jpy",
    "electricity_cost_final",
    "demand_charge",
    "demand_charge_cost_jpy",
    "demand_cost",
    "demand_cost_jpy",
    "fuel_cost",
    "fuel_cost_jpy",
    "fuel_cost_final",
    "fuel_cost_final_jpy",
    "fuel_cost_provisional",
    "fuel_cost_provisional_jpy",
    "fuel_cost_refueled",
    "fuel_cost_refueled_jpy",
    "fuel_cost_provisional_leftover",
    "fuel_cost_provisional_leftover_jpy",
    "co2_cost",
    "co2_cost_jpy",
    "battery_degradation_cost",
    "battery_degradation_cost_jpy",
    "degradation_cost",
    "deviation_cost",
    "vehicle_cost",
    "vehicle_cost_jpy",
    "vehicle_usage_cost",
    "vehicle_usage_cost_jpy",
    "driver_cost",
    "driver_cost_jpy",
    "penalty_unserved",
    "unserved_penalty",
    "switch_cost",
    "return_leg_bonus",
    "weather_strategy_objective_term_jpy_equivalent",
    "contract_overage_cost",
    "contract_overage_cost_jpy",
    "propulsion_energy_cost_jpy",
    "pv_self_consumption_cost_jpy",
    "grid_to_bus_kwh",
    "grid_to_bess_kwh",
    "grid_import_kwh",
    "grid_import_total_kwh",
    "grid_import_for_contract_kwh",
    "bus_charge_from_grid_kwh",
    "bus_charge_from_bess_kwh",
    "total_bus_charge_kwh",
    "total_bess_charge_kwh",
    "total_charge_input_kwh",
    "grid_total_kwh",
    "pv_to_bus_kwh",
    "pv_to_bess_kwh",
    "pv_curtail_kwh",
    "pv_curtailed_kwh",
    "pv_utilization_ratio",
    "pv_utilization_rate",
    "bess_to_bus_kwh",
    "bess_charge_kwh",
    "bess_discharge_kwh",
    "peak_grid_kw",
    "peak_grid_import_kw",
    "peak_grid_import_kw_all_depots",
    "peak_grid_import_kw_any_depot",
    "peak_total_charge_kw",
    "peak_total_charge_kw_all_depots",
    "peak_total_charge_kw_any_depot",
    "contract_over_limit_kwh",
    "contract_over_limit_kw_peak",
    "contract_over_limit_slot_count",
    "contract_limit_exceeded",
    "grid_purchase_cost_jpy",
    "bess_discharge_cost_jpy",
    "total_co2_kg",
}


def _canonical_trip_counts(
    canonical_solver_result: Optional[Dict[str, Any]],
    *,
    fallback_served: int,
    fallback_unserved: int,
) -> tuple[int, int]:
    canonical = dict(canonical_solver_result or {})

    def _count(explicit_key: str, ids_key: str, fallback: int) -> int:
        explicit = canonical.get(explicit_key)
        if explicit not in (None, ""):
            try:
                return max(int(explicit), 0)
            except (TypeError, ValueError):
                pass
        if ids_key in canonical:
            return len(list(canonical.get(ids_key) or []))
        return max(int(fallback), 0)

    return (
        _count("trip_count_served", "served_trip_ids", fallback_served),
        _count("trip_count_unserved", "unserved_trip_ids", fallback_unserved),
    )


def _invalid_result_failure_stage(optimization_result: Dict[str, Any]) -> str:
    settings = dict(optimization_result.get("solver_settings") or {})
    stage2_status = str(settings.get("stage2_solver_status") or "").lower()
    if stage2_status and stage2_status not in {"optimal", "feasible", "solved_feasible"}:
        return "stage2_energy_dispatch"
    stage1_status = str(settings.get("stage1_solver_status") or "").lower()
    if stage1_status in {"infeasible", "inf_or_unbd", "unbounded", "no_valid_incumbent"}:
        return "stage1_assignment"
    return "postsolve_validation"


def _invalidate_mapping_metrics(payload: Dict[str, Any]) -> None:
    for key in _INVALID_RESULT_METRIC_KEYS:
        if key in payload:
            payload[key] = None
    payload["objective_is_actual_cost"] = False
    payload["solver_objective_matches_accounting_total"] = False


def _apply_invalid_result_kpi_gate(
    optimization_result: Dict[str, Any],
    canonical_solver_result: Optional[Dict[str, Any]],
) -> None:
    validity = dict(optimization_result.get("solution_validity") or {})
    if bool(validity.get("validated_feasible", False)):
        return

    solver_status = str(optimization_result.get("solver_status") or "")
    result_status = "INFEASIBLE" if "INFEASIBLE" in solver_status.upper() else "INVALID"
    failure_stage = _invalid_result_failure_stage(optimization_result)
    summary = dict(optimization_result.get("summary") or {})
    served, unserved = _canonical_trip_counts(
        canonical_solver_result,
        fallback_served=int(summary.get("trip_count_served") or 0),
        fallback_unserved=int(summary.get("trip_count_unserved") or 0),
    )

    optimization_result.update(
        {
            "result_status": result_status,
            "failure_stage": failure_stage,
            "research_kpi_eligible": False,
            "objective_value": None,
            "kpi_eligibility_reason": str(
                validity.get("status_reason") or "canonical_result_not_validated_feasible"
            ),
        }
    )
    summary.update(
        {
            "trip_count_served": served,
            "trip_count_unserved": unserved,
            "coverage_rank_primary": unserved,
            "result_status": result_status,
            "failure_stage": failure_stage,
            "research_kpi_eligible": False,
        }
    )
    optimization_result["summary"] = summary

    cost_breakdown = dict(optimization_result.get("cost_breakdown") or {})
    _invalidate_mapping_metrics(cost_breakdown)
    cost_breakdown["evaluation_feasible"] = 0.0
    optimization_result["cost_breakdown"] = cost_breakdown

    graph_artifacts = dict(optimization_result.get("graph_artifacts") or {})
    accounting_summary = dict(graph_artifacts.get("accounting_summary") or {})
    _invalidate_mapping_metrics(accounting_summary)
    accounting_summary.update(
        {
            "served_trip_count": served,
            "unserved_trip_count": unserved,
            "research_kpi_eligible": False,
            "result_status": result_status,
            "failure_stage": failure_stage,
        }
    )
    graph_artifacts["accounting_summary"] = accounting_summary
    optimization_result["graph_artifacts"] = graph_artifacts

    charging_summary = optimization_result.get("charging_summary")
    if isinstance(charging_summary, dict):
        charging_summary.update(
            {
                "result_status": result_status,
                "failure_stage": failure_stage,
                "research_kpi_eligible": False,
            }
        )
        totals = dict(charging_summary.get("totals") or {})
        _invalidate_mapping_metrics(totals)
        charging_summary["totals"] = totals
        gated_depots = []
        for depot in list(charging_summary.get("depots") or []):
            if not isinstance(depot, dict):
                continue
            gated_depot = dict(depot)
            _invalidate_mapping_metrics(gated_depot)
            gated_depots.append(gated_depot)
        charging_summary["depots"] = gated_depots


def _solver_settings_payload(
    *,
    time_limit_seconds_requested: Any,
    mip_gap_requested: Any,
    solver_metadata: Dict[str, Any],
) -> Dict[str, Any]:
    def _float_or_none(value: Any) -> Optional[float]:
        if value is None or value == "":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _int_or_none(value: Any) -> Optional[int]:
        parsed = _float_or_none(value)
        return None if parsed is None else int(parsed)

    metadata = dict(solver_metadata or {})
    effective_limits = dict(metadata.get("effective_limits") or {})
    requested_gap = _float_or_none(mip_gap_requested)
    has_feasible_incumbent = bool(metadata.get("has_feasible_incumbent", False))
    achieved_gap = (
        _float_or_none(metadata.get("achieved_mip_gap", metadata.get("final_gap")))
        if has_feasible_incumbent
        else None
    )
    effective_time_limit = _int_or_none(
        effective_limits.get("time_limit_sec", metadata.get("time_limit_sec", time_limit_seconds_requested))
    )
    stage1_best_obj_stop_enabled = metadata.get("stage1_best_obj_stop_enabled")
    stage1_best_obj_stop_applied = metadata.get("stage1_best_obj_stop_applied")
    runtime_comparison_eligible = (
        None
        if stage1_best_obj_stop_applied is None
        else not bool(stage1_best_obj_stop_applied)
    )
    return {
        "time_limit_seconds_requested": _int_or_none(time_limit_seconds_requested),
        "time_limit_seconds_effective": effective_time_limit,
        "mip_gap_requested_ratio": requested_gap,
        "mip_gap_requested_percent": None if requested_gap is None else requested_gap * 100.0,
        "mip_gap_achieved_ratio": achieved_gap,
        "mip_gap_achieved_percent": None if achieved_gap is None else achieved_gap * 100.0,
        "gurobi_mip_gap_is_ratio": True,
        "has_feasible_incumbent": has_feasible_incumbent,
        "solver_termination_reason": metadata.get("termination_reason"),
        "supports_exact_milp": bool(metadata.get("supports_exact_milp", False)),
        "fallback_applied": bool(metadata.get("fallback_applied", False)),
        "fallback_reason": str(metadata.get("fallback_reason") or ""),
        "research_run": bool(metadata.get("research_run", False)),
        "research_run_accepted": bool(metadata.get("research_run_accepted", False)),
        "research_acceptance_checks": dict(metadata.get("research_acceptance_checks") or {}),
        "research_feasibility_eligible": bool(metadata.get("research_feasibility_eligible", False)),
        "research_assignment_eligible": bool(
            str(metadata.get("phase") or "") == "phase2_assignment_only"
            and bool(metadata.get("research_run", False))
            and bool(metadata.get("research_run_accepted", False))
            and bool(metadata.get("research_feasibility_eligible", False))
        ),
        "research_cost_kpi_eligible": bool(metadata.get("research_cost_kpi_eligible", False)),
        "git_sha": metadata.get("git_sha"),
        "git_dirty": metadata.get("git_dirty"),
        "git_state_available": bool(metadata.get("git_state_available", False)),
        "git_state_error": metadata.get("git_state_error"),
        "research_submission_git_provenance_eligible": bool(
            metadata.get("research_submission_git_provenance_eligible", False)
        ),
        "source_provenance_exact": bool(metadata.get("source_provenance_exact", False)),
        "derived_source_split": bool(metadata.get("derived_source_split", False)),
        "synthetic_pv_fallback_allowed": bool(metadata.get("synthetic_pv_fallback_allowed", False)),
        "synthetic_pv_fallback_applied": bool(metadata.get("synthetic_pv_fallback_applied", False)),
        "successor_pruning_enabled": bool(metadata.get("successor_pruning_enabled", False)),
        "arc_pruning_summary": dict(metadata.get("arc_pruning_summary") or {}),
        "requested_mip_gap": requested_gap,
        "achieved_mip_gap": achieved_gap,
        "requested_phase": str(metadata.get("requested_phase") or ""),
        "requested_phase_token": str(metadata.get("requested_phase_token") or ""),
        "resolved_phase": str(metadata.get("resolved_phase") or ""),
        "executed_phase": str(metadata.get("executed_phase") or ""),
        "stage1_solver_status": metadata.get("stage1_solver_status"),
        "stage1_termination_reason": metadata.get("stage1_termination_reason"),
        "stage1_best_obj_stop_enabled": stage1_best_obj_stop_enabled,
        "stage1_best_obj_stop_applied": stage1_best_obj_stop_applied,
        "stage1_best_obj_stop_threshold": metadata.get(
            "stage1_certified_gap_stop_threshold"
        ),
        "stage1_best_obj_stop_triggered": bool(
            metadata.get("stage1_certified_gap_stop_triggered", False)
        ),
        "stage1_gurobi_raw_best_bound": _float_or_none(
            metadata.get("stage1_gurobi_raw_best_bound")
        ),
        "stage1_gurobi_raw_mip_gap_ratio": _float_or_none(
            metadata.get("stage1_gurobi_raw_mip_gap_ratio")
        ),
        "stage1_gurobi_raw_mip_gap_percent": (
            None
            if _float_or_none(metadata.get("stage1_gurobi_raw_mip_gap_ratio")) is None
            else _float_or_none(metadata.get("stage1_gurobi_raw_mip_gap_ratio"))
            * 100.0
        ),
        "stage1_certified_best_bound": _float_or_none(
            metadata.get("stage1_certified_best_bound")
        ),
        "stage1_certified_mip_gap_ratio": _float_or_none(
            metadata.get("stage1_certified_mip_gap_ratio")
        ),
        "stage1_certified_mip_gap_percent": (
            None
            if _float_or_none(metadata.get("stage1_certified_mip_gap_ratio")) is None
            else _float_or_none(metadata.get("stage1_certified_mip_gap_ratio"))
            * 100.0
        ),
        "stage1_certified_mip_gap_semantics": metadata.get(
            "stage1_certified_mip_gap_semantics"
        ),
        "runtime_comparison_eligible": runtime_comparison_eligible,
        "runtime_comparison_eligibility_reason": (
            "Stage 1 BestObjStop was active; compare wall-clock time only after "
            "disabling it in every case."
            if runtime_comparison_eligible is False
            else "No Stage 1 BestObjStop threshold was applied. Other solver "
            "controls must still match across cases."
            if runtime_comparison_eligible is True
            else "Not applicable because this result has no Stage 1 telemetry."
        ),
        "gurobi_threads": _int_or_none(metadata.get("gurobi_threads")),
        "interactive_runtime_controls": dict(
            metadata.get("interactive_runtime_controls") or {}
        ),
        "interactive_operation_time_window_controls": dict(
            metadata.get("interactive_operation_time_window_controls") or {}
        ),
        "interactive_terminal_soc_controls": dict(
            metadata.get("interactive_terminal_soc_controls") or {}
        ),
        "stage2_solver_status": metadata.get("stage2_solver_status"),
        "stage1_feasible": metadata.get("stage1_feasible"),
        "stage2_feasible": metadata.get("stage2_feasible"),
        "supports_two_stage_milp": metadata.get("supports_two_stage_milp"),
        "supports_integrated_exact_milp": metadata.get("supports_integrated_exact_milp"),
        "assignment_candidate_available": bool(metadata.get("assignment_candidate_available", False)),
    }


def _run_optimization(
    scenario_id: str,
    job_id: str,
    prepared_input_id: str,
    requested_prepared_input_id: Optional[str],
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
    timestep_min: Optional[int] = None,
    enable_weather_operation_policy: Optional[bool] = None,
    weather_proxy_forecast_path: Optional[str] = None,
    research_run: bool = False,
    stage1_time_limit_seconds: Optional[int] = None,
    stage2_time_limit_seconds: Optional[int] = None,
    stage1_best_obj_stop_enabled: bool = INTERACTIVE_STAGE1_BEST_OBJ_STOP_ENABLED,
    gurobi_threads: Optional[int] = INTERACTIVE_GUROBI_THREADS,
    frontend_request_payload: Optional[Dict[str, Any]] = None,
) -> None:
    raw_frontend_request_payload = dict(frontend_request_payload or {})
    interactive_runtime_controls = _interactive_runtime_controls_payload(
        requested_stage1_best_obj_stop_enabled=stage1_best_obj_stop_enabled,
        requested_gurobi_threads=gurobi_threads,
    )
    # This worker is only entered by the BFF interactive endpoint.  Enforce at
    # the last boundary before OptimizationConfig construction rather than
    # trusting a UI/default request field.
    stage1_best_obj_stop_enabled = INTERACTIVE_STAGE1_BEST_OBJ_STOP_ENABLED
    gurobi_threads = INTERACTIVE_GUROBI_THREADS
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
        prepared_input_path = _prepared_inputs_root() / scenario_id / f"{prepared_input_id}.json"
        prepared_payload = load_prepared_input(
            scenario_id=scenario_id,
            prepared_input_id=prepared_input_id,
            scenarios_dir=_prepared_inputs_root(),
        )
        scenario = materialize_scenario_from_prepared_input(
            base_scenario,
            prepared_payload,
        )
        _apply_timestep_min_to_scenario(scenario, timestep_min)
        interactive_operation_time_window_controls = (
            _apply_interactive_operation_time_window_controls(scenario)
        )
        scenario, weather_forecast, weather_profile = _prepare_weather_policy_for_scenario(
            scenario,
            enable_weather_operation_policy=enable_weather_operation_policy,
            weather_proxy_forecast_path=weather_proxy_forecast_path,
        )
        interactive_terminal_soc_controls = _apply_interactive_bev_terminal_soc_policy(
            scenario
        )

        if rebuild_dispatch:
            _persist_prepared_scope_artifacts(
                scenario_id,
                scenario,
                clear_stale_dispatch=False,
            )
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
        elif use_existing_duties:
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
        else:
            scenario["duties"] = []
            scenario["blocks"] = []
            scenario["graph"] = {
                "source": "prepared_scope",
                "total_arcs": 0,
                "feasible_arcs": 0,
                "infeasible_arcs": 0,
            }
        feed_context = _scenario_feed_context(scenario_id)
        output_dir = _scoped_output_dir(
            root=str(output_paths.outputs_root()),
            feed_context=feed_context,
            scenario_id=scenario_id,
            stage="optimization",
            service_id=service_id,
            depot_id=depot_id,
        )
        # Capture the code state before the solver starts.  This same record is
        # written into both the input bundle and the result/audit artifacts so
        # a later reviewer cannot be left with an empty Git SHA.
        run_git_state = collect_git_state()

        charging_summary_payload: Optional[Dict[str, Any]] = None
        charging_flow_payload: Optional[Dict[str, Any]] = None
        charging_payload_warning: Optional[str] = None
        run_input_provenance: Dict[str, Any] = {
            "status": "not_captured",
            "reason": "solver_path_did_not_build_canonical_input_provenance",
        }

        if solver_mode in {
            "thesis_mode", "debug_mode", "mode_milp_only", "mode_alns_only",
            "mode_ga_only", "mode_abc_only", "mode_hybrid",
            "phase1_charging_only", "phase2_assignment_only", "phase3_two_stage",
            "phase4_integrated", "diagnostic",
        }:
            # CANONICAL PATH: Uses src/optimization/ engine stack
            opt_mode = _parse_optimization_mode(solver_mode)
            engine_label = str(opt_mode.value or "optimization").upper()
            job_store.update_job(
                job_id,
                status="running",
                progress=25,
                message="Building canonical problem...",
                metadata=_job_metadata(
                    scenario_id=scenario_id,
                    service_id=service_id,
                    depot_id=depot_id,
                    stage="build_canonical",
                    mode=mode,
                    extra={
                        "rebuild_dispatch": rebuild_dispatch,
                        "use_existing_duties": use_existing_duties,
                        "prepared_input_id": prepared_input_id,
                        "prepared_input_path": str(prepared_input_path),
                    },
                ),
            )
            phase_token = _phase_from_solver_mode(solver_mode)
            requested_phase = phase_token or solver_mode
            is_diagnostic_mode = solver_mode == "diagnostic" or solver_mode == "debug_mode"
            opt_config = OptimizationConfig(
                mode=opt_mode,
                time_limit_sec=time_limit_seconds,
                stage1_time_limit_sec=stage1_time_limit_seconds,
                stage2_time_limit_sec=stage2_time_limit_seconds,
                stage1_best_obj_stop_enabled=bool(stage1_best_obj_stop_enabled),
                gurobi_threads=gurobi_threads,
                mip_gap=mip_gap,
                random_seed=random_seed,
                alns_iterations=alns_iterations,
                no_improvement_limit=no_improvement_limit,
                destroy_fraction=destroy_fraction,
                warm_start=True,
                thesis_mode=solver_mode in {"thesis_mode", "mode_milp_only"} or phase_token == "phase3_two_stage",
                debug_mode=solver_mode == "debug_mode" or phase_token == "diagnostic",
                research_run=bool(research_run),
                allow_postsolve_repair=solver_mode == "debug_mode",
                phase=phase_token,
                requested_phase_token=solver_mode,
                requested_phase=requested_phase,
                resolved_phase=phase_token,
                executed_phase=phase_token,
                diagnostic_mode=is_diagnostic_mode,
            )
            problem = ProblemBuilder().build_from_scenario(
                scenario,
                depot_id=depot_id,
                service_id=service_id,
                config=opt_config,
                planning_days=max(
                    int(((scenario.get("simulation_config") or {}).get("planning_days") or 1)),
                    1,
                ),
            )
            if weather_forecast is not None and weather_profile is not None:
                problem = apply_weather_policy_to_problem(
                    problem,
                    weather_forecast,
                    weather_profile,
                    random_seed=random_seed,
                )
            if (
                phase_token == "phase3_two_stage"
                and isinstance(problem.metadata, dict)
            ):
                problem.metadata["phase3_diagnostics_dir"] = str(
                    Path(output_dir) / "diagnostics"
                )
            run_input_provenance = persist_run_input_provenance(
                run_dir=Path(output_dir),
                base_scenario=base_scenario,
                effective_scenario=scenario,
                prepared_input=prepared_payload,
                prepared_input_path=prepared_input_path,
                requested_prepared_input_id=requested_prepared_input_id,
                frontend_request={
                    "raw_frontend_body": raw_frontend_request_payload,
                    "interactive_runtime_controls": interactive_runtime_controls,
                    "interactive_operation_time_window_controls": (
                        interactive_operation_time_window_controls
                    ),
                    "interactive_terminal_soc_controls": interactive_terminal_soc_controls,
                    "scenario_id": scenario_id,
                    "prepared_input_id": prepared_input_id,
                    "requested_prepared_input_id": requested_prepared_input_id,
                    "mode": mode,
                    "solver_mode_effective": solver_mode,
                    "time_limit_seconds": time_limit_seconds,
                    "stage1_time_limit_seconds": stage1_time_limit_seconds,
                    "stage2_time_limit_seconds": stage2_time_limit_seconds,
                    "stage1_best_obj_stop_enabled": bool(
                        stage1_best_obj_stop_enabled
                    ),
                    "gurobi_threads": gurobi_threads,
                    "mip_gap": mip_gap,
                    "random_seed": random_seed,
                    "service_id": service_id,
                    "depot_id": depot_id,
                    "rebuild_dispatch": rebuild_dispatch,
                    "use_existing_duties": use_existing_duties,
                    "alns_iterations": alns_iterations,
                    "no_improvement_limit": no_improvement_limit,
                    "destroy_fraction": destroy_fraction,
                    "timestep_min": timestep_min,
                    "enable_weather_operation_policy": (
                        enable_weather_operation_policy
                    ),
                    "weather_proxy_forecast_path": weather_proxy_forecast_path,
                    "research_run": bool(research_run),
                },
                optimization_config=opt_config,
                canonical_problem=problem,
                code_provenance=run_git_state,
            )
            feasible_arc_count = sum(
                len(v) for v in (problem.feasible_connections or {}).values()
            )
            build_report = ScenarioBuildReport(
                scenario_id=scenario_id,
                depot_id=depot_id or "",
                service_id=service_id,
                trip_count=len(problem.trips),
                task_count=len(problem.trips),
                vehicle_count=len(problem.vehicles),
                charger_count=len(problem.chargers),
                travel_connection_count=feasible_arc_count,
            )
            store.set_field(scenario_id, "problemdata_build_audit", build_report.to_dict())

            price_slots = list(problem.price_slots or [])
            pv_slots = list(problem.pv_slots or [])

            job_store.update_job(
                job_id,
                status="running",
                progress=55,
                message=f"Running {engine_label} optimizer ({mode})...",
                metadata=_job_metadata(
                    scenario_id=scenario_id,
                    service_id=service_id,
                    depot_id=depot_id,
                    stage="solve",
                    mode=mode,
                    extra={
                        "prepared_input_id": prepared_input_id,
                        "problem_summary": {
                            "trips": len(problem.trips),
                            "vehicles": len(problem.vehicles),
                            "chargers": len(problem.chargers),
                            "feasible_arcs": feasible_arc_count,
                            "price_slots": len(price_slots),
                            "pv_slots": len(pv_slots),
                            "time_limit_seconds_requested": time_limit_seconds,
                        },
                    },
                ),
            )
            solve_started_at = time.perf_counter()
            engine_result = OptimizationEngine().solve(problem, opt_config)
            solve_elapsed = time.perf_counter() - solve_started_at
            engine_solver_metadata = dict(engine_result.solver_metadata or {})
            engine_solver_metadata.update(
                {
                    "git_sha": run_git_state.get("git_sha"),
                    "git_dirty": run_git_state.get("git_dirty"),
                    "git_state_available": bool(
                        run_git_state.get("git_state_available", False)
                    ),
                    "git_state_error": run_git_state.get("git_state_error"),
                    "git_provenance_captured_before_solve": True,
                    "research_submission_git_provenance_eligible": bool(
                        run_git_state.get("git_state_available", False)
                        and run_git_state.get("git_dirty") is False
                    ),
                    "interactive_runtime_controls": interactive_runtime_controls,
                    "interactive_operation_time_window_controls": (
                        interactive_operation_time_window_controls
                    ),
                    "interactive_terminal_soc_controls": interactive_terminal_soc_controls,
                }
            )
            # Production results are immutable dataclasses.  Lightweight
            # compatibility/test adapters may expose the same contract as a
            # mutable object, so do not make provenance capture itself prevent
            # result persistence for those adapters.
            if is_dataclass(engine_result):
                engine_result = replace(
                    engine_result,
                    solver_metadata=engine_solver_metadata,
                )
            else:
                engine_result.solver_metadata = engine_solver_metadata
            graph_artifacts = _persist_canonical_graph_exports(
                scenario=scenario,
                problem=problem,
                engine_result=engine_result,
                scenario_id=scenario_id,
                output_dir=output_dir,
            )
            try:
                charging_flow_payload = _canonical_charging_output_payload(problem, engine_result)
                charging_summary_payload = dict(charging_flow_payload.get("summary") or {})
            except Exception as exc:
                charging_flow_payload = None
                charging_summary_payload = None
                charging_payload_warning = (
                    "Charging breakdown export was skipped because the canonical energy-flow payload "
                    f"could not be constructed: {exc}"
                )
            smeta = dict(engine_result.solver_metadata or {})
            smeta.setdefault("solve_time_sec", float(solve_elapsed))
            if charging_payload_warning:
                warnings_list = list(smeta.get("warnings") or [])
                warnings_list.append(charging_payload_warning)
                smeta["warnings"] = warnings_list
            _cb = dict(engine_result.cost_breakdown or {})
            # Alias keys so _cost_breakdown() can read both naming conventions
            _cb.setdefault("electricity_cost", _cb.get("electricity_cost_final", _cb.get("energy_cost", 0.0)))
            _cb.setdefault("fuel_cost", _cb.get("fuel_cost", 0.0))
            _cb.setdefault("demand_charge_cost", _cb.get("demand_cost", 0.0))
            _cb.setdefault("battery_degradation_cost", _cb.get("degradation_cost", 0.0))
            _cb.setdefault("emission_cost", _cb.get("co2_cost", 0.0))
            _cb.update(normalize_pv_energy_breakdown(_cb))
            achieved_mip_gap = smeta.get("achieved_mip_gap", smeta.get("final_gap"))
            result_payload = {
                "status": engine_result.solver_status,
                "objective_value": engine_result.objective_value,
                "solve_time_seconds": float(smeta.get("solve_time_sec", 0.0) or solve_elapsed),
                "mip_gap": None if achieved_mip_gap is None else float(achieved_mip_gap),
                "requested_mip_gap": float(smeta.get("requested_mip_gap", smeta.get("mip_gap", mip_gap)) or 0.0),
                "achieved_mip_gap": None if achieved_mip_gap is None else float(achieved_mip_gap),
                "assignment": {
                    k: list(v)
                    for k, v in engine_result.plan.vehicle_paths().items()
                },
                "unserved_tasks": list(engine_result.plan.unserved_trip_ids),
                "obj_breakdown": _cb,
                "solver_metadata": smeta,
            }
            sim_payload = None
            vehicle_type_by_id = {
                v.vehicle_id: v.vehicle_type for v in problem.vehicles
            }
            # Expose full new-system result for solver_result field
            _full_new_result = ResultSerializer.serialize_result(engine_result)
            if charging_summary_payload is not None:
                _full_new_result["charging_summary"] = charging_summary_payload
            result_payload["warnings"] = list(_full_new_result.get("warnings") or [])
            result_payload["infeasibility_reasons"] = list(
                _full_new_result.get("infeasibility_reasons") or []
            )
            result_payload["strict_coverage_precheck"] = dict(
                _full_new_result.get("strict_coverage_precheck") or {}
            )
        else:
            # ── LEGACY PATH: Should not reach here due to _normalize_solver_mode gating ──
            # This branch is kept temporarily for backward compatibility during migration.
            import warnings
            warnings.warn(
                f"Legacy solver path triggered for mode '{mode}' (normalized: '{solver_mode}'). "
                f"This path is deprecated and will be removed. "
                f"Please update to canonical modes: mode_milp_only, mode_alns_only, mode_hybrid, etc.",
                DeprecationWarning,
                stacklevel=2,
            )
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
                        "prepared_input_id": prepared_input_id,
                        "requested_prepared_input_id": requested_prepared_input_id,
                        "prepared_input_path": str(prepared_input_path),
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

            if (
                int(build_report.travel_connection_count or 0) <= 0
                and int(build_report.task_count or 0) > int(build_report.vehicle_count or 0)
                and not bool(getattr(data, "allow_partial_service", False))
            ):
                setattr(data, "allow_partial_service", True)
                setattr(data, "service_coverage_mode", "penalized")
                auto_relax_msg = (
                    "No travel connections generated while allow_partial_service is OFF. "
                    "Auto-relaxed allow_partial_service=True for this run to avoid hard infeasible stop. "
                    f"tasks={build_report.task_count}, vehicles={build_report.vehicle_count}, "
                    f"travel_connections={build_report.travel_connection_count}, "
                    f"prepared_input_id={prepared_input_id}, "
                    f"requested_prepared_input_id={requested_prepared_input_id or '-'}, "
                    f"prepared_input_path={prepared_input_path}."
                )
                if hasattr(build_report, "warnings"):
                    build_report.warnings.append(auto_relax_msg)

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
                        "prepared_input_id": prepared_input_id,
                        "requested_prepared_input_id": requested_prepared_input_id,
                        "prepared_input_path": str(prepared_input_path),
                        "problem_summary": {
                            "trips": len(getattr(data, "tasks", []) or []),
                            "vehicles": len(getattr(data, "vehicles", []) or []),
                            "chargers": len(getattr(data, "chargers", []) or []),
                            "travel_connections": build_report.travel_connection_count,
                            "allow_partial_service_effective": bool(getattr(data, "allow_partial_service", False)),
                            "price_slots": len(price_slots),
                            "pv_slots": len(pv_slots),
                            "time_limit_seconds_requested": time_limit_seconds,
                            "time_limit_seconds_effective": min(time_limit_seconds, 86400),
                        },
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
                    root=str(output_paths.outputs_root()),
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
            _full_new_result = None
            graph_artifacts = {"enabled": False, "diagram_count": 0}
        vehicle_count_by_type: Dict[str, int] = {}
        trip_count_by_type: Dict[str, int] = {}
        for vehicle_id, task_ids in (result_payload.get("assignment") or {}).items():
            if not task_ids:
                continue
            vehicle_type = str(vehicle_type_by_id.get(vehicle_id) or "UNKNOWN")
            vehicle_count_by_type[vehicle_type] = vehicle_count_by_type.get(vehicle_type, 0) + 1
            trip_count_by_type[vehicle_type] = trip_count_by_type.get(vehicle_type, 0) + len(task_ids)
        available_vehicle_count_by_type: Dict[str, int] = {}
        unused_available_vehicle_ids_by_type: Dict[str, List[str]] = {}
        used_vehicle_ids = {
            str(vehicle_id)
            for vehicle_id, task_ids in (result_payload.get("assignment") or {}).items()
            if task_ids
        }
        for vehicle in problem.vehicles:
            if not bool(getattr(vehicle, "available", True)):
                continue
            vehicle_id = str(getattr(vehicle, "vehicle_id", "") or "")
            vehicle_type = str(getattr(vehicle, "vehicle_type", "UNKNOWN") or "UNKNOWN").upper()
            available_vehicle_count_by_type[vehicle_type] = available_vehicle_count_by_type.get(vehicle_type, 0) + 1
            if vehicle_id and vehicle_id not in used_vehicle_ids:
                unused_available_vehicle_ids_by_type.setdefault(vehicle_type, []).append(vehicle_id)
        for vehicle_ids in unused_available_vehicle_ids_by_type.values():
            vehicle_ids.sort()
        electric_types = {"BEV", "PHEV", "FCEV"}
        ev_available_count = sum(
            count for vehicle_type, count in available_vehicle_count_by_type.items() if vehicle_type.upper() in electric_types
        )
        ev_used_count = sum(
            count for vehicle_type, count in vehicle_count_by_type.items() if vehicle_type.upper() in electric_types
        )
        ice_available_count = sum(
            count for vehicle_type, count in available_vehicle_count_by_type.items() if vehicle_type.upper() not in electric_types
        )
        ice_used_count = sum(
            count for vehicle_type, count in vehicle_count_by_type.items() if vehicle_type.upper() not in electric_types
        )
        objective_mode = str(
            (
                ((scenario.get("scenario_overlay") or {}).get("solver_config") or {}).get("objective_mode")
                or (scenario.get("simulation_config") or {}).get("objective_mode")
                or "total_cost"
            )
        )
        prepared_scope_summary = dict(scenario.get("prepared_scope_summary") or {})
        prepared_scenario_hash = str(
            prepared_scope_summary.get("scenario_hash")
            or (prepared_payload.get("scenario_hash") if isinstance(prepared_payload, dict) else "")
            or ""
        )
        prepared_scope_hash = str(
            prepared_scope_summary.get("scope_hash")
            or (prepared_payload.get("scope_hash") if isinstance(prepared_payload, dict) else "")
            or ""
        )
        prepared_scope_audit = dict(
            prepared_scope_summary.get("prepared_scope_audit")
            or (prepared_payload.get("prepared_scope_audit") if isinstance(prepared_payload, dict) else {})
            or {}
        )
        if prepared_scope_audit:
            result_payload["prepared_scope_audit"] = prepared_scope_audit
            if isinstance(_full_new_result, dict):
                _full_new_result["prepared_scope_audit"] = prepared_scope_audit
        service_coverage_mode = str(getattr(problem.scenario, "service_coverage_mode", "strict") or "strict")
        fixed_route_band_mode = bool((problem.metadata or {}).get("fixed_route_band_mode", False))
        daily_fragment_limit = int((problem.metadata or {}).get("daily_fragment_limit") or 1)
        available_vehicle_count_total = sum(
            1 for vehicle in problem.vehicles if bool(getattr(vehicle, "available", True))
        )
        unused_available_vehicle_ids = list(engine_result.plan.unused_available_vehicle_ids(problem))
        solver_metadata = dict(engine_result.solver_metadata or {})
        strict_coverage_precheck = dict(
            solver_metadata.get("strict_coverage_precheck")
            or (result_payload.get("strict_coverage_precheck") if isinstance(result_payload, dict) else {})
            or (_full_new_result.get("strict_coverage_precheck") if isinstance(_full_new_result, dict) else {})
            or {}
        )
        result_warnings = list(
            (_full_new_result.get("warnings") if isinstance(_full_new_result, dict) else None)
            or result_payload.get("warnings")
            or []
        )
        result_infeasibility_reasons = list(
            (_full_new_result.get("infeasibility_reasons") if isinstance(_full_new_result, dict) else None)
            or result_payload.get("infeasibility_reasons")
            or []
        )
        startup_rejected_raw = (
            solver_metadata.get("startup_rejected_vehicle_ids_by_duty")
            or (engine_result.plan.metadata or {}).get("startup_rejected_vehicle_ids_by_duty")
            or {}
        )
        startup_rejected_vehicle_ids_by_duty: Dict[str, List[str]] = {}
        if isinstance(startup_rejected_raw, dict):
            for duty_id, vehicle_ids in startup_rejected_raw.items():
                normalized_vehicle_ids = sorted(
                    {
                        str(vehicle_id).strip()
                        for vehicle_id in list(vehicle_ids or [])
                        if str(vehicle_id).strip()
                    }
                )
                if normalized_vehicle_ids:
                    startup_rejected_vehicle_ids_by_duty[str(duty_id)] = normalized_vehicle_ids
        startup_rejected_duty_count = len(startup_rejected_vehicle_ids_by_duty)
        startup_rejected_vehicle_candidate_count = sum(
            len(vehicle_ids) for vehicle_ids in startup_rejected_vehicle_ids_by_duty.values()
        )
        startup_rejected_vehicle_count = len(
            {
                vehicle_id
                for vehicle_ids in startup_rejected_vehicle_ids_by_duty.values()
                for vehicle_id in vehicle_ids
            }
        )
        legacy_trip_count_served = sum(
            len(task_ids)
            for task_ids in (result_payload.get("assignment") or {}).values()
        )
        legacy_trip_count_unserved = len(result_payload.get("unserved_tasks") or [])
        trip_count_served, trip_count_unserved = _canonical_trip_counts(
            _full_new_result if isinstance(_full_new_result, dict) else None,
            fallback_served=legacy_trip_count_served,
            fallback_unserved=legacy_trip_count_unserved,
        )
        canonical_feasible = (
            bool(_full_new_result.get("feasible"))
            if isinstance(_full_new_result, dict) and "feasible" in _full_new_result
            else bool(engine_result.feasible)
        )
        solution_validity = _solution_validity_payload(
            solver_status=result_payload["status"],
            feasible=canonical_feasible,
            trip_count_unserved=trip_count_unserved,
            infeasibility_reasons=result_infeasibility_reasons,
            solver_metadata=solver_metadata,
        )
        if isinstance(_full_new_result, dict):
            _full_new_result["solution_validity"] = solution_validity
        result_payload["solution_validity"] = solution_validity
        weather_policy_payload = _weather_policy_payload_from_problem_metadata(
            dict(problem.metadata or {})
        )
        solver_settings = _solver_settings_payload(
            time_limit_seconds_requested=time_limit_seconds,
            mip_gap_requested=mip_gap,
            solver_metadata=solver_metadata,
        )
        result_cost_breakdown = _cost_breakdown(result_payload, sim_payload)
        accounting_summary_for_result = dict((graph_artifacts or {}).get("accounting_summary") or {})
        objective_value_for_result = result_payload.get("objective_value")
        if (
            bool(result_cost_breakdown.get("objective_is_actual_cost", False))
            and accounting_summary_for_result.get("reported_total_cost_jpy") is not None
        ):
            objective_value_for_result = float(accounting_summary_for_result.get("reported_total_cost_jpy") or 0.0)
            result_payload["objective_value"] = objective_value_for_result
            result_cost_breakdown["total_cost"] = objective_value_for_result
            result_cost_breakdown["objective_value"] = objective_value_for_result
            if isinstance(result_payload.get("obj_breakdown"), dict):
                result_payload["obj_breakdown"]["total_cost"] = objective_value_for_result
                result_payload["obj_breakdown"]["objective_value"] = objective_value_for_result
            if isinstance(_full_new_result, dict):
                _full_new_result["objective_value"] = objective_value_for_result
                if isinstance(_full_new_result.get("cost_breakdown"), dict):
                    _full_new_result["cost_breakdown"]["total_cost"] = objective_value_for_result
                    _full_new_result["cost_breakdown"]["objective_value"] = objective_value_for_result

        optimization_result: Dict[str, Any] = {
            "scenario_id": scenario_id,
            "feed_context": feed_context,
            "scope": {"serviceId": service_id, "depotId": depot_id},
            "prepared_input_id": prepared_input_id,
            "prepared_scope_summary": prepared_scope_summary,
            "scenario_hash": prepared_scenario_hash,
            "scope_hash": prepared_scope_hash,
            "solver_status": result_payload["status"],
            "mode": mode,
            "solver_mode": solver_mode,
            "objective_mode": objective_mode,
            "objective_value": objective_value_for_result,
            "solve_time_seconds": result_payload.get("solve_time_seconds", 0.0),
            "mip_gap": result_payload.get("mip_gap"),
            "solver_metadata": solver_metadata,
            "solver_settings": solver_settings,
            "warnings": result_warnings,
            "infeasibility_reasons": result_infeasibility_reasons,
            "strict_coverage_precheck": strict_coverage_precheck,
            "prepared_scope_audit": prepared_scope_audit,
            "solution_validity": solution_validity,
            "result_class": solution_validity.get("result_class"),
            "research_kpi_eligible": bool(solution_validity.get("research_kpi_eligible", False)),
            "electricity_cost_basis": str(
                (sim_payload or {}).get("electricity_cost_basis") or "provisional_drive"
            ),
            "cost_breakdown": result_cost_breakdown,
            "dispatch_report": scenario.get("graph") or store.get_field(scenario_id, "graph") or {},
            "build_report": build_report.to_dict(),
            "summary": {
                "same_day_depot_cycles_enabled": bool(
                    dict(engine_result.solver_metadata or {}).get(
                        "same_day_depot_cycles_enabled",
                        getattr(problem.scenario, "allow_same_day_depot_cycles", True),
                    )
                ),
                "service_coverage_mode": service_coverage_mode,
                "fixed_route_band_mode": fixed_route_band_mode,
                "daily_fragment_limit": daily_fragment_limit,
                "prepared_input_id": prepared_input_id,
                "scenario_hash": prepared_scenario_hash,
                "scope_hash": prepared_scope_hash,
                "strict_coverage_precheck": strict_coverage_precheck,
                "prepared_scope_audit": prepared_scope_audit,
                "available_vehicle_count_total": available_vehicle_count_total,
                "unused_available_vehicle_ids": unused_available_vehicle_ids,
                "startup_infeasible_assignment_count": int(
                    solver_metadata.get("startup_infeasible_assignment_count")
                    or (engine_result.plan.metadata or {}).get("startup_infeasible_assignment_count")
                    or 0
                ),
                "startup_infeasible_trip_ids": list(
                    solver_metadata.get("startup_infeasible_trip_ids")
                    or (engine_result.plan.metadata or {}).get("startup_infeasible_trip_ids")
                    or []
                ),
                "startup_infeasible_vehicle_ids": list(
                    solver_metadata.get("startup_infeasible_vehicle_ids")
                    or (engine_result.plan.metadata or {}).get("startup_infeasible_vehicle_ids")
                    or []
                ),
                "startup_rejected_duty_count": int(startup_rejected_duty_count),
                "startup_rejected_vehicle_candidate_count": int(startup_rejected_vehicle_candidate_count),
                "startup_rejected_vehicle_count": int(startup_rejected_vehicle_count),
                "startup_rejected_vehicle_ids_by_duty": startup_rejected_vehicle_ids_by_duty,
                "max_depot_cycles_per_vehicle_per_day": int(
                    solver_metadata.get(
                        "max_depot_cycles_per_vehicle_per_day",
                        getattr(problem.scenario, "max_depot_cycles_per_vehicle_per_day", 1),
                    )
                    or 1
                ),
                "vehicle_count_used": sum(
                    1
                    for _vehicle_id, task_ids in (
                        result_payload.get("assignment") or {}
                    ).items()
                    if task_ids
                ),
                "vehicle_count_by_type": vehicle_count_by_type,
                "available_vehicle_count_by_type": available_vehicle_count_by_type,
                "used_vehicle_count_by_type": vehicle_count_by_type,
                "unused_available_vehicle_ids_by_type": unused_available_vehicle_ids_by_type,
                "ev_available_count": ev_available_count,
                "ev_used_count": ev_used_count,
                "ev_unused_count": max(ev_available_count - ev_used_count, 0),
                "ice_available_count": ice_available_count,
                "ice_used_count": ice_used_count,
                "ice_unused_count": max(ice_available_count - ice_used_count, 0),
                "trip_count_by_type": trip_count_by_type,
                "trip_count_served": trip_count_served,
                "trip_count_unserved": trip_count_unserved,
                "coverage_rank_primary": trip_count_unserved,
                "solution_validity": solution_validity,
                "secondary_objective_value": result_payload.get("secondary_objective_value"),
                "vehicle_fragment_counts": dict(
                    engine_result.plan.vehicle_fragment_counts()
                ),
                "vehicles_with_multiple_fragments": list(
                    engine_result.plan.vehicles_with_multiple_fragments()
                ),
                "max_fragments_observed": int(engine_result.plan.max_fragments_observed()),
            },
            "solver_result": result_payload,
            "canonical_solver_result": _full_new_result,
            "canonical_problem_summary": {
                "trip_count": build_report.task_count,
                "vehicle_count": build_report.vehicle_count,
                "available_vehicle_count_total": available_vehicle_count_total,
                "charger_count": build_report.charger_count,
                "price_slot_count": len(price_slots),
                "pv_slot_count": len(pv_slots),
            },
            "graph_artifacts": graph_artifacts,
        }
        if weather_policy_payload is not None:
            optimization_result["weather_policy"] = weather_policy_payload
        if charging_summary_payload is not None:
            optimization_result["charging_summary"] = charging_summary_payload
        if charging_payload_warning:
            optimization_result["charging_summary_warning"] = charging_payload_warning
        if sim_payload is not None:
            optimization_result["simulation_summary"] = sim_payload
        if isinstance(optimization_result.get("cost_breakdown"), dict):
            optimization_result["cost_breakdown"]["evaluation_feasible"] = (
                1.0 if bool(solution_validity.get("validated_feasible")) else 0.0
            )
        if isinstance(result_payload.get("obj_breakdown"), dict):
            result_payload["obj_breakdown"]["evaluation_feasible"] = (
                1.0 if bool(solution_validity.get("validated_feasible")) else 0.0
            )
        if isinstance(_full_new_result, dict) and isinstance(_full_new_result.get("cost_breakdown"), dict):
            _full_new_result["cost_breakdown"]["evaluation_feasible"] = (
                1.0 if bool(solution_validity.get("validated_feasible")) else 0.0
            )
        _apply_invalid_result_kpi_gate(
            optimization_result,
            _full_new_result if isinstance(_full_new_result, dict) else None,
        )
        if not bool(solution_validity.get("validated_feasible")) and isinstance(
            optimization_result.get("charging_summary"), dict
        ):
            charging_summary_payload = dict(optimization_result["charging_summary"])

        optimization_audit = {
            "scenario_id": scenario_id,
            "feed_context": feed_context,
            "depot_id": depot_id,
            "service_id": service_id,
            "prepared_input_id": prepared_input_id,
            "prepared_scope_summary": prepared_scope_summary,
            "scenario_hash": prepared_scenario_hash,
            "scope_hash": prepared_scope_hash,
            "run_input_provenance": run_input_provenance,
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
            "warnings": list(
                dict.fromkeys(
                    [
                        *list(build_report.warnings or []),
                        *result_warnings,
                        *list(prepared_scope_audit.get("warnings") or []),
                    ]
                )
            ),
            "errors": list(
                dict.fromkeys(
                    [
                        *list(build_report.errors or []),
                        *result_infeasibility_reasons,
                    ]
                )
            ),
            "solver_mode": mode,
            "solver_mode_effective": solver_mode,
            "service_coverage_mode": service_coverage_mode,
            "fixed_route_band_mode": fixed_route_band_mode,
            "daily_fragment_limit": daily_fragment_limit,
            "strict_coverage_precheck": strict_coverage_precheck,
            "prepared_scope_audit": prepared_scope_audit,
            "available_vehicle_count_total": available_vehicle_count_total,
            "unused_available_vehicle_ids": unused_available_vehicle_ids,
            "startup_rejected_duty_count": int(startup_rejected_duty_count),
            "startup_rejected_vehicle_candidate_count": int(startup_rejected_vehicle_candidate_count),
            "startup_rejected_vehicle_count": int(startup_rejected_vehicle_count),
            "startup_rejected_vehicle_ids_by_duty": startup_rejected_vehicle_ids_by_duty,
            "time_limit": time_limit_seconds,
            "mip_gap": mip_gap,
            "solver_settings": solver_settings,
            **solver_settings,
            "random_seed": random_seed,
            "gurobi_seed": random_seed,
            "alns_iterations": alns_iterations,
            "no_improvement_limit": no_improvement_limit,
            "destroy_fraction": destroy_fraction,
            "git_sha": run_git_state.get("git_sha"),
            "git_dirty": run_git_state.get("git_dirty"),
            "git_state_available": bool(
                run_git_state.get("git_state_available", False)
            ),
            "git_state_error": run_git_state.get("git_state_error"),
            "source_snapshot": store.get_field(scenario_id, "source_snapshot"),
            "output_dir": output_dir,
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }
        if weather_policy_payload is not None:
            optimization_audit["weather_policy"] = weather_policy_payload.get("audit") or {}
        optimization_result["audit"] = optimization_audit

        store.set_field(scenario_id, "optimization_result", optimization_result)
        store.set_field(scenario_id, "optimization_audit", optimization_audit)
        _persist_json_outputs(
            output_dir,
            {
                "optimization_result.json": optimization_result,
                "optimization_audit.json": optimization_audit,
                "assignment_validation_diagnostics.json": {
                    "research_run": bool(
                        (optimization_result.get("solver_metadata") or {}).get("research_run", False)
                    ),
                    "diagnostics": list(
                        (optimization_result.get("solver_metadata") or {}).get(
                            "assignment_validation_diagnostics", []
                        )
                        or []
                    ),
                },
            },
        )
        reporting_finalizer_result = _persist_rich_run_outputs(
            run_dir=Path(output_dir),
            scenario=scenario,
            optimization_result=optimization_result,
            optimization_audit=optimization_audit,
            result_payload=result_payload,
            sim_payload=sim_payload,
            canonical_solver_result=_full_new_result,
            canonical_problem=problem,
            graph_source_dir=Path(output_dir) / "graph",
            charging_summary=charging_summary_payload,
            charging_flow_payload=charging_flow_payload,
            finalize_reporting=True,
        )
        if reporting_finalizer_result is not None:
            store.set_field(scenario_id, "optimization_result", optimization_result)
            store.set_field(scenario_id, "optimization_audit", optimization_audit)
            _persist_json_outputs(
                output_dir,
                {
                    "optimization_result.json": optimization_result,
                    "optimization_audit.json": optimization_audit,
                },
            )
        is_fallback = bool(solution_validity.get("result_class") in {"baseline_fallback", "postsolve_infeasible", "postsolve_repaired", "repaired_heuristic", "debug_result"})
        final_status = "optimized" if not is_fallback else "optimized_provisional"
        store.update_scenario(scenario_id, status=final_status)
        job_message = "Optimization complete." if not is_fallback else f"Optimization complete ({solution_validity.get('status_reason', 'provisional')})."
        job_store.update_job(
            job_id,
            status="completed",
            progress=100,
            message=job_message,
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
                    "run_dir": output_dir,
                    "reporting_finalizer_status": dict(
                        (optimization_result.get("graph_artifacts") or {}).get("reporting_finalizer")
                        or {}
                    ).get("status"),
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
        "actual_bess_soc_kwh": dict(body.actual_bess_soc_kwh),
        "observed_on_peak_kw_by_depot": dict(
            body.observed_on_peak_kw_by_depot
        ),
        "observed_off_peak_kw_by_depot": dict(
            body.observed_off_peak_kw_by_depot
        ),
        "actual_location_node_id": dict(body.actual_location_node_id),
        "delays": [item.model_dump() for item in body.delays],
        "reoptimization_strategy": body.reoptimization_strategy,
        "execution_minutes": body.execution_minutes,
        "bess_terminal_policy": body.bess_terminal_policy,
    }
    return updated


def _validate_day_ahead_result_contract(
    prior_result: Dict[str, Any],
    *,
    scenario_id: str,
    prepared_input_id: str,
    service_id: str,
    depot_id: str,
) -> None:
    """Reject a persisted result from a different scenario input or scope."""

    prior_scenario_id = str(prior_result.get("scenario_id") or "").strip()
    if prior_scenario_id != str(scenario_id):
        raise ValueError(
            "Persisted day-ahead result scenario mismatch: "
            f"expected {scenario_id!r}, got {prior_scenario_id!r}"
        )
    prior_prepared_input_id = str(
        prior_result.get("prepared_input_id") or ""
    ).strip()
    if prior_prepared_input_id != str(prepared_input_id):
        raise ValueError(
            "Persisted day-ahead result prepared input mismatch: "
            f"expected {prepared_input_id!r}, got {prior_prepared_input_id!r}"
        )

    prior_scope = prior_result.get("scope")
    if not isinstance(prior_scope, dict):
        raise ValueError("Persisted day-ahead result has no dispatch scope")
    expected_scope = {
        "serviceId": str(service_id),
        "depotId": str(depot_id),
    }
    actual_scope = {
        "serviceId": str(prior_scope.get("serviceId") or ""),
        "depotId": str(prior_scope.get("depotId") or ""),
    }
    if actual_scope != expected_scope:
        raise ValueError(
            "Persisted day-ahead result scope mismatch: "
            f"expected {expected_scope}, got {actual_scope}"
        )


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
    timestep_min = _request_timestep_min(body.timestep_min, body.time_step_min)
    try:
        if not depot_id:
            raise ValueError("No depot selected. Configure dispatch scope first.")

        base_scenario = store.get_scenario_document_shallow(scenario_id)
        prior_optimization_result = store.get_field(
            scenario_id, "optimization_result"
        )
        prepared_payload = load_prepared_input(
            scenario_id=scenario_id,
            prepared_input_id=prepared_input_id,
            scenarios_dir=_prepared_inputs_root(),
        )
        scenario = _apply_reoptimization_inputs(
            materialize_scenario_from_prepared_input(base_scenario, prepared_payload),
            body,
        )
        _apply_timestep_min_to_scenario(scenario, timestep_min)
        _apply_interactive_operation_time_window_controls(scenario)
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
        solver_mode = _normalize_solver_mode(mode)
        phase_token = _phase_from_solver_mode(solver_mode)
        requested_phase = phase_token or solver_mode
        is_diagnostic_mode = solver_mode in {"debug_mode", "diagnostic"}
        config = OptimizationConfig(
            mode=_parse_optimization_mode(solver_mode),
            time_limit_sec=body.time_limit_seconds,
            mip_gap=body.mip_gap,
            random_seed=body.random_seed,
            alns_iterations=body.alns_iterations,
            no_improvement_limit=body.no_improvement_limit,
            destroy_fraction=body.destroy_fraction,
            rolling_current_min=hhmm_to_min(body.current_time),
            thesis_mode=(
                solver_mode in {"thesis_mode", "mode_milp_only"}
                or phase_token == "phase3_two_stage"
            ),
            debug_mode=is_diagnostic_mode,
            diagnostic_mode=solver_mode == "diagnostic",
            research_run=bool(body.research_run),
            allow_postsolve_repair=solver_mode == "debug_mode",
            phase=phase_token,
            requested_phase_token=solver_mode,
            requested_phase=requested_phase,
            resolved_phase=phase_token,
            executed_phase=phase_token,
        )
        problem = ProblemBuilder().build_from_scenario(
            scenario,
            depot_id=depot_id,
            service_id=service_id,
            config=config,
            planning_days=max(
                int(((scenario.get("simulation_config") or {}).get("planning_days") or 1)),
                1,
            ),
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
        rolling_reoptimizer = RollingReoptimizer()
        strategy = str(body.reoptimization_strategy or "generic").strip().lower()
        serialized_day_ahead: Optional[Dict[str, Any]] = None
        if strategy == "day_ahead_hourly":
            if not isinstance(prior_optimization_result, dict):
                raise ValueError(
                    "day_ahead_hourly requires a persisted day-ahead optimization result"
                )
            _validate_day_ahead_result_contract(
                prior_optimization_result,
                scenario_id=scenario_id,
                prepared_input_id=prepared_input_id,
                service_id=service_id,
                depot_id=depot_id,
            )
            serialized_day_ahead = prior_optimization_result.get(
                "canonical_solver_result"
            )
            if not isinstance(serialized_day_ahead, dict):
                raise ValueError(
                    "Persisted optimization result has no canonical day-ahead assignment"
                )
            day_ahead_plan = assignment_plan_from_serialized_result(
                problem,
                serialized_day_ahead,
            )
            result = rolling_reoptimizer.reoptimize_charging_hour(
                problem,
                day_ahead_plan,
                config=config,
                current_min=hhmm_to_min(body.current_time),
                actual_soc=body.actual_soc,
                actual_bess_soc_kwh=body.actual_bess_soc_kwh,
                observed_on_peak_kw_by_depot=(
                    body.observed_on_peak_kw_by_depot
                ),
                observed_off_peak_kw_by_depot=(
                    body.observed_off_peak_kw_by_depot
                ),
                execution_minutes=body.execution_minutes,
                bess_terminal_policy=body.bess_terminal_policy,
            )
        elif strategy == "generic":
            result = rolling_reoptimizer.reoptimize(
                problem,
                config=config,
                current_min=hhmm_to_min(body.current_time),
                actual_soc=body.actual_soc,
                actual_bess_soc_kwh=body.actual_bess_soc_kwh,
            )
        else:
            raise ValueError(
                "reoptimization_strategy must be 'generic' or 'day_ahead_hourly'"
            )
        payload = {
            "scenario_id": scenario_id,
            "scope": {"serviceId": service_id, "depotId": depot_id},
            "prepared_input_id": prepared_input_id,
            "reoptimized": True,
            "reoptimization_request": {
                "current_time": body.current_time,
                "actual_soc": dict(body.actual_soc),
                "actual_bess_soc_kwh": dict(body.actual_bess_soc_kwh),
                "observed_on_peak_kw_by_depot": dict(
                    body.observed_on_peak_kw_by_depot
                ),
                "observed_off_peak_kw_by_depot": dict(
                    body.observed_off_peak_kw_by_depot
                ),
                "actual_location_node_id": dict(body.actual_location_node_id),
                "delays": [item.model_dump() for item in body.delays],
                "reoptimization_strategy": strategy,
                "execution_minutes": body.execution_minutes,
                "bess_terminal_policy": body.bess_terminal_policy,
            },
            **ResultSerializer.serialize_result(result),
        }
        if serialized_day_ahead is not None:
            # Keep the verified day-ahead assignment available for the next
            # hourly update; the newly optimized charging schedule must not
            # become the source of vehicle-trip assignment truth.
            payload["canonical_solver_result"] = serialized_day_ahead
            payload["day_ahead_reference"] = {
                "scenario_id": scenario_id,
                "prepared_input_id": prepared_input_id,
                "service_id": service_id,
                "depot_id": depot_id,
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
    request = body or RunOptimizationBody()
    timestep_min = _request_timestep_min(request.timestep_min, request.time_step_min)
    # Apply the request's depot/service to the persisted scope BEFORE building the
    # run preparation, so that resolve_scope sees the correct depotId/serviceId
    # even when the scenario's dispatch_scope was left empty by a previous operation.
    # Skip if a prepared_input_id was supplied — the prepare step already fixed the scope,
    # and persisting again would change the scenario_hash and invalidate the prepared input.
    if (request.service_id or request.depot_id) and not request.prepared_input_id:
        _resolve_dispatch_scope(
            scenario_id,
            service_id=request.service_id,
            depot_id=request.depot_id,
            persist=True,
        )
    scenario = store.get_scenario_document_shallow(scenario_id)
    if timestep_min is not None and not request.prepared_input_id:
        _apply_timestep_min_to_scenario(scenario, timestep_min)
        store.set_field(scenario_id, "simulation_config", scenario["simulation_config"])
    prep = get_or_build_run_preparation(
        scenario=scenario,
        built_dir=Path(_app_state.get("built_dir") or "data/built/tokyu_core"),
        scenarios_dir=_prepared_inputs_root(),
        routes_df=_app_state.get("routes_df"),
        force_rebuild=bool(request.force_reprepare),
    )
    if not prep.is_valid:
        error_code = AppErrorCode(prep.error_code) if prep.error_code else AppErrorCode.SCENARIO_INCOMPLETE
        raise HTTPException(
            status_code=422 if prep.error_code else 500,
            detail=make_error(
                error_code,
                f"Run preparation failed: {prep.error}",
                preparedInputId=prep.prepared_input_id,
                scopeSummary=prep.scope_summary,
            ),
        )
    _require_nonempty_prepared_scope(prep, action="Optimization preflight")
    _preflight_weather_proxy_request(
        scenario=scenario,
        enable_weather_operation_policy=request.enableWeatherOperationPolicy,
        weather_proxy_forecast_path=request.weatherProxyForecastPath,
    )
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
    job = job_store.create_job(execution_model=_executor_mode())
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
            request.prepared_input_id,
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
            timestep_min,
            request.enableWeatherOperationPolicy,
            request.weatherProxyForecastPath,
            request.research_run,
            request.stage1_time_limit_seconds,
            request.stage2_time_limit_seconds,
            request.stage1_best_obj_stop_enabled,
            request.gurobi_threads,
            request.model_dump(),
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
    timestep_min = _request_timestep_min(body.timestep_min, body.time_step_min)
    scenario = store.get_scenario_document_shallow(scenario_id)
    if timestep_min is not None and not body.prepared_input_id:
        _apply_timestep_min_to_scenario(scenario, timestep_min)
        store.set_field(scenario_id, "simulation_config", scenario["simulation_config"])
    prep = get_or_build_run_preparation(
        scenario=scenario,
        built_dir=Path(_app_state.get("built_dir") or "data/built/tokyu_core"),
        scenarios_dir=_prepared_inputs_root(),
        routes_df=_app_state.get("routes_df"),
    )
    if not prep.is_valid:
        error_code = AppErrorCode(prep.error_code) if prep.error_code else AppErrorCode.SCENARIO_INCOMPLETE
        raise HTTPException(
            status_code=422 if prep.error_code else 500,
            detail=make_error(
                error_code,
                f"Run preparation failed: {prep.error}",
                preparedInputId=prep.prepared_input_id,
                scopeSummary=prep.scope_summary,
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
    job = job_store.create_job(execution_model=_executor_mode())
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
