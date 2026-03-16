import json
from copy import deepcopy
from datetime import datetime

from bff.routers.optimization import _rebuild_dispatch_artifacts
from bff.mappers.scenario_to_problemdata import build_problem_data_from_scenario
from bff.store import scenario_store as store
from src.pipeline.solve import solve_problem_data

SCENARIO_ID = "41c6872a-717a-4357-81b0-87f5812bf06d"
DEPOT_ID = "tsurumaki"
SERVICE_ID = "WEEKDAY"
TIME_LIMIT_SEC = 600
MIP_GAP = 0.01
RANDOM_SEED = 42


def _build_chargers() -> list[dict]:
    chargers: list[dict] = []
    for i in range(10):
        chargers.append(
            {
                "id": f"{DEPOT_ID}_ac50_{i+1:02d}",
                "siteId": DEPOT_ID,
                "powerKw": 50.0,
                "efficiency": 0.95,
                "power_min_kw": 0.0,
            }
        )
    for i in range(5):
        chargers.append(
            {
                "id": f"{DEPOT_ID}_dc90_{i+1:02d}",
                "siteId": DEPOT_ID,
                "powerKw": 90.0,
                "efficiency": 0.94,
                "power_min_kw": 0.0,
            }
        )
    return chargers


def _apply_common_settings(scenario: dict) -> None:
    scenario["chargers"] = _build_chargers()

    overlay = dict(scenario.get("scenario_overlay") or {})
    overlay_cost = dict(overlay.get("cost_parameters") or {})

    # Realistic-ish Japan urban assumptions (2026):
    # diesel ~150 JPY/L, TOU 15-46 JPY/kWh, demand charge ~1800 JPY/kW-month equivalent.
    overlay_cost.update(
        {
            "diesel_price_per_l": 150.0,
            "grid_flat_price_per_kwh": 27.0,
            "grid_sell_price_per_kwh": 8.0,
            "demand_charge_cost_per_kw": 1800.0,
            "co2_price_per_kg": 8.0,
            "grid_co2_kg_per_kwh": 0.43,
            "tou_pricing": [
                {"start_hour": 0, "end_hour": 14, "price_per_kwh": 15.0},
                {"start_hour": 14, "end_hour": 34, "price_per_kwh": 31.0},
                {"start_hour": 34, "end_hour": 44, "price_per_kwh": 46.0},
                {"start_hour": 44, "end_hour": 48, "price_per_kwh": 22.0},
            ],
        }
    )
    overlay["cost_parameters"] = overlay_cost

    overlay_charging = dict(overlay.get("charging_constraints") or {})
    overlay_charging.update(
        {
            "depot_power_limit_kw": 1200.0,
            "grid_import_limit_kw": 1200.0,
            "contract_demand_limit_kw": 1200.0,
        }
    )
    overlay["charging_constraints"] = overlay_charging

    scenario["scenario_overlay"] = overlay

    if not isinstance(scenario.get("simulation_config"), dict):
        scenario["simulation_config"] = {}
    scenario["simulation_config"]["default_turnaround_min"] = 10
    scenario["simulation_config"]["time_limit_seconds"] = TIME_LIMIT_SEC


def _run_case(base_scenario: dict, objective_mode: str) -> dict:
    scenario = deepcopy(base_scenario)
    scenario["simulation_config"] = dict(scenario.get("simulation_config") or {})
    scenario["simulation_config"]["objective_mode"] = objective_mode

    data, report = build_problem_data_from_scenario(
        scenario,
        depot_id=DEPOT_ID,
        service_id=SERVICE_ID,
        mode="mode_milp_only",
        use_existing_duties=False,
        analysis_scope=store.get_dispatch_scope(SCENARIO_ID),
    )

    solved = solve_problem_data(
        data,
        mode="mode_milp_only",
        time_limit_seconds=TIME_LIMIT_SEC,
        mip_gap=MIP_GAP,
        random_seed=RANDOM_SEED,
        output_dir="output",
    )

    result = solved.get("result")
    sim_result = solved.get("sim_result")

    return {
        "objective_mode": objective_mode,
        "vehicles": len(getattr(data, "vehicles", []) or []),
        "tasks": len(getattr(data, "tasks", []) or []),
        "status": getattr(result, "status", None),
        "objective_value": getattr(result, "objective_value", None),
        "solve_time_sec": getattr(result, "solve_time_sec", None),
        "mip_gap": getattr(result, "mip_gap", None),
        "unserved_tasks": len(getattr(result, "unserved_tasks", []) or []),
        "infeasibility_info": getattr(result, "infeasibility_info", None),
        "total_cost": getattr(sim_result, "total_cost", None),
        "electricity_cost": getattr(sim_result, "electricity_cost", None),
        "fuel_cost": getattr(sim_result, "fuel_cost", None),
        "demand_charge_cost": getattr(sim_result, "demand_charge_cost", None),
        "total_co2_kg": getattr(sim_result, "total_co2_kg", None),
        "dispatch_warnings": list(getattr(report, "warnings", []) or []),
    }


def main() -> None:
    _rebuild_dispatch_artifacts(SCENARIO_ID, SERVICE_ID, DEPOT_ID)

    scenario = store.get_scenario_document_shallow(SCENARIO_ID)
    scenario["trips"] = store.get_field(SCENARIO_ID, "trips") or []
    scenario["duties"] = store.get_field(SCENARIO_ID, "duties") or []
    scenario["blocks"] = store.get_field(SCENARIO_ID, "blocks") or []
    scenario["timetable_rows"] = store.get_field(SCENARIO_ID, "timetable_rows") or []

    _apply_common_settings(scenario)

    results = [
        _run_case(scenario, "total_cost"),
        _run_case(scenario, "co2"),
    ]

    summary = {
        "timestamp": datetime.now().isoformat(),
        "scenario_id": SCENARIO_ID,
        "depot_id": DEPOT_ID,
        "service_id": SERVICE_ID,
        "solver": {
            "mode": "mode_milp_only",
            "time_limit_seconds": TIME_LIMIT_SEC,
            "mip_gap": MIP_GAP,
            "random_seed": RANDOM_SEED,
        },
        "assumptions": {
            "chargers": {
                "normal_50kw_count": 10,
                "fast_90kw_count": 5,
                "site_id": DEPOT_ID,
            },
            "cost_parameters": {
                "diesel_price_per_l": 150.0,
                "grid_flat_price_per_kwh": 27.0,
                "grid_sell_price_per_kwh": 8.0,
                "demand_charge_cost_per_kw": 1800.0,
                "co2_price_per_kg": 8.0,
                "grid_co2_kg_per_kwh": 0.43,
            },
            "tou_pricing_halfhour": [
                {"start": 0, "end": 14, "price": 15.0},
                {"start": 14, "end": 34, "price": 31.0},
                {"start": 34, "end": 44, "price": 46.0},
                {"start": 44, "end": 48, "price": 22.0},
            ],
            "depot_power_limit_kw": 1200.0,
            "default_turnaround_min": 10,
        },
        "results": results,
    }

    with open("tmp_tsurumaki_two_modes_result.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("wrote tmp_tsurumaki_two_modes_result.json")


if __name__ == "__main__":
    main()
