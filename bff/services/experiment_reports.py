from __future__ import annotations

from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Dict

from experiment_logger import ExperimentLogger
from bff.store import output_paths
from src.optimization.common.energy_flow_accounting import normalize_pv_energy_breakdown


def log_optimization_experiment(
    *,
    scenario_id: str,
    scenario_doc: Dict[str, Any],
    optimization_result: Dict[str, Any],
    accounting_summary_override: Dict[str, Any] | None = None,
    git_commit_override: str | None = None,
) -> Dict[str, Any]:
    method = _optimization_method_label(scenario_doc, optimization_result)
    solver_settings = dict(optimization_result.get("solver_settings") or {})

    def first_not_none(*values: Any) -> Any:
        return next((value for value in values if value is not None), None)

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
            result_summary=dict(optimization_result.get("summary") or {}),
        ),
        result=_optimization_result_payload(
            optimization_result,
            accounting_summary_override=accounting_summary_override,
        ),
        method=method,
        seed=_random_seed(scenario_doc),
        extra_solver={
            # ``mip_gap_pct`` is retained only for the generic result schema.
            # Prefer Gurobi's native Stage 1 gap when available; the report's
            # explicit requested/raw/certified fields below carry the research
            # semantics without conflating them.
            "mip_gap_pct": first_not_none(
                solver_settings.get("stage1_gurobi_raw_mip_gap_percent"),
                solver_settings.get("mip_gap_achieved_percent"),
            ),
            "mip_gap_requested_pct": solver_settings.get("mip_gap_requested_percent"),
            "stage1_gurobi_raw_mip_gap_pct": solver_settings.get(
                "stage1_gurobi_raw_mip_gap_percent"
            ),
            "stage1_certified_mip_gap_pct": solver_settings.get(
                "stage1_certified_mip_gap_percent"
            ),
            "stage1_certified_mip_gap_semantics": solver_settings.get(
                "stage1_certified_mip_gap_semantics"
            ),
            "stage1_termination_reason": solver_settings.get(
                "stage1_termination_reason"
            ),
            "threads": solver_settings.get("gurobi_threads"),
        },
        git_commit=git_commit_override,
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
    overlay = _scenario_overlay(scenario_doc)
    simulation_cfg = _simulation_config(scenario_doc)
    solver_config = dict(overlay.get("solver_config") or {})
    mode = solver_config.get("mode")
    method = _method_label(scenario_doc, mode)
    logger = ExperimentLogger(results_dir=_results_dir(scenario_id, "simulation"))
    report = logger.log(
        scenario=_logger_scenario_payload(
            scenario_doc=scenario_doc,
            objective=str(
                solver_config.get("objective_mode")
                or simulation_cfg.get("objective_mode")
                or "total_cost"
            ),
            method=method,
            mode=mode,
            result_summary=dict(simulation_result.get("summary") or {}),
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
        mode=mode,
    )


def _results_dir(scenario_id: str, report_type: str) -> Path:
    return output_paths.outputs_root() / "experiments" / scenario_id / report_type


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


def _optimization_method_label(
    scenario_doc: Dict[str, Any], optimization_result: Dict[str, Any]
) -> str:
    metadata = dict(optimization_result.get("solver_metadata") or {})
    phase = str(
        metadata.get("executed_phase")
        or metadata.get("resolved_phase")
        or optimization_result.get("phase")
        or ""
    ).strip().lower()
    if phase == "phase3_two_stage":
        if bool(metadata.get("successor_pruning_enabled", False)):
            return "二段階MILP（接続候補を削減）"
        return "二段階MILP"
    return _method_label(scenario_doc, optimization_result.get("mode"))


def _ratio_to_percent(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value) * 100.0


def _vehicle_type_label(item: Dict[str, Any]) -> str:
    return str(
        item.get("vehicle_type")
        or item.get("vehicleType")
        or item.get("powertrain_type")
        or item.get("powertrainType")
        or item.get("type")
        or "UNKNOWN"
    ).strip().upper() or "UNKNOWN"


def _first_present_text(item: Dict[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = str(item.get(field) or "").strip()
        if value:
            return value
    return ""


def _aggregate_fleet_entries(
    items: Any,
    *,
    default_count: int,
    count_fields: tuple[str, ...],
    name_fields: tuple[str, ...],
    id_fields: tuple[str, ...],
) -> list[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        vehicle_type = _vehicle_type_label(item)
        if not vehicle_type or vehicle_type == "UNKNOWN":
            continue
        count = default_count
        for field in count_fields:
            candidate = item.get(field)
            if candidate is None or candidate == "":
                continue
            try:
                count = max(int(candidate), 0)
                break
            except (TypeError, ValueError):
                continue
        if count <= 0:
            continue
        bucket = grouped.setdefault(
            vehicle_type,
            {
                "vehicle_type": vehicle_type,
                "vehicle_count": 0,
                "template_names": [],
                "template_ids": [],
            },
        )
        bucket["vehicle_count"] = int(bucket["vehicle_count"] or 0) + int(count)
        name = _first_present_text(item, name_fields)
        if name and name not in bucket["template_names"]:
            bucket["template_names"].append(name)
        template_id = _first_present_text(item, id_fields)
        if template_id and template_id not in bucket["template_ids"]:
            bucket["template_ids"].append(template_id)

    entries: list[Dict[str, Any]] = []
    for vehicle_type in sorted(grouped.keys()):
        bucket = grouped[vehicle_type]
        template_names = list(bucket.pop("template_names") or [])
        template_ids = list(bucket.pop("template_ids") or [])
        if not template_names:
            template_name = vehicle_type
        elif len(template_names) == 1:
            template_name = template_names[0]
        elif len(template_names) == 2:
            template_name = " + ".join(template_names)
        else:
            template_name = f"{template_names[0]} + {len(template_names) - 1} more"
        if not template_ids:
            template_id = vehicle_type.lower()
        elif len(template_ids) == 1:
            template_id = template_ids[0]
        else:
            template_id = f"{vehicle_type.lower()}_fleet"
        entries.append(
            {
                "vehicle_template_id": template_id,
                "template_name": template_name,
                "vehicle_type": vehicle_type,
                "vehicle_count": int(bucket["vehicle_count"] or 0),
            }
        )
    return entries


def _solver_name(mode: Any) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized in {"mode_alns_only", "alns"}:
        return "alns"
    if normalized in {"mode_alns_milp", "hybrid"}:
        return "gurobi+alns"
    return "gurobi"


def _fleet_template_entries(
    scenario_doc: Dict[str, Any],
    result_summary: Dict[str, Any] | None = None,
) -> list[Dict[str, Any]]:
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
    entries = [item for item in entries if item["vehicle_count"] > 0]
    if entries:
        return entries

    fallback_sources = (
        simulation_config.get("vehicles") or [],
        scenario_doc.get("vehicles") or [],
        simulation_config.get("vehicle_templates") or [],
        scenario_doc.get("vehicle_templates") or [],
    )
    for fallback_items in fallback_sources:
        fallback_entries = _aggregate_fleet_entries(
            fallback_items,
            default_count=1,
            count_fields=("vehicle_count", "count", "quantity", "num_vehicles", "fleet_count"),
            name_fields=("name", "modelName", "model_name", "vehicle_template_id", "id", "vehicle_id"),
            id_fields=("vehicle_template_id", "vehicleTemplateId", "id", "vehicle_id"),
        )
        if fallback_entries:
            return fallback_entries

    summary_counts = dict((result_summary or {}).get("vehicle_count_by_type") or {})
    if summary_counts:
        summary_entries: list[Dict[str, Any]] = []
        for vehicle_type, count in sorted(summary_counts.items()):
            vehicle_type_label = str(vehicle_type or "UNKNOWN").strip().upper() or "UNKNOWN"
            try:
                vehicle_count = int(count)
            except (TypeError, ValueError):
                continue
            if vehicle_type_label == "UNKNOWN" or vehicle_count <= 0:
                continue
            summary_entries.append(
                {
                    "vehicle_template_id": vehicle_type_label.lower(),
                    "template_name": vehicle_type_label,
                    "vehicle_type": vehicle_type_label,
                    "vehicle_count": vehicle_count,
                }
            )
        if summary_entries:
            return summary_entries

    return []


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
    result_summary: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    overlay = _scenario_overlay(scenario_doc)
    simulation_config = _simulation_config(scenario_doc)
    fleet_entries = _fleet_template_entries(scenario_doc, result_summary=result_summary)
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
    vehicle_usage_cost = simulation_config.get("vehicle_usage_cost_jpy_per_used_bus")
    if vehicle_usage_cost is None:
        vehicle_usage_cost = cost_coefficients.get("vehicle_usage_cost_jpy_per_used_bus")
    if vehicle_usage_cost is None:
        vehicle_usage_cost = (solver_config.get("objective_weights") or {}).get(
            "vehicle_fixed_cost"
        )
    if vehicle_usage_cost is None:
        vehicle_usage_cost = 0.0
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
                vehicle_usage_cost
            ),
        },
        "grid": {
            "max_kw": float(charging_constraints.get("depot_power_limit_kw") or 0.0),
        },
        "pv": {
            "capacity_kw": _pv_capacity_kw(scenario_doc),
        },
        "solver": {
            "name": _solver_name(mode),
            "time_limit_sec": int(solver_config.get("time_limit_seconds") or 0),
            "mip_gap_pct": _ratio_to_percent(solver_config.get("mip_gap")),
            "seed": _random_seed(scenario_doc),
        },
        # These fields are included in the experiment hash even though the
        # compact report dataclasses do not display them. Runs for different
        # service dates or effective energy inputs must not share a hash.
        "service_date": simulation_config.get("service_date"),
        "weather_reference_date": simulation_config.get("weather_reference_date"),
        "weather_profile": simulation_config.get("weather_profile"),
        "weather_operation_mode": simulation_config.get("weather_operation_mode"),
        "depot_energy_assets": simulation_config.get("depot_energy_assets") or [],
    }


def _pv_capacity_kw(scenario_doc: Dict[str, Any]) -> float:
    simulation_config = _simulation_config(scenario_doc)
    asset_sources = (
        simulation_config.get("depot_energy_assets") or [],
        scenario_doc.get("depot_energy_assets") or [],
    )
    for assets in asset_sources:
        total_capacity_kw = 0.0
        has_capacity = False
        for asset in list(assets or []):
            if not isinstance(asset, dict):
                continue
            for field in ("derived_pv_capacity_kw", "pv_capacity_kw", "legacy_pv_capacity_kw"):
                candidate = asset.get(field)
                if candidate is None or candidate == "":
                    continue
                try:
                    total_capacity_kw += float(candidate)
                    has_capacity = True
                    break
                except (TypeError, ValueError):
                    continue
        if has_capacity and total_capacity_kw > 0.0:
            return total_capacity_kw

    cost_coefficients = dict(_scenario_overlay(scenario_doc).get("cost_coefficients") or {})
    return float(cost_coefficients.get("pv_scale") or 0.0)


def _optimization_result_payload(
    optimization_result: Dict[str, Any],
    *,
    accounting_summary_override: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    cost_breakdown = dict(optimization_result.get("cost_breakdown") or {})
    cost_breakdown.update(normalize_pv_energy_breakdown(cost_breakdown))
    summary = dict(optimization_result.get("summary") or {})
    accounting_summary = dict(
        accounting_summary_override
        if accounting_summary_override is not None
        else ((optimization_result.get("graph_artifacts") or {}).get("accounting_summary"))
        or {}
    )
    trip_count_by_type = dict(summary.get("trip_count_by_type") or {})
    simulation_summary = dict(optimization_result.get("simulation_summary") or {})
    solver_settings = dict(optimization_result.get("solver_settings") or {})
    solver_metadata = dict(optimization_result.get("solver_metadata") or {})
    if accounting_summary.get("unserved_trip_count") is not None:
        trip_count_unserved = int(accounting_summary["unserved_trip_count"])
    elif summary.get("trip_count_unserved") is not None:
        trip_count_unserved = int(summary["trip_count_unserved"])
    else:
        trip_count_unserved = len(optimization_result.get("unserved_trip_ids") or [])
    electricity_cost_final = (
        cost_breakdown.get("electricity_cost_final")
        if cost_breakdown.get("electricity_cost_final") is not None
        else cost_breakdown.get("energy_cost")
    )
    electricity_cost_leftover = (
        cost_breakdown.get("electricity_cost_provisional_leftover")
        if cost_breakdown.get("electricity_cost_provisional_leftover") is not None
        else simulation_summary.get("electricity_cost_provisional_leftover_jpy")
    )
    achieved_gap_percent = solver_settings.get("mip_gap_achieved_percent")
    if achieved_gap_percent is None:
        achieved_gap_percent = accounting_summary.get("mip_gap_achieved_percent")
    if achieved_gap_percent is None:
        achieved_gap_percent = _ratio_to_percent(
            optimization_result.get("mip_gap", solver_metadata.get("achieved_mip_gap"))
        )
    stage1_gurobi_raw_gap_percent = solver_settings.get(
        "stage1_gurobi_raw_mip_gap_percent"
    )
    reported_gap_percent = (
        stage1_gurobi_raw_gap_percent
        if stage1_gurobi_raw_gap_percent is not None
        else achieved_gap_percent
    )
    accounting_total_cost = accounting_summary.get(
        "accounting_total_cost_jpy", accounting_summary.get("total_cost_jpy")
    )
    accounting_electricity_cost = electricity_cost_final
    if accounting_summary.get("energy_cost_jpy") is not None:
        # Use the canonical aggregate directly when it exists. Re-adding its
        # components can introduce a binary floating-point representation
        # change even when the monetary value is identical.
        accounting_electricity_cost = accounting_summary["energy_cost_jpy"]
    elif (
        accounting_summary.get("grid_purchase_cost_jpy") is not None
        or accounting_summary.get("bess_total_flow_cost_jpy") is not None
    ):
        # Preserve the canonical ledger value at full precision. Human-facing
        # Markdown may format currency, but machine-readable artifacts must
        # reconcile to executed-day accounting within 1e-6 JPY.
        accounting_electricity_cost = (
            float(accounting_summary.get("grid_purchase_cost_jpy", 0.0) or 0.0)
            + float(accounting_summary.get("bess_total_flow_cost_jpy", 0.0) or 0.0)
        )
    accounting_demand_charge = accounting_summary.get("demand_charge_cost_jpy")
    if accounting_demand_charge is None:
        accounting_demand_charge = (
            cost_breakdown.get("demand_charge")
            if cost_breakdown.get("demand_charge") is not None
            else cost_breakdown.get("demand_cost")
        )
    canonical_cost_components = dict(
        accounting_summary.get("canonical_cost_components_jpy") or {}
    )
    vehicle_usage_cost_jpy = accounting_summary.get(
        "vehicle_usage_cost_jpy",
        canonical_cost_components.get(
            "vehicle_usage_cost_jpy",
            cost_breakdown.get("vehicle_usage_cost"),
        ),
    )
    vehicle_fixed_cost_jpy = accounting_summary.get(
        "vehicle_fixed_cost_jpy",
        canonical_cost_components.get(
            "vehicle_fixed_cost_jpy",
            cost_breakdown.get(
                "vehicle_cost",
                cost_breakdown.get("vehicle_fixed_cost", 0.0),
            ),
        ),
    )
    vehicle_acquisition_cost_jpy = accounting_summary.get(
        "vehicle_acquisition_cost_jpy",
        cost_breakdown.get("vehicle_acquisition_cost", 0.0),
    )
    report_cost_breakdown = dict(cost_breakdown)
    if accounting_total_cost is not None:
        report_cost_breakdown["total_cost"] = accounting_total_cost
    report_cost_breakdown.update(
        {
            "electricity_cost": accounting_electricity_cost,
            "fuel_cost": accounting_summary.get(
                "fuel_cost_jpy", cost_breakdown.get("fuel_cost")
            ),
            "demand_charge": accounting_demand_charge,
            "vehicle_usage_cost": vehicle_usage_cost_jpy,
            "vehicle_fixed_cost": vehicle_fixed_cost_jpy,
            "vehicle_acquisition_cost": vehicle_acquisition_cost_jpy,
            "co2_cost": accounting_summary.get(
                "co2_cost_jpy", cost_breakdown.get("co2_cost")
            ),
        }
    )
    return {
        "status": str(optimization_result.get("solver_status", "UNKNOWN") or "UNKNOWN").upper(),
        "objective_value": optimization_result.get("objective_value"),
        "total_cost_jpy": accounting_total_cost if accounting_total_cost is not None else cost_breakdown.get("total_cost"),
        "electricity_cost_jpy": accounting_electricity_cost,
        "electricity_cost_final_jpy": accounting_electricity_cost,
        "electricity_cost_provisional_leftover_jpy": electricity_cost_leftover,
        "diesel_cost_jpy": accounting_summary.get("fuel_cost_jpy", cost_breakdown.get("fuel_cost")),
        "demand_charge_jpy": accounting_demand_charge,
        "vehicle_usage_cost_jpy": vehicle_usage_cost_jpy,
        "vehicle_fixed_cost_jpy": vehicle_fixed_cost_jpy,
        "vehicle_acquisition_cost_jpy": vehicle_acquisition_cost_jpy,
        "co2_cost_jpy": accounting_summary.get(
            "co2_cost_jpy", cost_breakdown.get("co2_cost")
        ),
        "canonical_cost_components_jpy": dict(
            accounting_summary.get("canonical_cost_components_jpy") or {}
        ),
        "canonical_cost_component_status": dict(
            accounting_summary.get("canonical_cost_component_status") or {}
        ),
        "return_leg_bonus_jpy": cost_breakdown.get("return_leg_bonus"),
        "grid_to_bus_kwh": cost_breakdown.get("grid_to_bus_kwh"),
        "bess_to_bus_kwh": cost_breakdown.get("bess_to_bus_kwh"),
        "pv_to_bess_kwh": cost_breakdown.get("pv_to_bess_kwh"),
        "grid_to_bess_kwh": cost_breakdown.get("grid_to_bess_kwh"),
        "co2_kg": accounting_summary.get("total_co2_kg", cost_breakdown.get("total_co2_kg")),
        "bev_trips": accounting_summary.get("bev_trip_count", trip_count_by_type.get("BEV")),
        "ice_trips": accounting_summary.get("ice_trip_count", trip_count_by_type.get("ICE")),
        "total_trips": accounting_summary.get("served_trip_count", summary.get("trip_count_served")),
        "trip_count_unserved": trip_count_unserved,
        "coverage_rank_primary": int(summary.get("coverage_rank_primary") or trip_count_unserved),
        "secondary_objective_value": summary.get("secondary_objective_value"),
        "total_charging_kwh": simulation_summary.get("total_grid_kwh"),
        "peak_charging_kw": simulation_summary.get("peak_demand_kw"),
        "solve_time_sec": optimization_result.get("solve_time_seconds"),
        # Generic report consumers receive the solver-native result when the
        # two-stage telemetry exists.  The detailed distinction is emitted by
        # ``log_optimization_experiment`` via SolverSettings.
        "mip_gap_pct": reported_gap_percent,
        "bev_terminal_soc_policy": solver_metadata.get("bev_terminal_soc_policy"),
        "bev_terminal_soc_balance_satisfied": solver_metadata.get(
            "bev_terminal_soc_balance_satisfied"
        ),
        "bev_terminal_soc_total_drawdown_kwh": solver_metadata.get(
            "bev_terminal_soc_total_drawdown_kwh"
        ),
        "cost_breakdown": report_cost_breakdown,
        "charging_schedule": (
            optimization_result.get("solver_result") or {}
        ).get("charge_schedule"),
        "trips": trip_count_by_type,
        "objective_is_actual_cost": bool(accounting_summary.get("objective_is_actual_cost", False)),
        "total_cost_definition": "canonical_accounting_total",
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
        "vehicle_usage_cost_jpy": 0.0,
        "vehicle_fixed_cost_jpy": 0.0,
        "vehicle_acquisition_cost_jpy": 0.0,
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
    result_summary: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    simulation_cfg = _simulation_config(scenario_doc)
    fleet_entries = _fleet_template_entries(scenario_doc, result_summary=result_summary)
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
        "service_date": simulation_cfg.get("service_date"),
        "day_type": simulation_cfg.get("day_type"),
        "notes": simulation_cfg.get("experiment_notes"),
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
