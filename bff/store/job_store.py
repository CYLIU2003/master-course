"""
bff/store/job_store.py

Disk-backed job store for background pipeline tasks.
Jobs survive BFF restarts; in-flight jobs are marked orphaned/failed on reload.
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Optional

from bff.store import output_paths


_JOB_DIR = output_paths.outputs_root() / "jobs"
_PERSIST_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4)
_thread_locks: Dict[str, threading.Lock] = {}
_thread_locks_guard = threading.Lock()


class StaleJobStateError(ValueError):
    """The job changed on disk between a recovery read and its write."""

JOB_PERSISTENCE_INFO: Dict[str, Any] = {
    "store": "json_files",
    "survives_restart": True,
    "warning": "Background jobs persist to output/jobs; after restart, only an exited or reused local process is marked failed. Remote and unverifiable work awaits reconciliation.",
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


def _normalize_execution_model(execution_model: Any) -> str:
    value = str(execution_model or "").strip().lower()
    return value if value in {"thread", "process"} else ""


def _should_reload_job_from_disk(job: Job) -> bool:
    return _normalize_execution_model(job.metadata.get("execution_model")) != "thread"


@contextmanager
def _locked_job(job_id: str):
    """Serialize read/modify/write across BFF threads and processes."""
    _JOB_DIR.mkdir(parents=True, exist_ok=True)
    key = str(_job_path(job_id))
    with _thread_locks_guard:
        thread_lock = _thread_locks.setdefault(key, threading.Lock())
    with thread_lock:
        with (_JOB_DIR / f".{job_id}.lock").open("a+b") as lock_file:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            deadline = time.monotonic() + 30.0
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Timed out locking job {job_id}")
                    time.sleep(0.05)
            try:
                yield
            finally:
                lock_file.seek(0)
                if os.name == "nt":
                    msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock_file, fcntl.LOCK_UN)


def _write_job_unlocked(job: Job) -> None:
    path = _job_path(job.job_id)
    temp_path = _JOB_DIR / f".{job.job_id}.{uuid.uuid4().hex}.tmp"
    payload = json.dumps(job_to_dict(job), ensure_ascii=False, indent=2, allow_nan=False)
    try:
        with temp_path.open("x", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt, delay in enumerate(_PERSIST_RETRY_DELAYS, start=1):
            try:
                temp_path.replace(path)
                return
            except PermissionError:
                if attempt >= len(_PERSIST_RETRY_DELAYS):
                    raise
                time.sleep(delay)
    finally:
        temp_path.unlink(missing_ok=True)


def _persist_job(job: Job, *, expect_new: bool = False) -> None:
    with _locked_job(job.job_id):
        path = _job_path(job.job_id)
        if expect_new and path.exists():
            raise ValueError(f"Job ID already exists: {job.job_id}")
        current_version = _version(_read_job(path)) if path.exists() else 0
        if _version(job) != current_version:
            raise StaleJobStateError(f"Stale job state for {job.job_id}")
        next_metadata = {**job.metadata, "state_version": current_version + 1}
        _write_job_unlocked(replace(job, metadata=next_metadata))
        job.metadata = next_metadata


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


def _read_job(path: Path) -> Job:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Job record must be an object")
    job = _job_from_payload(payload)
    if job.job_id != path.stem:
        raise ValueError("Job record ID does not match its filename")
    _version(job)
    return job


def _version(job: Job) -> int:
    raw = job.metadata.get("state_version", 0)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ValueError("Job state_version must be a nonnegative integer")
    return raw


def _record_error(job_id: str, exc: Exception, *, prior: Job | None = None,
                  kind: str = "read_unavailable") -> Job:
    job = replace(prior, metadata=dict(prior.metadata)) if prior is not None else Job(job_id=job_id, status="failed")
    job.message = f"Job record {kind}; original file retained."
    job.error = f"{kind}: {type(exc).__name__}"
    job.metadata = {**job.metadata, "persistence_error": job.error}
    return job


def _json_compatible(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_compatible(item) for item in value]
    if isinstance(value, tuple):
        return [_json_compatible(item) for item in value]
    return value


def _process_identity(pid: int) -> str | None:
    if pid <= 0:
        return None
    # The worker probe uses read-only Windows process APIs.
    from bff.services.cluster.runner import process_identity
    return process_identity(pid)


def _load_jobs_from_disk() -> Dict[str, Job]:
    jobs: Dict[str, Job] = {}
    if not _JOB_DIR.exists():
        return jobs
    for path in _JOB_DIR.glob("*.json"):
        try:
            job = _read_job(path)
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            kind = "invalid_record" if isinstance(exc, (ValueError, TypeError, UnicodeError)) else "read_unavailable"
            jobs[path.stem] = _record_error(path.stem, exc, kind=kind)
            continue
        if job.status in {"pending", "running"}:
            if job.metadata.get("cluster_job_id"):
                # Remote attempts are reconciled by the durable queue, not by local PID.
                job.metadata = {**job.metadata, "recovery_state": "remote_reconciliation_required"}
            else:
                try:
                    identity = _process_identity(int(job.metadata.get("pid") or 0))
                except Exception as exc:
                    identity = "unknown"
                    job.metadata = {**job.metadata, "recovery_probe_error": type(exc).__name__}
                recorded = str(job.metadata.get("process_identity") or "")
                if identity is None or (identity != "unknown" and recorded and identity != recorded):
                    job.status = "failed"
                    job.message = "Background process exited or PID was reused; original job retained."
                    job.error = "job_orphaned_after_restart"
                    job.metadata = {**job.metadata, "orphaned": True}
                    try:
                        _persist_job(job)
                    except StaleJobStateError:
                        try:
                            job = _read_job(path)
                        except (OSError, UnicodeError, ValueError, TypeError) as exc:
                            job = _record_error(job.job_id, exc, prior=job, kind="recovery_read_failed")
                    except (OSError, ValueError, TimeoutError) as exc:
                        job = _record_error(job.job_id, exc, prior=job, kind="recovery_persist_failed")
                elif identity == "unknown" or not recorded:
                    job.metadata = {**job.metadata, "recovery_state": "process_identity_unverified"}
                    job.message = "Process identity could not be verified after restart."
        jobs[job.job_id] = job
    return jobs


# Module-level store — hydrated from disk on process start
_jobs: Dict[str, Job] = _load_jobs_from_disk()


def create_job(*, execution_model: Optional[str] = None, job_id: Optional[str] = None) -> Job:
    job_id = str(uuid.UUID(job_id)) if job_id else str(uuid.uuid4())
    metadata: Dict[str, Any] = {
        "persistence": dict(JOB_PERSISTENCE_INFO),
        "pid": os.getpid(),
        "process_identity": _process_identity(os.getpid()),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    normalized_execution_model = _normalize_execution_model(execution_model)
    if normalized_execution_model:
        metadata["execution_model"] = normalized_execution_model
    job = Job(job_id=job_id, metadata=metadata)
    _persist_job(job, expect_new=True)
    _jobs[job_id] = job
    return job


def get_job(job_id: str) -> Job:
    job = _jobs.get(job_id)
    if job is not None and not _should_reload_job_from_disk(job):
        return job
    path = _job_path(job_id)
    if path.exists():
        try:
            disk_job = _read_job(path)
            if (job is None or _version(disk_job) > _version(job)
                    or not (job.metadata.get("recovery_state") or job.metadata.get("persistence_error"))):
                job = disk_job
                _jobs[job_id] = job
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            kind = "invalid_record" if isinstance(exc, (ValueError, TypeError, UnicodeError)) else "read_unavailable"
            return _record_error(job_id, exc, prior=job, kind=kind)
    if job is None:
        raise KeyError(job_id)
    return job


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
    with _locked_job(job_id):
        job = _read_job(_job_path(job_id))
        current_version = _version(job)
        _apply_update(job, status=status, progress=progress, message=message,
                      result_key=result_key, error=error, metadata=metadata)
        job.metadata = {**job.metadata, "state_version": current_version + 1}
        _write_job_unlocked(job)
        _jobs[job_id] = job
        return job


def _apply_update(job: Job, *, status: Optional[str], progress: Optional[int],
                  message: Optional[str], result_key: Optional[str], error: Optional[str],
                  metadata: Optional[Dict[str, Any]]) -> Job:
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
        "process_identity": _process_identity(os.getpid()),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    return job


def job_to_dict(job: Job) -> Dict[str, Any]:
    payload = {
        "job_id": job.job_id,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "result_key": job.result_key,
        "error": job.error,
        "metadata": job.metadata,
        "persistence": dict(JOB_PERSISTENCE_INFO),
    }
    return _json_compatible(payload)
