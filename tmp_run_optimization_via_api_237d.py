#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API経由での最適化実行スクリプト
シナリオ 237d5623-aa94-4f72-9da1-17b9070264be で MILP/ALNS/ABC/GA を実行
"""
import json
import requests
import time
from pathlib import Path
from typing import Optional, Dict, Any

BASE_URL = "http://localhost:8000/api"
SCENARIO_ID = "237d5623-aa94-4f72-9da1-17b9070264be"

def check_server_health() -> bool:
    """Check if BFF server is running."""
    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        return response.status_code == 200
    except:
        return False

def run_optimization(
    scenario_id: str,
    mode: str,
    time_limit_seconds: int = 300,
    mip_gap: float = 0.01,
    alns_iterations: int = 500,
) -> Optional[Dict[str, Any]]:
    """
    Run optimization via BFF API.
    
    Args:
        scenario_id: Scenario ID
        mode: "mode_milp_only" | "mode_alns_only" | "mode_abc_only" | "mode_ga_only"
        time_limit_seconds: Time limit
        mip_gap: MIP gap for MILP
        alns_iterations: Iterations for ALNS/ABC/GA
    
    Returns:
        Optimization result or None if failed
    """
    print(f"\n{'='*80}")
    print(f"Running {mode} optimization")
    print(f"{'='*80}")
    
    # Start optimization job
    request_body = {
        "mode": mode,
        "time_limit_seconds": time_limit_seconds,
        "mip_gap": mip_gap,
        "random_seed": 42,
        "service_id": "WEEKDAY",
        "depot_id": "tsurumaki",
        "rebuild_dispatch": False,
        "use_existing_duties": False,
        "alns_iterations": alns_iterations,
        "no_improvement_limit": 100,
        "destroy_fraction": 0.25,
    }
    
    print(f"[POST] {BASE_URL}/scenarios/{scenario_id}/run-optimization")
    print(f"Request: {json.dumps(request_body, indent=2)}")
    
    try:
        response = requests.post(
            f"{BASE_URL}/scenarios/{scenario_id}/run-optimization",
            json=request_body,
            timeout=30,
        )
        
        if response.status_code != 200:
            print(f"[ERROR] HTTP {response.status_code}: {response.text}")
            return None
        
        job = response.json()
        job_id = job.get("job_id")
        print(f"[OK] Job started: {job_id}")
        
    except Exception as e:
        print(f"[ERROR] Failed to start job: {e}")
        return None
    
    # Poll for completion
    print("\n[POLLING] Waiting for job completion...")
    poll_count = 0
    start_time = time.time()
    
    while True:
        try:
            response = requests.get(f"{BASE_URL}/jobs/{job_id}", timeout=10)
            if response.status_code != 200:
                print(f"[WARN] Failed to get job status: {response.status_code}")
                time.sleep(5)
                continue
            
            status_data = response.json()
            status = status_data.get("status")
            progress = status_data.get("progress", 0)
            message = status_data.get("message", "")
            
            elapsed = time.time() - start_time
            
            if poll_count % 6 == 0:  # Print every ~30 seconds
                print(f"[{elapsed:6.1f}s] Progress: {progress:3d}% - {status} - {message}")
            
            if status in ["completed", "failed", "cancelled"]:
                print(f"\n[FINAL] Status: {status} after {elapsed:.1f}s")
                break
            
            poll_count += 1
            time.sleep(5)
            
        except Exception as e:
            print(f"[WARN] Polling error: {e}")
            time.sleep(5)
    
    # Get result
    if status == "completed":
        try:
            print(f"[GET] {BASE_URL}/scenarios/{scenario_id}/optimization")
            response = requests.get(
                f"{BASE_URL}/scenarios/{scenario_id}/optimization",
                timeout=30,
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"[OK] Retrieved optimization result")
                return result
            else:
                print(f"[ERROR] Failed to get result: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"[ERROR] Failed to retrieve result: {e}")
            return None
    else:
        error = status_data.get("error", "Unknown error")
        print(f"[ERROR] Optimization failed: {error}")
        return None


def extract_key_metrics(result: Dict[str, Any]) -> Dict[str, Any]:
    """Extract key metrics from optimization result."""
    if not result:
        return {}

    cost_breakdown = result.get("cost_breakdown", {})
    solver_status = str(result.get("solver_status") or "").lower()
    summary = result.get("summary") or {}
    total_trips = int(result.get("trip_count") or 0)
    served = int(result.get("served_trip_count") or summary.get("trip_count_served") or 0)
    unserved = int(result.get("unserved_trip_count") or summary.get("trip_count_unserved") or 0)
    if total_trips <= 0 and (served > 0 or unserved > 0):
        total_trips = served + unserved

    return {
        "objective_value": result.get("objective_value", 0),
        "solver_status": solver_status,
        "solve_time_sec": result.get("solve_time_seconds", 0),
        "vehicle_cost": cost_breakdown.get("vehicle_cost", 0),
        "energy_cost": cost_breakdown.get("energy_cost", 0),
        "fuel_cost": cost_breakdown.get("fuel_cost", 0),
        "demand_charge": cost_breakdown.get("demand_charge", 0),
        "driver_cost": cost_breakdown.get("driver_cost", 0),
        "penalty_unserved": cost_breakdown.get("penalty_unserved", 0),
        "pv_generated_kwh": cost_breakdown.get("pv_generated_kwh", 0),
        "pv_to_bus_kwh": cost_breakdown.get("pv_to_bus_kwh", 0),
        "pv_curtailed_kwh": cost_breakdown.get("pv_curtailed_kwh", 0),
        "grid_import_kwh": cost_breakdown.get("grid_import_kwh", 0),
        "trip_count": total_trips,
        "served_trips": served,
        "unserved_trips": unserved,
        "used_vehicles": result.get("used_vehicle_count", 0),
    }


def compare_optimization_modes():
    """Run all 4 modes and compare results."""
    print("#" * 80)
    print("# OPTIMIZATION MODE COMPARISON - API EXECUTION")
    print(f"# Scenario: {SCENARIO_ID}")
    print("#" * 80)
    
    # Check server
    if not check_server_health():
        print("\n[ERROR] BFF server is not running at http://localhost:8000")
        print("Please start the server with:")
        print("  python -m bff.main")
        print("  or")
        print("  uvicorn bff.main:app --reload --port 8000")
        return
    
    print("\n[OK] BFF server is running")
    
    # Define modes and their configs
    modes = [
        ("mode_milp_only", 300, 500),
        ("mode_alns_only", 120, 500),
        ("mode_abc_only", 120, 700),
        ("mode_ga_only", 120, 600),
    ]
    
    results = {}
    
    # Run each mode
    for mode, time_limit, iterations in modes:
        result = run_optimization(
            SCENARIO_ID,
            mode,
            time_limit_seconds=time_limit,
            alns_iterations=iterations,
        )
        
        if result:
            metrics = extract_key_metrics(result)
            results[mode] = metrics
            
            # Print summary
            print(f"\n[SUMMARY] {mode}:")
            print(f"  Objective: {metrics['objective_value']:,.0f} JPY")
            print(f"  Vehicle cost: {metrics['vehicle_cost']:,.0f} JPY")
            print(f"  Energy cost: {metrics['energy_cost']:,.0f} JPY")
            print(f"  Unserved penalty: {metrics['penalty_unserved']:,.0f} JPY")
            print(f"  Solver status: {metrics['solver_status']}")
            print(f"  PV to bus: {metrics['pv_to_bus_kwh']:.1f} kWh")
            print(f"  Served trips: {metrics['served_trips']}/{metrics['trip_count']}")
        else:
            results[mode] = None
            print(f"\n[FAILED] {mode} did not complete")
        
        # Small delay between modes
        time.sleep(3)
    
    # Print comparison table
    print(f"\n{'='*100}")
    print("RESULTS COMPARISON")
    print(f"{'='*100}")
    
    header = f"{'Mode':<20} {'Objective':>15} {'Vehicle':>12} {'Energy':>12} {'Penalty':>12} {'Trips':>10} {'Status':>16}"
    print(header)
    print("-" * 100)
    
    for mode, metrics in results.items():
        if metrics:
            obj = metrics['objective_value']
            veh = metrics['vehicle_cost']
            eng = metrics['energy_cost']
            pen = metrics['penalty_unserved']
            trips = f"{metrics['served_trips']}/{metrics['trip_count']}"
            status = metrics['solver_status']
            
            print(f"{mode:<20} {obj:>15,.0f} {veh:>12,.0f} {eng:>12,.0f} {pen:>12,.0f} {trips:>10} {status:>16}")
        else:
            print(f"{mode:<20} {'ERROR':>15} {'-':>12} {'-':>12} {'-':>12} {'-':>10} {'error':>16}")
    
    print("=" * 100)
    
    # Save results
    output_path = Path("output/optimization_comparison_api_237d.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({
            "scenario_id": SCENARIO_ID,
            "modes": results,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }, f, indent=2)
    
    print(f"\n[SAVED] Results saved to: {output_path}")
    
    # Calculate PV utilization
    print("\n[ANALYSIS] PV Utilization:")
    for mode, metrics in results.items():
        if metrics and metrics['pv_generated_kwh'] > 0:
            utilization = (metrics['pv_to_bus_kwh'] / metrics['pv_generated_kwh']) * 100
            print(f"  {mode}: {utilization:.1f}% ({metrics['pv_to_bus_kwh']:.1f} / {metrics['pv_generated_kwh']:.1f} kWh)")


if __name__ == "__main__":
    compare_optimization_modes()
