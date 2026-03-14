from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict

from experiment_logger import ExperimentLogger


def log_optimization_experiment(
    *,
    scenario_id: str,
    scenario_doc: Dict[str, Any],
    optimization_result: Dict[str, Any],
) -> Dict[str, Any]:
    method = _method_label(scenario_doc, optimization_result.get("mode"))
    logger = ExperimentLogger(results_dir=_results_dir(scenario_id, "optimization"))
    report = logger.log(
        scenario=_logger_scenario_payload(
            scenario_doc=scenario_doc,
            objective=str(
                optimization_result.get("objective_mode")
                or _simulation_config(scenario_doc).get("objective_mode")
                or "total_cost"
            ),
            method=method,
            mode=optimization_result.get("mode"),
        ),
        result=_optimization_result_payload(optimization_result),
        method=method,
        seed=_random_seed(scenario_doc),
    )
    return _experiment_report_payload(
        report=report,
        report_type="optimization",
        scenario_id=scenario_id,
        scenario_doc=scenario_doc,
        method=method,
        mode=optimization_result.get("mode"),
    )


def log_simulation_experiment(
    *,
    scenario_id: str,
    scenario_doc: Dict[str, Any],
    simulation_result: Dict[str, Any],
) -> Dict[str, Any]:
    method = _method_label(
        scenario_doc,
        (_scenario_overlay(scenario_doc).get("solver_config") or {}).get("mode"),
    )
    logger = ExperimentLogger(results_dir=_results_dir(scenario_id, "simulation"))
    report = logger.log(
        scenario=_logger_scenario_payload(
            scenario_doc=scenario_doc,
            objective=str(
                (_scenario_overlay(scenario_doc).get("solver_config") or {}).get(
                    "objective_mode"
                )
                or _simulation_config(scenario_doc).get("objective_mode")
                or "total_cost"
            ),
            method=method,
            mode=(_scenario_overlay(scenario_doc).get("solver_config") or {}).get("mode"),
        ),
        result=_simulation_result_payload(simulation_result),
        method=method,
        seed=_random_seed(scenario_doc),
    )
    return _experiment_report_payload(
        report=report,
        report_type="simulation",
        scenario_id=scenario_id,
        scenario_doc=scenario_doc,
        method=method,
        mode=(_scenario_overlay(scenario_doc).get("solver_config") or {}).get("mode"),
    )


def _results_dir(scenario_id: str, report_type: str) -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "outputs"
        / "experiments"
        / scenario_id
        / report_type
    )


def _simulation_config(scenario_doc: Dict[str, Any]) -> Dict[str, Any]:
    return dict(scenario_doc.get("simulation_config") or {})


def _scenario_overlay(scenario_doc: Dict[str, Any]) -> Dict[str, Any]:
    return dict(scenario_doc.get("scenario_overlay") or {})


def _random_seed(scenario_doc: Dict[str, Any]) -> int | None:
    overlay = _scenario_overlay(scenario_doc)
    simulation_config = _simulation_config(scenario_doc)
    try:
        for candidate in (
            simulation_config.get("random_seed"),
            overlay.get("random_seed"),
            (scenario_doc.get("meta") or {}).get("randomSeed"),
        ):
            if candidate is not None:
                return int(candidate)
        return None
    except Exception:
        return None


def _method_label(scenario_doc: Dict[str, Any], mode: Any) -> str:
    simulation_config = _simulation_config(scenario_doc)
    explicit = str(simulation_config.get("experiment_method") or "").strip()
    if explicit:
        return explicit
    normalized = str(mode or "").strip().lower()
    if normalized in {"mode_milp_only", "milp"}:
        return "MILP"
    if normalized in {"mode_alns_only", "alns"}:
        return "ALNS"
    if normalized in {"mode_alns_milp", "hybrid"}:
        return "MILP+ALNS"
    return str(mode or "MILP")


def _solver_name(mode: Any) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized in {"mode_alns_only", "alns"}:
        return "alns"
    if normalized in {"mode_alns_milp", "hybrid"}:
        return "gurobi+alns"
    return "gurobi"


def _fleet_template_entries(scenario_doc: Dict[str, Any]) -> list[Dict[str, Any]]:
    simulation_config = _simulation_config(scenario_doc)
    templates_by_id = {
        str(item.get("id") or ""): dict(item)
        for item in scenario_doc.get("vehicle_templates") or []
        if str(item.get("id") or "")
    }
    entries: list[Dict[str, Any]] = []
    for item in simulation_config.get("fleet_templates") or []:
        if not isinstance(item, dict):
            continue
        template_id = str(item.get("vehicle_template_id") or "")
        template = templates_by_id.get(template_id, {})
        entries.append(
            {
                "vehicle_template_id": template_id,
                "template_name": template.get("name") or template.get("modelName") or template_id,
                "vehicle_type": str(template.get("type") or "UNKNOWN").upper(),
                "vehicle_count": int(item.get("vehicle_count") or 0),
                "initial_soc": item.get("initial_soc"),
                "battery_kwh": item.get("battery_kwh"),
                "charge_power_kw": item.get("charge_power_kw"),
            }
        )
    return [item for item in entries if item["vehicle_count"] > 0]


