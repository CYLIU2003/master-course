import json
from datetime import datetime

from bff.routers.optimization import _rebuild_dispatch_artifacts
from bff.mappers.scenario_to_problemdata import build_problem_data_from_scenario
from bff.store import scenario_store as store
from src.pipeline.solve import solve_problem_data

SCENARIO_ID = "41c6872a-717a-4357-81b0-87f5812bf06d"
DEPOT_ID = "tsurumaki"
SERVICE_ID = "WEEKDAY"


def main():
    result_payload = {
        "timestamp": datetime.now().isoformat(),
        "scenario_id": SCENARIO_ID,
        "depot_id": DEPOT_ID,
        "service_id": SERVICE_ID,
    }
    try:
        # Rebuild dispatch artifacts from timetable/shard scope
        _rebuild_dispatch_artifacts(SCENARIO_ID, SERVICE_ID, DEPOT_ID)

        scenario = store.get_scenario_document_shallow(SCENARIO_ID)
        scenario["trips"] = store.get_field(SCENARIO_ID, "trips") or []
        scenario["duties"] = store.get_field(SCENARIO_ID, "duties") or []
        scenario["blocks"] = store.get_field(SCENARIO_ID, "blocks") or []
        scenario["timetable_rows"] = store.get_field(SCENARIO_ID, "timetable_rows") or []

    # Set practical default parameters (user requested arbitrary but reasonable values)
        overlay = dict(scenario.get("scenario_overlay") or {})
        overlay_cost = dict(overlay.get("cost_parameters") or {})
        overlay_cost.update(
            {
                "diesel_price_per_l": 145.0,
                "grid_flat_price_per_kwh": 28.0,
                "grid_sell_price_per_kwh": 0.0,
                "demand_charge_cost_per_kw": 1500.0,
                "co2_price_per_kg": 1.0,
                "grid_co2_kg_per_kwh": 0.45,
            }
        )
        overlay["cost_parameters"] = overlay_cost
        scenario["scenario_overlay"] = overlay

        if not isinstance(scenario.get("simulation_config"), dict):
            scenario["simulation_config"] = {}
        scenario["simulation_config"]["default_turnaround_min"] = 10
        scenario["simulation_config"]["time_limit_seconds"] = 600

        analysis_scope = store.get_dispatch_scope(SCENARIO_ID)

        data, report = build_problem_data_from_scenario(
            scenario,
            depot_id=DEPOT_ID,
            service_id=SERVICE_ID,
            mode="mode_milp_only",
            use_existing_duties=False,
            analysis_scope=analysis_scope,
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
        result_payload.update(
            {
                "vehicles": len(getattr(data, "vehicles", []) or []),
                "tasks": len(getattr(data, "tasks", []) or []),
                "status": getattr(result, "status", None),
                "objective_value": getattr(result, "objective_value", None),
                "solve_time_sec": getattr(result, "solve_time_sec", None),
                "mip_gap": getattr(result, "mip_gap", None),
                "unserved_tasks": len(getattr(result, "unserved_tasks", []) or []),
                "infeasibility_info": getattr(result, "infeasibility_info", None),
                "dispatch_warnings": list(getattr(report, "warnings", []) or []),
            }
        )
    except Exception as exc:
        import traceback

        result_payload.update(
            {
                "status": "EXCEPTION",
                "exception": str(exc),
                "traceback": traceback.format_exc(),
            }
        )

    with open("tmp_direct_gurobi_tsurumaki_result.json", "w", encoding="utf-8") as f:
        json.dump(result_payload, f, ensure_ascii=False, indent=2)

    print("wrote tmp_direct_gurobi_tsurumaki_result.json")


if __name__ == "__main__":
    main()
