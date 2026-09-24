"""The dashboard must describe durable work, not infer solver progress."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "tools/research/publish_campaign_progress.py"
SPEC = importlib.util.spec_from_file_location("publish_campaign_progress", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def campaign(tmp_path: Path) -> Path:
    root = tmp_path / "month-campaign"
    write_json(root / "binding.json", {
        "git_sha": "fixed-source-sha",
        "weeks": ["2025-01-06", "2025-02-03"],
    })
    write_json(root / "2025-01-06/state.json", {
        "status": "PREPARED", "strict_scope_audit_passed": True,
        "prepared_input_id": "prepared-first", "prepared_input_sha256": "input-sha",
    })
    write_json(root / "2025-02-03/state.json", {"status": "DUPLICATED"})
    return root


def test_prepare_percentage_uses_completed_weeks_only(tmp_path: Path) -> None:
    root = campaign(tmp_path)
    progress = publisher.snapshot(root, prepare_running=True)

    assert progress["stages"]["prepare"] == {"completed": 1, "total": 2, "percent": 50}
    assert progress["stages"]["overall"] == {"completed": 1, "total": 6, "percent": 17}
    assert progress["stages"]["solve"]["percent"] == 0
    assert progress["weeks"][1]["status"] == "DUPLICATED"
    assert progress["status"] == "RUNNING"
    assert progress["research_status"] == "DIAGNOSTIC_NOT_RESEARCH_APPROVED"


def test_idle_prepare_and_failed_collection_remain_distinct(tmp_path: Path) -> None:
    root = campaign(tmp_path)
    write_json(root / "batch-state/batch-state.json", {"tasks": {
        "month-2025-01": {"state": "COMPLETED", "job_id": "job-first"},
    }})
    write_json(root / "artifact-audit.json", {"tasks": [
        {"task_id": "month-2025-01", "job_id": "job-first", "collection_verified": False,
         "error": "SHA mismatch"},
        {"task_id": "month-2025-02", "collection_verified": False,
         "error": "Task did not complete"},
    ]})

    progress = publisher.snapshot(root, prepare_running=False)

    assert progress["weeks"][0]["status"] == "AUDIT_FAILED"
    assert progress["weeks"][0]["error"] == "SHA mismatch"
    assert progress["weeks"][1]["status"] == "PAUSED"
    assert progress["weeks"][1]["error"] is None
    assert progress["stages"]["solve"]["completed"] == 1
    assert progress["stages"]["audit"]["completed"] == 0
    assert progress["status"] == "ERROR"


def test_stale_audit_from_another_attempt_is_not_accepted(tmp_path: Path) -> None:
    root = campaign(tmp_path)
    write_json(root / "batch-state/batch-state.json", {"tasks": {
        "month-2025-01": {"state": "COMPLETED", "job_id": "current-job"},
    }})
    write_json(root / "artifact-audit.json", {"tasks": [
        {"task_id": "month-2025-01", "job_id": "previous-job",
         "collection_verified": True},
    ]})

    progress = publisher.snapshot(root, prepare_running=False)

    assert progress["weeks"][0]["status"] == "COMPLETED"
    assert progress["stages"]["solve"]["completed"] == 1
    assert progress["stages"]["audit"]["completed"] == 0


def test_publish_preserves_source_and_replaces_one_snapshot(tmp_path: Path) -> None:
    root = campaign(tmp_path)
    destination = tmp_path / "static" / "campaign-progress.json"
    before = (root / "binding.json").read_bytes()

    publisher.publish(root, destination)
    first = json.loads(destination.read_text(encoding="utf-8"))
    publisher.publish(root, destination)

    assert first["campaign"] == root.name
    assert first["git_sha"] == "fixed-source-sha"
    assert (root / "binding.json").read_bytes() == before
    assert list(destination.parent.iterdir()) == [destination]


def test_invalid_binding_is_rejected_without_publish(tmp_path: Path) -> None:
    root = tmp_path / "invalid"
    write_json(root / "binding.json", {"weeks": [{"date": "2025-01-06"}]})
    destination = tmp_path / "static" / "campaign-progress.json"

    with pytest.raises(ValueError, match="service weeks"):
        publisher.publish(root, destination)
    assert not destination.exists()
