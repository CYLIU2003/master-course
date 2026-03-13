"""
bff/store/job_store.py

Disk-backed job store for background pipeline tasks.
Jobs survive BFF restarts; in-flight jobs are marked orphaned/failed on reload.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timezone
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


_JOB_DIR = Path(__file__).resolve().parents[2] / "outputs" / "jobs"

JOB_PERSISTENCE_INFO: Dict[str, Any] = {
    "store": "json_files",
    "survives_restart": True,
    "warning": "Background jobs are persisted to outputs/jobs; in-progress jobs are marked failed if the BFF restarts.",
}


@dataclass
class Job:
    job_id: str
    status: str = "pending"  # pending | running | completed | failed
    progress: int = 0  # 0-100
    message: str = ""
    result_key: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


def _job_path(job_id: str) -> Path:
    return _JOB_DIR / f"{job_id}.json"


def _persist_job(job: Job) -> None:
    _JOB_DIR.mkdir(parents=True, exist_ok=True)
    path = _job_path(job.job_id)
    temp_path = path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(job_to_dict(job), ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def _job_from_payload(payload: Dict[str, Any]) -> Job:
    metadata = {"persistence": dict(JOB_PERSISTENCE_INFO), **dict(payload.get("metadata") or {})}
    return Job(
        job_id=str(payload.get("job_id") or payload.get("jobId") or ""),
        status=str(payload.get("status") or "pending"),
        progress=int(payload.get("progress") or 0),
        message=str(payload.get("message") or ""),
        result_key=payload.get("result_key"),
        error=payload.get("error"),
        metadata=metadata,
    )


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _load_jobs_from_disk() -> Dict[str, Job]:
    jobs: Dict[str, Job] = {}
    if not _JOB_DIR.exists():
        return jobs
    for path in _JOB_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            job = _job_from_payload(payload)
            if job.status in {"pending", "running"}:
                pid = int(job.metadata.get("pid") or 0)
                if not _pid_exists(pid):
                    job.status = "failed"
                    job.message = "BFF restarted before the background job completed. Please retry the job."
                    job.error = job.error or "job_orphaned_after_restart"
                    job.metadata = {**job.metadata, "orphaned": True}
                    _persist_job(job)
            jobs[job.job_id] = job
        except Exception:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
            continue
    return jobs


# Module-level store — hydrated from disk on process start
_jobs: Dict[str, Job] = _load_jobs_from_disk()


def create_job() -> Job:
    job_id = str(uuid.uuid4())
    job = Job(
        job_id=job_id,
        metadata={
            "persistence": dict(JOB_PERSISTENCE_INFO),
            "pid": os.getpid(),
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    _jobs[job_id] = job
    _persist_job(job)
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
    metadata: Optional[Dict[str, Any]] = None,
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
    if metadata is not None:
        job.metadata = {**job.metadata, **dict(metadata)}
    job.metadata = {
        **job.metadata,
        "pid": os.getpid(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _persist_job(job)
    return job


def job_to_dict(job: Job) -> Dict[str, Any]:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "result_key": job.result_key,
        "error": job.error,
        "metadata": job.metadata,
        "persistence": dict(JOB_PERSISTENCE_INFO),
    }
