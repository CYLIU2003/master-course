"""Job records remain inspectable after recovery and concurrent updates."""
from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from bff.store import job_store
from bff.store.job_store import Job


def _save(path: Path, job: Job) -> bytes:
    raw = json.dumps(job_store.job_to_dict(job)).encode("utf-8")
    path.write_bytes(raw)
    return raw


def test_invalid_record_is_visible_and_never_deleted(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "_JOB_DIR", tmp_path)
    path = tmp_path / "broken.json"
    raw = b"{broken"
    path.write_bytes(raw)

    loaded = job_store._load_jobs_from_disk()

    assert path.read_bytes() == raw
    assert loaded["broken"].status == "failed"
    assert loaded["broken"].error == "invalid_record: JSONDecodeError"
    monkeypatch.setattr(job_store, "_jobs", loaded)
    from bff.routers.jobs import get_job
    assert get_job("broken")["error"] == "invalid_record: JSONDecodeError"


def test_corrupt_display_record_does_not_block_durable_cluster_mirror(tmp_path, monkeypatch, caplog):
    from bff.services.cluster.scheduler import Scheduler

    monkeypatch.setattr(job_store, "_JOB_DIR", tmp_path)
    path = tmp_path / "broken.json"
    path.write_bytes(b"{broken")
    monkeypatch.setattr(job_store, "_jobs", job_store._load_jobs_from_disk())

    Scheduler.mirror("broken", "completed", "done")

    assert path.read_bytes() == b"{broken"
    assert "Display job mirror unavailable" in caplog.text


def test_transient_read_error_is_visible_without_deleting_completed_record(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "_JOB_DIR", tmp_path)
    path = tmp_path / "completed.json"
    raw = _save(path, Job(job_id="completed", status="completed"))
    original_read = Path.read_text

    def fail_once(self, *args, **kwargs):
        if self == path:
            raise PermissionError("locked")
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_once)
    loaded = job_store._load_jobs_from_disk()
    assert loaded["completed"].error == "read_unavailable: PermissionError"
    assert path.read_bytes() == raw


def test_invalid_state_version_is_reported_without_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "_JOB_DIR", tmp_path)
    path = tmp_path / "bad-version.json"
    raw = _save(path, Job(job_id="bad-version", status="completed", metadata={"state_version": -1}))
    loaded = job_store._load_jobs_from_disk()
    assert loaded["bad-version"].error == "invalid_record: ValueError"
    assert path.read_bytes() == raw


def test_failed_atomic_replace_keeps_prior_record_and_removes_partial(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "_JOB_DIR", tmp_path)
    path = tmp_path / "job.json"
    raw = _save(path, Job(job_id="job", status="pending"))
    original_replace = Path.replace

    def disk_full(self, target):
        if target == path:
            raise OSError("disk full")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", disk_full)
    with pytest.raises(OSError, match="disk full"):
        job_store.update_job("job", status="running")
    assert path.read_bytes() == raw
    assert not list(tmp_path.glob("*.tmp"))


def test_recovery_save_failure_keeps_original_and_reports_cause(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "_JOB_DIR", tmp_path)
    path = tmp_path / "orphan.json"
    raw = _save(path, Job(job_id="orphan", status="running", metadata={"pid": 123, "process_identity": "old"}))
    monkeypatch.setattr(job_store, "_process_identity", lambda pid: None)
    monkeypatch.setattr(job_store, "_persist_job", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))

    loaded = job_store._load_jobs_from_disk()

    assert path.read_bytes() == raw
    assert loaded["orphan"].status == "failed"
    assert loaded["orphan"].error == "recovery_persist_failed: OSError"
    monkeypatch.setattr(job_store, "_jobs", loaded)
    assert job_store.get_job("orphan").error == "recovery_persist_failed: OSError"


