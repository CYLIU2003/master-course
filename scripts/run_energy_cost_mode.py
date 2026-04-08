"""
Run all 4 solvers in energy cost minimization mode.
Energy cost mode: energy_weight=10.0, demand_weight=10.0, vehicle_weight=0.1 (minimize electricity and demand charges)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dataclasses import replace
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
from src.optimization.common.problem import OptimizationObjectiveWeights


def run_solver(
    mode: OptimizationMode,
    problem: Any,
    base_config: OptimizationConfig,
    output_dir: Path,
) -> Dict[str, Any]:
    """Run a single solver and return results."""
    config = replace(base_config, mode=mode)
    
    print(f"\n{'='*80}")
    print(f"Running {mode.value.upper()} (energy cost minimization mode)")
    print(f"{'='*80}")
    
    start_time = time.time()
    engine = OptimizationEngine()
    result = engine.solve(problem, config)
    elapsed = time.time() - start_time
    
    # Serialize result
    serializer = ResultSerializer()
    result_json = serializer.serialize(result)
    
    # Save per-solver output
    solver_file = output_dir / f"{mode.value}.json"
    with open(solver_file, "w", encoding="utf-8") as f:
        json.dump(result_json, f, indent=2, ensure_ascii=False)
    
    summary = {
        "mode": mode.value,
        "solver_status": result.solver_status,
        "objective_value": result.objective_value,
        "solve_time_seconds": elapsed,
        "trip_count_served": len(result.plan.served_trip_ids),
        "trip_count_unserved": len(result.plan.unserved_trip_ids),
        "vehicle_count_used": len(set(duty.vehicle_id for duty in result.plan.duties)),
        "energy_cost": result.cost_breakdown.get("energy_cost", 0.0),
        "demand_cost": result.cost_breakdown.get("demand_cost", 0.0),
        "driver_cost": result.cost_breakdown.get("driver_cost", 0.0),
        "grid_import_kwh": result.cost_breakdown.get("grid_import_kwh", 0.0),
        "peak_grid_kw": result.cost_breakdown.get("peak_grid_kw", 0.0),
        "incumbent_history_count": len(result.incumbent_history),
    }
    
    print(f"Status: {result.solver_status}")
    print(f"Objective: {result.objective_value:,.2f}")
    print(f"Energy cost: {summary['energy_cost']:,.2f}")
    print(f"Demand cost: {summary['demand_cost']:,.2f}")
    print(f"Served: {summary['trip_count_served']}/{len(problem.trips)}")
    print(f"Time: {elapsed:.1f}s")
    
    return summary


def main():
    parser = argparse.ArgumentParser(description="Run 4 solvers in energy cost minimization mode")
    parser.add_argument("--scenario-id", default="237d5623-aa94-4f72-9da1-17b9070264be")
    parser.add_argument("--prepared-input-id", default="prepared-11efb997690030ef-byd20")
    parser.add_argument("--depot-id", default="tsurumaki")
    parser.add_argument("--service-id", default="WEEKDAY")
    parser.add_argument("--output-dir", default="output/energy_cost_mode")
    parser.add_argument("--time-limit", type=int, default=300)
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

    # Base config
    base_config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        time_limit_sec=args.time_limit,
        mip_gap=0.01,
        random_seed=42,
    )

    # Build problem with energy cost weights
    builder = ProblemBuilder()
    problem = builder.build_from_scenario(
        scenario,
        depot_id=args.depot_id,
        service_id=args.service_id,
        config=base_config,
        planning_days=1,
    )
    
    # Override objective weights for energy cost minimization
    problem = replace(
        problem,
        objective_weights=OptimizationObjectiveWeights(
            energy=10.0,      # High weight on electricity cost
            demand=10.0,      # High weight on demand charges
            vehicle=0.1,      # Low weight on vehicle fixed costs
            unserved=10000.0, # Keep unserved penalty high
            degradation=1.0,  # Consider battery degradation
        )
    )

    print(f"Scenario: {args.scenario_id}")
    print(f"Prepared input: {args.prepared_input_id}")
    print(f"Trips: {len(problem.trips)}, Vehicles: {len(problem.vehicles)}")
    print(f"Objective weights:")
    print(f"  energy={problem.objective_weights.energy}")
    print(f"  demand={problem.objective_weights.demand}")
    print(f"  vehicle={problem.objective_weights.vehicle}")
    print(f"  unserved={problem.objective_weights.unserved}")

    # Run all 4 solvers
    modes = [OptimizationMode.MILP, OptimizationMode.ALNS, OptimizationMode.GA, OptimizationMode.ABC]
    summaries = []
    
    for mode in modes:
        summary = run_solver(mode, problem, base_config, output_dir)
        summaries.append(summary)

    # Save combined results
    results = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "scenario_id": args.scenario_id,
        "prepared_input_id": args.prepared_input_id,
        "objective_mode": "energy_cost_minimization",
        "time_limit_seconds": args.time_limit,
        "objective_weights": {
            "energy": problem.objective_weights.energy,
            "demand": problem.objective_weights.demand,
            "vehicle": problem.objective_weights.vehicle,
            "unserved": problem.objective_weights.unserved,
        },
        "solvers": summaries,
    }
    
    results_file = output_dir / "comparison.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    # Create CSV
    csv_file = output_dir / "comparison.csv"
    with open(csv_file, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "mode", "solver_status", "objective_value", "energy_cost", "demand_cost",
            "driver_cost", "served", "unserved", "vehicles_used", "grid_kwh", "peak_kw",
            "solve_time", "incumbents"
        ])
        writer.writeheader()
        for s in summaries:
            writer.writerow({
                "mode": s["mode"],
                "solver_status": s["solver_status"],
                "objective_value": f"{s['objective_value']:.2f}",
                "energy_cost": f"{s['energy_cost']:.2f}",
                "demand_cost": f"{s['demand_cost']:.2f}",
                "driver_cost": f"{s['driver_cost']:.2f}",
                "served": s["trip_count_served"],
                "unserved": s["trip_count_unserved"],
                "vehicles_used": s["vehicle_count_used"],
                "grid_kwh": f"{s['grid_import_kwh']:.2f}",
                "peak_kw": f"{s['peak_grid_kw']:.2f}",
                "solve_time": f"{s['solve_time_seconds']:.1f}",
                "incumbents": s["incumbent_history_count"],
            })

    print(f"\n{'='*80}")
    print(f"ALL SOLVERS COMPLETE (Energy Cost Minimization Mode)")
    print(f"{'='*80}")
    print(f"Results saved to:")
    print(f"  {results_file}")
    print(f"  {csv_file}")
    print(f"\nComparison:")
    print(f"{'Mode':<8} {'Objective':>15} {'Energy':>12} {'Demand':>12} {'Served':>8} {'Time':>8}")
    print(f"{'-'*80}")
    for s in summaries:
        print(f"{s['mode']:<8} {s['objective_value']:>15,.2f} {s['energy_cost']:>12,.2f} "
              f"{s['demand_cost']:>12,.2f} {s['trip_count_served']:>8} {s['solve_time_seconds']:>8.1f}s")


if __name__ == "__main__":
    main()
