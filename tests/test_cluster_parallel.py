"""Parallel allocation must preserve per-PC memory and global license limits."""
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from bff.services.cluster import scheduler as module
from bff.services.cluster.contracts import ClusterConfig, Worker
from bff.services.cluster.scheduler import Scheduler
from bff.services.cluster.store import now
from tools.cluster.check_workers import build_report, run_diagnostics


def test_wls_reservation_survives_completion_restart_and_config_change(fleet, monkeypatch):
    from datetime import datetime, timedelta, timezone
    fleet.config.global_gurobi_slots = 1
    fleet.config.workers[0].gurobi_token_cooldown_seconds = 330
    monkeypatch.setattr(fleet, "execute", lambda *args: None)
    first = fleet.enqueue("optimization", {}, "a")
    second = fleet.enqueue("optimization", {}, "b")
    fleet.tick()
    fleet.store.transition(first["id"], "COMPLETED", expected={"STAGING"})
    fleet.licenses.finish(first["id"], cooldown_seconds=330)
    fleet.config.workers[0].gurobi_token_cooldown_seconds = 0
    fleet.store.recover()
    fleet.tick()
    assert fleet.store.get(second["id"])["state"] == "QUEUED"
    rows = fleet.store.rows()
    assert len(fleet.cooling_license_jobs(rows)) == 1
    assert not fleet.cooling_license_jobs(rows, at=datetime.now(timezone.utc)+timedelta(seconds=331))
    with fleet.store.connect() as db:
        db.execute("UPDATE license_reservations SET release_after=0 WHERE id=?", (first["id"],))
        db.execute("UPDATE jobs SET updated_at=? WHERE id=?",
                   ((datetime.now(timezone.utc)-timedelta(seconds=331)).isoformat(), first["id"]))
    fleet.tick()
    assert fleet.store.get(second["id"])["state"] == "STAGING"


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    config = ClusterConfig(global_gurobi_slots=2, workers=[
        Worker(id="a", name="PC A", slots=2, gurobi=True, ram_gb=32),
        Worker(id="b", name="PC B", slots=1, gurobi=True, ram_gb=32),
    ])
    scheduler = Scheduler(tmp_path, config)
    control = {"git": {"sha": "fixed", "dirty": False}, "source_digest": "source", "runtime_versions": {}}
    monkeypatch.setattr(module, "git_state", lambda: control["git"])
    monkeypatch.setattr(module, "source_digest", lambda: "source")
    monkeypatch.setattr(module, "runtime_versions", lambda: {})
    scheduler.monitor.controller = control
    for worker in config.workers:
        scheduler.registry.update(worker.id, {"session_verified": True, "last_probe_at": now(),
            "capability": {**control, "disk_free_gb": 100, "ram_gb": 32, "ram_free_gb": 30, "cpu_count": 8, "gurobi_version": [13]}})
    yield scheduler
    scheduler.stop_event.set()
    scheduler.controller_lock.close()


def test_two_workers_execute_concurrently_and_third_waits_for_license(fleet, monkeypatch):
    fleet.config.global_gurobi_slots = 2
    barrier = threading.Barrier(3)
    release = threading.Event()
    called = []
    def execute(job_id, worker):
        called.append((job_id, worker.id))
        barrier.wait(timeout=5)
        release.wait(timeout=5)
    monkeypatch.setattr(fleet, "execute", execute)
    jobs = [fleet.enqueue("optimization", {}, minimum_ram_gb=18) for _ in range(3)]
    try:
        fleet.tick()
        barrier.wait(timeout=5)  # Both dispatch threads reached this before either completed.
        assert {worker for _, worker in called} == {"a", "b"}
        assert fleet.store.get(jobs[2]["id"])["state"] == "QUEUED"
    finally:
        release.set()


def test_reserved_memory_including_lost_blocks_same_pc_overcommit(fleet, monkeypatch):
    monkeypatch.setattr(fleet, "execute", lambda *args: None)
    first = fleet.enqueue("optimization", {}, "a", minimum_ram_gb=18)
    second = fleet.enqueue("optimization", {}, "a", minimum_ram_gb=18)
    fleet.tick()
    assert fleet.store.get(first["id"])["state"] == "STAGING"
    assert fleet.store.get(second["id"])["state"] == "QUEUED"
    fleet.store.recover()
    fleet.tick()
    assert fleet.store.get(first["id"])["state"] == "LOST"
    assert fleet.store.get(second["id"])["state"] == "QUEUED"
    fleet.store.transition(first["id"], "FAILED", expected={"LOST"})
    fleet.tick()
    assert fleet.store.get(second["id"])["state"] == "STAGING"