def test_recovery_uses_newer_completed_record_instead_of_stale_orphan(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "_JOB_DIR", tmp_path)
    path = tmp_path / "job.json"
    _save(path, Job(job_id="job", status="running", metadata={"pid": 123, "process_identity": "old"}))
    monkeypatch.setattr(job_store, "_process_identity", lambda pid: None)

    def concurrent_completion(job):
        _save(path, Job(job_id="job", status="completed", metadata={"state_version": 1}))
        raise job_store.StaleJobStateError("changed")

    monkeypatch.setattr(job_store, "_persist_job", concurrent_completion)
    loaded = job_store._load_jobs_from_disk()["job"]
    assert loaded.status == "completed"
    assert loaded.metadata["state_version"] == 1


def test_pid_reuse_is_orphaned_but_remote_pid_is_never_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "_JOB_DIR", tmp_path)
    _save(tmp_path / "local.json", Job(job_id="local", status="running", metadata={"pid": 123, "process_identity": "old"}))
    _save(tmp_path / "remote.json", Job(job_id="remote", status="running", metadata={"pid": 123, "cluster_job_id": "remote"}))
    calls = []
    monkeypatch.setattr(job_store, "_process_identity", lambda pid: calls.append(pid) or "new")
    monkeypatch.setattr(job_store.os, "kill", lambda *a: pytest.fail("os.kill must not be used"))

    loaded = job_store._load_jobs_from_disk()

    assert calls == [123]
    assert loaded["local"].status == "failed"
    assert loaded["remote"].status == "running"
    assert loaded["remote"].metadata["recovery_state"] == "remote_reconciliation_required"


def test_inaccessible_process_remains_unverified_without_failing_job(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "_JOB_DIR", tmp_path)
    _save(tmp_path / "pending.json", Job(job_id="pending", status="pending", metadata={"pid": 456, "process_identity": "birth"}))
    monkeypatch.setattr(job_store, "_process_identity", lambda pid: "unknown")
    loaded = job_store._load_jobs_from_disk()["pending"]
    assert loaded.status == "pending"
    assert loaded.metadata["recovery_state"] == "process_identity_unverified"


def test_concurrent_updates_preserve_both_metadata_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "_JOB_DIR", tmp_path)
    monkeypatch.setattr(job_store, "_process_identity", lambda pid: "birth")
    _save(tmp_path / "job.json", Job(job_id="job", metadata={"state_version": 0}))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda key: job_store.update_job("job", metadata={key: True}), ("a", "b")))

    persisted = job_store._read_job(tmp_path / "job.json")
    assert persisted.metadata["a"] and persisted.metadata["b"]
    assert persisted.metadata["state_version"] == 2
    assert sorted(result.metadata["state_version"] for result in results) == [1, 2]
    assert not list(tmp_path.glob("*.tmp"))


def test_process_writers_preserve_both_metadata_changes(tmp_path):
    _save(tmp_path / "job.json", Job(job_id="job", metadata={"state_version": 0}))
    program = (
        "import sys; from pathlib import Path; from bff.store import job_store; "
        "job_store._JOB_DIR=Path(sys.argv[1]); "
        "job_store.update_job('job', metadata={sys.argv[2]: True})"
    )
    children = [subprocess.Popen([sys.executable, "-c", program, str(tmp_path), key]) for key in ("a", "b")]
    assert [child.wait(timeout=15) for child in children] == [0, 0]
    persisted = job_store._read_job(tmp_path / "job.json")
    assert persisted.metadata["a"] and persisted.metadata["b"]
    assert persisted.metadata["state_version"] == 2


def test_caller_metadata_cannot_override_state_version(tmp_path, monkeypatch):
    monkeypatch.setattr(job_store, "_JOB_DIR", tmp_path)
    monkeypatch.setattr(job_store, "_process_identity", lambda pid: "birth")
    _save(tmp_path / "job.json", Job(job_id="job", metadata={"state_version": 4}))
    updated = job_store.update_job("job", metadata={"state_version": -99})
    assert updated.metadata["state_version"] == 5
