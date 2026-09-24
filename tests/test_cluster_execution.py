"""Distributed execution contracts without paid solver sessions or remote hosts."""
import base64
import io
import json
import time
import zipfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from bff.services.cluster import scheduler as module
from bff.services.cluster.contracts import ClusterConfig, Worker, canonical, digest, git_state, runtime_versions, source_digest
from bff.services.cluster.runner import archive_result, execute_optimization, verify_bundle
from bff.services.cluster.scheduler import Scheduler, collect_artifacts
from bff.services.cluster.scheduler import validate_portable_paths
from bff.services.cluster.store import ControllerLock, JobStore
from bff.services.cluster import transport as transport_module
from bff.services.cluster.transport import SSHTransportError, command, invoke


@pytest.fixture
def scheduler(tmp_path):
    instance = Scheduler(tmp_path / "controller", ClusterConfig(workers=[
        Worker(id="local", name="Local", workspace=str(tmp_path / "worker")),
    ]))
    yield instance
    instance.stop_event.set()
    instance.monitor.stop()
    if instance.thread:
        instance.thread.join(timeout=4)
    instance.controller_lock.close()


def test_real_subprocess_roundtrip_and_restart_history(scheduler):
    row = scheduler.enqueue("diagnostic", {}, "local")
    scheduler.start()
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        result = scheduler.store.get(row["id"])
        if result["state"] in {"COMPLETED", "FAILED", "BLOCKED", "LOST"}:
            break
        time.sleep(0.1)
    assert result["state"] == "COMPLETED", result
    assert result["result"]["provenance"]["hostname"]
    assert result["result"]["research_approval"] == "NOT_GRANTED_BY_CLUSTER"
    assert (scheduler.store.root / "jobs" / row["id"] / "artifacts.zip").is_file()
    recovered = JobStore(scheduler.store.root)
    recovered.recover()
    assert recovered.get(row["id"])["state"] == "COMPLETED"


def test_batch_membership_is_frozen_and_retry_keeps_the_declared_denominator(scheduler):
    first = scheduler.enqueue("diagnostic", {}, batch_id="research-run", task_id="case-a", batch_task_count=2)
    second = scheduler.enqueue("diagnostic", {}, batch_id="research-run", task_id="case-b", batch_task_count=2)
    assert first["manifest"]["batch_task_count"] == second["manifest"]["batch_task_count"] == 2
    with pytest.raises(ValueError, match="different attempt"):
        scheduler.enqueue("diagnostic", {}, batch_id="research-run", task_id="case-a", batch_task_count=2)
    with pytest.raises(ValueError, match="task count changed"):
        scheduler.enqueue("diagnostic", {}, batch_id="research-run", task_id="case-c", batch_task_count=3)
    with pytest.raises(ValueError, match="reached its declared"):
        scheduler.enqueue("diagnostic", {}, batch_id="research-run", task_id="case-c", batch_task_count=2)
    scheduler.store.transition(first["id"], "FAILED", expected={"QUEUED"})
    with pytest.raises(ValueError, match="cannot change"):
        scheduler.enqueue("diagnostic", {}, retry_of=first["id"],
                          batch_id="research-run", task_id="case-b", batch_task_count=2)
    retry = scheduler.retry(first["id"])
    assert retry["manifest"]["task_id"] == "case-a"
    assert retry["manifest"]["batch_id"] == "research-run"
    assert retry["manifest"]["attempt_number"] == 2


def test_controller_persists_final_worker_checkpoint_before_terminal_transition(scheduler, monkeypatch):
    row = scheduler.enqueue("diagnostic", {})
    scheduler.store.transition(row["id"], "RUNNING", expected={"QUEUED"}, worker_id="local")
    monkeypatch.setattr(module, "collect_artifacts", lambda *args: {"state": "COMPLETED"})
    monkeypatch.setattr(scheduler, "mirror", lambda *args: None)
    response = {"id": row["id"], "state": "COMPLETED",
                "manifest_sha256": digest(canonical(row["manifest"])),
                "execution_progress": {"percent": 100, "stage": "finalize", "message": "Done"}}
    scheduler.finish(row, response)
    saved = JobStore(scheduler.store.root).get(row["id"])
    assert saved["state"] == "COMPLETED"
    assert saved["execution_progress"]["percent"] == 100