def _fleet_summary(entries: list[Dict[str, Any]], vehicle_type: str) -> tuple[str, int]:
    selected = [item for item in entries if item["vehicle_type"] == vehicle_type]
    if not selected:
        return "", 0
    count = sum(int(item.get("vehicle_count") or 0) for item in selected)
    names = [str(item.get("template_name") or item.get("vehicle_template_id") or "") for item in selected]
    unique_names = [name for index, name in enumerate(names) if name and name not in names[:index]]
    if not unique_names:
        model = vehicle_type
    elif len(unique_names) == 1:
        model = unique_names[0]
    elif len(unique_names) == 2:
        model = " + ".join(unique_names)
    else:
        model = f"{unique_names[0]} + {len(unique_names) - 1} more"
    return model, count


def _route_labels(scenario_doc: Dict[str, Any]) -> list[str]:
    overlay = _scenario_overlay(scenario_doc)
    selected_route_ids = [str(item) for item in overlay.get("route_ids") or []]
    if not selected_route_ids:
        selected_route_ids = [
            str(item)
            for item in (((scenario_doc.get("dispatch_scope") or {}).get("routeSelection") or {}).get("includeRouteIds") or [])
        ]
    routes_by_id = {
        str(item.get("id") or ""): dict(item)
        for item in scenario_doc.get("routes") or []
        if str(item.get("id") or "")
    }
    labels: list[str] = []
    for route_id in selected_route_ids:
        route = routes_by_id.get(route_id, {})
        label = (
            route.get("displayName")
            or route.get("routeLabel")
            or route.get("routeCode")
            or route.get("name")
            or route_id
        )
        labels.append(str(label))
    return labels


def _tou_rates(scenario_doc: Dict[str, Any]) -> Dict[str, float]:
    overlay = _scenario_overlay(scenario_doc)
    slots = sorted(
        list((overlay.get("cost_coefficients") or {}).get("tou_pricing") or []),
        key=lambda item: int(item.get("start_hour") or 0),
    )
    padded = slots[:3] + [{}] * max(0, 3 - len(slots[:3]))
    return {
        "offpeak": float(padded[0].get("price_per_kwh") or 0.0),
        "midpeak": float(padded[1].get("price_per_kwh") or 0.0),
        "onpeak": float(padded[2].get("price_per_kwh") or 0.0),
    }


def _logger_scenario_payload(
    *,
    scenario_doc: Dict[str, Any],
    objective: str,
    method: str,
    mode: Any,
) -> Dict[str, Any]:
    overlay = _scenario_overlay(scenario_doc)
    simulation_config = _simulation_config(scenario_doc)
    fleet_entries = _fleet_template_entries(scenario_doc)
    bev_model, bev_count = _fleet_summary(fleet_entries, "BEV")
    ice_model, ice_count = _fleet_summary(fleet_entries, "ICE")
    cost_coefficients = dict(overlay.get("cost_coefficients") or {})
    charging_constraints = dict(overlay.get("charging_constraints") or {})
    solver_config = dict(overlay.get("solver_config") or {})
    depot_id = str(
        ((scenario_doc.get("dispatch_scope") or {}).get("depotSelection") or {}).get("primaryDepotId")
        or (scenario_doc.get("dispatch_scope") or {}).get("depotId")
        or ""
    )
    return {
        "depot": depot_id,
        "routes": _route_labels(scenario_doc),
        "objective": objective,
        "method": method,
        "fleet": [
            {"vehicle_type": "BEV", "model": bev_model, "count": bev_count},
            {"vehicle_type": "ICE", "model": ice_model, "count": ice_count},
        ],
        "costs": {
            "tou_rates": _tou_rates(scenario_doc),
            "diesel_jpy_per_l": float(cost_coefficients.get("diesel_price_per_l") or 0.0),
            "demand_jpy_per_kw": float(
                cost_coefficients.get("demand_charge_cost_per_kw") or 0.0
            ),
            "vehicle_fixed_cost": float(
                (solver_config.get("objective_weights") or {}).get("vehicle_fixed_cost")
                or 0.0
            ),
        },
        "grid": {
            "max_kw": float(charging_constraints.get("depot_power_limit_kw") or 0.0),
        },
        "pv": {
            "capacity_kw": float(cost_coefficients.get("pv_scale") or 0.0),
        },
        "solver": {
            "name": _solver_name(mode),
            "time_limit_sec": int(solver_config.get("time_limit_seconds") or 0),
            "mip_gap_pct": solver_config.get("mip_gap"),
            "seed": _random_seed(scenario_doc),
        },
    }


