#!/usr/bin/env python3
"""Quick test - run MILP only"""
import json
import requests
import time

BASE_URL = "http://localhost:8000/api"
SCENARIO_ID = "237d5623-aa94-4f72-9da1-17b9070264be"

print("Testing optimization execution...")
print(f"Scenario: {SCENARIO_ID}")

# Test server
try:
    r = requests.get(f"{BASE_URL}/../health", timeout=5)
    print(f"[OK] Server health: {r.json()}")
except Exception as e:
    print(f"[ERROR] Server not responding: {e}")
    exit(1)

# Start MILP job
request_body = {
    "mode": "mode_milp_only",
    "time_limit_seconds": 60,  # Short time for testing
    "mip_gap": 0.05,
    "random_seed": 42,
    "service_id": "WEEKDAY",
    "depot_id": "tsurumaki",
    "rebuild_dispatch": False,
    "use_existing_duties": False,
}

print(f"\n[POST] Starting MILP optimization...")
print(f"URL: {BASE_URL}/scenarios/{SCENARIO_ID}/run-optimization")

try:
    r = requests.post(
        f"{BASE_URL}/scenarios/{SCENARIO_ID}/run-optimization",
        json=request_body,
        timeout=30,
    )
    
    print(f"[RESPONSE] Status: {r.status_code}")
    print(f"[RESPONSE] Body: {json.dumps(r.json(), indent=2)}")
    
    if r.status_code != 200:
        print("[ERROR] Failed to start optimization")
        exit(1)
    
    job = r.json()
    job_id = job.get("job_id")
    print(f"\n[OK] Job started: {job_id}")
    
    # Poll
    print("\n[POLLING] Waiting for completion...")
    for i in range(30):  # 30 polls = 2.5 minutes
        time.sleep(5)
        
        r = requests.get(f"{BASE_URL}/jobs/{job_id}", timeout=10)
        if r.status_code != 200:
            print(f"[WARN] Poll {i}: HTTP {r.status_code}")
            continue
        
        status_data = r.json()
        status = status_data.get("status")
        progress = status_data.get("progress", 0)
        message = status_data.get("message", "")
        
        print(f"[{i*5:3d}s] {status:12} Progress: {progress:3d}% - {message[:60]}")
        
        if status in ["completed", "failed", "cancelled"]:
            print(f"\n[FINAL] Status: {status}")
            if status == "completed":
                print("[SUCCESS] Optimization completed!")
            else:
                error = status_data.get("error", "Unknown")
                print(f"[ERROR] {error}")
            break
    else:
        print("\n[TIMEOUT] Job still running after 2.5 minutes")

except Exception as e:
    print(f"[ERROR] Exception: {e}")
    import traceback
    traceback.print_exc()