def test_confirmed_no_launch_releases_worker_and_license_for_next_job(fleet, monkeypatch):
    from bff.services.cluster.contracts import canonical, digest

    fleet.config.global_gurobi_slots = 1
    monkeypatch.setattr(fleet, "execute", lambda *args: None)
    first = fleet.enqueue("optimization", {}, "a")
    second = fleet.enqueue("optimization", {}, "b")
    fleet.tick()
    assert fleet.store.get(first["id"])["state"] == "STAGING"
    fleet.store.transition(first["id"], "LOST", expected={"STAGING"})
    manifest_hash = digest(canonical(first["manifest"]))
    operations = []

    def invoke_fence(worker, request, *args, **kwargs):
        operations.append(request["operation"])
        return {"id": first["id"], "state": "NOT_STARTED", "manifest_sha256": manifest_hash}

    monkeypatch.setattr(module, "invoke", invoke_fence)
    result = fleet.reconcile(first["id"])
    assert result["state"] == "BLOCKED"
    assert result["result"]["cluster_admission"] == "FENCED_BEFORE_LAUNCH"
    assert operations == ["fence-unstarted"]
    assert fleet.cooling_license_jobs(fleet.store.rows()) == []
    fleet.tick()
    assert fleet.store.get(second["id"])["state"] == "STAGING"


def test_external_license_reservation_does_not_block_solver_free_work(fleet, monkeypatch):
    fleet.config.external_gurobi_slots = fleet.config.global_gurobi_slots
    monkeypatch.setattr(fleet, "execute", lambda *args: None)
    optimization = fleet.enqueue("optimization", {})
    diagnostic = fleet.enqueue("diagnostic", {})
    fleet.tick()
    assert fleet.store.get(optimization["id"])["state"] == "QUEUED"
    assert fleet.store.get(diagnostic["id"])["state"] == "STAGING"


def test_concurrent_ticks_cannot_double_assign(fleet, monkeypatch):
    monkeypatch.setattr(fleet, "execute", lambda *args: None)
    jobs = [fleet.enqueue("optimization", {}, "a", minimum_ram_gb=18) for _ in range(5)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: fleet.tick(), range(4)))
    assert sum(fleet.store.get(job["id"])["state"] == "STAGING" for job in jobs) == 1


@pytest.mark.parametrize("changed", [{"ram_free_gb": 3}, {"runtime_versions": {"python": "different"}}])
def test_fresh_preflight_blocks_memory_or_runtime_drift_before_submit(fleet, monkeypatch, changed):
    row = fleet.enqueue("optimization", {}, "a", minimum_ram_gb=18)
    fleet.store.transition(row["id"], "STAGING", expected={"QUEUED"}, worker_id="a")
    capability = {**fleet.monitor.controller, "ram_gb": 32, "ram_free_gb": 30, **changed}
    operations = []
    def invoke(worker, request, directory, **kwargs):
        operations.append(request["operation"])
        return capability
    monkeypatch.setattr(module, "invoke", invoke)
    fleet.execute(row["id"], fleet.worker("a"))
    assert fleet.store.get(row["id"])["state"] == "BLOCKED"
    assert operations == ["probe"]


def test_one_shot_diagnostics_never_start_unrelated_queue(fleet, monkeypatch):
    unrelated = fleet.enqueue("optimization", {})
    def finish(job_id, worker):
        fleet.store.transition(job_id, "COMPLETED", expected={"STAGING"}, result={})
    monkeypatch.setattr(fleet, "execute", finish)
    views = [{"id": "a", "can_run_diagnostic": True}, {"id": "b", "can_run_diagnostic": False}]
    jobs = run_diagnostics(fleet, views, 5)
    assert len(jobs) == 1 and jobs[0]["state"] == "COMPLETED"
    assert fleet.store.get(unrelated["id"])["state"] == "QUEUED"


def test_report_does_not_call_local_success_remote_success():
    views = [{"id": "local", "transport": "local", "can_run_diagnostic": True},
             {"id": "remote", "transport": "ssh", "can_run_diagnostic": False}]
    report = build_report(views, [{"worker_id": "local", "state": "COMPLETED"}], diagnostics=True)
    assert report["status"] == "BLOCKED"
    assert report["ssh_diagnostics_completed"] == []
    assert report["research_approval"] == "NOT_GRANTED_BY_CLUSTER"


def test_external_reservations_must_fit_total_capacity():
    with pytest.raises(ValueError, match="External Gurobi"):
        ClusterConfig(global_gurobi_slots=1, external_gurobi_slots=2)
