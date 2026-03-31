#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test optimization for scenario 237d5623-aa94-4f72-9da1-17b9070264be
Run all 4 modes: MILP, ALNS, ABC, GA
"""
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from bff.store import scenario_store
from bff.services.run_preparation import get_or_build_run_preparation
from bff.mappers.scenario_to_problemdata import build_problem_data_from_scenario
from src.optimization import (
    OptimizationConfig,
    OptimizationEngine,
    OptimizationMode,
    ProblemBuilder,
)

SCENARIO_ID = "237d5623-aa94-4f72-9da1-17b9070264be"

def load_scenario():
    """Load scenario document."""
    scenario_path = Path(f"output/scenarios/{SCENARIO_ID}.json")
    with open(scenario_path, "r", encoding="utf-8") as f:
        return json.load(f)

def run_optimization_mode(mode_name: str, mode: OptimizationMode, time_limit: int = 60):
    """Run optimization for a specific mode."""
    print(f"\n{'='*80}")
    print(f"Testing {mode_name} Mode")
    print(f"{'='*80}")
    
    try:
        # Load scenario
        scenario = load_scenario()
        print(f"[OK] Loaded scenario: {scenario['name']}")
        
        # Build problem
        builder = ProblemBuilder()
        problem = builder.build_from_scenario(
            scenario,
            depot_id="tsurumaki",
            service_id="WEEKDAY",
        )
        print(f"[OK] Built problem:")
        print(f"   - Trips: {len(problem.trips)}")
        print(f"   - Vehicles: {len(problem.vehicles)}")
        print(f"   - Chargers: {len(problem.chargers)}")
        print(f"   - Depots: {len(problem.depots)}")
        print(f"   - Price slots: {len(problem.price_slots)}")
        print(f"   - PV slots: {len(problem.pv_slots)}")
        print(f"   - Depot energy assets: {len(problem.depot_energy_assets)}")
        
        # Check PV configuration
        for depot_id, asset in problem.depot_energy_assets.items():
            pv_total = sum(asset.pv_generation_kwh_by_slot)
            print(f"   - Depot '{depot_id}' PV: enabled={asset.pv_enabled}, total={pv_total:.2f} kWh/day")
        
        # Check objective weights
        print(f"   - Objective weights:")
        print(f"      energy: {problem.objective_weights.energy}")
        print(f"      demand: {problem.objective_weights.demand}")
        print(f"      vehicle: {problem.objective_weights.vehicle}")
        print(f"      unserved: {problem.objective_weights.unserved}")
        
        # Configure solver
        config = OptimizationConfig(
            mode=mode,
            time_limit_sec=time_limit,
            mip_gap=0.02,
            random_seed=42,
            alns_iterations=100 if mode in [OptimizationMode.ALNS, OptimizationMode.HYBRID] else 50,
            no_improvement_limit=30,
            destroy_fraction=0.25,
        )
        
        print(f"\n[CONFIG] Solver config:")
        print(f"   - Mode: {config.mode}")
        print(f"   - Time limit: {config.time_limit_sec}s")
        print(f"   - MIP gap: {config.mip_gap}")
        
        # Run optimization
        engine = OptimizationEngine()
        print(f"\n[RUN] Starting optimization...")
        
        start_time = time.time()
        result = engine.solve(problem, config)
        solve_time = time.time() - start_time
        
        print(f"\n[OK] Optimization completed in {solve_time:.2f}s")
        print(f"   - Status: {result.solver_status}")
        print(f"   - Feasible: {result.feasible}")
        print(f"   - Objective value: {result.objective_value:,.2f} JPY")
        
        # Print cost breakdown
        print(f"\n[BREAKDOWN] Cost Breakdown:")
        breakdown = result.cost_breakdown
        for key in sorted(breakdown.keys()):
            value = breakdown[key]
            if isinstance(value, (int, float)) and value != 0:
                print(f"   - {key}: {value:,.2f}")
        
        # Check key metrics
        print(f"\n[METRICS] Key Metrics:")
        print(f"   - Served trips: {len(result.plan.served_trip_ids)}")
        print(f"   - Unserved trips: {len(result.plan.unserved_trip_ids)}")
        print(f"   - Duties: {len(result.plan.duties)}")
        print(f"   - Vehicle cost: {breakdown.get('vehicle_cost', 0):,.2f} JPY")
        print(f"   - Energy cost: {breakdown.get('energy_cost', 0):,.2f} JPY")
        print(f"   - Demand cost: {breakdown.get('demand_cost', 0):,.2f} JPY")
        print(f"   - Driver cost: {breakdown.get('driver_cost', 0):,.2f} JPY")
        print(f"   - PV generated: {breakdown.get('pv_generated_kwh', 0):.2f} kWh")
        print(f"   - PV to bus: {breakdown.get('pv_to_bus_kwh', 0):.2f} kWh")
        print(f"   - PV curtailed: {breakdown.get('pv_curtailed_kwh', 0):.2f} kWh")
        print(f"   - Grid import: {breakdown.get('grid_import_kwh', 0):.2f} kWh")
        
        # Validation checks
        print(f"\n[VALIDATION] Checks:")
        issues = []
        
        if breakdown.get('vehicle_cost', 0) == 0:
            issues.append("[FAIL] vehicle_cost is 0 (should be > 0)")
        else:
            print(f"   [PASS] vehicle_cost > 0")
        
        if breakdown.get('energy_cost', 0) == 0:
            issues.append("[WARN] energy_cost is 0 (may be valid if PV covers all)")
        else:
            print(f"   [PASS] energy_cost > 0")
        
        pv_gen = breakdown.get('pv_generated_kwh', 0)
        pv_used = breakdown.get('pv_to_bus_kwh', 0)
        pv_curt = breakdown.get('pv_curtailed_kwh', 0)
        
        if pv_gen > 0:
            pv_utilization = (pv_used / pv_gen * 100) if pv_gen > 0 else 0
            print(f"   [INFO] PV utilization: {pv_utilization:.1f}%")
            
            if pv_used == 0:
                issues.append("[FAIL] PV is generated but not used at all")
            elif pv_curt > pv_gen * 0.8:
                issues.append(f"[WARN] High PV curtailment: {pv_curt/pv_gen*100:.1f}%")
        
        if issues:
            print(f"\n[ISSUES] Found {len(issues)} issue(s):")
            for issue in issues:
                print(f"   {issue}")
        else:
            print(f"   [PASS] All checks passed")
        
        return result
        
    except Exception as e:
        print(f"\n[ERROR] in {mode_name} mode:")
        print(f"   {type(e).__name__}: {e}")
        traceback.print_exc()
        return None


def main():
    """Run all optimization modes."""
    print(f"{'#'*80}")
    print(f"# Optimization Test Suite for Scenario {SCENARIO_ID}")
    print(f"{'#'*80}")
    
    results = {}
    
    # Test each mode with shorter time limits for quick validation
    modes = [
        ("MILP", OptimizationMode.MILP, 120),
        ("ALNS", OptimizationMode.ALNS, 60),
        ("ABC", OptimizationMode.ABC, 60),
        ("GA", OptimizationMode.GA, 60),
    ]
    
    for mode_name, mode, time_limit in modes:
        result = run_optimization_mode(mode_name, mode, time_limit)
        results[mode_name] = result
        
        # Small delay between runs
        time.sleep(2)
    
    # Summary comparison
    print(f"\n{'='*80}")
    print(f"SUMMARY COMPARISON")
    print(f"{'='*80}")
    
    print(f"\n{'Mode':<10} {'Objective':>15} {'Vehicle':>12} {'Energy':>12} {'PV Used':>10} {'Status':<15}")
    print(f"{'-'*80}")
    
    for mode_name in ["MILP", "ALNS", "ABC", "GA"]:
        result = results.get(mode_name)
        if result:
            obj = result.objective_value
            veh = result.cost_breakdown.get('vehicle_cost', 0)
            eng = result.cost_breakdown.get('energy_cost', 0)
            pv = result.cost_breakdown.get('pv_to_bus_kwh', 0)
            status = "[OK]" if result.feasible else "[FAIL]"
            print(f"{mode_name:<10} {obj:>15,.0f} {veh:>12,.0f} {eng:>12,.0f} {pv:>10.1f} {status:<15}")
        else:
            print(f"{mode_name:<10} {'ERROR':>15} {'-':>12} {'-':>12} {'-':>10} {'[ERROR]':<15}")
    
    print(f"\n[DONE] Test suite completed!")


if __name__ == "__main__":
    main()