def _optimization_result_payload(optimization_result: Dict[str, Any]) -> Dict[str, Any]:
    cost_breakdown = dict(optimization_result.get("cost_breakdown") or {})
    summary = dict(optimization_result.get("summary") or {})
    trip_count_by_type = dict(summary.get("trip_count_by_type") or {})
    simulation_summary = dict(optimization_result.get("simulation_summary") or {})
    return {
        "status": optimization_result.get("solver_status", "UNKNOWN"),
        "objective_value": optimization_result.get("objective_value"),
        "total_cost_jpy": cost_breakdown.get("total_cost"),
        "electricity_cost_jpy": cost_breakdown.get("energy_cost"),
        "diesel_cost_jpy": cost_breakdown.get("fuel_cost"),
        "demand_charge_jpy": cost_breakdown.get("peak_demand_cost"),
        "vehicle_fixed_cost_jpy": cost_breakdown.get("vehicle_cost"),
        "co2_kg": cost_breakdown.get("total_co2_kg"),
        "bev_trips": trip_count_by_type.get("BEV"),
        "ice_trips": trip_count_by_type.get("ICE"),
        "total_trips": summary.get("trip_count_served"),
        "total_charging_kwh": simulation_summary.get("total_grid_kwh"),
        "peak_charging_kw": simulation_summary.get("peak_demand_kw"),
        "solve_time_sec": optimization_result.get("solve_time_seconds"),
        "mip_gap_pct": optimization_result.get("mip_gap"),
        "cost_breakdown": cost_breakdown,
        "charging_schedule": (
            optimization_result.get("solver_result") or {}
        ).get("charge_schedule"),
        "trips": trip_count_by_type,
    }


def _simulation_result_payload(simulation_result: Dict[str, Any]) -> Dict[str, Any]:
    sim_summary = dict(simulation_result.get("simulation_summary") or {})
    feasibility = dict(sim_summary.get("feasibility_report") or {})
    summary = dict(simulation_result.get("summary") or {})
    trip_count_by_type = dict(summary.get("trip_count_by_type") or {})
    return {
        "status": "FEASIBLE" if feasibility.get("feasible", True) else "INFEASIBLE",
        "objective_value": sim_summary.get("total_operating_cost"),
        "total_cost_jpy": sim_summary.get("total_operating_cost"),
        "electricity_cost_jpy": sim_summary.get("total_energy_cost"),
        "diesel_cost_jpy": sim_summary.get("total_fuel_cost"),
        "demand_charge_jpy": sim_summary.get("total_demand_charge"),
        "vehicle_fixed_cost_jpy": 0.0,
        "co2_kg": sim_summary.get("total_co2_kg"),
        "bev_trips": trip_count_by_type.get("BEV"),
        "ice_trips": trip_count_by_type.get("ICE"),
        "total_trips": summary.get("trip_count_served"),
        "total_charging_kwh": sim_summary.get("total_grid_kwh"),
        "peak_charging_kw": sim_summary.get("peak_demand_kw"),
        "cost_breakdown": {
            "electricity": sim_summary.get("total_energy_cost"),
            "diesel": sim_summary.get("total_fuel_cost"),
            "demand": sim_summary.get("total_demand_charge"),
            "total": sim_summary.get("total_operating_cost"),
        },
        "charging_schedule": simulation_result.get("charger_usage_timeline"),
    }


def _experiment_report_payload(
    *,
    report: Any,
    report_type: str,
    scenario_id: str,
    scenario_doc: Dict[str, Any],
    method: str,
    mode: Any,
) -> Dict[str, Any]:
    fleet_entries = _fleet_template_entries(scenario_doc)
    payload = _to_jsonable(report)
    return {
        "report_type": report_type,
        "scenario_id": scenario_id,
        "experiment_id": payload.get("experiment_id"),
        "json_path": str(getattr(report, "json_path", "") or ""),
        "md_path": str(getattr(report, "md_path", "") or ""),
        "method": method,
        "mode": mode,
        "selected_route_labels": _route_labels(scenario_doc),
        "fleet_templates": fleet_entries,
        "service_date": _simulation_config(scenario_doc).get("service_date"),
        "day_type": _simulation_config(scenario_doc).get("day_type"),
        "notes": _simulation_config(scenario_doc).get("experiment_notes"),
        "report": payload,
    }


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    return value
