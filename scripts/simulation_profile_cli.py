from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from bff.routers import scenarios, simulation
from bff.services.simulation_builder import apply_builder_configuration
from bff.store import scenario_store


def _profile_output_path(scenario_id: str) -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "outputs"
        / "scenario_profiles"
        / f"{scenario_id}.json"
    )


def _load_bootstrap(scenario_id: str) -> Dict[str, Any]:
    return scenarios.get_editor_bootstrap(scenario_id)


def _first_defined(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value is not None:
            return value
    return default


def _current_profile_payload(scenario_id: str) -> Dict[str, Any]:
    bootstrap = _load_bootstrap(scenario_id)
    doc = scenario_store.get_scenario_document(scenario_id, repair_missing_master=False)
    defaults = dict(bootstrap.get("builderDefaults") or {})
    simulation_config = dict(doc.get("simulation_config") or {})
    overlay = dict(doc.get("scenario_overlay") or {})
    solver_config = dict(overlay.get("solver_config") or {})

    payload = {
        "selected_depot_ids": list(defaults.get("selectedDepotIds") or []),
        "selected_route_ids": list(defaults.get("selectedRouteIds") or []),
        "day_type": defaults.get("dayType") or "WEEKDAY",
        "service_date": defaults.get("serviceDate"),
        "simulation_settings": {
            "vehicle_template_id": defaults.get("vehicleTemplateId"),
            "vehicle_count": int(defaults.get("vehicleCount") or 0),
            "initial_soc": float(defaults.get("initialSoc") or 0.8),
            "battery_kwh": defaults.get("batteryKwh"),
            "fleet_templates": list(defaults.get("fleetTemplates") or []),
            "charger_count": int(defaults.get("chargerCount") or 0),
            "charger_power_kw": float(defaults.get("chargerPowerKw") or 0.0),
            "solver_mode": defaults.get("solverMode") or "mode_milp_only",
            "objective_mode": defaults.get("objectiveMode") or "total_cost",
            "allow_partial_service": bool(defaults.get("allowPartialService") or False),
            "unserved_penalty": float(defaults.get("unservedPenalty") or 10000.0),
            "time_limit_seconds": int(defaults.get("timeLimitSeconds") or 300),
            "mip_gap": float(defaults.get("mipGap") or 0.01),
            "include_deadhead": bool(defaults.get("includeDeadhead", True)),
            "grid_flat_price_per_kwh": defaults.get("gridFlatPricePerKwh"),
            "grid_sell_price_per_kwh": defaults.get("gridSellPricePerKwh"),
            "demand_charge_cost_per_kw": defaults.get("demandChargeCostPerKw"),
            "diesel_price_per_l": defaults.get("dieselPricePerL"),
            "grid_co2_kg_per_kwh": defaults.get("gridCo2KgPerKwh"),
            "co2_price_per_kg": defaults.get("co2PricePerKg"),
            "depot_power_limit_kw": defaults.get("depotPowerLimitKw"),
            "tou_pricing": list(defaults.get("touPricing") or []),
            "service_date": defaults.get("serviceDate"),
            "start_time": simulation_config.get("start_time") or "05:00",
            "planning_horizon_hours": simulation_config.get("planning_horizon_hours") or 20.0,
            "alns_iterations": int(
                simulation_config.get("alns_iterations")
                or solver_config.get("alns_iterations")
                or 500
            ),
            "random_seed": _first_defined(
                simulation_config.get("random_seed"),
                overlay.get("random_seed"),
            ),
            "experiment_method": simulation_config.get("experiment_method"),
            "experiment_notes": simulation_config.get("experiment_notes"),
        },
        "_meta": _profile_meta(bootstrap),
    }
    return payload


def _profile_meta(bootstrap: Dict[str, Any]) -> Dict[str, Any]:
    depots = [
        {
            "depot_id": item.get("id"),
            "name": item.get("name"),
        }
        for item in bootstrap.get("depots") or []
    ]
    routes_by_depot = {}
    route_lookup = {
        str(route.get("id") or ""): route
        for route in bootstrap.get("routes") or []
        if str(route.get("id") or "")
    }
    for depot_id, route_ids in dict(bootstrap.get("depotRouteIndex") or {}).items():
        routes_by_depot[depot_id] = [
            {
                "route_id": route_id,
                "label": (
                    route_lookup.get(route_id, {}).get("displayName")
                    or route_lookup.get(route_id, {}).get("routeCode")
                    or route_lookup.get(route_id, {}).get("name")
                    or route_id
                ),
                "start_stop": route_lookup.get(route_id, {}).get("startStop"),
                "end_stop": route_lookup.get(route_id, {}).get("endStop"),
                "trip_count": route_lookup.get(route_id, {}).get("tripCount"),
            }
            for route_id in route_ids
        ]
    vehicle_templates = [
        {
            "vehicle_template_id": item.get("id"),
            "name": item.get("name"),
            "type": item.get("type"),
            "battery_kwh": item.get("batteryKwh"),
            "charge_power_kw": item.get("chargePowerKw"),
            "fuel_tank_l": item.get("fuelTankL"),
        }
        for item in bootstrap.get("vehicleTemplates") or []
    ]
    return {
        "usage": {
            "edit": "selected_depot_ids, selected_route_ids, simulation_settings.* を編集して apply してください。",
            "commands": [
                "python -m scripts.simulation_profile_cli export --scenario <scenario_id>",
                "python -m scripts.simulation_profile_cli apply --scenario <scenario_id> --input <profile.json>",
                "python -m scripts.simulation_profile_cli show --scenario <scenario_id>",
            ],
        },
        "depots": depots,
        "routes_by_depot": routes_by_depot,
        "vehicle_templates": vehicle_templates,
    }


def _template_name_lookup(meta: Dict[str, Any]) -> Dict[str, str]:
    return {
        str(item.get("vehicle_template_id") or ""): str(
            item.get("name") or item.get("vehicle_template_id") or ""
        )
        for item in meta.get("vehicle_templates") or []
        if str(item.get("vehicle_template_id") or "")
    }


def _route_label_lookup(meta: Dict[str, Any]) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    for items in dict(meta.get("routes_by_depot") or {}).values():
        for item in items or []:
            route_id = str(item.get("route_id") or "")
            if route_id:
                labels[route_id] = str(item.get("label") or route_id)
    return labels


def export_profile(scenario_id: str, output: Path) -> Path:
    payload = _current_profile_payload(scenario_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output


def apply_profile(scenario_id: str, input_path: Path) -> Dict[str, Any]:
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    body = simulation.PrepareSimulationBody.model_validate(payload)
    return apply_builder_configuration(scenario_id, body)


def show_profile(scenario_id: str) -> None:
    payload = _current_profile_payload(scenario_id)
    settings = dict(payload.get("simulation_settings") or {})
    meta = dict(payload.get("_meta") or {})
    route_lookup = _route_label_lookup(meta)
    template_lookup = _template_name_lookup(meta)
    selected_route_ids = [str(item) for item in payload.get("selected_route_ids") or []]
    selected_route_labels = [
        route_lookup.get(route_id, route_id) for route_id in selected_route_ids
    ]
    fleet_templates = list(settings.get("fleet_templates") or [])

    print(f"scenario: {scenario_id}")
    print(f"depots: {', '.join(payload.get('selected_depot_ids') or ['-'])}")
    print(f"day_type: {payload.get('day_type') or '-'}")
    print(f"service_date: {payload.get('service_date') or '-'}")
    print(
        "routes: "
        f"{len(selected_route_ids)} selected"
        + (f" ({', '.join(selected_route_labels)})" if selected_route_labels else "")
    )
    print("")
    print("[fleet]")
    if fleet_templates:
        for item in fleet_templates:
            template_id = str(item.get("vehicle_template_id") or "")
            template_name = template_lookup.get(template_id, template_id)
            print(
                f"- {template_name}: count={int(item.get('vehicle_count') or 0)}, "
                f"initial_soc={item.get('initial_soc')}, "
                f"battery_kwh={item.get('battery_kwh')}, "
                f"charge_power_kw={item.get('charge_power_kw')}"
            )
    else:
        template_id = str(settings.get("vehicle_template_id") or "")
        print(
            f"- single_template={template_lookup.get(template_id, template_id or '-')}, "
            f"vehicle_count={int(settings.get('vehicle_count') or 0)}, "
            f"initial_soc={settings.get('initial_soc')}, "
            f"battery_kwh={settings.get('battery_kwh')}, "
            f"charger_power_kw={settings.get('charger_power_kw')}"
        )
    print("")
    print("[charging]")
    print(
        f"charger_count={int(settings.get('charger_count') or 0)}, "
        f"charger_power_kw={settings.get('charger_power_kw')}, "
        f"depot_power_limit_kw={settings.get('depot_power_limit_kw')}"
    )
    print("")
    print("[solver]")
    print(
        f"solver_mode={settings.get('solver_mode')}, "
        f"objective_mode={settings.get('objective_mode')}, "
        f"time_limit_seconds={settings.get('time_limit_seconds')}, "
        f"mip_gap={settings.get('mip_gap')}, "
        f"alns_iterations={settings.get('alns_iterations')}, "
        f"random_seed={settings.get('random_seed')}, "
        f"allow_partial_service={settings.get('allow_partial_service')}, "
        f"include_deadhead={settings.get('include_deadhead')}"
    )
    print("")
    print("[costs]")
    print(
        f"grid_flat_price_per_kwh={settings.get('grid_flat_price_per_kwh')}, "
        f"grid_sell_price_per_kwh={settings.get('grid_sell_price_per_kwh')}, "
        f"demand_charge_cost_per_kw={settings.get('demand_charge_cost_per_kw')}, "
        f"diesel_price_per_l={settings.get('diesel_price_per_l')}, "
        f"grid_co2_kg_per_kwh={settings.get('grid_co2_kg_per_kwh')}, "
        f"co2_price_per_kg={settings.get('co2_price_per_kg')}"
    )
    tou_pricing = list(settings.get("tou_pricing") or [])
    if tou_pricing:
        print("tou_pricing:")
        for item in tou_pricing:
            print(
                f"- {item.get('start_hour')}:00-{item.get('end_hour')}:00 "
                f"=> {item.get('price_per_kwh')} JPY/kWh"
            )
    print("")
    print("[experiment]")
    print(
        f"method={settings.get('experiment_method') or '-'}\n"
        f"notes={settings.get('experiment_notes') or '-'}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="simulation profile JSON を export/apply する lightweight CLI"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    export_parser = subparsers.add_parser("export", help="現在の profile JSON を書き出す")
    export_parser.add_argument("--scenario", required=True, help="scenario id")
    export_parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="出力先。未指定時は outputs/scenario_profiles/<scenario>.json",
    )

    apply_parser = subparsers.add_parser("apply", help="profile JSON を scenario に適用する")
    apply_parser.add_argument("--scenario", required=True, help="scenario id")
    apply_parser.add_argument("--input", type=Path, required=True, help="profile JSON")

    show_parser = subparsers.add_parser("show", help="現在の profile JSON を標準出力する")
    show_parser.add_argument("--scenario", required=True, help="scenario id")

    args = parser.parse_args()

    if args.command == "export":
        output = args.output or _profile_output_path(args.scenario)
        path = export_profile(args.scenario, output)
        print(f"exported: {path}")
        return 0
    if args.command == "apply":
        doc = apply_profile(args.scenario, args.input)
        dispatch_scope = dict(doc.get("dispatch_scope") or {})
        simulation_config = dict(doc.get("simulation_config") or {})
        print(
            json.dumps(
                {
                    "scenario_id": args.scenario,
                    "applied": True,
                    "primary_depot_id": dispatch_scope.get("depotId"),
                    "service_id": dispatch_scope.get("serviceId"),
                    "route_ids": ((dispatch_scope.get("routeSelection") or {}).get("includeRouteIds") or []),
                    "fleet_templates": simulation_config.get("fleet_templates") or [],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "show":
        show_profile(args.scenario)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
