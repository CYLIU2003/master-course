from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from bff.services.cluster.license_broker import LicenseBroker
from bff.services.cluster.store import JobStore
from src.gurobi_runtime import GurobiFacade
from src.gurobi_session import managed_gurobi_session, GurobiLicenseUnavailable
from src.solver_policy import solver_policy_scope, optimize_model


def test_ten_simultaneous_callers_share_exactly_two_durable_slots(tmp_path):
    def acquire(index):
        broker = LicenseBroker(JobStore(tmp_path), total=2, external=0)
        return broker.acquire(str(index), owner_kind="local" if index % 2 else "remote")
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(acquire, range(10)))
    assert sum(results) == 2
    assert not LicenseBroker(JobStore(tmp_path), total=2, external=0).acquire("third", owner_kind="local")


def test_other_controller_queue_cannot_open_an_independent_pool(tmp_path, monkeypatch):
    from bff.services.cluster.license_authority import claim_authority
    authority = tmp_path / "parent/authority.json"
    designated = tmp_path / "designated"
    claim_authority(authority, designated)
    monkeypatch.setenv("MC_GUROBI_AUTHORITY_FILE", str(authority))
    owner = LicenseBroker(JobStore(designated), total=2, external=0)
    other = LicenseBroker(JobStore(tmp_path / "other"), total=2, external=0)
    assert owner.acquire("first", owner_kind="remote")
    assert not other.acquire("other-first", owner_kind="local")
    with pytest.raises(ValueError, match="OTHER_QUEUE"):
        claim_authority(authority, tmp_path / "other")
    assert owner.acquire("second", owner_kind="local")
    assert not owner.acquire("third", owner_kind="remote")
    authority.write_text("invalid")
    assert not owner.acquire("after-corruption", owner_kind="local")


def test_local_gurobi_rejects_16gb_before_reserving_or_starting_env(tmp_path, monkeypatch):
    from bff.services.cluster import contracts, system_metrics
    from bff.services.optimization_run.solver_policy import local_license_callbacks
    from src.solver_policy import SolverPolicyViolation
    monkeypatch.setenv("MC_GUROBI_AUTHORITY_FILE", str(tmp_path / "authority.json"))
    monkeypatch.setenv("MC_CLUSTER_DIR", str(tmp_path / "queue"))
    monkeypatch.setattr(contracts, "read_config", lambda: contracts.ClusterConfig())
    monkeypatch.setattr(system_metrics, "memory_metrics", lambda: {"installed_ram_gb": 16, "ram_gb": 15.8})
    acquire, _ = local_license_callbacks("small-host")
    with pytest.raises(SolverPolicyViolation, match="32GB"):
        acquire()
    assert LicenseBroker(JobStore(tmp_path / "queue"), total=2, external=0).snapshot() == []


def test_reconnect_never_expires_unknown_owner_and_respects_token_tail(tmp_path, monkeypatch):
    from bff.services.cluster import license_broker
    monkeypatch.setattr(license_broker.time, "time", lambda: 1000)
    broker = LicenseBroker(JobStore(tmp_path), total=2, external=1)
    assert broker.acquire("worker", owner_kind="remote")
    broker.mark_uncertain("worker")
    monkeypatch.setattr(license_broker.time, "time", lambda: 100000)
    broker = LicenseBroker(JobStore(tmp_path), total=2, external=1)
    assert not broker.acquire("next", owner_kind="local")
    broker.finish("worker", cooldown_seconds=330)
    assert not broker.acquire("next", owner_kind="local")
    monkeypatch.setattr(license_broker.time, "time", lambda: 100331)
    assert broker.acquire("next", owner_kind="local")


def test_cluster_grant_and_staging_are_atomic(tmp_path):
    store = JobStore(tmp_path)
    store.add({"id": "job", "requires_gurobi": True})
    broker = LicenseBroker(store, total=2, external=0)
    assert broker.acquire("job", owner_kind="remote", worker_id="worker")
    assert store.get("job")["state"] == "STAGING"
    assert not broker.acquire("job", owner_kind="remote", worker_id="worker")
    store.recover()
    assert store.get("job")["state"] == "LOST"
    assert len([r for r in broker.snapshot() if r["state"] == "ACTIVE"]) == 1


def test_legacy_fenced_attempt_does_not_consume_license_cooldown(tmp_path):
    store = JobStore(tmp_path)
    manifest = {"id": "legacy", "requires_gurobi": True, "gurobi_token_cooldown_seconds": 330}
    store.add(manifest)
    store.transition("legacy", "BLOCKED", expected={"QUEUED"},
                     result={"cluster_admission": "FENCED_BEFORE_LAUNCH"})
    broker = LicenseBroker(store, total=1, external=0)
    assert broker.acquire("next", owner_kind="local")


