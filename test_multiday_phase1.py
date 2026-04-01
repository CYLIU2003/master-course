#!/usr/bin/env python
"""
Phase 1: Multi-day simulation basic validation
- Create 2-day scenario (planning_days=2)
- Prepare input
- Run MILP only
- Compare with single-day baseline

"""

import requests
import json
import time
from pprint import pprint

BASE_URL = "http://localhost:8000/api"

def poll_job(job_id, timeout=600, poll_interval=2):
    """Poll job until completion."""
    start = time.time()
    while time.time() - start < timeout:
        r = requests.get(f"{BASE_URL}/jobs/{job_id}")
        if r.status_code != 200:
            print(f"[ERR] Job fetch failed: {r.text}")
            return None
        job = r.json()
        status = job.get("status")
        progress = job.get("progress", 0)
        message = job.get("message", "")
        elapsed = time.time() - start
        print(f"[{elapsed:6.1f}s] {status:12} progress={progress}% - {message}")
        
        if status in ("completed", "failed", "cancelled"):
            return job
        time.sleep(poll_interval)
    
    print(f"[TIMEOUT] Job {job_id} did not complete within {timeout}s")
    return None

def test_multiday_scenario():
    """Test multi-day scenario end-to-end."""
    
    # Step 1: Scenarios
    print("\n=== STEP 1: Fetching base scenarios ===")
    r = requests.get(f"{BASE_URL}/scenarios")
    scenarios = r.json() if r.status_code == 200 else []
    if isinstance(scenarios, dict):
        scenarios = scenarios.get("items", [])
    print(f"Available scenarios: {len(scenarios)}")
    
    # Use existing 237d for baseline
    scenario_id_base = "237d5623-aa94-4f72-9da1-17b9070264be"
    
    # Step 2: Get scenario and check planning_days
    print(f"\n=== STEP 2: Checking base scenario {scenario_id_base} ===")
    r = requests.get(f"{BASE_URL}/scenarios/{scenario_id_base}")
    if r.status_code != 200:
        print(f"[ERR] Cannot fetch scenario: {r.status_code} {r.text}")
        return
    
    scenario = r.json()
    sim_config = scenario.get("simulation_config") or {}
    planning_days_base = int(sim_config.get("planning_days") or 1)
    service_date_base = sim_config.get("service_date") or "2025-08-04"
    
    print(f"  Base: planning_days={planning_days_base}, service_date={service_date_base}")
    
    # Step 3: Create multi-day scenario by cloning and modifying
    print(f"\n=== STEP 3: Creating 2-day variant ===")
    scenario_multiday = dict(scenario)
    sim_config_md = dict(sim_config)
    
    # Set planning_days=2 and add service_dates
    sim_config_md["planning_days"] = 2
    sim_config_md["service_dates"] = [service_date_base, service_date_base]  # same day twice for now
    
    scenario_multiday["simulation_config"] = sim_config_md
    scenario_multiday["name"] = f"{scenario.get('name', 'scenario')}_2day"
    scenario_multiday["description"] = f"Multi-day test: planning_days=2"
    
    # Save new scenario
    r = requests.post(f"{BASE_URL}/scenarios", json=scenario_multiday)
    if r.status_code not in (200, 201):
        print(f"[ERR] Cannot create scenario: {r.status_code} {r.text}")
        return
    
    new_scenario = r.json()
    scenario_id_md = new_scenario.get("id")
    print(f"  Created: scenario_id={scenario_id_md}")
    
    # Step 4: Run base optimization (single-day reference)
    print(f"\n=== STEP 4: Running MILP on base scenario (reference) ===")
    r = requests.post(
        f"{BASE_URL}/scenarios/{scenario_id_base}/run-optimization",
        json={
            "mode": "mode_milp_only",
            "time_limit_seconds": 120,
            "mip_gap": 0.01,
            "random_seed": 42,
            "service_id": "WEEKDAY",
            "depot_id": "tsurumaki",
            "rebuild_dispatch": True,
        }
    )
    if r.status_code not in (200, 201):
        print(f"[ERR] Cannot start optimization: {r.status_code} {r.text}")
        return
    
    job_base = r.json()
    job_id_base = job_base.get("job_id")
    print(f"  Job started: {job_id_base}")
    
    job_result_base = poll_job(job_id_base, timeout=180)
    if not job_result_base:
        print(f"[ERR] Base job failed or timed out")
        return
    
    print(f"  Base job completed: status={job_result_base.get('status')}")
    
    # Fetch result
    r = requests.get(f"{BASE_URL}/scenarios/{scenario_id_base}/optimization")
    if r.status_code != 200:
        print(f"[ERR] Cannot fetch optimization result: {r.status_code}")
        return
    
    opt_base = r.json()
    obj_base = opt_base.get("objective_value")
    cost_base = opt_base.get("cost_breakdown", {})
    summary_base = opt_base.get("summary", {})
    
    print(f"  Objective: {obj_base:,.2f} JPY")
    print(f"  Trips: {summary_base.get('trip_count_served')}/{summary_base.get('trip_count_served', 0) + summary_base.get('trip_count_unserved', 0)}")
    print(f"  Energy cost: {cost_base.get('energy_cost', 0):,.2f} JPY")
    
    # Step 5: Run multi-day optimization
    print(f"\n=== STEP 5: Running MILP on multi-day scenario ===")
    r = requests.post(
        f"{BASE_URL}/scenarios/{scenario_id_md}/run-optimization",
        json={
            "mode": "mode_milp_only",
            "time_limit_seconds": 180,
            "mip_gap": 0.01,
            "random_seed": 42,
            "service_id": "WEEKDAY",
            "depot_id": "tsurumaki",
            "rebuild_dispatch": True,
        }
    )
    if r.status_code not in (200, 201):
        print(f"[ERR] Cannot start optimization: {r.status_code} {r.text}")
        return
    
    job_md = r.json()
    job_id_md = job_md.get("job_id")
    print(f"  Job started: {job_id_md}")
    
    job_result_md = poll_job(job_id_md, timeout=300)
    if not job_result_md:
        print(f"[ERR] Multi-day job failed or timed out")
        return
    
    print(f"  Multi-day job completed: status={job_result_md.get('status')}")
    
    # Fetch result
    r = requests.get(f"{BASE_URL}/scenarios/{scenario_id_md}/optimization")
    if r.status_code != 200:
        print(f"[ERR] Cannot fetch optimization result: {r.status_code}")
        return
    
    opt_md = r.json()
    obj_md = opt_md.get("objective_value")
    cost_md = opt_md.get("cost_breakdown", {})
    summary_md = opt_md.get("summary", {})
    
    print(f"  Objective: {obj_md:,.2f} JPY")
    print(f"  Trips: {summary_md.get('trip_count_served')}/{summary_md.get('trip_count_served', 0) + summary_md.get('trip_count_unserved', 0)}")
    print(f"  Energy cost: {cost_md.get('energy_cost', 0):,.2f} JPY")
    
    # Step 6: Analysis
    print(f"\n=== STEP 6: Analysis & Comparison ===")
    print(f"   Metric                Base         Multi-day    Ratio      Note")
    print(f"   ─────────────────────────────────────────────────────────────────")
    
    obj_ratio = obj_md / obj_base if obj_base else 0
    print(f"   Objective             {obj_base:>12,.0f}  {obj_md:>12,.0f}  {obj_ratio:>6.2f}x   (expect ~2x if no optimization gain)")
    
    trips_base_total = (summary_base.get('trip_count_served', 0) + summary_base.get('trip_count_unserved', 0))
    trips_md_total = (summary_md.get('trip_count_served', 0) + summary_md.get('trip_count_unserved', 0))
    trips_ratio = trips_md_total / trips_base_total if trips_base_total else 0
    print(f"   Total trips           {trips_base_total:>12}  {trips_md_total:>12}  {trips_ratio:>6.2f}x   (expect ~2x)")
    
    energy_ratio = cost_md.get('energy_cost', 0) / cost_base.get('energy_cost', 1) if cost_base.get('energy_cost', 0) else 0
    print(f"   Energy cost           {cost_base.get('energy_cost', 0):>12,.0f}  {cost_md.get('energy_cost', 0):>12,.0f}  {energy_ratio:>6.2f}x")
    
    unserved_base = summary_base.get('trip_count_unserved', 0)
    unserved_md = summary_md.get('trip_count_unserved', 0)
    print(f"   Unserved trips        {unserved_base:>12}  {unserved_md:>12}")
    
    if obj_ratio >= 1.8 and obj_ratio <= 2.2:
        print(f"\n   ✓ Multi-day replication appears CORRECT")
        print(f"     - Trip count scaled appropriately (~{trips_ratio:.1f}x)")
        print(f"     - Cost scaled reasonably (~{obj_ratio:.1f}x, no huge optimization gain)")
    else:
        print(f"\n   ⚠ Multi-day result may have issues")
        print(f"     - Expected objective ratio ~2x, got {obj_ratio:.2f}x")
        print(f"     - Could indicate solver timeout, infeasibility, or multi-day bug")
    
    print(f"\n=== DONE ===")

if __name__ == "__main__":
    test_multiday_scenario()
