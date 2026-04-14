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
import os
import threading
from concurrent.futures import Executor, Future, ProcessPoolExecutor, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

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
from bff.services.experiment_reports import log_simulation_experiment
from bff.services.simulation_builder import apply_builder_configuration as _apply_builder_configuration
from bff.services.run_preparation import (
    get_or_build_run_preparation,
    load_prepared_input,
    materialize_scenario_from_prepared_input,
    solver_prepare_profile,
)
from bff.store import job_store, output_paths, scenario_store as store
from src.milp_model import MILPResult
from src.run_output_layout import allocate_run_dir
from src.pipeline.simulate import simulate_problem_data

router = APIRouter(tags=["simulation"])
_SIMULATION_EXECUTOR: Optional[Executor] = None
_SIMULATION_FUTURES: set[Future[Any]] = set()
_SIMULATION_FUTURE_LOCK = threading.RLock()


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


class RunSimulationBody(BaseModel):
    service_id: Optional[str] = None
    depot_id: Optional[str] = None
    source: str = "duties"


class PrepareTimeOfUseBandBody(BaseModel):
    start_hour: int
    end_hour: int
    price_per_kwh: float


class PrepareFleetTemplateBody(BaseModel):
    vehicle_template_id: str
    vehicle_count: int = 0
    initial_soc: Optional[float] = None
    battery_kwh: Optional[float] = None
    charge_power_kw: Optional[float] = None


class PrepareSimulationSettingsBody(BaseModel):
    vehicle_template_id: Optional[str] = None
    vehicle_count: int = 10
    initial_soc: float = 0.8
    soc_min: Optional[float] = None
    soc_max: Optional[float] = None
    battery_kwh: Optional[float] = None
    fleet_templates: list[PrepareFleetTemplateBody] = Field(default_factory=list)
    charger_count: int = 4
    charger_power_kw: float = 90.0
    use_selected_depot_vehicle_inventory: bool = True
    use_selected_depot_charger_inventory: bool = True
    disable_vehicle_acquisition_cost: bool = False
    enable_vehicle_cost: bool = True
    enable_driver_cost: bool = True
    enable_other_cost: bool = True
    cost_component_flags: Dict[str, bool] = Field(default_factory=dict)
    restrict_vehicle_types: list[str] = Field(default_factory=list)
    solver_mode: str = "mode_milp_only"
    objective_mode: str = "total_cost"
    objective_preset: Optional[str] = None
    fixed_route_band_mode: bool = False
    enable_vehicle_diagram_output: bool = True
    allow_partial_service: bool = False
    unserved_penalty: float = 10000.0
    milp_max_successors_per_trip: Optional[int] = Field(default=None, ge=1)
    time_limit_seconds: int = 300
    mip_gap: float = 0.01
    include_deadhead: bool = True
    deadhead_speed_kmh: float = 18.0
    grid_flat_price_per_kwh: Optional[float] = None
    grid_sell_price_per_kwh: Optional[float] = None
    demand_charge_cost_per_kw: Optional[float] = None
    diesel_price_per_l: Optional[float] = None
    ice_co2_kg_per_l: Optional[float] = None
    grid_co2_kg_per_kwh: Optional[float] = None
    co2_price_per_kg: Optional[float] = None
    depot_power_limit_kw: Optional[float] = None
    tou_pricing: list[PrepareTimeOfUseBandBody] = Field(default_factory=list)
    service_date: Optional[str] = None
    service_dates: list[str] = Field(default_factory=list)
    planning_days: int = 1
    start_time: str = "05:00"
    end_time: str = "23:00"
    planning_horizon_hours: float = 20.0
    depot_energy_assets: Optional[list[Dict[str, Any]]] = None
    pv_profile_id: Optional[str] = None
    weather_mode: Optional[str] = None
    weather_factor_scalar: Optional[float] = None
    alns_iterations: int = 500
    no_improvement_limit: int = 100
    destroy_fraction: float = 0.25
    objective_weights: Dict[str, float] = Field(default_factory=dict)
    max_start_fragments_per_vehicle: Optional[int] = None
    max_end_fragments_per_vehicle: Optional[int] = None
    random_seed: Optional[int] = None
    experiment_method: Optional[str] = None
    experiment_notes: Optional[str] = None


