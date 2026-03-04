"""
bff/store/job_store.py

In-memory job store for background pipeline tasks.
Jobs are ephemeral — they do not survive server restarts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Job:
    job_id: str
    status: str = "pending"  # pending | running | completed | failed
    progress: int = 0  # 0-100
    message: str = ""
    result_key: Optional[str] = None
    error: Optional[str] = None


# Module-level store — single instance per process
_jobs: Dict[str, Job] = {}


def create_job() -> Job:
    job_id = str(uuid.uuid4())
    job = Job(job_id=job_id)
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Job:
    if job_id not in _jobs:
        raise KeyError(job_id)
    return _jobs[job_id]


def update_job(
    job_id: str,
    *,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    message: Optional[str] = None,
    result_key: Optional[str] = None,
    error: Optional[str] = None,
) -> Job:
    job = get_job(job_id)
    if status is not None:
        job.status = status
    if progress is not None:
        job.progress = progress
    if message is not None:
        job.message = message
    if result_key is not None:
        job.result_key = result_key
    if error is not None:
        job.error = error
    return job


def job_to_dict(job: Job) -> Dict[str, Any]:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "result_key": job.result_key,
        "error": job.error,
    }
