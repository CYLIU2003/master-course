import json
from bff.store import job_store

jobs = list(job_store._jobs.values())
failed = [j for j in jobs if j.status == 'failed']
print(f"Total jobs: {len(jobs)}")
print(f"Failed jobs: {len(failed)}")
if failed:
    last = failed[-1]
    print(last.error)
    print(job_store.job_to_dict(last))
else:
    print("No failed jobs")

running = [j for j in jobs if j.status == 'running']
print(f"Running jobs: {len(running)}")
if running:
    print(running[-1].job_id)
