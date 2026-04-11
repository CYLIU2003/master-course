from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from bff.store import job_store
from bff.store.job_store import Job


def test_persist_job_retries_after_permission_error(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(job_store, "_JOB_DIR", tmp_path)
    monkeypatch.setattr(job_store.time, "sleep", lambda *_args, **_kwargs: None)

    job = Job(
        job_id="job-1",
        status="running",
        progress=42,
        metadata={"execution_model": "process"},
    )

    original_replace = job_store.Path.replace
    call_count = {"value": 0}

    def flaky_replace(self: Path, target: Path) -> Path:
        call_count["value"] += 1
        if call_count["value"] == 1:
            raise PermissionError(5, "locked", str(target))
        return original_replace(self, target)

    monkeypatch.setattr(job_store.Path, "replace", flaky_replace)

    job_store._persist_job(job)

    payload = json.loads((tmp_path / "job-1.json").read_text(encoding="utf-8"))
    assert payload["job_id"] == "job-1"
    assert call_count["value"] == 2


def test_get_job_skips_disk_reload_for_thread_jobs(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(job_store, "_JOB_DIR", tmp_path)

    job = Job(job_id="job-2", metadata={"execution_model": "thread"})
    monkeypatch.setattr(job_store, "_jobs", {"job-2": job})

    with patch.object(job_store.Path, "read_text", side_effect=AssertionError("should not read disk")):
        assert job_store.get_job("job-2") is job


def test_get_job_returns_in_memory_job_when_disk_read_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(job_store, "_JOB_DIR", tmp_path)

    job = Job(job_id="job-3", status="running", metadata={"execution_model": "process"})
    monkeypatch.setattr(job_store, "_jobs", {"job-3": job})
    (tmp_path / "job-3.json").write_text("{}", encoding="utf-8")

    with patch.object(job_store.Path, "read_text", side_effect=PermissionError(5, "locked", str(tmp_path / "job-3.json"))):
        assert job_store.get_job("job-3") is job
