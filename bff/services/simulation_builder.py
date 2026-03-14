from __future__ import annotations

from typing import Any, Dict, Optional

from bff.services.service_ids import canonical_service_id
from bff.store import scenario_store as store
from src.scenario_overlay import TimeOfUseBand, default_scenario_overlay


def _first_defined(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is not None:
            return value
    return default


def select_builder_template(
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


def resolve_builder_template_selections(
    doc: Dict[str, Any],
    settings: Any,
) -> list[Dict[str, Any]]:
    if settings.fleet_templates:
        selections: list[Dict[str, Any]] = []
        for item in settings.fleet_templates:
            template = select_builder_template(doc, item.vehicle_template_id)
            if not template:
                continue
            selections.append(
                {
                    "template": template,
                    "vehicle_count": max(int(item.vehicle_count), 0),
                    "initial_soc": settings.initial_soc
                    if item.initial_soc is None
                    else item.initial_soc,
                    "battery_kwh": item.battery_kwh,
                    "charge_power_kw": item.charge_power_kw,
                }
            )
        return [item for item in selections if item["vehicle_count"] > 0]

    template = select_builder_template(doc, settings.vehicle_template_id)
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


def objective_weights_for_mode(
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


def build_builder_vehicles(
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
            item["batteryKwh"] = (
                battery_kwh if battery_kwh is not None else template.get("batteryKwh")
            )
            item["chargePowerKw"] = charger_power_kw or template.get("chargePowerKw")
            item["fuelTankL"] = None
        else:
            item["batteryKwh"] = None
        items.append(item)
    return items


def build_builder_fleet_vehicles(
    *,
    primary_depot_id: str,
    selections: list[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    items: list[Dict[str, Any]] = []
    sequence = 1
    for selection in selections:
        template = dict(selection.get("template") or {})
        vehicle_count = int(selection.get("vehicle_count") or 0)
        built = build_builder_vehicles(
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


def build_builder_chargers(
    *,
    primary_depot_id: str,
    has_bev: bool,
    charger_count: int,
    charger_power_kw: float,
) -> list[Dict[str, Any]]:
    if not has_bev:
        return []
    items: list[Dict[str, Any]] = []
    power_kw = charger_power_kw or 90.0
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


def apply_builder_configuration(
    scenario_id: str,
    body: Any,
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
        raise ValueError("No valid depot is selected.")

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

    template_selections = resolve_builder_template_selections(
        doc, body.simulation_settings
    )
    if not template_selections:
        raise ValueError("No vehicle template is available for builder prepare.")
    primary_template = dict(template_selections[0]["template"] or {})
    fleet_counts = {"BEV": 0, "ICE": 0}
    for selection in template_selections:
        template_type = str(
            (selection.get("template") or {}).get("type") or "BEV"
        ).upper()
        fleet_counts[template_type] = fleet_counts.get(template_type, 0) + int(
            selection.get("vehicle_count") or 0
        )

    scenario_meta = store.get_scenario(scenario_id)
    current_overlay = dict(doc.get("scenario_overlay") or {})
    overlay = default_scenario_overlay(
        scenario_id=scenario_id,
        dataset_id=str(
            scenario_meta.get("datasetId") or current_overlay.get("dataset_id") or "tokyu_core"
        ),
        dataset_version=str(
            scenario_meta.get("datasetVersion")
            or current_overlay.get("dataset_version")
            or "unknown"
        ),
        random_seed=int(
            _first_defined(
                body.simulation_settings.random_seed,
                scenario_meta.get("randomSeed"),
                current_overlay.get("random_seed"),
                default=42,
            )
        ),
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

    overlay.random_seed = int(
        _first_defined(
            body.simulation_settings.random_seed,
            overlay.random_seed,
            scenario_meta.get("randomSeed"),
            default=42,
        )
    )
    overlay.fleet.n_bev = int(fleet_counts.get("BEV", 0))
    overlay.fleet.n_ice = int(fleet_counts.get("ICE", 0))
    overlay.charging_constraints.max_simultaneous_sessions = (
        body.simulation_settings.charger_count
    )
    overlay.charging_constraints.charger_power_limit_kw = (
        body.simulation_settings.charger_power_kw
    )
    if body.simulation_settings.depot_power_limit_kw is not None:
        overlay.charging_constraints.depot_power_limit_kw = (
            body.simulation_settings.depot_power_limit_kw
        )
    overlay.solver_config.mode = body.simulation_settings.solver_mode
    overlay.solver_config.objective_mode = str(
        body.simulation_settings.objective_mode or "total_cost"
    )
    overlay.solver_config.allow_partial_service = bool(
        body.simulation_settings.allow_partial_service
    )
    overlay.solver_config.unserved_penalty = float(
        body.simulation_settings.unserved_penalty
    )
    overlay.solver_config.time_limit_seconds = (
        body.simulation_settings.time_limit_seconds
    )
    overlay.solver_config.mip_gap = body.simulation_settings.mip_gap
    overlay.solver_config.alns_iterations = int(
        body.simulation_settings.alns_iterations or overlay.solver_config.alns_iterations
    )
    overlay.solver_config.objective_weights = objective_weights_for_mode(
        objective_mode=overlay.solver_config.objective_mode,
        unserved_penalty=overlay.solver_config.unserved_penalty,
    )
    if body.simulation_settings.grid_flat_price_per_kwh is not None:
        overlay.cost_coefficients.grid_flat_price_per_kwh = (
            body.simulation_settings.grid_flat_price_per_kwh
        )
    if body.simulation_settings.grid_sell_price_per_kwh is not None:
        overlay.cost_coefficients.grid_sell_price_per_kwh = (
            body.simulation_settings.grid_sell_price_per_kwh
        )
    if body.simulation_settings.demand_charge_cost_per_kw is not None:
        overlay.cost_coefficients.demand_charge_cost_per_kw = (
            body.simulation_settings.demand_charge_cost_per_kw
        )
    if body.simulation_settings.diesel_price_per_l is not None:
        overlay.cost_coefficients.diesel_price_per_l = (
            body.simulation_settings.diesel_price_per_l
        )
    if body.simulation_settings.grid_co2_kg_per_kwh is not None:
        overlay.cost_coefficients.grid_co2_kg_per_kwh = (
            body.simulation_settings.grid_co2_kg_per_kwh
        )
    if body.simulation_settings.co2_price_per_kg is not None:
        overlay.cost_coefficients.co2_price_per_kg = (
            body.simulation_settings.co2_price_per_kg
        )
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
        "alns_iterations": overlay.solver_config.alns_iterations,
        "random_seed": overlay.random_seed,
        "experiment_method": body.simulation_settings.experiment_method,
        "experiment_notes": body.simulation_settings.experiment_notes,
    }
    doc["vehicles"] = build_builder_fleet_vehicles(
        primary_depot_id=primary_depot_id,
        selections=template_selections,
    )
    doc["chargers"] = build_builder_chargers(
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
