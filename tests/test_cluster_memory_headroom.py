import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from bff.services.cluster.contracts import ClusterConfig, Worker
from bff.services.cluster.resource_policy import resource_fit
from tools.cluster.configure_memory_headroom import configure, raise_reserves


def test_reserves_preserve_larger_values_and_other_controls():
    config = ClusterConfig(workers=[Worker(id="parent", name="parent", reserved_system_ram_gb=2),
        Worker(id="child", name="child", transport="ssh", host="child", reserved_system_ram_gb=0),
        Worker(id="large", name="large", reserved_system_ram_gb=12)])
    raise_reserves(config)
    assert [w.reserved_system_ram_gb for w in config.workers] == [6, 4, 12]
    assert config.global_gurobi_slots == 2
    assert all(w.slots == 1 for w in config.workers)


def test_config_dry_run_and_backup(tmp_path):
    path = tmp_path / "workers.json"
    raw = b'{"workers":[{"id":"local","name":"local","reserved_system_ram_gb":0}]}'
    path.write_bytes(raw)
    assert not configure(path)["applied"]
    assert path.read_bytes() == raw
    result = configure(path, apply=True)
    assert Path(result["backup"]).read_bytes() == raw
    assert json.loads(path.read_bytes())["workers"][0]["reserved_system_ram_gb"] == 6


@pytest.mark.parametrize("free,commit,eligible", [(21.9, 40, False), (30, 21.9, False), (22, 22, True)])
def test_18gb_job_requires_additional_4gb_in_both_memory_pools(free, commit, eligible):
    worker = Worker(id="child", name="child", transport="ssh", host="child")
    capability = {"platform": "Windows", "installed_ram_gb": 32, "ram_gb": 31.7,
                  "ram_free_gb": free, "commit_available_gb": commit,
                  "disk_free_gb": 40, "cpu_count": 8, "cpu_percent": 1}
    manifest = {"minimum_ram_gb": 18, "requires_gurobi": True,
                "resource_requirements": {"cpu_threads": 4}}
    assert resource_fit(worker, capability, manifest, [])["eligible"] is eligible


def test_nonfinite_reserve_rejected():
    with pytest.raises(ValidationError):
        Worker(id="a", name="a", reserved_system_ram_gb=float("nan"))
