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
from bff.services.service_ids import canonical_service_id
from bff.services.run_preparation import get_or_build_run_preparation
from bff.store import job_store, scenario_store as store
from src.scenario_overlay import TimeOfUseBand, default_scenario_overlay
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
    battery_kwh: Optional[float] = None
    fleet_templates: list[PrepareFleetTemplateBody] = Field(default_factory=list)
    charger_count: int = 4
    charger_power_kw: float = 90.0
    solver_mode: str = "mode_milp_only"
    objective_mode: str = "total_cost"
    allow_partial_service: bool = False
    unserved_penalty: float = 10000.0
    time_limit_seconds: int = 300
    mip_gap: float = 0.01
    include_deadhead: bool = True
    grid_flat_price_per_kwh: Optional[float] = None
    grid_sell_price_per_kwh: Optional[float] = None
    demand_charge_cost_per_kw: Optional[float] = None
    diesel_price_per_l: Optional[float] = None
    grid_co2_kg_per_kwh: Optional[float] = None
    co2_price_per_kg: Optional[float] = None
    depot_power_limit_kw: Optional[float] = None
    tou_pricing: list[PrepareTimeOfUseBandBody] = Field(default_factory=list)
    service_date: Optional[str] = None
    start_time: str = "05:00"
    planning_horizon_hours: float = 20.0


class PrepareSimulationBody(BaseModel):
    selected_depot_ids: list[str] = Field(default_factory=list)
    selected_route_ids: list[str] = Field(default_factory=list)
    day_type: Optional[str] = None
    service_date: Optional[str] = None
    simulation_settings: PrepareSimulationSettingsBody = Field(
        default_factory=PrepareSimulationSettingsBody
    )


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


def _prepared_inputs_root() -> Path:
    return Path(__file__).resolve().parents[2] / "outputs" / "prepared_inputs"


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


def _select_builder_template(
    doc: Dict[str, Any],
    template_id: Optional[str],
) -> Dict[str, Any]:
    templates = [dict(item) for item in doc.get("vehicle_templates") or []]
    if template_id:
        for template in templates:
            if str(template.get("id") or "") == str(template_id):
                return template
    for template in templates:
        if str(template.get("type") or "").upper() == "BEV":
            return template
    return templates[0] if templates else {}


def _resolve_builder_template_selections(
    doc: Dict[str, Any],
    settings: PrepareSimulationSettingsBody,
) -> list[Dict[str, Any]]:
    if settings.fleet_templates:
        selections: list[Dict[str, Any]] = []
        for item in settings.fleet_templates:
            template = _select_builder_template(doc, item.vehicle_template_id)
            if not template:
                continue
            selections.append(
                {
                    "template": template,
                    "vehicle_count": max(int(item.vehicle_count), 0),
                    "initial_soc": settings.initial_soc if item.initial_soc is None else item.initial_soc,
                    "battery_kwh": item.battery_kwh,
                    "charge_power_kw": item.charge_power_kw,
                }
            )
        return [item for item in selections if item["vehicle_count"] > 0]

    template = _select_builder_template(doc, settings.vehicle_template_id)
    if not template:
        return []
    return [
        {
            "template": template,
            "vehicle_count": max(int(settings.vehicle_count), 0),
            "initial_soc": settings.initial_soc,
            "battery_kwh": settings.battery_kwh,
            "charge_power_kw": settings.charger_power_kw,
        }
    ]


def _objective_weights_for_mode(
    *,
    objective_mode: str,
    unserved_penalty: float,
) -> Dict[str, float]:
    if str(objective_mode or "").strip().lower() == "co2":
        return {
            "vehicle_fixed_cost": 0.0,
            "electricity_cost": 0.0,
            "demand_charge_cost": 0.0,
            "fuel_cost": 0.0,
            "deadhead_cost": 0.0,
            "battery_degradation_cost": 0.0,
            "emission_cost": 1.0,
            "unserved_penalty": float(unserved_penalty),
            "slack_penalty": 1000000.0,
        }
    return {
        "vehicle_fixed_cost": 0.0,
        "electricity_cost": 1.0,
        "demand_charge_cost": 1.0,
        "fuel_cost": 1.0,
        "deadhead_cost": 0.0,
        "battery_degradation_cost": 0.0,
        "emission_cost": 0.0,
        "unserved_penalty": float(unserved_penalty),
        "slack_penalty": 1000000.0,
    }


