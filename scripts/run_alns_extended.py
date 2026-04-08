"""
Extended ALNS run with higher iteration count for better optimization.
"""
import sys
import json
from pathlib import Path

# Add repo root to path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import OptimizationConfig, OptimizationMode
from src.optimization.alns.engine import ALNSEngine

def main():
    # Load prepared input
    scenario_id = "237d5623-aa94-4f72-9da1-17b9070264be"
    prepared_id = "prepared-11efb997690030ef-byd20"
    prepared_path = repo_root / "output" / "prepared_inputs" / scenario_id / f"{prepared_id}.json"
    
    print(f"Loading prepared input: {prepared_path}")
    with open(prepared_path, "r", encoding="utf-8") as f:
        prepared = json.load(f)
    
    scenario = prepared["scenario"]
    
    # Extended ALNS config
    config = OptimizationConfig(
        mode=OptimizationMode.ALNS,
        time_limit_sec=600,  # 10 minutes
        alns_iterations=2000,  # Increased from 800
        no_improvement_limit=300,  # More patience
        destroy_fraction=0.25,
        random_seed=42,
        warm_start=True,
        acceptance="simulated_annealing",
        operator_selection="adaptive_roulette",
    )
    
    # Build problem
    print("Building problem...")
    builder = ProblemBuilder()
    problem = builder.build_from_scenario(
        scenario,
        depot_id="tsurumaki",
        service_id="WEEKDAY",
        config=config,
        planning_days=1,
    )
    
    # Run ALNS
    print(f"Running ALNS with {config.alns_iterations} iterations, {config.time_limit_sec}s limit...")
    engine = ALNSEngine()
    result = engine.solve(problem, config)
    
    # Save result
    output_dir = repo_root / "output" / "alns_extended"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    output_file = output_dir / "result.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, indent=2, ensure_ascii=False)
    
    print(f"\n{'='*80}")
    print(f"ALNS Extended Run Complete")
    print(f"{'='*80}")
    print(f"Status: {result.report.solver_status}")
    print(f"Objective: {result.report.objective_value:,.2f} JPY")
    print(f"Served: {result.report.trip_count_served}/{result.report.trip_count_served + result.report.trip_count_unserved}")
    print(f"Vehicles: {result.report.vehicle_count_used}")
    print(f"Time: {result.report.solve_time_seconds:.1f}s")
    print(f"Incumbents: {len(result.report.incumbent_history)}")
    print(f"\nOutput: {output_file}")
    print(f"{'='*80}")
    
    # Print incumbent history
    if result.report.incumbent_history:
        print("\nIncumbent History:")
        for inc in result.report.incumbent_history[-10:]:  # Last 10
            status = "✓" if inc.get("feasible", False) else "✗"
            print(f"  {status} iter {inc['iteration']:4d}: {inc['objective_value']:,.2f}")

if __name__ == "__main__":
    main()