class PrepareSimulationBody(BaseModel):
    selected_depot_ids: list[str] = Field(default_factory=list)
    selected_route_ids: list[str] = Field(default_factory=list)
    day_type: Optional[str] = None
    service_date: Optional[str] = None
    service_dates: list[str] = Field(default_factory=list)
    simulation_settings: PrepareSimulationSettingsBody = Field(
        default_factory=PrepareSimulationSettingsBody
    )
    # Trip selection overrides — None means "keep existing scope value"
    include_short_turn: Optional[bool] = None
    include_depot_moves: Optional[bool] = None
    include_deadhead: Optional[bool] = None
    # Vehicle swap permissions
    allow_intra_depot_route_swap: Optional[bool] = None
    allow_inter_depot_swap: Optional[bool] = None


class RunPreparedSimulationBody(BaseModel):
    prepared_input_id: str
    source: str = "duties"


def _simulation_capabilities() -> Dict[str, Any]:
    return {
        "implemented": True,
        "async_job": True,
        "job_persistence": dict(job_store.JOB_PERSISTENCE_INFO),
        "primary_inputs": ["scenario", "dispatch_scope", "problem_data"],
        "supported_sources": ["duties", "optimization_result"],
        "execution_model": f"{_simulation_executor_mode()}_pool",
        "notes": [
            "Simulation runs against scenario-derived ProblemData.",
            "Dispatch artifacts are auto-built when missing.",
            "Results are persisted to the scenario snapshot; job state is not.",
            "Simulation runs in a dedicated executor so API polling stays responsive.",
        ],
    }


_MAX_SIMULATION_WORKERS = max(1, multiprocessing.cpu_count() - 1)

def _simulation_executor_mode() -> str:
    mode = (os.getenv("BFF_SIM_EXECUTOR") or "").strip().lower()
    if mode in {"process", "thread"}:
        return mode
    # Windows + spawn blocks noticeably during submit; default to thread there.
    return "thread" if os.name == "nt" else "process"


def _get_simulation_executor() -> Executor:
    global _SIMULATION_EXECUTOR
    with _SIMULATION_FUTURE_LOCK:
        if _SIMULATION_EXECUTOR is None:
            if _simulation_executor_mode() == "thread":
                _SIMULATION_EXECUTOR = ThreadPoolExecutor(
                    max_workers=_MAX_SIMULATION_WORKERS
                )
            else:
                _SIMULATION_EXECUTOR = ProcessPoolExecutor(
                    max_workers=_MAX_SIMULATION_WORKERS,
                    mp_context=multiprocessing.get_context("spawn"),
                )
    return _SIMULATION_EXECUTOR


def shutdown_simulation_executor() -> None:
    global _SIMULATION_EXECUTOR, _SIMULATION_FUTURES
    with _SIMULATION_FUTURE_LOCK:
        executor = _SIMULATION_EXECUTOR
        _SIMULATION_EXECUTOR = None
        _SIMULATION_FUTURES.clear()
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
    global _SIMULATION_FUTURES
    with _SIMULATION_FUTURE_LOCK:
        # clear done futures
        _SIMULATION_FUTURES = {f for f in _SIMULATION_FUTURES if not f.done()}
        
        executor = _get_simulation_executor()
        if len(_SIMULATION_FUTURES) >= _MAX_SIMULATION_WORKERS:
            return False
            
        future = executor.submit(_run_simulation, *args)
        _SIMULATION_FUTURES.add(future)
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


def _prepared_inputs_root() -> Path:
    return output_paths.outputs_root() / "prepared_inputs"


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
    return str(allocate_run_dir(root))