def test_scheduler_allocates_distinct_workers_and_retains_lost_slots(scheduler, monkeypatch):
    scheduler.config = ClusterConfig(global_gurobi_slots=1, workers=[
        Worker(id="a", name="A", gurobi=True, ram_gb=16),
        Worker(id="b", name="B", gurobi=True, ram_gb=16),
    ])
    monkeypatch.setattr(module, "git_state", lambda: {"sha": "abc", "dirty": False})
    dispatched = []
    from bff.services.cluster.worker_registry import WorkerRegistry
    from bff.services.cluster.store import now
    scheduler.registry = WorkerRegistry(scheduler.store, scheduler.config.workers)
    scheduler.monitor.controller = {"git": {"sha": "abc", "dirty": False}, "source_digest": "same", "runtime_versions": {}}
    for worker in scheduler.config.workers:
        scheduler.registry.update(worker.id, {"session_verified": True, "last_probe_at": now(), "capability": {
            **scheduler.monitor.controller, "disk_free_gb": 100, "ram_gb": 16, "ram_free_gb": 16, "cpu_count": 8, "gurobi_version": [13]}})
    monkeypatch.setattr(scheduler, "execute", lambda job_id, worker: dispatched.append((job_id, worker.id)))
    first = scheduler.enqueue("optimization", {}, minimum_ram_gb=16)
    second = scheduler.enqueue("optimization", {}, minimum_ram_gb=16)
    diagnostic = scheduler.enqueue("diagnostic", {})
    scheduler.tick()
    assert scheduler.store.get(first["id"])["state"] == "STAGING"
    assert scheduler.store.get(second["id"])["state"] == "QUEUED"
    assert scheduler.store.get(diagnostic["id"])["worker_id"] == "b"
    scheduler.store.recover()
    assert scheduler.store.get(first["id"])["state"] == "LOST"
    scheduler.tick()
    assert scheduler.store.get(second["id"])["state"] == "QUEUED"
    with pytest.raises(ValueError, match="confirmed terminal"):
        scheduler.retry(first["id"])


def test_worker_ram_and_solver_matching(scheduler, monkeypatch):
    monkeypatch.setattr(module, "git_state", lambda: {"sha": "abc", "dirty": False})
    row = scheduler.enqueue("optimization", {}, minimum_ram_gb=32)
    scheduler.tick()
    assert scheduler.store.get(row["id"])["state"] == "QUEUED"


def test_worker_job_role_rejects_incompatible_pinned_jobs(scheduler, monkeypatch):
    worker = scheduler.config.workers[0]
    monkeypatch.setattr(module, "git_state", lambda: {"sha": "abc", "dirty": False})
    assert scheduler.registry.job_role(worker) == "alns_only"
    row = scheduler.enqueue("optimization", {"kwargs": {"execution_profile": "alns_no_gurobi_v1"}}, worker.id)
    with pytest.raises(ValueError, match="Pinned queued jobs"):
        scheduler.set_worker_job_role(worker.id, "diagnostic_only")
    assert scheduler.registry.job_role(worker) == "alns_only"
    with pytest.raises(ValueError, match="Gurobi jobs require"):
        scheduler.set_worker_job_role(worker.id, "gurobi_only")
    with pytest.raises(ValueError, match="job role"):
        scheduler.enqueue("optimization", {}, worker.id)
    assert scheduler.store.get(row["id"])["state"] == "QUEUED"


def test_license_test_rejects_worker_without_verified_solver(scheduler):
    with pytest.raises(ValueError, match="License test requires"):
        scheduler.enqueue("license_test", {}, "local")
    assert scheduler.store.rows() == []


def test_worker_fences_unstarted_attempt_and_rejects_delayed_submit(tmp_path):
    from bff.services.cluster.runner import handle

    manifest = {"id": "attempt"}
    manifest_hash = digest(canonical(manifest))
    fence = {"operation": "fence-unstarted", "id": "attempt", "manifest_sha256": manifest_hash}
    receipt = handle(fence, tmp_path)
    assert receipt == {"id": "attempt", "state": "NOT_STARTED", "manifest_sha256": manifest_hash}
    assert handle(fence, tmp_path) == receipt
    with pytest.raises(ValueError, match="ATTEMPT_NOT_STARTED"):
        handle({"operation": "submit", "id": "attempt", "manifest": manifest, "bundle": {}}, tmp_path)
    assert not (tmp_path / "attempt").exists()


