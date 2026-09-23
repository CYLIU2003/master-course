"""A failed atomic save must leave the caller's version available for retry."""

from __future__ import annotations

from pathlib import Path

import pytest

from bff.store import job_store
from bff.store.job_store import Job


def test_failed_persist_can_retry_same_job_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(job_store, "_JOB_DIR", tmp_path)
    job = Job(job_id="retry")
    job_store._persist_job(job)
    original_write = job_store._write_job_unlocked
    monkeypatch.setattr(job_store, "_write_job_unlocked", lambda _job: (_ for _ in ()).throw(OSError("disk full")))

    with pytest.raises(OSError, match="disk full"):
        job_store._persist_job(job)

    monkeypatch.setattr(job_store, "_write_job_unlocked", original_write)
    job_store._persist_job(job)

    assert job.metadata["state_version"] == 2
    assert job_store._read_job(tmp_path / "retry.json").metadata["state_version"] == 2
