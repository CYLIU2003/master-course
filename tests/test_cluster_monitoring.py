"""Network, readiness and operator controls must not weaken job ownership."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bff.services.cluster.contracts import Worker, ClusterConfig
from bff.services.cluster.store import JobStore, now
from bff.services.cluster.worker_registry import WorkerRegistry
from bff.services.cluster.worker_monitor import WorkerMonitor
from bff.services.cluster.scheduler import Scheduler

@pytest.fixture
def pool(tmp_path):
    worker = Worker(id="pc", name="PC", transport="ssh", host="100.64.1.2", tailscale_ip="100.64.1.2", ssh_user="user", gurobi=True)
    store = JobStore(tmp_path)
    registry = WorkerRegistry(store, [worker])
    monitor = WorkerMonitor(registry, [worker])
    monitor.controller = {"git": {"sha": "same", "dirty": False}, "source_digest": "same", "runtime_versions": {"python": "3.14"}}
    registry.update(worker.id, {"tailscale_online": True, "network_checked_at": now(), "session_verified": True,
        "last_probe_at": now(), "ssh_ready": True, "capability": {**monitor.controller, "disk_free_gb": 100,
        "ram_gb": 32, "ram_free_gb": 20, "gurobi_version": [13]}})
    return worker, store, registry, monitor

def test_unknown_and_stale_network_never_mean_ready(pool):
    worker, store, registry, monitor = pool
    assert registry.view(worker, [], monitor.controller)["can_run_optimization"]
    for online in (None, False):
        registry.update(worker.id, {"tailscale_online": online})
        assert not registry.view(worker, [], monitor.controller)["can_run_optimization"]
    registry.update(worker.id, {"tailscale_online": True, "network_checked_at": (datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()})
    view = registry.view(worker, [], monitor.controller)
    assert view["tailscale_online"] is None
    assert not view["can_run_optimization"]

def test_drain_disable_survive_restart_without_cancelling_active_job(pool):
    worker, store, registry, monitor = pool
    store.add({"id": "running", "kind": "diagnostic"})
    store.transition("running", "RUNNING", expected={"QUEUED"}, worker_id=worker.id)
    registry.set_mode(worker.id, "draining")
    assert registry.view(worker, store.rows(), monitor.controller)["status"] == "DRAINING"
    assert store.get("running")["state"] == "RUNNING"
    restarted = WorkerRegistry(store, [worker])
    assert restarted.get(worker.id)["mode"] == "draining"
    assert not restarted.view(worker, store.rows(), monitor.controller)["can_run_diagnostic"]
    restarted.set_mode(worker.id, "active")
    assert not restarted.view(worker, store.rows(), monitor.controller)["can_run_optimization"]  # requires a fresh probe

def test_tailscale_failure_is_unknown_not_offline(pool, monkeypatch):
    from bff.services.cluster import worker_monitor
    worker, _, registry, monitor = pool
    monkeypatch.setattr(worker_monitor, "tailscale_status", lambda: (_ for _ in ()).throw(FileNotFoundError("tailscale")))
    monitor.refresh_network()
    assert registry.view(worker, [], monitor.controller)["tailscale_online"] is None
    monkeypatch.setattr(worker_monitor, "tailscale_status", lambda: {worker.tailscale_ip: {"Online": False, "LastSeen": "2026-09-20T10:00:00Z"}})
    monitor.refresh_network()
    assert registry.view(worker, [], monitor.controller)["status"] == "OFFLINE"

@pytest.mark.parametrize("changed", [{"git": {"sha": "different", "dirty": False}}, {"disk_free_gb": 0}, {"runtime_versions": {}}])
def test_environment_mismatch_or_disk_shortage_blocks_jobs(pool, changed):
    worker, _, registry, monitor = pool
    capability = registry.get(worker.id)["observation"]["capability"]
    registry.update(worker.id, {"capability": {**capability, **changed}})
    assert not registry.view(worker, [], monitor.controller)["can_run_optimization"]

def test_ssh_success_is_reported_even_when_runner_is_missing(pool, monkeypatch):
    from bff.services.cluster import worker_monitor
    worker, _, registry, monitor = pool
    monkeypatch.setattr(worker_monitor, "probe_ssh", lambda _: None)
    monkeypatch.setattr(worker_monitor, "invoke", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("python missing")))
    monitor.probe(worker)
    view = registry.view(worker, [], monitor.controller)
    assert view["ssh_ready"] and not view["environment_ready"]
    assert view["status"] == "SSH_READY"

def test_modes_are_local_only_and_diagnostic_route_still_works(tmp_path, monkeypatch):
    from bff.routers import cluster
    scheduler = Scheduler(tmp_path, ClusterConfig(workers=[Worker(id="local", name="local")]))
    monkeypatch.setattr(cluster, "get_scheduler", lambda: scheduler)
    monkeypatch.setattr(scheduler.monitor, "request_probe", lambda _: True)
    app = FastAPI(); app.include_router(cluster.router)
    try:
        with TestClient(app, base_url="http://localhost", client=("127.0.0.1", 123)) as client:
            assert client.post("/cluster/workers/local/drain").json()["mode"] == "draining"
            assert client.post("/cluster/workers/local/diagnostic").status_code == 409
            assert client.post("/cluster/workers/local/enable").status_code == 200
            assert client.post("/cluster/workers/local/diagnostic").status_code == 200
            assert client.post("/cluster/workers/local/disable", headers={"Origin": "https://evil.example"}).status_code == 403
    finally:
        scheduler.controller_lock.close()

def test_keep_awake_releases_windows_sleep_request(monkeypatch):
    from bff.services.cluster import system_metrics
    if system_metrics.os.name != "nt": pytest.skip("Windows API")
    requests = []
    monkeypatch.setattr(system_metrics.ctypes.windll.kernel32, "SetThreadExecutionState", lambda flag: requests.append(flag) or 1)
    with pytest.raises(RuntimeError):
        with system_metrics.keep_awake(): raise RuntimeError("job failed")
    assert requests == [0x80000001, 0x80000000]


def test_detached_launch_failure_is_collectable_without_rerunning(tmp_path, monkeypatch):
    from bff.services.cluster import runner
    from bff.services.cluster.scheduler import collect_artifacts
    manifest = {"id": "spawn-failed"}
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError("spawn denied")))
    request = {"operation": "submit", "id": manifest["id"], "manifest": manifest, "bundle": {}}
    assert runner.handle(request, tmp_path)["state"] == "FAILED"
    assert runner.handle(request, tmp_path)["state"] == "FAILED"  # Same attempt returns its first receipt.
    response = runner.handle({"operation": "collect", "id": manifest["id"]}, tmp_path)
    result = collect_artifacts(response, manifest, tmp_path / "controller" / "artifacts")
    assert result["state"] == "FAILED"
    assert "spawn denied" in result["error"]
