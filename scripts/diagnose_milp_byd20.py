"""
MILP診断スクリプト - BYD+20 prepared scope用

詳細なMILP診断ログを有効化してBYD+20ケースを実行し、
制約違反やinfeasibilityの原因を特定する。
"""

from __future__ import annotations

import sys
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
)


def main():
    # BYD+20 prepared scope
    scenario_id = "237d5623-aa94-4f72-9da1-17b9070264be"
    prepared_input_id = "prepared-11efb997690030ef-byd20"
    depot_id = "tsurumaki"
    
    print("=" * 80)
    print("MILP Diagnostic Run - BYD+20 Prepared Scope")
    print("=" * 80)
    
    # Load prepared input
    print("\n[1/4] Loading prepared input...")
    prepared_root = _prepared_inputs_root()
    prepared_payload = load_prepared_input(
        scenario_id=scenario_id,
        prepared_input_id=prepared_input_id,
        scenarios_dir=prepared_root,
    )
    scenario = materialize_scenario_from_prepared_input(
        store.get_scenario_document_shallow(scenario_id),
        prepared_payload,
    )
    print(f"  Scenario: {scenario_id}")
    print(f"  Prepared: {prepared_input_id}")
    print(f"  Depot: {depot_id}")
    
    # Build canonical problem
    print("\n[2/4] Building canonical problem...")
    builder = ProblemBuilder()
    service_id = prepared_payload.get("service_id", "WEEKDAY")
    planning_days = prepared_payload.get("planning_days", 1)
    problem = builder.build_from_scenario(
        scenario,
        depot_id=depot_id,
        service_id=service_id,
        planning_days=planning_days,
    )
    print(f"  Trips: {len(problem.trips)}")
    print(f"  Vehicles: {len(problem.vehicles)}")
    print(f"  Slots: {len(problem.price_slots)}")
    
    # Configure MILP with diagnostics enabled
    print("\n[3/4] Configuring MILP optimizer with diagnostics...")
    import os
    os.environ["MILP_ENABLE_DIAGNOSTICS"] = "1"
    os.environ["MILP_DIAGNOSTIC_DIR"] = "output/milp_diagnostics/byd20_diagnosis"
    
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        time_limit_sec=300,
        mip_gap=0.01,
        random_seed=42,
    )
    print(f"  Time limit: {config.time_limit_sec}s")
    print(f"  MIP gap: {config.mip_gap}")
    print(f"  Diagnostics: ENABLED (via environment variable)")
    print(f"  Output dir: output/milp_diagnostics/byd20_diagnosis")
    
    # Run optimization
    print("\n[4/4] Running MILP optimization...")
    print("  (詳細ログはoutput/milp_diagnostics/byd20_diagnosisに出力されます)")
    print()
    
    engine = OptimizationEngine()
    result = engine.solve(problem, config)
    
    # Summary
    print("\n" + "=" * 80)
    print("MILP Diagnostic Run - Results Summary")
    print("=" * 80)
    print(f"  Solver status: {result.solver_status}")
    print(f"  Feasible: {result.feasible}")
    print(f"  Objective: {result.objective_value:,.2f}")
    print(f"  Solve time: {result.solve_time:.2f}s")
    print(f"  Trips served: {len(result.plan.served_trip_ids)}/{len(problem.trips)}")
    print(f"  Trips unserved: {len(result.plan.unserved_trip_ids)}")
    
    if result.warnings:
        print(f"\n  Warnings ({len(result.warnings)}):")
        for w in result.warnings[:5]:
            print(f"    - {w}")
        if len(result.warnings) > 5:
            print(f"    ... and {len(result.warnings) - 5} more")
    
    if result.infeasibility_reasons:
        print(f"\n  Infeasibility reasons ({len(result.infeasibility_reasons)}):")
        for r in result.infeasibility_reasons[:5]:
            print(f"    - {r}")
        if len(result.infeasibility_reasons) > 5:
            print(f"    ... and {len(result.infeasibility_reasons) - 5} more")
    
    print("\n診断ログファイル:")
    print("  - output/milp_diagnostics/byd20_diagnosis/gurobi_*.log")
    print("  - output/milp_diagnostics/byd20_diagnosis/pre_stats_*.json")
    print("  - output/milp_diagnostics/byd20_diagnosis/post_stats_*.json")
    if result.solver_status == "infeasible":
        print("  - output/milp_diagnostics/byd20_diagnosis/infeasible_iis_*.ilp")
    print()


if __name__ == "__main__":
    main()