def test_worker_fence_preserves_uncertain_and_existing_launches(tmp_path):
    from bff.services.cluster.runner import handle, write_json

    manifest = {"id": "attempt"}
    manifest_hash = digest(canonical(manifest))
    request = {"operation": "fence-unstarted", "id": "attempt", "manifest_sha256": manifest_hash}
    launch = tmp_path / ".launch" / "attempt"
    launch.mkdir(parents=True)
    assert handle(request, tmp_path)["state"] == "UNCERTAIN"
    assert not (launch / "abandoned.json").exists()
    write_json(launch / "request.json", {"manifest": manifest, "bundle": {}})
    assert handle(request, tmp_path)["state"] == "EXISTS"


def test_delayed_submit_error_cannot_overwrite_confirmed_terminal_display(scheduler, monkeypatch):
    row = scheduler.enqueue("diagnostic", {}, "local")
    scheduler.store.transition(row["id"], "STAGING", expected={"QUEUED"}, worker_id="local")
    mirrored = []
    monkeypatch.setattr(scheduler, "mirror", lambda job_id, status, message: mirrored.append(status))

    def invoke_with_late_error(worker, request, directory, **kwargs):
        if request["operation"] == "probe":
            return {"git": row["manifest"]["git"], "source_digest": row["manifest"]["source_digest"],
                    "ram_gb": 16, "ram_free_gb": 16}
        scheduler.store.transition(row["id"], "BLOCKED", expected={"RUNNING"})
        raise RuntimeError("Late submit was rejected after reconciliation")

    monkeypatch.setattr(module, "invoke", invoke_with_late_error)
    scheduler.execute(row["id"], scheduler.config.workers[0])
    assert scheduler.store.get(row["id"])["state"] == "BLOCKED"
    assert mirrored == ["running"]


@pytest.mark.parametrize("gurobi,role,profile", [
    (False, "alns_only", "existing_solver_v1"),
    (True, "gurobi_only", "alns_no_gurobi_v1"),
])
def test_pinned_role_rejected_before_parent_job_creation(scheduler, monkeypatch, gurobi, role, profile):
    from bff.routers import cluster
    from bff.services.cluster.worker_registry import WorkerRegistry

    worker = Worker(id="local", name="Local", gurobi=gurobi)
    scheduler.config = ClusterConfig(workers=[worker])
    scheduler.registry = WorkerRegistry(scheduler.store, [worker])
    scheduler.registry.set_job_role(worker.id, role)
    monkeypatch.setattr(cluster, "enqueue_optimization", lambda *args, **kwargs: pytest.fail("parent job created"))

    body = cluster.SubmitBody(scenario_id="scenario", worker_id=worker.id,
                              request=cluster.RunOptimizationBody(execution_profile=profile))
    with pytest.raises(HTTPException, match="job role") as error:
        cluster._submit_once(scheduler, body, {})
    assert error.value.status_code == 409
    assert scheduler.store.rows() == []


def test_automatic_placement_obeys_parent_job_role(scheduler, monkeypatch):
    from bff.services.cluster.worker_registry import WorkerRegistry
    from bff.services.cluster.store import now

    workers = [Worker(id="solver", name="Solver", gurobi=True), Worker(id="alns", name="ALNS")]
    scheduler.config = ClusterConfig(workers=workers)
    scheduler.registry = WorkerRegistry(scheduler.store, workers)
    scheduler.monitor.controller = {"git": {"sha": "abc", "dirty": False},
                                    "source_digest": "same", "runtime_versions": {}}
    for worker in workers:
        scheduler.registry.update(worker.id, {"session_verified": True, "last_probe_at": now(),
            "capability": {**scheduler.monitor.controller, "disk_free_gb": 100,
                           "ram_gb": 16, "ram_free_gb": 16, "cpu_count": 8,
                           "cpu_percent": 10, "gurobi_version": [13]}})
    scheduler.set_worker_job_role("solver", "gurobi_only")
    monkeypatch.setattr(module, "git_state", lambda: {"sha": "abc", "dirty": False})
    launched = []
    monkeypatch.setattr(scheduler, "execute", lambda job_id, worker: launched.append((job_id, worker.id)))
    alns = scheduler.enqueue("optimization", {"kwargs": {"execution_profile": "alns_no_gurobi_v1"}})
    solver = scheduler.enqueue("optimization", {})
    scheduler.tick()
    assert scheduler.store.get(alns["id"])["worker_id"] == "alns"
    assert scheduler.store.get(solver["id"])["worker_id"] == "solver"


def test_only_one_controller_can_own_a_queue(scheduler):
    with pytest.raises(RuntimeError, match="Another cluster controller"):
        ControllerLock(scheduler.store.root)


