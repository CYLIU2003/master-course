"""Lab-open low-memory PCs: a per-worker Gurobi RAM floor that never relaxes the per-task memory budget."""
import pytest
from pydantic import ValidationError

from bff.services.cluster.contracts import Worker
from bff.services.cluster.resource_policy import (
    GUROBI_MINIMUM_RAM_ENV, gurobi_ram_eligible, gurobi_ram_floor, resource_fit)
from bff.services.cluster.transport import command


def capability(installed):
    return {"platform": "Windows", "installed_ram_gb": installed, "ram_gb": installed - 0.2,
            "ram_free_gb": installed - 1, "commit_available_gb": installed * 2,
            "disk_free_gb": 40, "cpu_count": 8, "cpu_percent": 1}


def manifest(ram, threads=1):
    return {"minimum_ram_gb": ram, "requires_gurobi": True, "resource_requirements": {"cpu_threads": threads}}


def worker(**extra):
    return Worker(id="lab", name="lab", transport="ssh", host="lab", gurobi=True, reserved_system_ram_gb=1, **extra)


def test_default_floor_still_rejects_16gb_machine():
    fit = resource_fit(worker(), capability(15.9), manifest(2), [])
    assert not fit["eligible"] and "GUROBI_REQUIRES_24GB_INSTALLED_RAM" in fit["reasons"]
    assert not gurobi_ram_eligible(capability(23.8))
    assert gurobi_ram_eligible(capability(24))


def test_worker_floor_admits_small_task_on_16gb_machine():
    fit = resource_fit(worker(gurobi_minimum_installed_ram_gb=8), capability(15.9), manifest(2), [])
    assert fit["eligible"], fit["reasons"]


def test_worker_floor_does_not_relax_the_task_memory_budget():
    # Research-sized tasks (16 GiB) stay off a 15.9 GiB PC: budget = installed - 8 GiB = 7.9 GiB.
    fit = resource_fit(worker(gurobi_minimum_installed_ram_gb=8), capability(15.9), manifest(16), [])
    assert not fit["eligible"] and "EXCEEDS_MACHINE_MEMORY_BUDGET" in fit["reasons"]


def test_unknown_installed_ram_is_still_rejected_by_floor_logic():
    assert not gurobi_ram_eligible({"installed_ram_gb": None, "ram_gb": None}, 8)


def test_floor_below_installed_ram_of_a_tiny_machine_is_not_a_blanket_admission():
    assert not gurobi_ram_eligible(capability(7.9), 8)
    assert gurobi_ram_eligible(capability(8), 8)


def test_worker_process_reads_floor_from_environment(monkeypatch):
    monkeypatch.delenv(GUROBI_MINIMUM_RAM_ENV, raising=False)
    assert gurobi_ram_floor() == 24
    monkeypatch.setenv(GUROBI_MINIMUM_RAM_ENV, "8")
    assert gurobi_ram_floor() == 8 and gurobi_ram_eligible(capability(16))
    monkeypatch.setenv(GUROBI_MINIMUM_RAM_ENV, "garbage")
    assert gurobi_ram_floor() == 24
    monkeypatch.setenv(GUROBI_MINIMUM_RAM_ENV, "-1")
    assert gurobi_ram_floor() == 24


def test_launch_command_passes_floor_only_when_set():
    local = dict(id="lab", name="lab", transport="local", gurobi=True)
    assert "--gurobi-min-ram-gb" not in command(Worker(**local))
    args = command(Worker(**local, gurobi_minimum_installed_ram_gb=8))
    assert args[args.index("--gurobi-min-ram-gb") + 1] == "8"


def test_ssh_launch_command_carries_floor_in_encoded_script():
    import base64
    encoded = command(worker(gurobi_minimum_installed_ram_gb=8))[-1].rsplit(" ", 1)[-1]
    script = base64.b64decode(encoded).decode("utf-16-le")
    assert "--gurobi-min-ram-gb" in script and "'8'" in script


@pytest.mark.parametrize("value", [0, -3, float("nan"), float("inf")])
def test_invalid_floor_rejected(value):
    with pytest.raises(ValidationError):
        worker(gurobi_minimum_installed_ram_gb=value)
