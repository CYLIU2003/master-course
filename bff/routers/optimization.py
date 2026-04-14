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
import csv
import shutil
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
from pydantic import BaseModel

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
from bff.services.run_preparation import (
    get_or_build_run_preparation,
    load_prepared_input,
    materialize_scenario_from_prepared_input,
)
from bff.store import job_store, output_paths, scenario_store as store
from src.dispatch.models import hhmm_to_min
from src.optimization import (
    OptimizationConfig,
    OptimizationEngine,
    OptimizationMode,
    ProblemBuilder,
    ResultSerializer,
)
from src.optimization.rolling.reoptimizer import RollingReoptimizer
from src.run_output_layout import allocate_run_dir
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
    force_reprepare: bool = False
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
            "mode_milp_only",
            "mode_alns_only",
            "mode_ga_only",
            "mode_abc_only",
            "mode_hybrid",
        ],
        "mode_aliases": {
            "milp": "mode_milp_only",
            "exact": "mode_milp_only",
            "alns": "mode_alns_only",
            "heuristic": "mode_alns_only",
            "ga": "mode_ga_only",
            "genetic": "mode_ga_only",
            "abc": "mode_abc_only",
            "colony": "mode_abc_only",
            "hybrid": "mode_hybrid",
        },
        "deprecated_modes": {
            "mode_alns_milp": "mode_hybrid (auto-routed)",
            "thesis_mode": "BLOCKED - no longer supported",
            "mode_a_journey_charge": "BLOCKED - no longer supported",
            "mode_b_optimistic": "BLOCKED - no longer supported",
        },
        "default_mode": "mode_milp_only",
        "authoritative_engine": "canonical (src/optimization/)",
        "supports_reoptimization": True,
        "max_concurrent_jobs": 1,
        "execution_model": f"{_executor_mode()}_pool",
        "notes": [
            "All supported modes use the canonical optimization engine (src/optimization/).",
            "Legacy thesis modes have been deprecated for consistency and maintainability.",
            "mode_alns_milp is auto-routed to mode_hybrid (ALNS+MILP hybrid).",
            "Optimization runs against canonical CanonicalOptimizationProblem built from scenario.",
            "Dispatch artifacts can be rebuilt before solve when requested.",
            "Results are persisted to the scenario snapshot; job state is not.",
            "Optimization/re-optimization runs in a dedicated executor so API polling stays responsive.",
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


def _persist_json_outputs(output_dir: str, payloads: Dict[str, Dict[str, Any]]) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (output_path / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _run_stamp() -> str:
    return datetime.now().strftime("run_%Y%m%d_%H%M")


def _service_date_for_output(scenario: Dict[str, Any]) -> str:
    sim = dict(scenario.get("simulation_config") or {})
    primary = str(sim.get("service_date") or "").strip()
    if primary:
        return primary[:10]
    dates = [str(v).strip() for v in list(sim.get("service_dates") or []) if str(v).strip()]
    if dates:
        return dates[0][:10]
    return datetime.now().strftime("%Y-%m-%d")


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


def _write_csv_rows(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


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


def _canonical_energy_flow_context(problem, plan) -> Dict[str, Any]:
    timestep_min = max(int(getattr(problem.scenario, "timestep_min", 0) or 0), 1)
    timestep_h = timestep_min / 60.0

    raw_grid_to_bus = _normalize_depot_slot_mapping(getattr(plan, "grid_to_bus_kwh_by_depot_slot", {}))
    raw_pv_to_bus = _normalize_depot_slot_mapping(getattr(plan, "pv_to_bus_kwh_by_depot_slot", {}))
    raw_bess_to_bus = _normalize_depot_slot_mapping(getattr(plan, "bess_to_bus_kwh_by_depot_slot", {}))
    raw_pv_to_bess = _normalize_depot_slot_mapping(getattr(plan, "pv_to_bess_kwh_by_depot_slot", {}))
    raw_grid_to_bess = _normalize_depot_slot_mapping(getattr(plan, "grid_to_bess_kwh_by_depot_slot", {}))
    raw_pv_curtail = _normalize_depot_slot_mapping(getattr(plan, "pv_curtail_kwh_by_depot_slot", {}))
    raw_bess_soc = _normalize_depot_slot_mapping(getattr(plan, "bess_soc_kwh_by_depot_slot", {}))
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

    return {
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
        "contract_over_limit_kwh_by_depot_slot": raw_contract_over_limit,
        "pv_generation_kwh_by_depot_slot": pv_generation_kwh_by_depot_slot,
        "depot_limit_kw": depot_limit_kw,
        "price_by_slot": price_by_slot,
        "demand_flag_by_slot": demand_flag_by_slot,
        "source_provenance_exact": not derived_from_charging_slots,
        "source_provenance_note": provenance_note,
        "derived_from_charging_slots": derived_from_charging_slots,
        "derived_depots": sorted(derived_depots),
    }


def _canonical_charging_output_payload(problem, engine_result) -> Dict[str, Any]:
    plan = engine_result.plan
    flow_ctx = _canonical_energy_flow_context(problem, plan)
    timestep_h = float(flow_ctx["timestep_h"] or 1.0)
    breakdown = dict(engine_result.cost_breakdown or {})
    penalty_enabled = bool(
        (dict(getattr(plan, "metadata", {}) or {}).get("enable_contract_overage_penalty"))
        if getattr(plan, "metadata", None)
        else dict(engine_result.solver_metadata or {}).get("enable_contract_overage_penalty", True)
    )
    raw_penalty_yen_per_kwh = (
        dict(getattr(plan, "metadata", {}) or {}).get("contract_overage_penalty_yen_per_kwh")
        if getattr(plan, "metadata", None)
        else dict(engine_result.solver_metadata or {}).get("contract_overage_penalty_yen_per_kwh", 0.0)
    )
    penalty_yen_per_kwh = float(raw_penalty_yen_per_kwh or 0.0)

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
            pv_curtail = float((flow_ctx["pv_curtail_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            bess_soc = float((flow_ctx["bess_soc_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            contract_over_limit_kwh = float((flow_ctx["contract_over_limit_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            pv_generation_kwh = float((flow_ctx["pv_generation_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            contract_limit_kw = float((flow_ctx["depot_limit_kw"].get(depot_id, 0.0)) or 0.0)
            grid_import_total_kwh = grid_to_bus + grid_to_bess
            total_bus_charge_kwh = grid_to_bus + pv_to_bus + bess_to_bus
            total_bess_charge_kwh = pv_to_bess + grid_to_bess
            grid_import_kw = grid_import_total_kwh / timestep_h if timestep_h > 0.0 else 0.0
            total_charge_kw = total_bus_charge_kwh / timestep_h if timestep_h > 0.0 else 0.0
            if contract_over_limit_kwh <= 1.0e-9 and contract_limit_kw > 0.0:
                contract_limit_kwh = contract_limit_kw * timestep_h
                contract_over_limit_kwh = max(grid_import_total_kwh - contract_limit_kwh, 0.0)
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
                    "pv_generation_kwh": pv_generation_kwh,
                    "bess_soc_kwh": bess_soc,
                    "grid_import_total_kwh": grid_import_total_kwh,
                    "grid_import_kw": grid_import_kw,
                    "total_bus_charge_kwh": total_bus_charge_kwh,
                    "total_bess_charge_kwh": total_bess_charge_kwh,
                    "total_charge_kw": total_charge_kw,
                    "contract_limit_kw": contract_limit_kw,
                    "contract_over_limit_kwh": contract_over_limit_kwh,
                    "contract_over_limit_kw": contract_over_limit_kw,
                    "contract_limit_exceeded": contract_over_limit_kwh > 1.0e-9,
                    "energy_price_yen_per_kwh": float((flow_ctx["price_by_slot"].get(slot_idx, 0.0)) or 0.0),
                    "demand_charge_window_flag": bool(flow_ctx["demand_flag_by_slot"].get(slot_idx, False)),
                    "source_provenance_exact": bool(flow_ctx["source_provenance_exact"]),
                }
            )

        contract_overage_cost = contract_over_total * penalty_yen_per_kwh if penalty_enabled else 0.0
        per_depot.append(
            {
                "depot_id": depot_id,
                "source_provenance_exact": bool(flow_ctx["source_provenance_exact"]) and depot_id not in set(flow_ctx["derived_depots"]),
                "grid_to_bus_kwh": grid_to_bus_total,
                "pv_to_bus_kwh": pv_to_bus_total,
                "bess_to_bus_kwh": bess_to_bus_total,
                "pv_to_bess_kwh": pv_to_bess_total,
                "grid_to_bess_kwh": grid_to_bess_total,
                "pv_curtail_kwh": pv_curtail_total,
                "grid_import_total_kwh": grid_to_bus_total + grid_to_bess_total,
                "total_bus_charge_kwh": grid_to_bus_total + pv_to_bus_total + bess_to_bus_total,
                "total_bess_charge_kwh": pv_to_bess_total + grid_to_bess_total,
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
            }
        )

    overall_grid_import_total_kwh = sum(float(row["grid_import_total_kwh"]) for row in per_depot)
    overall_contract_over_kwh = sum(float(row["contract_over_limit_kwh"]) for row in per_depot)
    overall_contract_over_cost = (
        float(breakdown.get("contract_overage_cost", 0.0) or 0.0)
        if breakdown
        else overall_contract_over_kwh * penalty_yen_per_kwh
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
            "source_provenance_exact": bool(flow_ctx["source_provenance_exact"]),
            "source_provenance_note": str(flow_ctx["source_provenance_note"] or ""),
            "depots": per_depot,
            "totals": {
                "grid_to_bus_kwh": sum(float(row["grid_to_bus_kwh"]) for row in per_depot),
                "pv_to_bus_kwh": sum(float(row["pv_to_bus_kwh"]) for row in per_depot),
                "bess_to_bus_kwh": sum(float(row["bess_to_bus_kwh"]) for row in per_depot),
                "pv_to_bess_kwh": sum(float(row["pv_to_bess_kwh"]) for row in per_depot),
                "grid_to_bess_kwh": sum(float(row["grid_to_bess_kwh"]) for row in per_depot),
                "pv_curtail_kwh": sum(float(row["pv_curtail_kwh"]) for row in per_depot),
                "grid_import_total_kwh": overall_grid_import_total_kwh,
                "total_bus_charge_kwh": sum(float(row["total_bus_charge_kwh"]) for row in per_depot),
                "total_bess_charge_kwh": sum(float(row["total_bess_charge_kwh"]) for row in per_depot),
                "peak_grid_import_kw_any_depot": overall_peak_grid_kw,
                "peak_grid_import_kw_all_depots": overall_by_slot_grid_peak,
                "peak_total_charge_kw_any_depot": overall_peak_total_charge_kw,
                "peak_total_charge_kw_all_depots": overall_by_slot_charge_peak,
                "contract_over_limit_kwh": overall_contract_over_kwh,
                "contract_limit_exceeded": overall_contract_over_kwh > 1.0e-9,
                "contract_overage_penalty_enabled": penalty_enabled,
                "contract_overage_penalty_yen_per_kwh": penalty_yen_per_kwh,
                "contract_overage_cost_jpy": overall_contract_over_cost,
                "demand_charge_cost_jpy": float(breakdown.get("demand_cost", 0.0) or 0.0),
                "grid_purchase_cost_jpy": float(breakdown.get("grid_purchase_cost", 0.0) or 0.0),
                "bess_discharge_cost_jpy": float(breakdown.get("bess_discharge_cost", 0.0) or 0.0),
                "electricity_cost_jpy": float(breakdown.get("energy_cost", 0.0) or 0.0),
            },
        },
        "rows": rows,
    }


def _persist_rich_run_outputs(
    *,
    run_dir: Path,
    scenario: Dict[str, Any],
    optimization_result: Dict[str, Any],
    optimization_audit: Dict[str, Any],
    result_payload: Dict[str, Any],
    sim_payload: Optional[Dict[str, Any]],
    canonical_solver_result: Optional[Dict[str, Any]],
    graph_source_dir: Optional[Path] = None,
    charging_summary: Optional[Dict[str, Any]] = None,
    charging_flow_payload: Optional[Dict[str, Any]] = None,
) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)

    unit_map = {
        "objective_value": "JPY",
        "solve_time_seconds": "s",
        "energy_cost": "JPY",
        "demand_charge": "JPY",
        "vehicle_cost": "JPY",
        "driver_cost": "JPY",
        "fuel_cost": "JPY",
        "penalty_unserved": "JPY",
        "total_cost": "JPY",
        "co2_cost": "JPY",
        "total_co2_kg": "kg-CO2",
        "grid_to_bus_kwh": "kWh",
        "pv_to_bus_kwh": "kWh",
        "grid_to_bess_kwh": "kWh",
        "bess_to_bus_kwh": "kWh",
        "pv_to_bess_kwh": "kWh",
        "pv_curtail_kwh": "kWh",
        "grid_import_total_kwh": "kWh",
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

    summary = {
        "scenario_id": optimization_result.get("scenario_id"),
        "mode": optimization_result.get("mode"),
        "solver_status": optimization_result.get("solver_status"),
        "objective_mode": optimization_result.get("objective_mode"),
        "objective_value": optimization_result.get("objective_value"),
        "objective_value_unit": "JPY",
        "solve_time_seconds": optimization_result.get("solve_time_seconds"),
        "solve_time_unit": "s",
        "trip_count_served": (optimization_result.get("summary") or {}).get("trip_count_served"),
        "trip_count_unserved": (optimization_result.get("summary") or {}).get("trip_count_unserved"),
        "vehicle_count_used": (optimization_result.get("summary") or {}).get("vehicle_count_used"),
        "same_day_depot_cycles_enabled": (optimization_result.get("summary") or {}).get("same_day_depot_cycles_enabled"),
        "max_depot_cycles_per_vehicle_per_day": (optimization_result.get("summary") or {}).get("max_depot_cycles_per_vehicle_per_day"),
        "vehicle_fragment_counts": (optimization_result.get("summary") or {}).get("vehicle_fragment_counts"),
        "vehicles_with_multiple_fragments": (optimization_result.get("summary") or {}).get("vehicles_with_multiple_fragments"),
        "max_fragments_observed": (optimization_result.get("summary") or {}).get("max_fragments_observed"),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
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
    (run_dir / "simulation_conditions.json").write_text(
        json.dumps(sim_cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Legacy-compatible simulation condition tables.
    vehicles = list(scenario.get("vehicles") or [])
    vehicle_cost_rows: List[Dict[str, Any]] = []
    for vehicle in vehicles:
        if not isinstance(vehicle, dict):
            continue
        vehicle_cost_rows.append(
            {
                "vehicle_id": vehicle.get("vehicle_id") or vehicle.get("id") or vehicle.get("name") or "",
                "vehicle_type": vehicle.get("vehicle_type") or vehicle.get("type") or "",
                "fixed_use_cost_yen": vehicle.get("fixed_use_cost_yen") or vehicle.get("fixed_cost_yen") or 0.0,
                "fuel_cost_coeff_yen_per_liter": vehicle.get("fuel_cost_coeff_yen_per_liter") or vehicle.get("fuel_price_yen_per_liter") or 0.0,
                "battery_degradation_cost_coeff_yen_per_kwh": vehicle.get("battery_degradation_cost_coeff_yen_per_kwh") or 0.0,
                "co2_emission_coeff_kg_per_liter": vehicle.get("co2_emission_coeff_kg_per_liter") or 0.0,
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

    slot_count = int(sim_cfg.get("planning_horizon_hours") or 24)
    timestep = int(sim_cfg.get("time_step_min") or sim_cfg.get("timestep_min") or 60)
    if timestep > 0:
        slot_count = max(slot_count * 60 // timestep, 1)
    tou_price_series = list(sim_cfg.get("tou_prices_yen_per_kwh") or [])
    default_price = float(sim_cfg.get("grid_energy_price_yen_per_kwh") or 0.0)
    grid_co2_series = list(sim_cfg.get("grid_co2_factor_kg_per_kwh") or [])
    base_load_series = list(sim_cfg.get("base_load_kw") or [])
    site_id = str(sim_cfg.get("depot_id") or "depot_A")
    tou_rows: List[Dict[str, Any]] = []
    for time_idx in range(slot_count):
        tou_rows.append(
            {
                "site_id": site_id,
                "time_idx": time_idx,
                "grid_energy_price_yen_per_kwh": (
                    tou_price_series[time_idx] if time_idx < len(tou_price_series) else default_price
                ),
                "sell_back_price_yen_per_kwh": 0.0,
                "base_load_kw": base_load_series[time_idx] if time_idx < len(base_load_series) else 0.0,
                "grid_co2_factor_kg_per_kwh": grid_co2_series[time_idx] if time_idx < len(grid_co2_series) else 0.0,
            }
        )
    _write_csv_rows(
        run_dir / "simulation_conditions_tou_prices.csv",
        tou_rows,
        [
            "site_id",
            "time_idx",
            "grid_energy_price_yen_per_kwh",
            "sell_back_price_yen_per_kwh",
            "base_load_kw",
            "grid_co2_factor_kg_per_kwh",
        ],
    )

    contract_rows = [
        {
            "site_id": site_id,
            "site_type": "depot",
            "contract_demand_limit_kw": float(sim_cfg.get("contract_demand_limit_kw") or 0.0),
            "grid_import_limit_kw": float(sim_cfg.get("grid_import_limit_kw") or 0.0),
            "site_transformer_limit_kw": float(sim_cfg.get("site_transformer_limit_kw") or 0.0),
        }
    ]
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

    co2_rows = [
        {"component": "engine_bus_co2_kg", "value": float(cost_breakdown.get("engine_bus_co2_kg", 0.0) or 0.0)},
        {"component": "power_generation_co2_kg", "value": float(cost_breakdown.get("power_generation_co2_kg", 0.0) or 0.0)},
        {"component": "total_co2_kg", "value": float(cost_breakdown.get("total_co2_kg", 0.0) or 0.0)},
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
                "grid_to_bus_kwh",
                "pv_to_bus_kwh",
                "bess_to_bus_kwh",
                "pv_to_bess_kwh",
                "grid_to_bess_kwh",
                "pv_curtail_kwh",
                "grid_import_total_kwh",
                "total_bus_charge_kwh",
                "total_bess_charge_kwh",
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
                "pv_generation_kwh",
                "bess_soc_kwh",
                "grid_import_total_kwh",
                "grid_import_kw",
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
            ],
        )
    else:
        grid_to_bus_kwh = float(cost_breakdown.get("grid_to_bus_kwh", 0.0) or 0.0)
        grid_to_bess_kwh = float(cost_breakdown.get("grid_to_bess_kwh", 0.0) or 0.0)
        grid_import_total_kwh = grid_to_bus_kwh + grid_to_bess_kwh
        fallback_rows = [
            {"metric": "grid_to_bus_kwh", "value": grid_to_bus_kwh, "unit": "kWh"},
            {"metric": "grid_to_bess_kwh", "value": grid_to_bess_kwh, "unit": "kWh"},
            {"metric": "grid_import_total_kwh", "value": grid_import_total_kwh, "unit": "kWh"},
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
        site_rows = [
            {"metric": "grid_to_bus_kwh", "value": float(totals.get("grid_to_bus_kwh", 0.0) or 0.0), "unit": "kWh"},
            {"metric": "pv_to_bus_kwh", "value": float(totals.get("pv_to_bus_kwh", 0.0) or 0.0), "unit": "kWh"},
            {"metric": "bess_to_bus_kwh", "value": float(totals.get("bess_to_bus_kwh", 0.0) or 0.0), "unit": "kWh"},
            {"metric": "pv_to_bess_kwh", "value": float(totals.get("pv_to_bess_kwh", 0.0) or 0.0), "unit": "kWh"},
            {"metric": "grid_to_bess_kwh", "value": float(totals.get("grid_to_bess_kwh", 0.0) or 0.0), "unit": "kWh"},
            {"metric": "pv_curtail_kwh", "value": float(totals.get("pv_curtail_kwh", 0.0) or 0.0), "unit": "kWh"},
            {"metric": "grid_import_total_kwh", "value": float(totals.get("grid_import_total_kwh", 0.0) or 0.0), "unit": "kWh"},
            {"metric": "peak_grid_import_kw_all_depots", "value": float(totals.get("peak_grid_import_kw_all_depots", 0.0) or 0.0), "unit": "kW"},
            {"metric": "contract_over_limit_kwh", "value": float(totals.get("contract_over_limit_kwh", 0.0) or 0.0), "unit": "kWh"},
            {"metric": "contract_overage_cost_jpy", "value": float(totals.get("contract_overage_cost_jpy", 0.0) or 0.0), "unit": "JPY"},
            {"metric": "demand_charge_cost_jpy", "value": float(totals.get("demand_charge_cost_jpy", 0.0) or 0.0), "unit": "JPY"},
            {"metric": "grid_purchase_cost_jpy", "value": float(totals.get("grid_purchase_cost_jpy", 0.0) or 0.0), "unit": "JPY"},
            {"metric": "bess_discharge_cost_jpy", "value": float(totals.get("bess_discharge_cost_jpy", 0.0) or 0.0), "unit": "JPY"},
            {"metric": "electricity_cost_jpy", "value": float(totals.get("electricity_cost_jpy", 0.0) or 0.0), "unit": "JPY"},
            {"metric": "contract_limit_exceeded", "value": bool(totals.get("contract_limit_exceeded", False)), "unit": "flag"},
        ]
    else:
        grid_to_bus_kwh = float(cost_breakdown.get("grid_to_bus_kwh", 0.0) or 0.0)
        grid_to_bess_kwh = float(cost_breakdown.get("grid_to_bess_kwh", 0.0) or 0.0)
        grid_import_total_kwh = grid_to_bus_kwh + grid_to_bess_kwh
        site_rows = [
            {"metric": "grid_to_bus_kwh", "value": grid_to_bus_kwh, "unit": "kWh"},
            {"metric": "grid_to_bess_kwh", "value": grid_to_bess_kwh, "unit": "kWh"},
            {"metric": "grid_import_total_kwh", "value": grid_import_total_kwh, "unit": "kWh"},
        ]
    _write_csv_rows(run_dir / "site_power_balance.csv", site_rows, ["metric", "value", "unit"])

    kpi_summary = {
        "total_cost_jpy": float(cost_breakdown.get("total_cost", 0.0) or 0.0),
        "electricity_cost_jpy": float(cost_breakdown.get("energy_cost", 0.0) or 0.0),
        "grid_import_total_kwh": float(
            dict((charging_summary_payload or {}).get("totals") or {}).get("grid_import_total_kwh", 0.0)
            or (float(cost_breakdown.get("grid_to_bus_kwh", 0.0) or 0.0) + float(cost_breakdown.get("grid_to_bess_kwh", 0.0) or 0.0))
        ),
        "served_trip_count": int(summary_payload.get("trip_count_served") or 0),
        "unserved_trip_count": int(summary_payload.get("trip_count_unserved") or 0),
        "solver_runtime_sec": float(optimization_result.get("solve_time_seconds") or 0.0),
    }
    if charging_summary_payload:
        totals = dict(charging_summary_payload.get("totals") or {})
        kpi_summary.update(
            {
                "pv_to_bus_kwh": float(totals.get("pv_to_bus_kwh", 0.0) or 0.0),
                "bess_to_bus_kwh": float(totals.get("bess_to_bus_kwh", 0.0) or 0.0),
                "grid_to_bess_kwh": float(totals.get("grid_to_bess_kwh", 0.0) or 0.0),
                "pv_to_bess_kwh": float(totals.get("pv_to_bess_kwh", 0.0) or 0.0),
                "contract_over_limit_kwh": float(totals.get("contract_over_limit_kwh", 0.0) or 0.0),
                "contract_overage_cost_jpy": float(totals.get("contract_overage_cost_jpy", 0.0) or 0.0),
                "demand_charge_cost_jpy": float(totals.get("demand_charge_cost_jpy", 0.0) or 0.0),
                "peak_grid_import_kw_all_depots": float(totals.get("peak_grid_import_kw_all_depots", 0.0) or 0.0),
                "contract_limit_exceeded": bool(totals.get("contract_limit_exceeded", False)),
                "charging_source_provenance_exact": bool(charging_summary_payload.get("source_provenance_exact", False)),
            }
        )
    (run_dir / "kpi_summary.json").write_text(
        json.dumps(kpi_summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    exp_report = dict(optimization_result.get("experiment_report") or {})
    md_path = exp_report.get("md_path")
    if isinstance(md_path, str) and md_path.strip():
        src_md = Path(md_path)
        if src_md.exists():
            shutil.copy2(src_md, run_dir / "experiment_report.md")

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

    run_manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": sorted(
            [p.relative_to(run_dir).as_posix() for p in run_dir.rglob("*") if p.is_file()]
        ),
        "units": unit_map,
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
        },
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


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

    for vehicle_id, duties in duties_by_vehicle.items():
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


def _canonical_output_base_date(problem, graph_context: Optional[Dict[str, Any]]) -> date:
    service_date = str((problem.metadata or {}).get("service_date") or "").strip()
    if service_date:
        try:
            return datetime.fromisoformat(service_date[:10]).date()
        except ValueError:
            pass
    return datetime.now().date()


def _canonical_datetime_from_min(base_date, minute_from_midnight: int) -> datetime:
    return datetime.combine(base_date, datetime.min.time()) + timedelta(minutes=int(minute_from_midnight))


def _canonical_horizon_start_min(problem) -> int:
    try:
        hh_text, mm_text = str(getattr(problem.scenario, "horizon_start", None) or "00:00").split(":", 1)
        return int(hh_text) * 60 + int(mm_text)
    except ValueError:
        return 0


def _canonical_slot_datetime(problem, base_date: date, slot_index: int) -> datetime:
    timestep_min = max(int(getattr(problem.scenario, "timestep_min", 0) or 0), 1)
    absolute_min = _canonical_horizon_start_min(problem) + int(slot_index) * timestep_min
    return _canonical_datetime_from_min(base_date, absolute_min)


def _canonical_deadhead_distance_km(problem, deadhead_min: int) -> float:
    try:
        speed_kmh = float((problem.metadata or {}).get("deadhead_speed_kmh") or 18.0)
    except (TypeError, ValueError):
        speed_kmh = 18.0
    return max(float(deadhead_min or 0), 0.0) * max(speed_kmh, 0.0) / 60.0


def _canonical_estimated_deadhead_energy_kwh(
    problem,
    *,
    deadhead_min: int,
    trip_energy_kwh: float,
    trip_distance_km: float,
) -> float:
    if deadhead_min <= 0:
        return 0.0
    safe_distance = max(float(trip_distance_km or 0.0), 1.0e-6)
    energy_per_km = max(float(trip_energy_kwh or 0.0), 0.0) / safe_distance
    return _canonical_deadhead_distance_km(problem, deadhead_min) * energy_per_km


def _canonical_vehicle_initial_soc_kwh(vehicle: Any) -> float:
    capacity = max(float(getattr(vehicle, "battery_capacity_kwh", 0.0) or 0.0), 0.0)
    value = getattr(vehicle, "initial_soc", None)
    if value is None:
        return capacity
    parsed = float(value)
    if parsed <= 1.0 and capacity > 0.0:
        return parsed * capacity
    return parsed


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
    for duty in engine_result.plan.duties:
        vehicle_id = str(engine_result.plan.vehicle_id_for_duty(duty.duty_id))
        vehicle = vehicle_by_id.get(vehicle_id)
        duty_legs = list(duty.legs)
        for index, leg in enumerate(duty_legs):
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
    rows.sort(key=lambda row: str(row.get("trip_id", "")))
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

    slot_values_by_depot: Dict[str, Dict[int, Dict[str, float]]] = defaultdict(dict)
    for depot_id in list(flow_ctx["depot_ids"]):
        for slot_idx in range(slot_count):
            grid_to_bus = float((flow_ctx["grid_to_bus_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            pv_to_bus = float((flow_ctx["pv_to_bus_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            bess_to_bus = float((flow_ctx["bess_to_bus_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            pv_to_bess = float((flow_ctx["pv_to_bess_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            grid_to_bess = float((flow_ctx["grid_to_bess_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            pv_curtail = float((flow_ctx["pv_curtail_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            pv_generation = float((flow_ctx["pv_generation_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            contract_over_limit_kwh = float((flow_ctx["contract_over_limit_kwh_by_depot_slot"].get(depot_id, {}) or {}).get(slot_idx, 0.0) or 0.0)
            contract_limit_kw = float((flow_ctx["depot_limit_kw"].get(depot_id, 0.0)) or 0.0)
            if contract_over_limit_kwh <= 1.0e-9 and contract_limit_kw > 0.0:
                contract_over_limit_kwh = max((grid_to_bus + grid_to_bess) - (contract_limit_kw * timestep_h), 0.0)
            slot_values_by_depot[depot_id][slot_idx] = {
                "grid_import_kw": (grid_to_bus + grid_to_bess) / timestep_h,
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
                "contract_limit_kw": contract_limit_kw,
                "contract_over_limit_kwh": contract_over_limit_kwh,
                "contract_over_limit_kw": contract_over_limit_kwh / timestep_h if timestep_h > 0.0 else 0.0,
            }

    horizon_min = slot_count * timestep_min
    five_min_points = list(range(0, max(horizon_min, 1), 5))
    rows: List[Dict[str, Any]] = []
    for depot_id, slot_map in slot_values_by_depot.items():
        peak_grid = max((values.get("grid_import_kw", 0.0) for values in slot_map.values()), default=0.0)
        for minute in five_min_points:
            slot_idx = min(int(minute // timestep_min), max(slot_count - 1, 0))
            values = slot_map.get(slot_idx, {})
            timestamp = (
                datetime.combine(base_date, datetime.min.time(), timezone(timedelta(hours=9)))
                + timedelta(minutes=_canonical_horizon_start_min(problem) + minute)
            ).isoformat()
            rows.append(
                {
                    "scenario_id": scenario_id,
                    "timestamp": timestamp,
                    "depot_id": depot_id,
                    "total_charge_kw": float(values.get("total_charge_kw", 0.0) or 0.0),
                    "grid_import_kw": float(values.get("grid_import_kw", 0.0) or 0.0),
                    "grid_to_bus_kwh": float(values.get("grid_to_bus_kwh", 0.0) or 0.0),
                    "pv_to_bus_kwh": float(values.get("pv_to_bus_kwh", 0.0) or 0.0),
                    "bess_to_bus_kwh": float(values.get("bess_to_bus_kwh", 0.0) or 0.0),
                    "pv_to_bess_kwh": float(values.get("pv_to_bess_kwh", 0.0) or 0.0),
                    "grid_to_bess_kwh": float(values.get("grid_to_bess_kwh", 0.0) or 0.0),
                    "pv_generation_kw": float(values.get("pv_generation_kw", 0.0) or 0.0),
                    "pv_used_for_charging_kw": float(values.get("pv_used_for_charging_kw", 0.0) or 0.0),
                    "pv_used_for_building_kw": float(values.get("pv_used_for_building_kw", 0.0) or 0.0),
                    "pv_curtailed_kw": float(values.get("pv_curtailed_kw", 0.0) or 0.0),
                    "building_load_kw": float(values.get("building_load_kw", 0.0) or 0.0),
                    "battery_storage_charge_kw": float(values.get("battery_storage_charge_kw", 0.0) or 0.0),
                    "battery_storage_discharge_kw": float(values.get("battery_storage_discharge_kw", 0.0) or 0.0),
                    "net_load_kw": float(values.get("net_load_kw", 0.0) or 0.0),
                    "contract_limit_kw": float(values.get("contract_limit_kw", 0.0) or 0.0),
                    "contract_over_limit_kwh": float(values.get("contract_over_limit_kwh", 0.0) or 0.0),
                    "contract_over_limit_kw": float(values.get("contract_over_limit_kw", 0.0) or 0.0),
                    "contract_limit_exceeded": float(values.get("contract_over_limit_kwh", 0.0) or 0.0) > 1.0e-9,
                    "demand_peak_candidate": abs(float(values.get("grid_import_kw", 0.0) or 0.0) - peak_grid) <= 1.0e-9,
                    "energy_price_yen_per_kwh": float(flow_ctx["price_by_slot"].get(slot_idx, 0.0) or 0.0),
                    "demand_charge_window_flag": bool(flow_ctx["demand_flag_by_slot"].get(slot_idx, False)),
                    "source_provenance_exact": bool(flow_ctx["source_provenance_exact"]),
                }
            )
    rows.sort(key=lambda row: (str(row.get("depot_id", "")), str(row.get("timestamp", ""))))
    return rows


def _canonical_cost_breakdown_json(*, problem, engine_result, scenario_id: str) -> Dict[str, Any]:
    breakdown = dict(engine_result.cost_breakdown or {})
    return {
        "scenario_id": scenario_id,
        "currency": "JPY",
        "total_cost": float(breakdown.get("total_cost", engine_result.objective_value) or engine_result.objective_value or 0.0),
        "components": {
            "electricity_energy_cost": float(breakdown.get("energy_cost", 0.0) or 0.0),
            "demand_charge_cost": float(breakdown.get("demand_cost", 0.0) or 0.0),
            "diesel_cost": float(breakdown.get("fuel_cost", 0.0) or 0.0),
            "co2_cost": float(breakdown.get("co2_cost", 0.0) or 0.0),
            "battery_degradation_cost": float(breakdown.get("degradation_cost", 0.0) or 0.0),
            "charger_operation_cost": 0.0,
            "pv_capex_daily_equivalent": float(breakdown.get("pv_asset_cost", 0.0) or 0.0),
            "ess_cost": float(breakdown.get("bess_asset_cost", 0.0) or 0.0),
            "unserved_trip_penalty": float(breakdown.get("unserved_penalty", 0.0) or 0.0),
        },
        "meta": {
            "objective_mode": str((engine_result.solver_metadata or {}).get("objective_mode") or problem.scenario.objective_mode or "total_cost"),
            "solver_mode": str(getattr(getattr(engine_result, "mode", None), "value", "") or ""),
            "includes_pv": bool(problem.depot_energy_assets),
        },
    }


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
        "total_cost_jpy": float(breakdown.get("total_cost", engine_result.objective_value) or engine_result.objective_value or 0.0),
        "electricity_cost_jpy": float(breakdown.get("energy_cost", 0.0) or 0.0),
        "electricity_cost_basis": "canonical_plan",
        "electricity_cost_provisional_jpy": float(breakdown.get("operating_cost_provisional_total", 0.0) or 0.0),
        "electricity_cost_charged_jpy": float(breakdown.get("realized_ev_charge_cost", breakdown.get("energy_cost", 0.0)) or 0.0),
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
    timeline_rows = _canonical_vehicle_timeline_rows(
        problem=problem,
        engine_result=engine_result,
        scenario_id=scenario_id,
        graph_context=graph_context,
    )
    trip_assignment_rows = _canonical_trip_assignment_rows(
        problem=problem,
        engine_result=engine_result,
        scenario_id=scenario_id,
        base_date=base_date,
        timeline_rows=timeline_rows,
    )
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
    graph_dir = Path(output_dir) / "graph"
    graph_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(graph_dir / "vehicle_timeline.csv", timeline_rows)
    _write_csv(graph_dir / "soc_events.csv", soc_rows)
    _write_csv(graph_dir / "depot_power_timeseries_5min.csv", depot_power_rows)
    _write_csv(graph_dir / "trip_assignment.csv", trip_assignment_rows)
    _write_csv(graph_dir / "refuel_events.csv", refuel_rows)
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
        "time_resolution_minutes": 5,
        "timezone": "Asia/Tokyo",
        "source": "canonical_assignment_plan",
        "files": [
            "vehicle_timeline.csv",
            "soc_events.csv",
            "depot_power_timeseries_5min.csv",
            "trip_assignment.csv",
            "refuel_events.csv",
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
        "soc_events_path": "graph/soc_events.csv",
        "depot_power_timeseries_path": "graph/depot_power_timeseries_5min.csv",
        "cost_breakdown_path": "graph/cost_breakdown.json",
        "kpi_summary_path": "graph/kpi_summary.json",
        "refuel_events_path": "graph/refuel_events.csv",
        "planning_days": planning_days,
    }


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
        or obj_breakdown.get("energy_cost")
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
            or obj_breakdown.get("energy_cost", 0.0)
            or 0.0
        ),
        "electricity_cost_final": final_energy_cost,
        "electricity_cost_provisional": provisional_energy,
        "electricity_cost_charged": charged_energy,
        "electricity_cost_provisional_leftover": provisional_leftover,
        "demand_charge": float(
            (sim_payload or {}).get("total_demand_charge", obj_breakdown.get("demand_charge_cost", 0.0))
            or obj_breakdown.get("demand_cost", 0.0)
            or 0.0
        ),
        "total_demand_charge": float(
            (sim_payload or {}).get("total_demand_charge", obj_breakdown.get("demand_charge_cost", 0.0))
            or obj_breakdown.get("demand_cost", 0.0)
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
        "total_fuel_cost": float(
            (sim_payload or {}).get("total_fuel_cost", obj_breakdown.get("fuel_cost", 0.0))
            or 0.0
        ),
        "battery_degradation_cost": float(
            (sim_payload or {}).get("total_degradation_cost", obj_breakdown.get("battery_degradation_cost", 0.0))
            or obj_breakdown.get("degradation_cost", 0.0)
            or 0.0
        ),
        "degradation_cost": float(
            (sim_payload or {}).get("total_degradation_cost", obj_breakdown.get("battery_degradation_cost", 0.0))
            or obj_breakdown.get("degradation_cost", 0.0)
            or 0.0
        ),
        "total_degradation_cost": float(
            (sim_payload or {}).get("total_degradation_cost", obj_breakdown.get("battery_degradation_cost", 0.0))
            or obj_breakdown.get("degradation_cost", 0.0)
            or 0.0
        ),
        "grid_purchase_cost": float(obj_breakdown.get("grid_purchase_cost", 0.0) or 0.0),
        "bess_discharge_cost": float(obj_breakdown.get("bess_discharge_cost", 0.0) or 0.0),
        "grid_import_kwh": float(obj_breakdown.get("grid_import_kwh", 0.0) or 0.0),
        "peak_grid_kw": float(obj_breakdown.get("peak_grid_kw", 0.0) or 0.0),
        "grid_to_bus_kwh": float(obj_breakdown.get("grid_to_bus_kwh", 0.0) or 0.0),
        "pv_to_bus_kwh": float(obj_breakdown.get("pv_to_bus_kwh", 0.0) or 0.0),
        "bess_to_bus_kwh": float(obj_breakdown.get("bess_to_bus_kwh", 0.0) or 0.0),
        "pv_to_bess_kwh": float(obj_breakdown.get("pv_to_bess_kwh", 0.0) or 0.0),
        "grid_to_bess_kwh": float(obj_breakdown.get("grid_to_bess_kwh", 0.0) or 0.0),
        "pv_curtail_kwh": float(obj_breakdown.get("pv_curtailed_kwh", 0.0) or obj_breakdown.get("pv_curtail_kwh", 0.0) or 0.0),
        "contract_over_limit_kwh": float(obj_breakdown.get("contract_over_limit_kwh", 0.0) or 0.0),
        "contract_overage_cost": float(obj_breakdown.get("contract_overage_cost", 0.0) or 0.0),
        "stationary_battery_degradation_cost": float(
            obj_breakdown.get("stationary_battery_degradation_cost", 0.0) or 0.0
        ),
        "pv_asset_cost": float(obj_breakdown.get("pv_asset_cost", 0.0) or 0.0),
        "bess_asset_cost": float(obj_breakdown.get("bess_asset_cost", 0.0) or 0.0),
        "total_cost_with_assets": float(obj_breakdown.get("total_cost_with_assets", 0.0) or 0.0),
        "co2_cost": float(obj_breakdown.get("emission_cost", 0.0) or obj_breakdown.get("co2_cost", 0.0) or 0.0),
        "penalty_unserved": float(obj_breakdown.get("unserved_penalty", 0.0) or 0.0),
        "total_co2_kg": float(
            (sim_payload or {}).get("total_co2_kg", obj_breakdown.get("total_co2_kg", 0.0))
            or 0.0
        ),
        "total_cost": float(
            (sim_payload or {}).get("total_operating_cost", result_payload.get("objective_value", 0.0))
            or obj_breakdown.get("total_cost", 0.0)
            or 0.0
        ),
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

        charging_summary_payload: Optional[Dict[str, Any]] = None
        charging_flow_payload: Optional[Dict[str, Any]] = None
        charging_payload_warning: Optional[str] = None

        if solver_mode in {"mode_milp_only", "mode_alns_only", "mode_ga_only", "mode_abc_only", "mode_hybrid"}:
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
            opt_config = OptimizationConfig(
                mode=opt_mode,
                time_limit_sec=time_limit_seconds,
                mip_gap=mip_gap,
                random_seed=random_seed,
                alns_iterations=alns_iterations,
                no_improvement_limit=no_improvement_limit,
                destroy_fraction=destroy_fraction,
                warm_start=True,
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
            _cb.setdefault("electricity_cost", _cb.get("energy_cost", 0.0))
            _cb.setdefault("demand_charge_cost", _cb.get("demand_cost", 0.0))
            _cb.setdefault("battery_degradation_cost", _cb.get("degradation_cost", 0.0))
            _cb.setdefault("emission_cost", _cb.get("co2_cost", 0.0))
            result_payload = {
                "status": engine_result.solver_status,
                "objective_value": engine_result.objective_value,
                "solve_time_seconds": float(smeta.get("solve_time_sec", 0.0) or solve_elapsed),
                "mip_gap": float(smeta.get("mip_gap") or 0.0),
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
            "objective_value": result_payload.get("objective_value"),
            "solve_time_seconds": result_payload.get("solve_time_seconds", 0.0),
            "mip_gap": result_payload.get("mip_gap"),
            "warnings": result_warnings,
            "infeasibility_reasons": result_infeasibility_reasons,
            "strict_coverage_precheck": strict_coverage_precheck,
            "prepared_scope_audit": prepared_scope_audit,
            "electricity_cost_basis": str(
                (sim_payload or {}).get("electricity_cost_basis") or "provisional_drive"
            ),
            "cost_breakdown": _cost_breakdown(result_payload, sim_payload),
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
                "trip_count_by_type": trip_count_by_type,
                "trip_count_served": sum(
                    len(task_ids)
                    for task_ids in (result_payload.get("assignment") or {}).values()
                ),
                "trip_count_unserved": len(result_payload.get("unserved_tasks") or []),
                "coverage_rank_primary": len(result_payload.get("unserved_tasks") or []),
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
        if charging_summary_payload is not None:
            optimization_result["charging_summary"] = charging_summary_payload
        if charging_payload_warning:
            optimization_result["charging_summary_warning"] = charging_payload_warning
        if sim_payload is not None:
            optimization_result["simulation_summary"] = sim_payload

        optimization_audit = {
            "scenario_id": scenario_id,
            "feed_context": feed_context,
            "depot_id": depot_id,
            "service_id": service_id,
            "prepared_input_id": prepared_input_id,
            "prepared_scope_summary": prepared_scope_summary,
            "scenario_hash": prepared_scenario_hash,
            "scope_hash": prepared_scope_hash,
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
        _persist_rich_run_outputs(
            run_dir=Path(output_dir),
            scenario=scenario,
            optimization_result=optimization_result,
            optimization_audit=optimization_audit,
            result_payload=result_payload,
            sim_payload=sim_payload,
            canonical_solver_result=_full_new_result,
            graph_source_dir=Path(output_dir) / "graph",
            charging_summary=charging_summary_payload,
            charging_flow_payload=charging_flow_payload,
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
                    "run_dir": output_dir,
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
    """Normalize and validate solver mode.
    
    Canonical modes use src/optimization/ engine stack.
    Legacy modes are DEPRECATED and will raise errors unless explicitly allowed.
    """
    normalized = (mode or "").strip().lower()
    alias_map = {
        "milp": "mode_milp_only",
        "exact": "mode_milp_only",
        "alns": "mode_alns_only",
        "heuristic": "mode_alns_only",
        "ga": "mode_ga_only",
        "genetic": "mode_ga_only",
        "abc": "mode_abc_only",
        "colony": "mode_abc_only",
        "hybrid": "mode_hybrid",
    }
    
    resolved_mode = alias_map.get(normalized, normalized or "mode_milp_only")
    
    # Hard-gate legacy modes
    _LEGACY_MODES = {
        "thesis_mode",
        "mode_a_journey_charge",
        "mode_a",
        "mode_b_optimistic",
        "mode_b",
        "mode_alns_milp",  # Deprecated: use mode_hybrid instead
    }
    
    if resolved_mode.lower() in _LEGACY_MODES:
        legacy_to_canonical = {
            "mode_alns_milp": "mode_hybrid",
            "thesis_mode": None,
            "mode_a_journey_charge": None,
            "mode_a": None,
            "mode_b_optimistic": None,
            "mode_b": None,
        }
        canonical_replacement = legacy_to_canonical.get(resolved_mode.lower())
        if canonical_replacement:
            import warnings
            warnings.warn(
                f"Solver mode '{mode}' is deprecated. "
                f"Auto-routing to canonical mode '{canonical_replacement}'.",
                DeprecationWarning,
                stacklevel=2,
            )
            return canonical_replacement
        else:
            raise ValueError(
                f"Solver mode '{mode}' (normalized: '{resolved_mode}') is no longer supported. "
                f"Legacy thesis modes have been deprecated. "
                f"Supported modes: mode_milp_only, mode_alns_only, mode_ga_only, mode_abc_only, mode_hybrid. "
                f"These use the canonical optimization engine (src/optimization/)."
            )
    
    return resolved_mode


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
        result = RollingReoptimizer().reoptimize(
            problem,
            config=config,
            current_min=hhmm_to_min(body.current_time),
            actual_soc=body.actual_soc,
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
    request = body or RunOptimizationBody()
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
    prep = get_or_build_run_preparation(
        scenario=scenario,
        built_dir=Path(_app_state.get("built_dir") or "data/built/tokyu_core"),
        scenarios_dir=_prepared_inputs_root(),
        routes_df=_app_state.get("routes_df"),
        force_rebuild=bool(request.force_reprepare),
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