def test_bundle_and_code_tampering_are_rejected(scheduler):
    manifest = scheduler.enqueue("diagnostic", {})["manifest"]
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_bundle(manifest, {"changed": True})
    with pytest.raises(ValueError, match="code does not match"):
        verify_bundle({**manifest, "source_digest": "bad"}, {})


def test_portable_input_check_accepts_profiles_but_rejects_unstaged_files():
    validate_portable_paths({"run_profile": "research", "stage1_gurobi_search_profile": "default", "nested": [{"pv_profile": "summer"}]})
    with pytest.raises(ValueError, match="unstaged file"):
        validate_portable_paths({"weatherProxyForecastPath": "C:/weather.json"})


def test_next_morning_timetable_source_path_is_provenance_only():
    row = {"source_provenance": {"path": "C:/capture/original.json", "sha256": "a" * 64},
           "source_departure": "06:00"}
    contract = {"terminal_overnight_contract": {"next_day_timetable_rows": [row]}}
    validate_portable_paths(contract)
    with pytest.raises(ValueError, match="unstaged file"):
        validate_portable_paths({"next_day_timetable_rows": [row]})
    with pytest.raises(ValueError, match="unstaged file"):
        validate_portable_paths({"terminal_overnight_contract": {"next_day_timetable_rows": [
            {"source_provenance": {"path": "C:/capture/original.json", "sha256": "invalid"}}]}})
    with pytest.raises(ValueError, match="unstaged file"):
        validate_portable_paths({"terminal_overnight_contract": {"next_day_timetable_rows": [
            {**row, "weather_path": "C:/unstaged/weather.json"}]}})


def test_freezer_binds_snapshot_to_prepared_identity(scheduler, tmp_path, monkeypatch):
    from bff.store import output_paths, scenario_store
    from bff.services.run_preparation import _scenario_hash
    root = tmp_path / "repo"
    dataset = root / "data/built/test"
    dataset.mkdir(parents=True)
    (dataset / "data.json").write_text("{}")
    output = tmp_path / "prepared-output"
    directory = output / "prepared_inputs/scenario"
    directory.mkdir(parents=True)
    scenario = {"meta": {"id": "scenario"}, "simulation_config": {"initial_soc_percent": 80}, "refs": {}}
    payload = {"scenario_id": "scenario", "prepared_input_id": "prepared", "scenario_hash": _scenario_hash(scenario),
               "trips": [{"operator_id": "tokyu", "distance_km": 7.25}]}
    prepared = canonical(payload)
    (directory / "prepared.json").write_bytes(prepared)
    monkeypatch.setattr(module, "ROOT", root)
    monkeypatch.setattr(module, "git_state", lambda: {"sha": "abc", "dirty": False})
    monkeypatch.setattr(output_paths, "outputs_root", lambda: output)
    monkeypatch.setattr(scenario_store, "get_scenario_document",
                        lambda _scenario_id, **_kwargs: dict(scenario))
    monkeypatch.setattr(scenario_store, "get_scenario_document_shallow",
                        lambda _scenario_id: pytest.fail("Snapshot checks must load the complete scenario"))
    def executor(scenario_id, job_id, prepared_input_id, rebuild_dispatch, use_existing_duties):
        raise AssertionError("Freezing must not execute a solver")
    submission = {"fn": executor, "args": ("scenario", "frozen-job", "prepared", False, False), "job_id": "frozen-job"}
    assert scheduler.freeze_optimization(None, {"built_dir": str(dataset)}, 0, **submission)
    saved = json.loads((scheduler.store.root / "jobs/frozen-job/bundle.json").read_text(encoding="utf-8"))
    assert base64.b64decode(saved["prepared_base64"]) == prepared
    scenario["simulation_config"]["initial_soc_percent"] = 90
    with pytest.raises(ValueError, match="changed after Prepare"):
        scheduler.freeze_optimization(None, {"built_dir": str(dataset)}, 0, **submission)


