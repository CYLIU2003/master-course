"""T13–T17/T31: retry identities and interrupted result transfer remain isolated."""
import copy
from pathlib import Path
import pytest

from bff.services.cluster import runner, scheduler as module
from bff.services.cluster.contracts import canonical, digest
from bff.services.cluster.store import JobStore


def test_T14_duplicate_submit_returns_same_launch_and_changed_input_is_rejected(tmp_path, monkeypatch):
    calls = []
    class Child:
        pid = 123
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: calls.append(a) or Child())
    monkeypatch.setattr(runner, "process_identity", lambda pid: "birth-1")
    request = {"operation": "submit", "id": "attempt-a", "manifest": {"id": "attempt-a"}, "bundle": {"value": 1}}
    first = runner.handle(request, tmp_path)
    second = runner.handle(request, tmp_path)
    assert first == second and len(calls) == 1
    changed = copy.deepcopy(request); changed["bundle"]["value"] = 2
    with pytest.raises(ValueError, match="IDEMPOTENCY_CONFLICT"):
        runner.handle(changed, tmp_path)
    assert len(calls) == 1


def test_T16_pid_reuse_is_not_the_original_worker(tmp_path, monkeypatch):
    directory = tmp_path / "attempt-a"; directory.mkdir()
    runner.write_json(directory / "state.json", {"id": "attempt-a", "state": "RUNNING", "pid": 123, "process_identity": "birth-1"})
    monkeypatch.setattr(runner, "process_identity", lambda pid: "birth-2")
    assert runner.worker_state(tmp_path, "attempt-a")["state"] == "FAILED"


def test_T15_T32_recovery_backoff_survives_restart_and_keeps_reservation(tmp_path):
    store = JobStore(tmp_path)
    store.add({"id": "job", "requires_gurobi": True})
    store.transition("job", "RUNNING", expected={"QUEUED"}, worker_id="remote")
    store.defer_recovery("job", 100)
    restarted = JobStore(tmp_path); restarted.recover()
    assert restarted.get("job")["state"] == "LOST"
    assert not restarted.recovery_due("job", 129)
    assert restarted.recovery_due("job", 130)


def test_T31_failed_stream_copy_never_publishes_artifacts(tmp_path, monkeypatch):
    target = tmp_path / "artifacts"
    def fail(response, manifest, directory, archive_path):
        directory.mkdir(); (directory / "partial.txt").write_text("partial")
        raise OSError("disk full")
    monkeypatch.setattr(module, "_collect_artifacts_uncommitted", fail)
    with pytest.raises(OSError, match="disk full"):
        module.collect_artifacts({}, {}, target, Path("unused.zip"))
    assert not target.exists()
    assert not list(tmp_path.glob("artifacts.partial-*"))


def test_T31_full_disk_during_archive_copy_leaves_no_published_directory(tmp_path, monkeypatch):
    target = tmp_path / "artifacts"
    def unpack(response, manifest, directory, archive_path):
        directory.mkdir()
        (directory / "verified.txt").write_text("verified")
        return {"state": "COMPLETED"}
    def disk_full(*args):
        raise OSError("disk full while copying archive")
    monkeypatch.setattr(module, "_collect_artifacts_uncommitted", unpack)
    monkeypatch.setattr(module.shutil, "copyfile", disk_full)
    with pytest.raises(OSError, match="disk full"):
        module.collect_artifacts({}, {}, target, Path("verified.zip"))
    assert not target.exists()
    assert not (tmp_path / "artifacts.zip").exists()
    assert not list(tmp_path.glob("artifacts.partial-*"))


def test_T23_japanese_space_workspace_survives_native_process_roundtrip(tmp_path):
    from bff.services.cluster.contracts import Worker
    from bff.services.cluster.transport import invoke
    root = tmp_path / "研究 計算の出力"
    worker = Worker(id="local", name="親機", workspace=str(root / "子機の領域"))
    response = invoke(worker, {"operation": "probe"}, root / "通信 ログ", timeout=30)
    assert response["protocol_version"] == 1
    import json
    assert json.loads((root / "通信 ログ" / "transport.stdout").read_text(encoding="utf-8")) == response


def test_T18_cancel_is_bound_to_the_owned_manifest_and_waits_for_exit(tmp_path, monkeypatch):
    launch = tmp_path / ".launch" / "owned"
    launch.mkdir(parents=True)
    manifest = {"id": "owned"}
    runner.write_json(launch / "request.json", {"manifest": manifest})
    runner.write_json(launch / "state.json", {"id": "owned", "state": "RUNNING"})
    with pytest.raises(ValueError, match="owned attempt"):
        runner.handle({"operation": "cancel", "id": "owned", "manifest_sha256": "wrong"}, tmp_path)
    assert not (launch / "cancel.json").exists()
    response = runner.handle({"operation": "cancel", "id": "owned", "manifest_sha256": digest(canonical(manifest))}, tmp_path)
    assert response["state"] == "RUNNING" and response["cancel_requested"]
    assert (launch / "cancel.json").exists()


def test_T18_cancellation_terminates_only_current_model_and_preserves_callbacks():
    from src.execution_control import cancellation_scope, ExecutionCancelled
    from src.solver_policy import optimize_model
    calls = []
    cancelled = [False]
    class Model:
        def optimize(self, callback):
            callback(self, 1)
            cancelled[0] = True
            callback(self, 2)
        def terminate(self): calls.append("owned_terminated")
    with pytest.raises(ExecutionCancelled):
        with cancellation_scope(lambda: cancelled[0]):
            optimize_model(Model(), lambda model, where: calls.append(where))
    assert calls == [1, "owned_terminated"]


@pytest.mark.parametrize("message,code", [
    ("Permission denied (publickey)", "SSH_AUTHENTICATION_FAILED"),
    ("REMOTE HOST IDENTIFICATION HAS CHANGED", "SSH_HOST_KEY_MISMATCH"),
    ("Connection refused", "SSH_PORT_UNREACHABLE"), ("Connection timed out", "SSH_TIMEOUT"),
])
def test_T04_ssh_failures_remain_distinct(message, code):
    from bff.services.cluster.worker_monitor import classify_probe_error
    assert classify_probe_error(RuntimeError(message)) == code