def _build_builder_vehicles(
    *,
    primary_depot_id: str,
    template: Dict[str, Any],
    vehicle_count: int,
    initial_soc: float,
    battery_kwh: Optional[float],
    charger_power_kw: float,
) -> list[Dict[str, Any]]:
    items: list[Dict[str, Any]] = []
    vehicle_type = str(template.get("type") or "BEV").upper()
    for index in range(max(vehicle_count, 0)):
        item = dict(template)
        item["id"] = f"builder-{vehicle_type.lower()}-{primary_depot_id}-{index + 1:03d}"
        item["vehicleTemplateId"] = template.get("id")
        item["depotId"] = primary_depot_id
        item["enabled"] = True
        item["initialSoc"] = initial_soc if vehicle_type == "BEV" else None
        if vehicle_type == "BEV":
            item["batteryKwh"] = battery_kwh if battery_kwh is not None else template.get("batteryKwh")
            item["chargePowerKw"] = charger_power_kw or template.get("chargePowerKw")
            item["fuelTankL"] = None
        else:
            item["batteryKwh"] = None
        items.append(item)
    return items


def _build_builder_fleet_vehicles(
    *,
    primary_depot_id: str,
    selections: list[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    items: list[Dict[str, Any]] = []
    sequence = 1
    for selection in selections:
        template = dict(selection.get("template") or {})
        vehicle_count = int(selection.get("vehicle_count") or 0)
        built = _build_builder_vehicles(
            primary_depot_id=primary_depot_id,
            template=template,
            vehicle_count=vehicle_count,
            initial_soc=float(selection.get("initial_soc") or 0.8),
            battery_kwh=selection.get("battery_kwh"),
            charger_power_kw=float(selection.get("charge_power_kw") or 0.0),
        )
        for vehicle in built:
            vehicle_type = str(vehicle.get("type") or "BEV").upper()
            vehicle["id"] = f"builder-{vehicle_type.lower()}-{primary_depot_id}-{sequence:03d}"
            sequence += 1
            items.append(vehicle)
    return items


def _build_builder_chargers(
    *,
    primary_depot_id: str,
    has_bev: bool,
    charger_count: int,
    charger_power_kw: float,
) -> list[Dict[str, Any]]:
    if not has_bev:
        return []
    items: list[Dict[str, Any]] = []
    power_kw = charger_power_kw or float(template.get("chargePowerKw") or 90.0)
    for index in range(max(charger_count, 0)):
        items.append(
            {
                "id": f"builder-charger-{primary_depot_id}-{index + 1:03d}",
                "siteId": primary_depot_id,
                "powerKw": power_kw,
                "bidirectional": False,
                "simultaneous_ports": 1,
            }
        )
    return items


def _apply_builder_configuration(
    scenario_id: str,
    body: PrepareSimulationBody,
) -> Dict[str, Any]:
    doc = store.get_scenario_document(scenario_id, repair_missing_master=False)
    valid_depot_ids = {
        str(item.get("id") or item.get("depotId") or "").strip()
        for item in doc.get("depots") or []
        if str(item.get("id") or item.get("depotId") or "").strip()
    }
    selected_depot_ids = [
        depot_id
        for depot_id in body.selected_depot_ids
        if str(depot_id or "").strip() in valid_depot_ids
    ]
    if not selected_depot_ids and valid_depot_ids:
        selected_depot_ids = [sorted(valid_depot_ids)[0]]
    if not selected_depot_ids:
        raise HTTPException(status_code=422, detail="No valid depot is selected.")

    selected_day_type = canonical_service_id(
        body.day_type
        or (doc.get("dispatch_scope") or {}).get("serviceId")
        or "WEEKDAY"
    )
    candidate_scope = {
        "depotSelection": {
            "mode": "include",
            "depotIds": selected_depot_ids,
            "primaryDepotId": selected_depot_ids[0],
        },
        "routeSelection": {"mode": "all"},
        "serviceSelection": {"serviceIds": [selected_day_type]},
        "tripSelection": {
            "includeShortTurn": True,
            "includeDepotMoves": True,
            "includeDeadhead": bool(body.simulation_settings.include_deadhead),
        },
        "depotId": selected_depot_ids[0],
        "serviceId": selected_day_type,
    }
    candidate_route_ids = store.route_ids_for_selected_depots(scenario_id, candidate_scope)
    selected_route_ids = [
        route_id
        for route_id in body.selected_route_ids
        if str(route_id or "").strip() in set(candidate_route_ids)
    ]
    if not selected_route_ids:
        selected_route_ids = list(candidate_route_ids)

    template_selections = _resolve_builder_template_selections(doc, body.simulation_settings)
    if not template_selections:
        raise HTTPException(status_code=422, detail="No vehicle template is available for builder prepare.")
    primary_template = dict(template_selections[0]["template"] or {})
    fleet_counts = {"BEV": 0, "ICE": 0}
    for selection in template_selections:
        template_type = str((selection.get("template") or {}).get("type") or "BEV").upper()
        fleet_counts[template_type] = fleet_counts.get(template_type, 0) + int(
            selection.get("vehicle_count") or 0
        )

    scenario_meta = store.get_scenario(scenario_id)
    current_overlay = dict(doc.get("scenario_overlay") or {})
    overlay = default_scenario_overlay(
        scenario_id=scenario_id,
        dataset_id=str(
            scenario_meta.get("datasetId")
            or current_overlay.get("dataset_id")
            or "tokyu_core"
        ),
        dataset_version=str(
            scenario_meta.get("datasetVersion")
            or current_overlay.get("dataset_version")
            or "unknown"
        ),
        random_seed=int(scenario_meta.get("randomSeed") or current_overlay.get("random_seed") or 42),
        depot_ids=selected_depot_ids,
        route_ids=selected_route_ids,
    )
    if isinstance(current_overlay.get("cost_coefficients"), dict):
        current_cost_coefficients = dict(current_overlay.get("cost_coefficients") or {})
        if current_cost_coefficients.get("tou_pricing"):
            current_cost_coefficients["tou_pricing"] = [
                item
                if isinstance(item, TimeOfUseBand)
                else TimeOfUseBand(**dict(item))
                for item in current_cost_coefficients.get("tou_pricing") or []
                if isinstance(item, (dict, TimeOfUseBand))
            ]
        overlay.cost_coefficients = overlay.cost_coefficients.model_copy(
            update=current_cost_coefficients
        )
    if isinstance(current_overlay.get("solver_config"), dict):
        overlay.solver_config = overlay.solver_config.model_copy(
            update=current_overlay.get("solver_config") or {}
        )
    overlay.fleet.n_bev = int(fleet_counts.get("BEV", 0))
    overlay.fleet.n_ice = int(fleet_counts.get("ICE", 0))
    overlay.charging_constraints.max_simultaneous_sessions = body.simulation_settings.charger_count
    overlay.charging_constraints.charger_power_limit_kw = body.simulation_settings.charger_power_kw
    if body.simulation_settings.depot_power_limit_kw is not None:
        overlay.charging_constraints.depot_power_limit_kw = body.simulation_settings.depot_power_limit_kw
    overlay.solver_config.mode = body.simulation_settings.solver_mode
    overlay.solver_config.objective_mode = str(body.simulation_settings.objective_mode or "total_cost")
    overlay.solver_config.allow_partial_service = bool(body.simulation_settings.allow_partial_service)
    overlay.solver_config.unserved_penalty = float(body.simulation_settings.unserved_penalty)
    overlay.solver_config.time_limit_seconds = body.simulation_settings.time_limit_seconds
    overlay.solver_config.mip_gap = body.simulation_settings.mip_gap
    overlay.solver_config.objective_weights = _objective_weights_for_mode(
        objective_mode=overlay.solver_config.objective_mode,
        unserved_penalty=overlay.solver_config.unserved_penalty,
    )
    if body.simulation_settings.grid_flat_price_per_kwh is not None:
        overlay.cost_coefficients.grid_flat_price_per_kwh = body.simulation_settings.grid_flat_price_per_kwh
    if body.simulation_settings.grid_sell_price_per_kwh is not None:
        overlay.cost_coefficients.grid_sell_price_per_kwh = body.simulation_settings.grid_sell_price_per_kwh
    if body.simulation_settings.demand_charge_cost_per_kw is not None:
        overlay.cost_coefficients.demand_charge_cost_per_kw = body.simulation_settings.demand_charge_cost_per_kw
    if body.simulation_settings.diesel_price_per_l is not None:
        overlay.cost_coefficients.diesel_price_per_l = body.simulation_settings.diesel_price_per_l
    if body.simulation_settings.grid_co2_kg_per_kwh is not None:
        overlay.cost_coefficients.grid_co2_kg_per_kwh = body.simulation_settings.grid_co2_kg_per_kwh
    if body.simulation_settings.co2_price_per_kg is not None:
        overlay.cost_coefficients.co2_price_per_kg = body.simulation_settings.co2_price_per_kg
    if body.simulation_settings.tou_pricing:
        overlay.cost_coefficients.tou_pricing = [
            TimeOfUseBand(**item.model_dump())
            for item in body.simulation_settings.tou_pricing
        ]

    primary_depot_id = selected_depot_ids[0]
    doc["dispatch_scope"] = {
        "scopeId": f"{scenario_meta.get('datasetId') or 'tokyu_core'}:{scenario_meta.get('datasetVersion') or 'unknown'}",
        "operatorId": scenario_meta.get("operatorId") or "tokyu",
        "datasetVersion": scenario_meta.get("datasetVersion"),
        "depotSelection": {
            "mode": "include",
            "depotIds": selected_depot_ids,
            "primaryDepotId": primary_depot_id,
        },
        "routeSelection": {
            "mode": "include",
            "includeRouteIds": selected_route_ids,
            "excludeRouteIds": [],
        },
        "serviceSelection": {"serviceIds": [selected_day_type]},
        "tripSelection": {
            "includeShortTurn": True,
            "includeDepotMoves": True,
            "includeDeadhead": bool(body.simulation_settings.include_deadhead),
        },
        "depotId": primary_depot_id,
        "serviceId": selected_day_type,
    }
    doc["scenario_overlay"] = overlay.model_dump()
    doc["simulation_config"] = {
        "service_date": body.service_date or body.simulation_settings.service_date,
        "day_type": selected_day_type,
        "initial_soc": body.simulation_settings.initial_soc,
        "start_time": body.simulation_settings.start_time,
        "planning_horizon_hours": body.simulation_settings.planning_horizon_hours,
        "time_step_min": 15,
        "vehicle_template_id": primary_template.get("id"),
        "fleet_templates": [
            {
                "vehicle_template_id": (selection.get("template") or {}).get("id"),
                "vehicle_count": int(selection.get("vehicle_count") or 0),
                "initial_soc": selection.get("initial_soc"),
                "battery_kwh": selection.get("battery_kwh"),
                "charge_power_kw": selection.get("charge_power_kw"),
            }
            for selection in template_selections
        ],
        "charger_count": body.simulation_settings.charger_count,
        "charger_power_kw": body.simulation_settings.charger_power_kw,
        "solver_mode": body.simulation_settings.solver_mode,
        "objective_mode": overlay.solver_config.objective_mode,
        "allow_partial_service": overlay.solver_config.allow_partial_service,
        "unserved_penalty": overlay.solver_config.unserved_penalty,
        "objective_weights": dict(overlay.solver_config.objective_weights),
        "time_limit_seconds": body.simulation_settings.time_limit_seconds,
        "mip_gap": body.simulation_settings.mip_gap,
    }
    doc["vehicles"] = _build_builder_fleet_vehicles(
        primary_depot_id=primary_depot_id,
        selections=template_selections,
    )
    doc["chargers"] = _build_builder_chargers(
        primary_depot_id=primary_depot_id,
        has_bev=overlay.fleet.n_bev > 0,
        charger_count=body.simulation_settings.charger_count,
        charger_power_kw=body.simulation_settings.charger_power_kw,
    )
    if overlay.charging_constraints.depot_power_limit_kw is not None:
        doc["charger_sites"] = [
            {
                "id": primary_depot_id,
                "site_type": "depot",
                "grid_import_limit_kw": overlay.charging_constraints.depot_power_limit_kw,
                "contract_demand_limit_kw": overlay.charging_constraints.depot_power_limit_kw,
            }
        ]
    store._normalize_dispatch_scope(doc)
    store._invalidate_dispatch_artifacts(doc)
    doc["meta"]["updatedAt"] = store._now_iso()
    store._save(doc)
    return doc

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


@router.post("/scenarios/{scenario_id}/simulation/prepare")
def prepare_simulation(
    scenario_id: str,
    body: PrepareSimulationBody,
    _app_state: dict = Depends(require_built),
) -> Dict[str, Any]:
    _require_scenario(scenario_id)
    scenario_doc = _apply_builder_configuration(scenario_id, body)
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
    return {
        "preparedInputId": prep.prepared_input_id,
        "ready": bool(prep.is_valid and prep.scope_summary.get("trip_count", 0) > 0 and prep.scope_summary.get("primary_depot_id")),
        "tripCount": prep.scope_summary.get("trip_count", 0),
        "blockCount": 0,
        "routeCount": len(prep.scope_summary.get("route_ids") or []),
        "depotCount": len(prep.scope_summary.get("depot_ids") or []),
        "timetableRowCount": prep.scope_summary.get("timetable_row_count", 0),
        "primaryDepotId": prep.scope_summary.get("primary_depot_id"),
        "serviceIds": prep.scope_summary.get("service_ids") or [],
        "serviceDate": prep.scope_summary.get("service_date"),
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
    scenario_doc = store.get_scenario_document(scenario_id)
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
    job = job_store.create_job()
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
    scenario = store.get_scenario(scenario_id)
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