def _stub_pinned_optimization_enqueue(monkeypatch, *, actual_prepared_id="prepared", resolved_service_id=None):
    from types import SimpleNamespace
    from bff.routers import optimization
    from bff.services.optimization_run import solver_policy

    class JobCreationReached(Exception):
        pass

    calls = {"full_load": [], "prepare_ids": [], "scope_persist": [], "job_create": 0}
    monkeypatch.setattr(optimization, "_require_scenario", lambda _scenario_id: None)
    monkeypatch.setattr(optimization, "_require_research_git_preflight_before_job_creation",
                        lambda **_kwargs: None)
    monkeypatch.setattr(solver_policy, "validate_execution_request", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(optimization, "_normalize_solver_mode", lambda _mode: "phase3_two_stage")
    monkeypatch.setattr(optimization, "normalize_frontend_run_profile", lambda _profile: "test-profile")
    monkeypatch.setattr(optimization, "frontend_rolling_is_required", lambda _profile: False)
    monkeypatch.setattr(optimization, "_validate_formal_runtime_controls_or_http_error", lambda _request: None)
    monkeypatch.setattr(optimization, "_request_timestep_min", lambda *_args: None)
    monkeypatch.setattr(optimization, "_preflight_weather_proxy_request", lambda **_kwargs: None)
    monkeypatch.setattr(optimization, "_executor_mode", lambda: "cluster")
    monkeypatch.setattr(optimization, "_apply_research_phase3_candidate_coverage_policy_or_http_error",
                        lambda request, **_kwargs: request)
    monkeypatch.setattr(optimization.store, "get_scenario_document_shallow",
                        lambda _scenario_id: {"simulation_config": {}})

    def load_full(scenario_id, **kwargs):
        calls["full_load"].append((scenario_id, kwargs))
        return {"meta": {"id": scenario_id}, "simulation_config": {}}

    monkeypatch.setattr(optimization.store, "get_scenario_document", load_full)
    prep = SimpleNamespace(
        is_valid=True,
        prepared_input_id=actual_prepared_id,
        solver_input_path=Path("prepared.json"),
        error=None,
        error_code=None,
        scope_summary={
            "trip_count": 1,
            "service_ids": ["WEEKDAY"],
            "depot_ids": ["depot-1"],
        },
    )

    def get_preparation(**kwargs):
        calls["prepare_ids"].append(kwargs.get("expected_prepared_input_id"))
        return prep

    monkeypatch.setattr(optimization, "get_or_build_run_preparation", get_preparation)

    def resolve_scope(_scenario_id, *, service_id=None, depot_id=None, persist=False):
        calls["scope_persist"].append(persist)
        return {
            "serviceId": resolved_service_id or service_id or "WEEKDAY",
            "depotId": depot_id or "depot-1",
        }

    monkeypatch.setattr(optimization, "_resolve_dispatch_scope", resolve_scope)

    def stop_before_job(*_args, **_kwargs):
        calls["job_create"] += 1
        raise JobCreationReached()

    monkeypatch.setattr(optimization.job_store, "create_job", stop_before_job)
    request = optimization.RunOptimizationBody(
        mode="phase3_two_stage",
        prepared_input_id="prepared",
        service_id="WEEKDAY",
        depot_id="depot-1",
    )
    return optimization, request, calls, JobCreationReached


def test_pinned_optimization_uses_full_scenario_and_never_persists_scope(monkeypatch):
    optimization, request, calls, JobCreationReached = _stub_pinned_optimization_enqueue(monkeypatch)

    with pytest.raises(JobCreationReached):
        optimization.enqueue_optimization("scenario", request, {"built_dir": "built"})

    assert calls["full_load"] == [("scenario", {"repair_missing_master": False})]
    assert calls["prepare_ids"] == ["prepared"]
    assert calls["scope_persist"] == [False, False]
    assert calls["job_create"] == 1


def test_pinned_optimization_rejects_scope_mismatch_before_job_creation(monkeypatch):
    optimization, request, calls, _ = _stub_pinned_optimization_enqueue(
        monkeypatch, resolved_service_id="SATURDAY"
    )

    with pytest.raises(HTTPException) as error:
        optimization.enqueue_optimization("scenario", request, {"built_dir": "built"})

    assert error.value.status_code == 409
    assert calls["scope_persist"] == [False]
    assert calls["job_create"] == 0


def test_pinned_optimization_rejects_stale_id_before_job_creation(monkeypatch):
    optimization, request, calls, _ = _stub_pinned_optimization_enqueue(
        monkeypatch, actual_prepared_id="current-prepared"
    )

    with pytest.raises(HTTPException) as error:
        optimization.enqueue_optimization("scenario", request, {"built_dir": "built"})

    assert error.value.status_code == 409
    assert calls["prepare_ids"] == ["prepared"]
    assert calls["job_create"] == 0


def test_dataset_mismatch_is_blocked_before_solver(tmp_path, monkeypatch):
    from bff.services.cluster import runner
    (tmp_path / "dataset").mkdir()
    (tmp_path / "dataset" / "trips.json").write_text("changed")
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "git_state", lambda: {"sha": "abc", "dirty": False})
    monkeypatch.setattr(runner, "source_digest", lambda: "source")
    bundle = {"dataset_path": "dataset", "dataset_hashes": {"trips.json": "wrong"}}
    manifest = {"schema_version": 1, "id": "test", "kind": "optimization", "requires_gurobi": True, "bundle_sha256": digest(canonical(bundle)),
                "runtime_versions": runtime_versions(),
                "git": {"sha": "abc", "dirty": False}, "source_digest": "source"}
    with pytest.raises(ValueError, match="DATASET_MISMATCH"):
        verify_bundle(manifest, bundle)


