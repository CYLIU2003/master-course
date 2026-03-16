import json
import traceback
from datetime import datetime

from bff.routers.optimization import _run_optimization
from bff.store import job_store

SCENARIO_ID = "41c6872a-717a-4357-81b0-87f5812bf06d"
SERVICE_ID = "WEEKDAY"
DEPOT_ID = "tsurumaki"

job = job_store.create_job()
job_id = job.job_id

with open("tmp_sync_run_marker.txt", "w", encoding="utf-8") as f:
    f.write(f"started {datetime.now().isoformat()} job={job_id}\n")
result: dict = {"job_id": job_id}
try:
    _run_optimization(
        scenario_id=SCENARIO_ID,
        job_id=job_id,
        mode="mode_milp_only",
        time_limit_seconds=600,
        mip_gap=0.01,
        random_seed=42,
        service_id=SERVICE_ID,
        depot_id=DEPOT_ID,
        rebuild_dispatch=True,
        use_existing_duties=False,
        alns_iterations=200,
    )
    result["run_call"] = "returned"
except Exception as exc:
    result["run_call"] = "exception"
    result["exception"] = str(exc)
    result["traceback"] = traceback.format_exc()

job_path = f"outputs/jobs/{job_id}.json"
try:
    with open(job_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    result["job"] = payload
except Exception as exc:
    result["job_read_error"] = str(exc)

with open("tmp_sync_run_optimization_result.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("wrote tmp_sync_run_optimization_result.json")
