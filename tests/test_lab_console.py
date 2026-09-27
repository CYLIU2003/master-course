from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from uuid import uuid4

import pytest

from tools.research import lab_console as lab


def payload():
    return {"request_id": str(uuid4()), "requester": "研究者", "project": "別研究", "title": "試算",
            "workload": "python", "solver": "gurobi", "memory_gib": 16, "threads": 2,
            "time_limit_minutes": 60, "license_basis": "未確認", "instructions": "入力は別途共有"}


def test_receipt_persists_without_any_solver_queue_and_duplicate_is_idempotent(tmp_path):
    request = payload()
    result = lab.receive(tmp_path, request)
    assert result["state"] == "REVIEW_REQUIRED" and not result["solver_submitted"]
    assert lab.receive(tmp_path, request)["reused"]
    assert len(lab.requests(tmp_path)) == 1
    assert list(p.name for p in tmp_path.iterdir()) == ["requests.sqlite3"]
    with pytest.raises(ValueError):
        lab.receive(tmp_path, {**request, "threads": 4})
    assert lab.requests(tmp_path)[0]["request"]["threads"] == 2


def test_parallel_same_request_has_one_durable_receipt(tmp_path):
    request = payload()
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(lambda _: lab.receive(tmp_path, request), range(6)))
    assert len(lab.requests(tmp_path)) == 1


def test_concurrent_conflicting_requests_never_report_unstored_content(tmp_path):
    from threading import Barrier
    request = payload()
    barrier = Barrier(6)
    def submit(i):
        barrier.wait()
        try:
            return lab.receive(tmp_path, {**request, "title": str(i)})
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = [r for r in pool.map(submit, range(6)) if r is not None]
    assert len(responses) == 1
    assert responses[0]["sha256"] == lab.requests(tmp_path)[0]["sha256"]


@pytest.mark.parametrize("changes", [{"memory_gib": float('nan')}, {"threads": 0}, {"solver": "typo"},
                                     {"requester": "   "}, {"command": "execute something"},
                                     {"attachments": [{"name": "../secret", "size": 1, "sha256": "a" * 64}]}])
def test_invalid_requests_do_not_create_a_database(tmp_path, changes):
    with pytest.raises(ValueError):
        lab.receive(tmp_path, {**payload(), **changes})
    assert not (tmp_path / "requests.sqlite3").exists()


def make_report(tmp_path):
    revision = "a" * 64
    directory = tmp_path / "reports" / "revisions" / revision
    directory.mkdir(parents=True)
    data = {"source_sha": "b" * 40, "parent": "scenario", "rows": [{}],
            "cases": [{"week": "2025-01-06", "state": "REPORTING_RECOVERED", "included": True,
                       "original_state": "FAILED", "total_cost_jpy": 123}], "complete": False}
    body = json.dumps(data).encode()
    (directory / "comparison.json").write_bytes(body)
    (directory / "manifest.json").write_text(json.dumps({"comparison.json": hashlib.sha256(body).hexdigest()}))
    (tmp_path / "reports" / "latest.json").write_text(json.dumps({"revision": revision, "observed_at_utc": "2026-09-27"}))
    (tmp_path / "lab-config.json").write_text(json.dumps({"inventory_port": 8868, "report_root": str(tmp_path / "reports")}))
    return directory, revision


def test_report_keeps_recovery_and_original_failure_separate(tmp_path):
    make_report(tmp_path)
    report = lab.view(tmp_path, {"port": 8891, "git_sha": "b" * 40})["report"]
    assert report["included"] == 1 and not report["complete"]
    assert report["cases"][0]["original_state"] == "FAILED"
    with pytest.raises(ValueError, match="version differs"):
        lab.view(tmp_path, {"port": 8891, "git_sha": "c" * 40})


def test_report_rejects_tampered_artifact_and_path_traversal(tmp_path):
    directory, revision = make_report(tmp_path)
    with pytest.raises(ValueError):
        lab.report_file(tmp_path / "reports", "../" + revision, "comparison.json")
    with pytest.raises(ValueError):
        lab.report_file(tmp_path / "reports", revision, "../../secret")
    with pytest.raises(ValueError, match="version differs"):
        lab.report_file(tmp_path / "reports", revision, "manifest.json", "c" * 40)
    (directory / "comparison.json").write_text('{}')
    with pytest.raises(ValueError, match="hash mismatch"):
        lab.report_file(tmp_path / "reports", revision, "comparison.json")