def test_crashed_worker_is_reconciled_without_rerunning(tmp_path, monkeypatch):
    from bff.services.cluster import runner
    directory = tmp_path / "job"
    directory.mkdir()
    state = {"id": "job", "state": "RUNNING", "pid": 12345, "process_identity": "previous"}
    (directory / "manifest.json").write_bytes(canonical({"id": "job"}))
    (directory / "state.json").write_bytes(canonical(state))
    monkeypatch.setattr(runner, "process_identity", lambda pid: "different-birth-token")
    result = runner.handle({"operation": "collect", "id": "job"}, tmp_path)
    assert result["state"] == "FAILED"
    assert "exited" in result["error"]


def test_missing_worker_receipts_do_not_release_the_reservation(tmp_path):
    from bff.services.cluster import runner
    directory = tmp_path / "job"
    directory.mkdir()
    (directory / "state.json").write_bytes(canonical({"id": "job", "state": "FAILED"}))
    with pytest.raises(ValueError, match="retain the reservation"):
        runner.handle({"operation": "collect", "id": "job"}, tmp_path)


def test_transport_failure_before_dispatch_is_blocked_not_lost(scheduler, monkeypatch):
    row = scheduler.enqueue("diagnostic", {}, "local")
    scheduler.store.transition(row["id"], "STAGING", expected={"QUEUED"}, worker_id="local")
    def disconnected(*args, **kwargs):
        raise OSError("SSH is unavailable")
    monkeypatch.setattr(module, "invoke", disconnected)
    scheduler.execute(row["id"], scheduler.worker("local"))
    assert scheduler.store.get(row["id"])["state"] == "BLOCKED"


