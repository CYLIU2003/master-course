"""T01–T06: private registration and solver-free observation boundaries."""
import copy
import pytest

from bff.services.cluster.contracts import ClusterConfig
from bff.services.cluster.seed_import import merge_private_seed
from bff.services.cluster.worker_monitor import parse_tailscale_status


def seed():
    return {"schema_version": "cluster-worker-seed-proposal-v1", "local_worker": {
        "id": "local", "name": "Parent", "transport": "local"}, "workers": [
        {"id": f"pc-{i}", "name": f"Test PC {i}", "host": f"100.64.1.{i}", "ssh_user": f"user{i}",
         "transport": "ssh", "accepting_jobs": True} for i in range(1, 12)]}


def test_T01_T02_import_exact_inventory_but_never_trust_seed_readiness():
    config = merge_private_seed(seed(), ClusterConfig(global_gurobi_slots=2), self_name="Parent")
    assert len(config.workers) == 12
    for incoming, worker in zip(seed()["workers"], config.workers[1:]):
        assert (worker.host, worker.ssh_user, worker.name) == (incoming["host"], incoming["ssh_user"], incoming["name"])
    assert all(not w.enabled and not w.gurobi and not w.identity_verified and w.slots == 1 for w in config.workers)
    assert all(w.monitoring_enabled for w in config.workers)
    assert all(w.repo == "C:/mc-worker/cluster" for w in config.workers[1:])


def test_T01_duplicate_local_node_ip_and_worker_ids_rejected():
    payload = seed()
    with pytest.raises(ValueError, match="identity"):
        merge_private_seed(payload, ClusterConfig(), self_addresses={"100.64.1.1"})
    payload["workers"][1]["host"] = payload["workers"][0]["host"]
    with pytest.raises(ValueError, match="identity"):
        merge_private_seed(payload, ClusterConfig())
    payload = seed(); payload["workers"][1]["id"] = "pc-1"
    with pytest.raises(ValueError, match="Duplicate worker"):
        merge_private_seed(payload, ClusterConfig())


def test_T01_reimport_preserves_verified_configuration_and_rejects_drift():
    payload = seed(); original = merge_private_seed(payload, ClusterConfig())
    original.workers[1].enabled = True; original.workers[1].identity_verified = True
    original.workers[1].python = "C:/verified/python.exe"
    assert merge_private_seed(payload, original).model_dump() == original.model_dump()
    changed = copy.deepcopy(payload); changed["workers"][0]["ssh_user"] = "different"
    with pytest.raises(ValueError, match="refusing to overwrite"):
        merge_private_seed(changed, original)


@pytest.mark.parametrize("payload", [None, [], {}, {"BackendState": "Running", "Peer": []},
    {"BackendState": "Running", "Peer": {"bad": 7}},
    {"BackendState": "Running", "Peer": {"bad": {"TailscaleIPs": "100.64.1.1"}}}])
def test_T05_parser_rejects_incompatible_shapes(payload):
    with pytest.raises(ValueError):
        parse_tailscale_status(payload)


def test_T05_missing_online_is_unknown_not_false():
    result = parse_tailscale_status({"BackendState": "Running", "NewField": 1, "Peer": {
        "a": {"TailscaleIPs": ["100.64.1.1"], "Online": "true"}}})
    assert result["100.64.1.1"]["Online"] is None


def test_T06_eleven_probes_never_start_gurobi(monkeypatch):
    from bff.services.cluster import runner
    import sys
    from types import SimpleNamespace
    counts = {"env": 0, "model": 0}
    def forbidden(kind):
        counts[kind] += 1
        raise AssertionError("A normal probe must not acquire a license")
    monkeypatch.setitem(sys.modules, "gurobipy", SimpleNamespace(gurobi=SimpleNamespace(version=lambda: (13,0,1)),
        Env=lambda *a, **k: forbidden("env"), Model=lambda *a, **k: forbidden("model")))
    monkeypatch.setattr(runner, "git_state", lambda: {"sha": "test", "dirty": False})
    monkeypatch.setattr(runner, "source_digest", lambda: "test")
    monkeypatch.setattr(runner, "cpu_percent", lambda: None)
    for _ in range(11):
        assert runner.probe()["gurobi_license_checked"] is False
    assert counts == {"env": 0, "model": 0}