def _persist_json_outputs(output_dir: str, payloads: Dict[str, Dict[str, Any]]) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (output_path / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _read_text_if_exists(path_value: Any) -> str | None:
    path_str = str(path_value or "").strip()
    if not path_str:
        return None
    path = Path(path_str)
    if not path.exists() or not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


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


def _sync_prepared_scope_artifacts(
    scenario_id: str,
    prepared_scenario: Dict[str, Any],
) -> None:
    prepared_trips = list(prepared_scenario.get("trips") or [])
    prepared_timetable_rows = list(
        prepared_scenario.get("timetable_rows")
        or prepared_trips
    )
    prepared_stops = list(prepared_scenario.get("stops") or [])
    prepared_stop_timetables = list(prepared_scenario.get("stop_timetables") or [])
    if prepared_trips:
        store.set_field(scenario_id, "trips", prepared_trips)
    if prepared_timetable_rows:
        store.set_field(scenario_id, "timetable_rows", prepared_timetable_rows)
    if prepared_stops:
        store.set_field(scenario_id, "stops", prepared_stops)
    if prepared_stop_timetables:
        store.set_field(scenario_id, "stop_timetables", prepared_stop_timetables)
    # Prepared scope changed; stale dispatch artifacts must be rebuilt against
    # the synced prepared trips before a prepared simulation can run.
    store.set_field(scenario_id, "graph", {})
    store.set_field(scenario_id, "duties", [])
    store.set_field(scenario_id, "blocks", [])
    store.set_field(scenario_id, "dispatch_plan", {})


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
        soc_max = vehicle.soc_max or vehicle.battery_capacity or 300.0
        current_soc = vehicle.soc_init or soc_max
        series = [current_soc for _ in range(data.num_periods + 1)]
        
        # P1: SOC充電反映 (シミュレーション時のダミー充電)
        assigned_tasks = []
        for task_id in result.assignment.get(vehicle.vehicle_id, []):
            task = task_lut.get(task_id)
            if task is not None:
                assigned_tasks.append(task)
        assigned_tasks.sort(key=lambda t: t.start_time_idx)

        charge_kw = 50.0  # 仮の充電電力
        eff = vehicle.charge_efficiency if hasattr(vehicle, "charge_efficiency") else 0.95
        charge_kwh_per_slot = charge_kw * data.delta_t_hour * eff
        
        last_t = 0
        for task in assigned_tasks:
            start_t = min(max(task.start_time_idx, 0), data.num_periods)
            end_t = min(max(task.end_time_idx, 0), data.num_periods)
            
            # 空き時間で充電
            for t in range(last_t + 1, start_t + 1):
                series[t] = min(soc_max, series[t - 1] + charge_kwh_per_slot)
            
            # タスク中の消費
            energy = task.energy_required_kwh_bev
            duration = max(1, end_t - start_t)
            consume_per_slot = energy / duration
            
            for t in range(start_t + 1, end_t + 1):
                series[t] = max(0.0, series[t - 1] - consume_per_slot)
                
            last_t = end_t
            
        # 最後のタスク以降の充電
        for t in range(last_t + 1, data.num_periods + 1):
            series[t] = min(soc_max, series[t - 1] + charge_kwh_per_slot)

        result.soc_series[vehicle.vehicle_id] = series

    return result


def _deserialize_canonical_result(canonical_dict: Dict[str, Any]) -> MILPResult:
    """Convert canonical optimization result dict to MILPResult for simulation (Phase 3).
    
    Canonical results have more structure (plan, ledger, metadata).
    Extract the parts needed for simulation and map to MILPResult.
    """
    plan = canonical_dict.get("plan") or {}
    metadata = canonical_dict.get("solver_metadata") or {}
    ledger_entries = canonical_dict.get("vehicle_cost_ledger") or []
    
    # Current canonical output keeps plan fields at top level.
    # Preserve backward compatibility with older nested "plan" payloads.
    assignment = (
        plan.get("vehicle_paths")
        or canonical_dict.get("vehicle_paths")
        or {}
    )
    
    # Extract SOC series
    soc_series = (
        plan.get("soc_kwh_by_vehicle_slot")
        or canonical_dict.get("soc_kwh_by_vehicle_slot")
        or {}
    )
    
    # Extract charging info
    charging_slots = (
        plan.get("charging_slots")
        or canonical_dict.get("charging_slots")
        or canonical_dict.get("charging_schedule")
        or []
    )
    charge_schedule: Dict[str, Dict[str, List[int]]] = {}
    charge_power_kw: Dict[str, Dict[str, List[float]]] = {}
    
    # Group charging slots by vehicle and charger
    from collections import defaultdict
    by_vehicle: Dict[str, Dict[str, List[tuple[int, float]]]] = defaultdict(lambda: defaultdict(list))
    for slot_dict in charging_slots:
        vehicle_id = slot_dict.get("vehicle_id")
        charger_id = slot_dict.get("charger_id")
        slot_idx = slot_dict.get("slot_index")
        charge_kw = slot_dict.get("charge_kw", 0.0)
        if vehicle_id and charger_id is not None and slot_idx is not None:
            by_vehicle[vehicle_id][charger_id].append((slot_idx, charge_kw))
    
    # Convert to charge_schedule and charge_power_kw format
    for vehicle_id, by_charger in by_vehicle.items():
        charge_schedule[vehicle_id] = {}
        charge_power_kw[vehicle_id] = {}
        for charger_id, slots in by_charger.items():
            # Assuming slots are ordered
            max_slot = max(s[0] for s in slots) if slots else 0
            schedule = [0] * (max_slot + 1)
            power = [0.0] * (max_slot + 1)
            for slot_idx, charge_kw in slots:
                schedule[slot_idx] = 1 if charge_kw > 0.01 else 0
                power[slot_idx] = charge_kw
            charge_schedule[vehicle_id][charger_id] = schedule
            charge_power_kw[vehicle_id][charger_id] = power
    
    # Extract refuel info (if any)
    refuel_slots = (
        plan.get("refuel_slots")
        or canonical_dict.get("refuel_slots")
        or canonical_dict.get("refueling_schedule")
        or []
    )
    refuel_schedule_l: Dict[str, List[float]] = defaultdict(list)
    for slot_dict in refuel_slots:
        vehicle_id = slot_dict.get("vehicle_id")
        slot_idx = slot_dict.get("slot_index")
        refuel_liters = slot_dict.get("refuel_liters", 0.0)
        if vehicle_id and slot_idx is not None:
            # Extend list if needed
            while len(refuel_schedule_l[vehicle_id]) <= slot_idx:
                refuel_schedule_l[vehicle_id].append(0.0)
            refuel_schedule_l[vehicle_id][slot_idx] = refuel_liters
    
    # Extract peak demand and objective breakdown
    peak_demand_kw = {}
    depot_ledger = canonical_dict.get("depot_cost_ledger") or []
    for entry in depot_ledger:
        depot_id = entry.get("depot_id")
        peak = entry.get("peak_demand_kw")
        if depot_id and peak is not None:
            peak_demand_kw[depot_id] = peak
    
    obj_breakdown = canonical_dict.get("cost_breakdown") or {}
    
    return MILPResult(
        status=(
            metadata.get("solver_status")
            or canonical_dict.get("solver_status")
            or "OPTIMAL"
        ),
        objective_value=(
            canonical_dict.get("objective_value")
            if canonical_dict.get("objective_value") is not None
            else canonical_dict.get("total_cost")
        ),
        solve_time_sec=metadata.get("solve_time_sec", 0.0),
        mip_gap=metadata.get("mip_gap"),
        assignment=assignment,
        soc_series=soc_series,
        charge_schedule=charge_schedule,
        charge_power_kw=charge_power_kw,
        refuel_schedule_l=dict(refuel_schedule_l),
        grid_import_kw={},  # Can extract from ledger if needed
        grid_export_kw={},
        pv_used_kw={},
        pv_to_bus_kwh={},
        peak_demand_kw=peak_demand_kw,
        obj_breakdown=obj_breakdown,
        unserved_tasks=list(
            plan.get("unserved_trip_ids")
            or canonical_dict.get("unserved_trip_ids")
            or []
        ),
        infeasibility_info="",
    )


def _run_simulation(
    scenario_id: str,
    job_id: str,
    prepared_input_id: str,
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

        scenario = materialize_scenario_from_prepared_input(
            store.get_scenario_document_shallow(scenario_id),
            load_prepared_input(
                scenario_id=scenario_id,
                prepared_input_id=prepared_input_id,
                scenarios_dir=_prepared_inputs_root(),
            ),
        )
        _sync_prepared_scope_artifacts(scenario_id, scenario)
        _ensure_dispatch_artifacts(scenario_id, service_id, depot_id)
        feed_context = _scenario_feed_context(scenario_id)
        output_dir = _scoped_output_dir(
            root=str(output_paths.outputs_root()),
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
            analysis_scope=scenario.get("dispatch_scope") or store.get_dispatch_scope(scenario_id),
        )
        store.set_field(scenario_id, "problemdata_build_audit", build_report.to_dict())

        if source == "optimization_result":
            optimization_result = (
                store.get_field(scenario_id, "optimization_result") or {}
            )
            
            # Phase 3: Prefer canonical_solver_result if available
            canonical_result = optimization_result.get("canonical_solver_result")
            legacy_result = optimization_result.get("solver_result")
            
            if canonical_result:
                # Use canonical result (full fidelity, all PV/grid/BESS fields preserved)
                milp_result = _deserialize_canonical_result(canonical_result)
            elif legacy_result:
                # Fallback to legacy format
                milp_result = deserialize_milp_result(legacy_result)
            else:
                raise ValueError(
                    "No optimization_result found. Run optimization first."
                )
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
        vehicle_type_by_id = {
            vehicle.vehicle_id: vehicle.vehicle_type for vehicle in data.vehicles
        }
        vehicle_count_by_type: Dict[str, int] = {}
        trip_count_by_type: Dict[str, int] = {}
        for vehicle_id, task_ids in (milp_result.assignment or {}).items():
            if not task_ids:
                continue
            vehicle_type = str(vehicle_type_by_id.get(vehicle_id) or "UNKNOWN")
            vehicle_count_by_type[vehicle_type] = (
                vehicle_count_by_type.get(vehicle_type, 0) + 1
            )
            trip_count_by_type[vehicle_type] = (
                trip_count_by_type.get(vehicle_type, 0) + len(task_ids)
            )
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
            "summary": {
                "vehicle_count_used": sum(vehicle_count_by_type.values()),
                "vehicle_count_by_type": vehicle_count_by_type,
                "trip_count_by_type": trip_count_by_type,
                "trip_count_served": sum(trip_count_by_type.values()),
            },
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
        try:
            experiment_report = log_simulation_experiment(
                scenario_id=scenario_id,
                scenario_doc=scenario,
                simulation_result=result,
            )
            result["experiment_report"] = experiment_report
            simulation_audit["experiment_report"] = {
                "experiment_id": experiment_report.get("experiment_id"),
                "json_path": experiment_report.get("json_path"),
                "md_path": experiment_report.get("md_path"),
            }
        except Exception as exc:
            warnings = list(simulation_audit.get("warnings") or [])
            warnings.append(f"Experiment report generation failed: {exc}")
            simulation_audit["warnings"] = warnings
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


@router.get("/scenarios/{scenario_id}/simulation/experiment-log")
def get_simulation_experiment_log(scenario_id: str) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    result = store.get_field(scenario_id, "simulation_result") or {}
    if not isinstance(result, dict):
        raise HTTPException(status_code=404, detail="Simulation has not been run yet.")
    experiment_report = dict(result.get("experiment_report") or {})
    if not experiment_report:
        raise HTTPException(
            status_code=404,
            detail="Simulation experiment log has not been generated yet.",
        )
    markdown = _read_text_if_exists(experiment_report.get("md_path"))
    if markdown is not None:
        experiment_report["markdown"] = markdown
    return experiment_report


@router.get("/scenarios/{scenario_id}/simulation/capabilities")
def get_simulation_capabilities(scenario_id: str) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    return _simulation_capabilities()


@router.post("/scenarios/{scenario_id}/simulation/prepare")
def prepare_simulation(
    scenario_id: str,
    body: PrepareSimulationBody,
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    try:
        scenario_doc = _apply_builder_configuration(scenario_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    prep = get_or_build_run_preparation(
        scenario=scenario_doc,
        built_dir=Path(_app_state.get("built_dir") or "data/built/tokyu_core"),
        scenarios_dir=_prepared_inputs_root(),
        routes_df=_app_state.get("routes_df"),
    )
    if not prep.is_valid:
        raise HTTPException(
            status_code=500,
            detail=make_error(
                AppErrorCode.SCENARIO_INCOMPLETE,
                f"Simulation prepare failed: {prep.error}",
            ),
        )
    warnings = list(prep.warnings)
    if not prep.scope_summary.get("primary_depot_id"):
        warnings.append("A primary depot is required before simulation can run.")
    prepare_profile = solver_prepare_profile(body.simulation_settings.solver_mode)
    vehicle_count = len(scenario_doc.get("vehicles") or [])
    charger_count = len(scenario_doc.get("chargers") or [])
    return {
        "preparedInputId": prep.prepared_input_id,
        "ready": bool(prep.is_valid and prep.scope_summary.get("trip_count", 0) > 0 and prep.scope_summary.get("primary_depot_id")),
        "tripCount": prep.scope_summary.get("trip_count", 0),
        "vehicleCount": vehicle_count,
        "chargerCount": charger_count,
        "blockCount": 0,
        "routeCount": len(prep.scope_summary.get("route_ids") or []),
        "depotCount": len(prep.scope_summary.get("depot_ids") or []),
        "timetableRowCount": prep.scope_summary.get("timetable_row_count", 0),
        "primaryDepotId": prep.scope_summary.get("primary_depot_id"),
        "serviceIds": prep.scope_summary.get("service_ids") or [],
        "serviceDate": prep.scope_summary.get("service_date"),
        "serviceDates": prep.scope_summary.get("service_dates") or [],
        "planningDays": prep.scope_summary.get("planning_days") or 1,
        "solverModeRequested": body.simulation_settings.solver_mode,
        "solverModeEffective": prepare_profile.get("solver_mode_effective"),
        "objectiveMode": body.simulation_settings.objective_mode,
        "prepareProfile": prepare_profile,
        "preparedScopeAudit": prep.scope_summary.get("prepared_scope_audit") or {},
        "warnings": warnings,
        "scopeSummary": prep.scope_summary,
    }


@router.post("/scenarios/{scenario_id}/simulation/run")
def run_prepared_simulation(
    scenario_id: str,
    body: RunPreparedSimulationBody,
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    scenario_doc = store.get_scenario_document_shallow(scenario_id)
    prep = get_or_build_run_preparation(
        scenario=scenario_doc,
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
    _require_nonempty_prepared_scope(prep, action="Prepared simulation")
    if prep.prepared_input_id != body.prepared_input_id:
        raise HTTPException(
            status_code=409,
            detail=make_error(
                AppErrorCode.SCENARIO_INCOMPLETE,
                "Prepared input is stale. Run prepare again before starting simulation.",
                preparedInputId=body.prepared_input_id,
                currentPreparedInputId=prep.prepared_input_id,
            ),
        )
    service_id = str((prep.scope_summary.get("service_ids") or ["WEEKDAY"])[0])
    depot_id = prep.scope_summary.get("primary_depot_id")
    scope = _resolve_dispatch_scope(
        scenario_id,
        service_id=service_id,
        depot_id=depot_id,
        persist=True,
    )
    job = job_store.create_job(execution_model=_simulation_executor_mode())
    job_store.update_job(
        job.job_id,
        metadata={
            "scenario_id": scenario_id,
            "feed_context": store.get_feed_context(scenario_id),
            "service_id": scope.get("serviceId") or service_id,
            "depot_id": scope.get("depotId"),
            "stage": "queued",
            "source": body.source,
            "prepared_input_id": body.prepared_input_id,
            "persistence": dict(job_store.JOB_PERSISTENCE_INFO),
        },
    )
    submitted = _submit_simulation_job(
        args=(
            scenario_id,
            job.job_id,
            body.prepared_input_id,
            scope.get("serviceId") or service_id,
            scope.get("depotId"),
            body.source,
        ),
        job_id=job.job_id,
        scenario_id=scenario_id,
        service_id=scope.get("serviceId") or service_id,
        depot_id=scope.get("depotId"),
        source=body.source,
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


@router.post("/scenarios/{scenario_id}/run-simulation")
def run_simulation(
    scenario_id: str,
    body: Optional[RunSimulationBody] = None,
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    scenario = store.get_scenario_document_shallow(scenario_id)
    prep = get_or_build_run_preparation(
        scenario=scenario,
        built_dir=Path(_app_state.get("built_dir") or "data/built/tokyu_core"),
        scenarios_dir=Path(__file__).resolve().parents[2] / "app" / "scenarios",
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
    _require_nonempty_prepared_scope(prep, action="Simulation preflight")
    request = body or RunSimulationBody()
    scope = _resolve_dispatch_scope(
        scenario_id,
        service_id=request.service_id,
        depot_id=request.depot_id,
        persist=True,
    )
    job = job_store.create_job(execution_model=_simulation_executor_mode())
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
            prep.prepared_input_id,  # Fixed: was missing, required by _run_simulation signature
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