def test_ssh_operation_retries_same_attempt_and_identical_request_bytes(tmp_path, monkeypatch):
    calls = []
    worker = Worker(id="remote", name="Remote", transport="ssh", host="worker.example",
                    ssh_user="runner", repo="C:/worker/repo")

    class FakeProcess:
        def __init__(self, attempt, stdout, stderr):
            self.attempt = attempt
            self.stdout = stdout
            self.stderr = stderr
            self.returncode = 255 if attempt == 1 else 0

        def communicate(self, payload, timeout=None):
            calls.append((self.attempt, payload))
            if self.attempt == 1:
                self.stderr.write(b"Connection timed out\n")
            else:
                self.stdout.write(b'{"state":"COMPLETED"}')

    def fake_popen(_command, **kwargs):
        return FakeProcess(len(calls) + 1, kwargs["stdout"], kwargs["stderr"])

    monkeypatch.setattr(transport_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(transport_module.time, "sleep", lambda _seconds: None)

    request = {"operation": "submit", "id": "same-attempt"}
    result = transport_module.invoke(worker, request, tmp_path, timeout=5)

    assert result == {"state": "COMPLETED"}
    assert len(calls) == 2
    assert [attempt for attempt, _payload in calls] == [1, 2]
    assert calls[0][1] == calls[1][1] == canonical(request)


def test_ssh_authentication_failure_is_not_retried(tmp_path, monkeypatch):
    calls = []
    worker = Worker(id="remote", name="Remote", transport="ssh", host="worker.example",
                    ssh_user="runner", repo="C:/worker/repo")

    class FakeProcess:
        returncode = 255

        def __init__(self, stderr):
            self.stderr = stderr

        def communicate(self, _payload, timeout=None):
            calls.append(True)
            self.stderr.write(b"Permission denied (publickey)\n")

    def fake_popen(_command, **kwargs):
        return FakeProcess(kwargs["stderr"])

    monkeypatch.setattr(transport_module.subprocess, "Popen", fake_popen)

    with pytest.raises(SSHTransportError) as error:
        transport_module.invoke(worker, {"operation": "probe"}, tmp_path, timeout=5)

    assert len(calls) == 1
    assert error.value.error_code == "SSH_AUTHENTICATION_FAILED"
    assert error.value.attempts == 1


def test_runtime_ssh_failure_quarantines_worker_until_a_new_probe(scheduler, monkeypatch):
    worker = scheduler.worker("local")
    scheduler.registry.update(worker.id, {"session_verified": True, "ssh_ready": True})

    def disconnected(*_args, **_kwargs):
        raise SSHTransportError("status", "SSH_TIMEOUT", 2)

    monkeypatch.setattr(module, "invoke", disconnected)
    with pytest.raises(SSHTransportError):
        scheduler.invoke_worker(worker, {"operation": "status", "id": "attempt"}, scheduler.store.root)

    observation = scheduler.registry.get(worker.id)["observation"]
    assert observation["session_verified"] is False
    assert observation["ssh_ready"] is False
    assert observation["probe_error_code"] == "SSH_TIMEOUT"
    assert observation["next_probe_at"] > time.time()


def test_ssh_commands_reject_host_options_and_quote_paths():
    with pytest.raises(ValueError):
        Worker(id="x", name="X", transport="ssh", host="-oProxyCommand=bad")
    worker = Worker(id="x", name="X", transport="ssh", host="lab-pc", repo="C:/User's Lab/repo")
    cmd = command(worker)
    assert "StrictHostKeyChecking=yes" in cmd
    script = base64.b64decode(cmd[-1].split()[-1]).decode("utf-16le")
    assert "C:/User''s Lab/repo" in script
    assert "bff.services.cluster.runner" in script
    posix = command(worker.model_copy(update={"shell": "posix", "repo": "/tmp/lab folder"}))
    assert "cd '/tmp/lab folder'" in posix[-1]


@pytest.mark.parametrize("name", ["../escape.txt", "/absolute.txt", "C:/escape.txt", "folder\\escape.txt"])
def test_collector_rejects_unsafe_archives(tmp_path, name):
    manifest = {"id": "job"}
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr(name, b"test")
    response = {"id": "job", "manifest_sha256": digest(canonical(manifest)), "archive_base64": base64.b64encode(data.getvalue()).decode(),
                "artifact_hashes": {name: digest(b"test")}}
    with pytest.raises(ValueError, match="Unsafe artifact|inventory mismatch"):
        collect_artifacts(response, manifest, tmp_path / "artifacts")


def test_recollecting_same_attempt_does_not_leave_large_partial_copies(tmp_path):
    manifest = {"id": "job"}
    state = {"id": "job", "state": "COMPLETED", "manifest_sha256": digest(canonical(manifest)),
             "result": {}, "error": None}
    files = {"manifest.json": canonical(manifest), "state.json": canonical(state), "result.txt": b"done"}
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    response = {**state, "archive_base64": base64.b64encode(data.getvalue()).decode(),
                "artifact_hashes": {name: digest(content) for name, content in files.items()}}
    target = tmp_path / "artifacts"
    collect_artifacts(response, manifest, target)
    collect_artifacts(response, manifest, target)
    assert (target / "result.txt").read_bytes() == b"done"
    assert not list(tmp_path.glob("artifacts.partial-*"))


def test_retry_preserves_inputs_and_has_a_new_id(scheduler):
    row = scheduler.enqueue("diagnostic", {"input": "unchanged"})
    scheduler.store.transition(row["id"], "CANCELLED", expected={"QUEUED"})
    retry = scheduler.retry(row["id"])
    assert retry["id"] != row["id"]
    assert retry["manifest"]["retry_of"] == row["id"]
    assert retry["manifest"]["bundle_sha256"] == row["manifest"]["bundle_sha256"]


def test_result_hash_mismatch_never_writes_artifacts(tmp_path):
    original = tmp_path / "worker"
    original.mkdir()
    manifest = {"id": "job"}
    (original / "manifest.json").write_bytes(canonical(manifest))
    response = archive_result(original, {"id": "job", "manifest_sha256": digest(canonical(manifest))})
    response["artifact_hashes"]["manifest.json"] = "tampered"
    target = tmp_path / "artifacts"
    with pytest.raises(ValueError, match="hash mismatch"):
        collect_artifacts(response, manifest, target)
    assert not target.exists()


def test_worker_adapter_preserves_prepared_bytes_and_solver_controls(tmp_path, monkeypatch):
    from bff.routers import optimization
    from bff.store import job_store, scenario_store
    output = tmp_path / "output"
    monkeypatch.setattr(scenario_store, "_STORE_DIR", output / "scenarios")
    monkeypatch.setattr(job_store, "_JOB_DIR", output / "jobs")
    monkeypatch.setattr(job_store, "_jobs", {})
    monkeypatch.setenv("MC_OUTPUTS_DIR", str(output))
    monkeypatch.setenv("SCENARIO_STORE_PATH", str(output / "scenarios"))
    monkeypatch.setenv("BUILT_ROOT", str(tmp_path))
    monkeypatch.setenv("DEFAULT_DATASET_ID", "dataset")
    monkeypatch.setenv("MC_EXECUTION_INPUTS_ROOT", str(tmp_path / "execution_inputs"))
    # No solver runs: verify the adapter calls the existing entrypoint verbatim.
    raw_prepared = b'{ "trips": [{"operator_id": "tokyu", "distance_km": 7.25}] }\n'
    captured = []
    def fake_run(**kwargs):
        captured.append(kwargs)
        assert (output / "prepared_inputs" / "scenario" / "prepared.json").read_bytes() == raw_prepared
        assert scenario_store.get_field("scenario", "timetable_rows")[0]["distance_km"] == 7.25
        job_store.update_job(kwargs["job_id"], status="completed", metadata={"teacher_release_status": "BLOCKED"})
    monkeypatch.setattr(optimization, "_run_optimization", fake_run)
    bundle = {"kwargs": {"scenario_id": "scenario", "prepared_input_id": "prepared", "job_id": "controller-job",
                         "random_seed": 1001, "research_run": False, "gurobi_threads": 2},
              "scenario": {"meta": {"id": "scenario"}, "depots": [], "routes": [], "vehicles": [],
                           "timetable_rows": [{"trip_id": "trip", "operator_id": "tokyu", "distance_km": 7.25}]},
              "dataset_path": "data/built/test", "prepared_base64": base64.b64encode(raw_prepared).decode()}
    before = canonical(bundle)
    result = execute_optimization({"id": "cluster-job"}, bundle, tmp_path)
    assert canonical(bundle) == before
    assert len(captured) == 1
    assert captured[0]["random_seed"] == 1001
    assert captured[0]["gurobi_threads"] == 2
    assert result["metadata"]["teacher_release_status"] == "BLOCKED"


def test_reconciliation_retrieves_terminal_result_without_resubmitting(scheduler, monkeypatch, tmp_path):
    row = scheduler.enqueue("diagnostic", {}, "local")
    scheduler.store.transition(row["id"], "RUNNING", expected={"QUEUED"}, worker_id="local")
    scheduler.store.recover()
    directory = tmp_path / "completed-worker"
    directory.mkdir()
    manifest = row["manifest"]
    state = {"id": row["id"], "state": "COMPLETED", "manifest_sha256": digest(canonical(manifest)), "result": {}}
    (directory / "manifest.json").write_bytes(canonical(manifest))
    (directory / "state.json").write_bytes(canonical(state))
    called = []
    def fake_invoke(worker, request, directory, **kwargs):
        called.append(request["operation"])
        if request["operation"] == "fence-unstarted":
            return {"id": row["id"], "state": "EXISTS", "manifest_sha256": digest(canonical(manifest))}
        return archive_result(tmp_path / "completed-worker", state)
    monkeypatch.setattr(module, "invoke", fake_invoke)
    result = scheduler.reconcile(row["id"])
    assert result["state"] == "COMPLETED"
    assert called == ["fence-unstarted", "collect"]


def test_api_is_loopback_only_and_queue_cancel_is_atomic(scheduler, monkeypatch):
    from bff.routers import cluster
    monkeypatch.setattr(cluster, "get_scheduler", lambda: scheduler)
    app = FastAPI()
    app.include_router(cluster.router)
    with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 50000)) as client:
        assert client.get("/cluster/workers").status_code == 200
        assert client.post("/cluster/workers/local/diagnostic", headers={"Origin": "https://evil.example"}).status_code == 403
        created = client.post("/cluster/workers/local/diagnostic").json()
        assert client.post(f"/cluster/jobs/{created['id']}/cancel").status_code == 200
        assert client.post(f"/cluster/jobs/{created['id']}/cancel").status_code == 409
    with TestClient(app, base_url="http://localhost", client=("192.168.1.5", 50000)) as remote:
        assert remote.get("/cluster/workers").status_code == 403
