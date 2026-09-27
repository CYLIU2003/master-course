import math

import pytest

from bff.services.cluster.contracts import Worker
from tools.research.run_charging_replay_pair import check_admission, json_value


def capability():
    return {"installed_ram_gb": 32, "ram_gb": 31.7, "ram_free_gb": 16,
            "commit_available_gb": 24, "platform": "Windows", "disk_free_gb": 40,
            "cpu_count": 12, "cpu_percent": 20}


def test_small_diagnostic_fits_while_weekly_budget_does_not():
    worker = Worker(id="local", name="parent", gurobi=True, reserved_system_ram_gb=6)
    fit = check_admission(worker, {"mode": "active"}, capability(), 8, 4, [])
    assert fit["available_ram_gb"] == 10
    with pytest.raises(RuntimeError, match="INSUFFICIENT_OR_UNKNOWN_RAM"):
        check_admission(worker, {"mode": "active"}, capability(), 16, 4, [])


@pytest.mark.parametrize("mode", ["draining", "disabled", None])
def test_worker_mode_cannot_be_bypassed(mode):
    with pytest.raises(RuntimeError, match="disabled, draining"):
        check_admission(Worker(id="local", name="p", gurobi=True), {"mode": mode}, capability(), 8, 4, [])


@pytest.mark.parametrize("change,reason", [
    ({"installed_ram_gb": 16}, "GUROBI_REQUIRES_32GB"),
    ({"commit_available_gb": 8}, "COMMIT_CAPACITY"),
    ({"ram_free_gb": None}, "UNKNOWN_RAM"),
])
def test_resource_uncertainty_and_shortage_refuse_native_work(change, reason):
    with pytest.raises(RuntimeError, match=reason):
        check_admission(Worker(id="local", name="p", gurobi=True), {"mode": "active"},
                        {**capability(), **change}, 8, 4, [])


def test_unknown_cost_is_not_serialized_as_zero():
    assert json_value({"cost": math.inf, "nested": (math.nan,)}) == {"cost": "inf", "nested": ["nan"]}
