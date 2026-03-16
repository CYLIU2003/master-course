import json
import traceback
from datetime import datetime

from bff.routers.optimization import _rebuild_dispatch_artifacts
from bff.mappers.scenario_to_problemdata import build_problem_data_from_scenario
from bff.store import scenario_store as store
from src.model_sets import build_model_sets
from src.parameter_builder import build_derived_params
from src.pipeline.solve import _solve_milp_core

SCENARIO_ID = "41c6872a-717a-4357-81b0-87f5812bf06d"
DEPOT_ID = "tsurumaki"
SERVICE_ID = "WEEKDAY"


def main() -> None:
    payload = {
        "timestamp": datetime.now().isoformat(),
        "scenario_id": SCENARIO_ID,
        "depot_id": DEPOT_ID,
        "service_id": SERVICE_ID,
    }
    try:
        _rebuild_dispatch_artifacts(SCENARIO_ID, SERVICE_ID, DEPOT_ID)
        scenario = store.get_scenario_document_shallow(SCENARIO_ID)
        scenario["trips"] = store.get_field(SCENARIO_ID, "trips") or []
        scenario["duties"] = store.get_field(SCENARIO_ID, "duties") or []
        scenario["blocks"] = store.get_field(SCENARIO_ID, "blocks") or []
        scenario["timetable_rows"] = store.get_field(SCENARIO_ID, "timetable_rows") or []

        data, _ = build_problem_data_from_scenario(
            scenario,
            depot_id=DEPOT_ID,
            service_id=SERVICE_ID,
            mode="mode_milp_only",
            use_existing_duties=False,
            analysis_scope=store.get_dispatch_scope(SCENARIO_ID),
        )

        ms = build_model_sets(data)
        dp = build_derived_params(data, ms)
        cfg = {
            "time_limit_sec": 600,
            "mip_gap": 0.01,
            "random_seed": 42,
            "output_dir": "output",
        }

        result, solve_time = _solve_milp_core(
            cfg,
            data,
            ms,
            dp,
            "thesis_mode",
            flag_overrides=None,
        )
        payload.update(
            {
                "status": getattr(result, "status", None),
                "objective": getattr(result, "objective_value", None),
                "solve_time": solve_time,
                "infeasibility_info": getattr(result, "infeasibility_info", None),
            }
        )
    except Exception as exc:
        payload.update(
            {
                "status": "EXCEPTION",
                "exception": str(exc),
                "traceback": traceback.format_exc(),
            }
        )

    with open("tmp_debug_milp_core_result.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("wrote tmp_debug_milp_core_result.json")


if __name__ == "__main__":
    main()
