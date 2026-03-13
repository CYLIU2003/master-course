import json
from pathlib import Path
from unittest.mock import patch

from bff.store import job_store


def test_job_store_metadata_roundtrip():
    job = job_store.create_job()
    job_store.update_job(
        job.job_id,
        status="running",
        progress=42,
        metadata={"stage": "solve", "trip_count": 12},
    )

    payload = job_store.job_to_dict(job_store.get_job(job.job_id))

    assert payload["status"] == "running"
    assert payload["progress"] == 42
    assert payload["metadata"] == {"stage": "solve", "trip_count": 12}


def test_job_store_exposes_ephemeral_persistence_contract():
    job = job_store.create_job()

    payload = job_store.job_to_dict(job)

    assert payload["persistence"]["store"] == "json_files"
    assert payload["persistence"]["survives_restart"] is True
    assert "outputs/jobs" in payload["persistence"]["warning"]
    assert payload["metadata"]["persistence"]["store"] == "json_files"


def test_job_store_persists_and_marks_running_jobs_orphaned(tmp_path: Path):
    with patch.object(job_store, "_JOB_DIR", tmp_path), patch.object(job_store, "_jobs", {}):
        job = job_store.create_job()
        job_store.update_job(job.job_id, status="running", progress=50, message="Working")

        persisted = json.loads((tmp_path / f"{job.job_id}.json").read_text(encoding="utf-8"))
        assert persisted["status"] == "running"

        reloaded = job_store._load_jobs_from_disk()
        assert reloaded[job.job_id].status == "failed"
        assert reloaded[job.job_id].metadata["orphaned"] is True