def test_managed_models_and_probe_reuse_one_env_and_dispose_before_release():
    calls = []
    class Env:
        def __init__(self, **kwargs): calls.append("env")
        def setParam(self, *args): pass
        def start(self): calls.append("start")
        def dispose(self): calls.append("dispose_env")
    class Model:
        def __init__(self, name, env):
            self.env = env
            calls.append(name)
        def optimize(self, callback=None): calls.append("solve")
        def dispose(self): calls.append("dispose_model")
    facade = GurobiFacade(SimpleNamespace(Env=Env, Model=Model))
    with solver_policy_scope() as usage:
        with managed_gurobi_session(lambda: calls.append("admit"), lambda started: calls.append("release")):
            a, b = facade.Model("a"), facade.Model("b")
            assert a.env is b.env
            optimize_model(a)
            optimize_model(b)
    assert calls == ["admit", "env", "start", "a", "b", "solve", "solve", "dispose_model", "dispose_model", "dispose_env", "release"]
    assert usage.environment_starts == 1 and usage.optimize_calls == 2


def test_long_campaign_disposes_completed_models_without_restarting_env():
    calls = []
    class Env:
        def __init__(self, **kwargs): calls.append("env")
        def setParam(self, *args): pass
        def start(self): calls.append("start")
        def dispose(self): calls.append("dispose_env")
    class Model:
        def __init__(self, name, env): calls.append(name)
        def dispose(self): calls.append("dispose_model")
    facade = GurobiFacade(SimpleNamespace(Env=Env, Model=Model))
    with managed_gurobi_session(lambda: calls.append("admit"), lambda started: calls.append("release")) as session:
        facade.Model("week1")
        session.dispose_models()
        assert session.models == []
        facade.Model("week2")
        session.dispose_models()
    assert calls == ["admit", "env", "start", "week1", "dispose_model",
                     "week2", "dispose_model", "dispose_env", "release"]


def test_license_failure_is_not_infeasibility_or_repeat_start():
    calls = []
    class Env:
        def __init__(self, **kwargs): pass
        def setParam(self, *args): pass
        def start(self): raise RuntimeError("private provider diagnostic")
        def dispose(self): pass
    facade = GurobiFacade(SimpleNamespace(Env=Env))
    with pytest.raises(GurobiLicenseUnavailable, match="GUROBI_LICENSE_UNAVAILABLE"):
        with managed_gurobi_session(lambda: None, lambda started: calls.append(started)) as session:
            session.environment(facade._module)
    assert calls == [True]


def test_T28_local_and_cluster_share_the_same_pc_slot(tmp_path):
    from bff.services.cluster.local_resources import LocalResources
    from bff.services.cluster.contracts import Worker
    store = JobStore(tmp_path)
    local = LocalResources(store)
    worker = Worker(id="local", name="parent", slots=1)
    store.add({"id": "cluster-cpu", "requires_gurobi": False})
    assert local.acquire("normal", worker, 1)
    assert not store.reserve_worker("cluster-cpu", "local", 1)
    local.release("normal")
    assert store.reserve_worker("cluster-cpu", "local", 1)
    assert not local.acquire("next-normal", worker, 1)


def test_T32_remote_pids_are_never_looked_up_locally(tmp_path, monkeypatch):
    from bff.services.cluster import runner
    calls = []
    monkeypatch.setattr(runner, "process_identity", lambda pid: calls.append(pid) or None)
    broker = LicenseBroker(JobStore(tmp_path), total=2, external=0)
    assert broker.acquire("remote", owner_kind="remote", owner_identity="123:birth")
    assert broker.acquire("local", owner_kind="local", owner_identity="456:birth")
    broker.reconcile_local_owners()
    assert calls == [456]
    assert {r["id"]: r["state"] for r in broker.snapshot()} == {"remote": "ACTIVE", "local": "RELEASING"}


def test_automatic_threads_reserve_all_cpu_without_changing_solver_controls(tmp_path, monkeypatch):
    from bff.services.cluster import local_resources
    from bff.services.cluster.contracts import Worker
    monkeypatch.setattr(local_resources.os, "cpu_count", lambda: 8)
    store = JobStore(tmp_path)
    resources = local_resources.LocalResources(store)
    worker = Worker(id="local", name="parent", slots=4)
    assert resources.acquire("normal", worker, 0)
    assert resources.rows()[0]["manifest"]["resource_requirements"]["cpu_threads"] == 8
    assert not resources.acquire("other", worker, 1)
    store.add({"id": "cluster", "requires_gurobi": False, "resource_requirements": {"cpu_threads": 1}})
    assert not store.reserve_worker("cluster", "local", 4, cpu_threads=1, cpu_count=8)
    resources.release("normal")
    assert store.reserve_worker("cluster", "local", 4, cpu_threads=1, cpu_count=8)
    assert not resources.acquire("auto", worker, 0)
