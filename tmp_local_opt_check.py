import json
from datetime import datetime

from bff.mappers.scenario_to_problemdata import build_problem_data_from_scenario
from bff.store import scenario_store as store
from src.pipeline.solve import solve_problem_data

SCENARIO_ID = "41c6872a-717a-4357-81b0-87f5812bf06d"
DEPOT_ID = "tsurumaki"
SERVICE_ID = "WEEKDAY"


def main():
    scenario = store.get_scenario_document(SCENARIO_ID)
    scope = store.get_dispatch_scope(SCENARIO_ID)

    # Ensure 10-minute tolerance baseline in dispatch mapping (default_turnaround_min).
    if not isinstance(scenario.get("simulation_config"), dict):
        scenario["simulation_config"] = {}
    scenario["simulation_config"]["default_turnaround_min"] = 10

    data, report = build_problem_data_from_scenario(
        scenario,
        depot_id=DEPOT_ID,
        service_id=SERVICE_ID,
        mode="mode_milp_only",
        use_existing_duties=False,
        analysis_scope=scope,
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
    payload = {
        "timestamp": datetime.now().isoformat(),
        "scenario_id": SCENARIO_ID,
        "depot_id": DEPOT_ID,
        "service_id": SERVICE_ID,
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

    with open("tmp_local_opt_result.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print("wrote tmp_local_opt_result.json")


if __name__ == "__main__":
    main()
