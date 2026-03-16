import json
from datetime import datetime

from bff.routers.optimization import _rebuild_dispatch_artifacts
from bff.mappers.scenario_to_problemdata import build_problem_data_from_scenario
from bff.store import scenario_store as store
from src.pipeline.solve import solve_problem_data

BASE_SCENARIO_ID = "41c6872a-717a-4357-81b0-87f5812bf06d"
DEPOT_ID = "tsurumaki"
SERVICE_ID = "WEEKDAY"


def build_chargers() -> list[dict]:
    chargers: list[dict] = []
    for i in range(10):
        chargers.append(
            {
                "id": f"{DEPOT_ID}_normal_{i+1:02d}",
                "siteId": DEPOT_ID,
                "powerKw": 50.0,
                "efficiency": 0.95,
            }
        )
    for i in range(5):
        chargers.append(
            {
                "id": f"{DEPOT_ID}_fast_{i+1:02d}",
                "siteId": DEPOT_ID,
                "powerKw": 90.0,
                "efficiency": 0.95,
            }
        )
    return chargers


def apply_pricing_and_solver_setup(scenario_id: str) -> None:
    overlay = store.get_scenario_overlay(scenario_id) or {}

    cost_parameters = dict(overlay.get("cost_parameters") or {})
    cost_parameters.update(
        {
            "diesel_price_per_l": 160.0,
            "grid_flat_price_per_kwh": 28.0,
            "grid_sell_price_per_kwh": 8.0,
            "demand_charge_cost_per_kw": 1800.0,
            "co2_price_per_kg": 3.0,
            "grid_co2_kg_per_kwh": 0.45,
            # half-hour slot scale (0..48)
            "tou_pricing": [
                {"start_hour": 0, "end_hour": 12, "price_per_kwh": 18.0},
                {"start_hour": 12, "end_hour": 34, "price_per_kwh": 28.0},
                {"start_hour": 34, "end_hour": 42, "price_per_kwh": 40.0},
                {"start_hour": 42, "end_hour": 48, "price_per_kwh": 24.0},
            ],
        }
    )

    solver_config = dict(overlay.get("solver_config") or {})
    solver_config.update(
        {
            "mode": "mode_milp_only",
            "time_limit_seconds": 600,
            "mip_gap": 0.01,
        }
    )

    overlay["cost_parameters"] = cost_parameters
    overlay["solver_config"] = solver_config
    store.set_scenario_overlay(scenario_id, overlay)

    simulation_config = store.get_field(scenario_id, "simulation_config") or {}
    if not isinstance(simulation_config, dict):
        simulation_config = {}
    simulation_config["default_turnaround_min"] = 10
    simulation_config["time_limit_seconds"] = 600
    store.set_field(scenario_id, "simulation_config", simulation_config)


def run_once(scenario_id: str, objective_mode: str) -> dict:
    overlay = store.get_scenario_overlay(scenario_id) or {}
    solver_config = dict(overlay.get("solver_config") or {})
    solver_config["objective_mode"] = objective_mode
    overlay["solver_config"] = solver_config
    store.set_scenario_overlay(scenario_id, overlay)

    _rebuild_dispatch_artifacts(scenario_id, SERVICE_ID, DEPOT_ID)

    scenario = store.get_scenario_document_shallow(scenario_id)
    scenario["trips"] = store.get_field(scenario_id, "trips") or []
    scenario["duties"] = store.get_field(scenario_id, "duties") or []
    scenario["blocks"] = store.get_field(scenario_id, "blocks") or []
    scenario["timetable_rows"] = store.get_field(scenario_id, "timetable_rows") or []

    data, report = build_problem_data_from_scenario(
        scenario,
        depot_id=DEPOT_ID,
        service_id=SERVICE_ID,
        mode="mode_milp_only",
        use_existing_duties=False,
        analysis_scope=store.get_dispatch_scope(scenario_id),
    )

    solved = solve_problem_data(
        data,
        mode="mode_milp_only",
        time_limit_seconds=600,
        mip_gap=0.01,
        random_seed=42,
        output_dir="output",
    )

    result = solved.get("result")
    sim_result = solved.get("sim_result")

    return {
        "objective_mode": objective_mode,
        "status": getattr(result, "status", None),
        "objective_value": getattr(result, "objective_value", None),
        "solve_time_sec": getattr(result, "solve_time_sec", None),
        "mip_gap": getattr(result, "mip_gap", None),
        "unserved_tasks": len(getattr(result, "unserved_tasks", []) or []),
        "infeasibility_info": getattr(result, "infeasibility_info", None),
        "vehicles": len(getattr(data, "vehicles", []) or []),
        "tasks": len(getattr(data, "tasks", []) or []),
        "chargers": len(getattr(data, "chargers", []) or []),
        "dispatch_warnings": list(getattr(report, "warnings", []) or []),
        "sim_total_co2_kg": getattr(sim_result, "total_co2_kg", None) if sim_result is not None else None,
        "sim_total_cost": getattr(sim_result, "total_operating_cost", None) if sim_result is not None else None,
    }


def main() -> None:
    duplicated = store.duplicate_scenario(
        BASE_SCENARIO_ID,
        name=f"tsurumaki_2obj_charger_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
    )
    scenario_id = str(duplicated.get("id") or "")
    if not scenario_id:
        raise RuntimeError("Failed to create duplicated scenario")

    store.set_field(scenario_id, "chargers", build_chargers())
    apply_pricing_and_solver_setup(scenario_id)

    total_cost_result = run_once(scenario_id, "total_cost")
    co2_result = run_once(scenario_id, "co2")

    payload = {
        "timestamp": datetime.now().isoformat(),
        "base_scenario_id": BASE_SCENARIO_ID,
        "scenario_id": scenario_id,
        "depot_id": DEPOT_ID,
        "service_id": SERVICE_ID,
        "charger_setup": {
            "normal_50kw": 10,
            "fast_90kw": 5,
        },
        "assumptions": {
            "diesel_price_per_l": 160.0,
            "grid_flat_price_per_kwh": 28.0,
            "grid_sell_price_per_kwh": 8.0,
            "demand_charge_cost_per_kw": 1800.0,
            "co2_price_per_kg": 3.0,
            "grid_co2_kg_per_kwh": 0.45,
            "default_turnaround_min": 10,
            "time_limit_seconds": 600,
            "mip_gap": 0.01,
        },
        "runs": [total_cost_result, co2_result],
    }

    with open("tmp_tsurumaki_two_objectives_result.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("wrote tmp_tsurumaki_two_objectives_result.json")


if __name__ == "__main__":
    main()
