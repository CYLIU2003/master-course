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

    assert payload["persistence"]["store"] == "process_memory"
    assert payload["persistence"]["survives_restart"] is False
    assert "restarts" in payload["persistence"]["warning"]
    assert payload["metadata"]["persistence"]["store"] == "process_memory"
