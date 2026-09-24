"""Generic worker checkpoints are bound to one durable cluster attempt."""

import json

from bff.services.cluster import runner
from bff.services.cluster.contracts import canonical, digest
from bff.services.cluster.store import JobStore


def test_progress_survives_restart_and_rejects_other_or_older_attempts(tmp_path):
    store = JobStore(tmp_path)
    manifest = {"id": "attempt-a", "kind": "optimization"}
    store.add(manifest)
    assert not store.record_progress("attempt-a", {
        "id": "attempt-a", "manifest_sha256": digest(canonical(manifest)),
        "execution_progress": {"percent": 25},
    })  # Queued work has not been accepted by a worker.
    assert store.transition("attempt-a", "RUNNING", expected={"QUEUED"}, worker_id="pc")
    receipt = {"id": "attempt-a", "manifest_sha256": digest(canonical(manifest)),
               "execution_progress": {"percent": 55, "stage": "solve",
                                      "message": "Running token=private-value optimizer"}}
    assert store.record_progress("attempt-a", receipt)
    restarted = JobStore(tmp_path)
    progress = restarted.get("attempt-a")["execution_progress"]
    assert progress["percent"] == 55 and progress["stage"] == "solve"
    assert "private-value" not in progress["message"]
    assert progress["meaning"] == "pipeline_checkpoint_not_solver_gap"
    assert not store.record_progress("attempt-a", {**receipt, "manifest_sha256": "wrong"})
    assert not store.record_progress("attempt-a", {**receipt, "id": "attempt-b"})
    assert not store.record_progress("attempt-a", {**receipt,
        "execution_progress": {"percent": 25, "stage": "old"}})
    assert store.get("attempt-a")["execution_progress"]["percent"] == 55
    assert store.transition("attempt-a", "COMPLETED", expected={"RUNNING"})
    assert not store.record_progress("attempt-a", receipt)
    assert store.rows()[0]["execution_progress"]["percent"] == 55


def test_worker_reports_only_matching_local_checkpoint(tmp_path, monkeypatch):
    job_id = "attempt-a"
    directory = tmp_path / job_id
    directory.mkdir()
    runner.write_json(directory / "state.json", {
        "id": job_id, "state": "RUNNING", "pid": 42,
        "process_identity": "birth-1", "manifest_sha256": "bound-hash",
    })
    monkeypatch.setattr(runner, "process_identity", lambda pid: "birth-1")
    local_job_id = runner.local_progress_job_id(job_id)
    checkpoint = directory / "output" / "jobs" / f"{local_job_id}.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text(json.dumps({
        "job_id": local_job_id, "progress": 55, "message": "Running optimizer",
        "metadata": {"stage": "solve"},
    }), encoding="utf-8")
    state = runner.worker_state(tmp_path, job_id)
    assert state["execution_progress"] == {
        "percent": 55, "stage": "solve", "message": "Running optimizer"}
    checkpoint.write_text(json.dumps({"job_id": "other", "progress": 100}), encoding="utf-8")
    assert "execution_progress" not in runner.worker_state(tmp_path, job_id)
    checkpoint.write_text("{broken", encoding="utf-8")
    assert runner.worker_state(tmp_path, job_id)["state"] == "RUNNING"
