import json
import time
from pathlib import Path

from bff.routers.optimization import _prepared_inputs_root
from bff.services.run_preparation import load_prepared_input, materialize_scenario_from_prepared_input
from bff.store import scenario_store as store
from src.optimization import OptimizationConfig, OptimizationEngine, OptimizationMode, ProblemBuilder, ResultSerializer

SCENARIO_ID = "237d5623-aa94-4f72-9da1-17b9070264be"
PREPARED_INPUT_ID = "prepared-11efb997690030ef-byd20"
DEPOT_ID = "tsurumaki"
SERVICE_ID = "WEEKDAY"
OUTPUT_DIR = Path("output/reports/20260407_route_band_standard_rerun_byd20_milp_fix_warmstart")


def main() -> None:
    prepared_root = _prepared_inputs_root()
    prepared_payload = load_prepared_input(
        scenario_id=SCENARIO_ID,
        prepared_input_id=PREPARED_INPUT_ID,
        scenarios_dir=prepared_root,
    )
    scenario_doc = store.get_scenario_document_shallow(SCENARIO_ID)
    scenario = materialize_scenario_from_prepared_input(scenario_doc, prepared_payload)

    base_config = OptimizationConfig(
        time_limit_sec=300,
        mip_gap=0.01,
        random_seed=42,
        alns_iterations=500,
        no_improvement_limit=120,
        destroy_fraction=0.25,
        warm_start=True,
    )
    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id=DEPOT_ID,
        service_id=SERVICE_ID,
        config=base_config,
        planning_days=1,
    )
    engine = OptimizationEngine()
    started = time.perf_counter()
    result = engine.solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            time_limit_sec=300,
            mip_gap=0.01,
            random_seed=42,
            alns_iterations=500,
            no_improvement_limit=120,
            destroy_fraction=0.25,
            warm_start=True,
        ),
    )
    elapsed = time.perf_counter() - started
    payload = ResultSerializer.serialize_result(result)

    summary = {
        "scenario_id": SCENARIO_ID,
        "prepared_input_id": PREPARED_INPUT_ID,
        "depot_id": DEPOT_ID,
        "service_id": SERVICE_ID,
        "solver_status": payload.get("solver_status"),
        "supports_exact_milp": (payload.get("solver_metadata") or {}).get("supports_exact_milp"),
        "termination_reason": payload.get("termination_reason"),
        "objective_value": payload.get("objective_value"),
        "trip_count_served": len(payload.get("served_trip_ids") or []),
        "trip_count_unserved": len(payload.get("unserved_trip_ids") or []),
        "vehicle_count_used": sum(1 for trip_ids in (payload.get("vehicle_paths") or {}).values() if trip_ids),
        "solve_time_seconds_wall": round(float(elapsed), 3),
        "backend_objective_value_raw": (payload.get("solver_metadata") or {}).get("backend_objective_value_raw"),
        "postsolve_objective_value": (payload.get("solver_metadata") or {}).get("postsolve_objective_value"),
        "postsolve_feasible": (payload.get("solver_metadata") or {}).get("postsolve_feasible"),
        "warnings_count": len(payload.get("warnings") or []),
    }

    baseline_path = Path("output/reports/20260406_route_band_standard_rerun_byd20/milp.json")
    if baseline_path.exists():
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        baseline_summary = {
            "solver_status": baseline.get("solver_status"),
            "objective_value": baseline.get("objective_value"),
            "trip_count_served": len(baseline.get("served_trip_ids") or []),
            "trip_count_unserved": len(baseline.get("unserved_trip_ids") or []),
        }
        summary["baseline"] = baseline_summary
        summary["delta_vs_baseline"] = {
            "objective_value": (summary["objective_value"] or 0) - (baseline_summary["objective_value"] or 0),
            "trip_count_served": summary["trip_count_served"] - baseline_summary["trip_count_served"],
            "trip_count_unserved": summary["trip_count_unserved"] - baseline_summary["trip_count_unserved"],
        }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "milp.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
