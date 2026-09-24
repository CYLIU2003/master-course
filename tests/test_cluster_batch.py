import json
import hashlib
import io
from pathlib import Path

import pytest

from bff.services.cluster.store import JobStore
from bff.services.cluster.submissions import claim_submission
from tools.cluster.batch import validate_batch, load_state, advance, Client


def test_download_streams_existing_archive_and_removes_failed_partial(tmp_path, monkeypatch):
    from tools.cluster import batch as module
    payload = b"archive" * 400_000
    expected = hashlib.sha256(payload).hexdigest()
    target = tmp_path / "attempt.zip"
    target.write_bytes(payload)
    monkeypatch.setattr(module, "urlopen", lambda *args, **kwargs: io.BytesIO(payload))
    def forbid_read_bytes(self):
        raise AssertionError("Large archives must be hashed without loading them into memory")
    monkeypatch.setattr(Path, "read_bytes", forbid_read_bytes)
    Client("http://127.0.0.1:8000").download("attempt", target, expected)
    assert target.stat().st_size == len(payload)
    assert not list(tmp_path.glob("attempt.zip.partial-*"))
    with pytest.raises(ValueError, match="Downloaded artifact hash"):
        Client("http://127.0.0.1:8000").download("attempt", target, "bad")
    assert not list(tmp_path.glob("attempt.zip.partial-*"))


def spec():
    return {"schema_version": 1, "batch_id": "test-batch", "git_sha": "a"*40, "controller_url": "http://127.0.0.1:8000",
            "tasks": [{"task_id": str(index), "submission": {"scenario_id": "s", "minimum_ram_gb": 1, "request": {
                "mode": "alns", "prepared_input_id": "prepared", "research_run": False}}} for index in range(12)]}


def test_idempotent_controller_submission_survives_restart(tmp_path):
    first = claim_submission(JobStore(tmp_path), "same-key", {"input": "frozen"})
    assert claim_submission(JobStore(tmp_path), "same-key", {"input": "frozen"}) == first
    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        claim_submission(JobStore(tmp_path), "same-key", {"input": "changed"})


def test_twelve_cases_resume_after_lost_submission_response_without_duplicates(tmp_path):
    class FakeClient:
        def __init__(self):
            self.jobs, self.dropped = {}, False
        def request(self, path, body=None):
            if body is not None:
                assert body["batch_id"] == "test-batch"
                assert body["task_id"] in {str(index) for index in range(12)}
                assert body["batch_task_count"] == 12
                key = body["idempotency_key"]
                self.jobs.setdefault(key, str(len(self.jobs)))
                if not self.dropped:
                    self.dropped = True
                    raise ConnectionError("reply lost after server accepted")
                return {"job_id": self.jobs[key]}
            return {"state": "COMPLETED", "result": {"archive_sha256": "verified"}}
        def download(self, job_id, target, expected):
            target.write_text(expected)
    batch, client = spec(), FakeClient()
    path = tmp_path / "state.json"
    state = load_state(batch, path)
    with pytest.raises(ConnectionError):
        advance(batch, state, path, client)
    summary = advance(batch, load_state(batch, path), path, client)
    assert len(client.jobs) == 12
    assert summary == {"total": 12, "completed": 12, "failed": 0, "unresolved": 0, "collected": 12,
                       "failure_fraction_of_declared_tasks": 0, "excluded_tasks": 0}
    advance(batch, load_state(batch, path), path, client)
    assert len(client.jobs) == 12


def test_batch_changes_formal_runs_and_external_urls_are_rejected(tmp_path):
    batch = spec()
    validate_batch(batch)
    load_state(batch, tmp_path / "state.json")
    batch["tasks"][0]["submission"]["request"]["research_run"] = True
    with pytest.raises(ValueError, match="allow-formal"):
        validate_batch(batch)
    with pytest.raises(ValueError, match="Batch changed"):
        load_state(batch, tmp_path / "state.json")
    with pytest.raises(ValueError, match="loopback"):
        Client("http://example.com")


def test_failed_cases_remain_in_the_denominator(tmp_path):
    class FailureClient:
        def request(self, path, body=None):
            return {"job_id": body["idempotency_key"]} if body else {"state": "FAILED", "error": "worker failure"}
    batch = spec()
    path = tmp_path / "state.json"
    summary = advance(batch, load_state(batch, path), path, FailureClient())
    assert summary["total"] == summary["failed"] == 12
    assert summary["completed"] == 0
    assert summary["failure_fraction_of_declared_tasks"] == 1 and summary["excluded_tasks"] == 0


def test_http_rejection_keeps_api_error_code_and_redacts_credentials():
    from urllib.error import HTTPError
    from tools.cluster.batch import sanitized_rejection

    body = json.dumps({"detail": {
        "error": "SCENARIO_INCOMPLETE",
        "message": "Run preparation failed: Bearer private-token-value",
    }}).encode("utf-8")
    error = HTTPError("http://127.0.0.1:8868/api/cluster/jobs", 500, "Error", {}, io.BytesIO(body))

    result = sanitized_rejection(error)

    assert result["error_code"] == "SCENARIO_INCOMPLETE"
    assert result["detail"] == "Run preparation failed: Bearer [REDACTED]"
    assert "private-token-value" not in json.dumps(result)
