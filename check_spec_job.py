import json
from bff.store import job_store

jobs = list(job_store._jobs.values())
job = job_store._jobs.get("eaf778fb-1cdf-40f3-86e3-5b4af8f0a571")
if job:
    print(job_store.job_to_dict(job))
