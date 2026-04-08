"""
Run MILP optimization without time limit for large-scale scenarios.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from bff.routers.optimization import _prepared_inputs_root
from bff.services.run_preparation import load_prepared_input, materialize_scenario_from_prepared_input
from bff.store import scenario_store as store
from src.optimization import (
    OptimizationConfig,
    OptimizationEngine,
    OptimizationMode,
    ProblemBuilder,
    ResultSerializer,
)


def main():
    parser = argparse.ArgumentParser(description="Run MILP without time limit")
    parser.add_argument("--scenario-id", default="237d5623-aa94-4f72-9da1-17b9070264be")
    parser.add_argument("--prepared-input-id", default="prepared-11efb997690030ef-byd20")
    parser.add_argument("--depot-id", default="tsurumaki")
    parser.add_argument("--service-id", default="WEEKDAY")
    parser.add_argument("--output-dir", default="output/milp_unlimited")
    parser.add_argument("--mip-gap", type=float, default=0.01)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load prepared scope
    prepared_root = _prepared_inputs_root()
    prepared_payload = load_prepared_input(
        scenario_id=args.scenario_id,
        prepared_input_id=args.prepared_input_id,
        scenarios_dir=prepared_root,
    )
    scenario = materialize_scenario_from_prepared_input(
        store.get_scenario_document_shallow(args.scenario_id),
        prepared_payload,
    )

    # Build canonical problem
    builder = ProblemBuilder()
    
    # MILP config with very long time limit
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        time_limit_sec=7200,  # 2 hours
        mip_gap=args.mip_gap,
        random_seed=42,
    )
    
    problem = builder.build_from_scenario(
        scenario,
        depot_id=args.depot_id,
        service_id=args.service_id,
        config=config,
        planning_days=1,
    )

    # Run optimization
    print(f"Starting MILP optimization (time limit: {config.time_limit_sec}s, MIP gap: {config.mip_gap})...")
    print(f"Trips: {len(problem.trips)}, Vehicles: {len(problem.vehicles)}")
    start_time = time.time()
    
    engine = OptimizationEngine()
    result = engine.solve(problem, config)
    
    elapsed = time.time() - start_time

    # Serialize result
    serializer = ResultSerializer()
    result_json = serializer.serialize(result)

    # Save outputs
    output_file = output_dir / "milp_result.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result_json, f, indent=2, ensure_ascii=False)

    summary = {
        "scenario_id": args.scenario_id,
        "prepared_input_id": args.prepared_input_id,
        "mode": "milp",
        "solver_status": result.solver_status,
        "objective_value": result.objective_value,
        "solve_time_seconds": elapsed,
        "trip_count_total": len(problem.trips),
        "trip_count_served": len(result.plan.served_trip_ids),
        "trip_count_unserved": len(result.plan.unserved_trip_ids),
        "vehicle_count_total": len(problem.vehicles),
        "vehicle_count_used": len(set(duty.vehicle_id for duty in result.plan.duties)),
        "config": {
            "time_limit_sec": config.time_limit_sec,
            "mip_gap": config.mip_gap,
        },
        "cost_breakdown": result.cost_breakdown,
        "warnings": result.warnings,
        "infeasibility_reasons": result.infeasibility_reasons,
        "incumbent_history_count": len(result.incumbent_history),
    }

    summary_file = output_dir / "summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*80}")
    print(f"MILP Optimization Complete")
    print(f"{'='*80}")
    print(f"Solver status: {result.solver_status}")
    print(f"Objective: {result.objective_value:,.2f}")
    print(f"Solve time: {elapsed:.1f}s")
    print(f"Served: {len(result.plan.served_trip_ids)}/{len(problem.trips)}")
    print(f"Unserved: {len(result.plan.unserved_trip_ids)}")
    print(f"Vehicles used: {len(set(duty.vehicle_id for duty in result.plan.duties))}/{len(problem.vehicles)}")
    print(f"\nOutputs:")
    print(f"  {output_file}")
    print(f"  {summary_file}")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
