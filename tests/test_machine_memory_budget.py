from types import SimpleNamespace
import pytest
from bff.services.cluster.resource_policy import machine_memory_budget, resource_fit
from bff.services.cluster.contracts import Worker
from src.solver_memory import ENV_KEY, memory_limits, apply_memory_limits

@pytest.mark.parametrize("installed,budget", [(16,8),(32,16),(64,32)])
def test_half_capacity(installed,budget):
    assert machine_memory_budget({"installed_ram_gb":installed,"ram_gb":installed-.3}) == budget

@pytest.mark.parametrize("required,free,commit,allowed", [(16,21.18,22.69,True),(18,30,40,False),(16,19,40,False),(16,30,19,False)])
def test_fresh_admission(required,free,commit,allowed):
    worker=Worker(id="worker",name="worker")
    cap={"installed_ram_gb":32,"ram_gb":31.7,"ram_free_gb":free,"platform":"Windows","commit_available_gb":commit,"disk_free_gb":40,"cpu_count":8}
    fit=resource_fit(worker,cap,{"minimum_ram_gb":required,"requires_gurobi":True,"resource_requirements":{"cpu_threads":4}},[])
    assert fit["eligible"] is allowed
    assert fit["machine_memory_budget_gib"] == 16
    assert fit["physical_free_ram_gb"] == free
    assert fit["system_reserve_gb"] == 4

def test_native_cap_applied_again_after_profile_overrides(monkeypatch):
    monkeypatch.setenv(ENV_KEY,"16")
    model=SimpleNamespace(Params=SimpleNamespace(MemLimit=float("inf"),SoftMemLimit=18.0))
    apply_memory_limits(model)
    limits=memory_limits()
    assert model.Params.MemLimit == pytest.approx(14*1024**3/1e9)
    assert model.Params.SoftMemLimit == pytest.approx(limits["native_soft_gb"])
    model.Params.SoftMemLimit=32
    apply_memory_limits(model)
    assert model.Params.SoftMemLimit == pytest.approx(limits["native_soft_gb"])
    model.Params.SoftMemLimit=1
    apply_memory_limits(model)
    assert model.Params.SoftMemLimit == 1

@pytest.mark.parametrize("value",["nan","inf","-1","0","3"])
def test_invalid_native_budget_rejected(monkeypatch,value):
    monkeypatch.setenv(ENV_KEY,value)
    with pytest.raises(ValueError): memory_limits()

def test_legacy_without_budget_does_not_change_model(monkeypatch):
    monkeypatch.delenv(ENV_KEY,raising=False)
    apply_memory_limits(object())

def test_optimize_boundary_enforces_budget_on_clones(monkeypatch):
    from src.solver_policy import optimize_model
    monkeypatch.setenv(ENV_KEY,"16")
    class Model:
        Params=SimpleNamespace(MemLimit=float("inf"),SoftMemLimit=32.0)
        def optimize(self):
            assert self.Params.MemLimit == pytest.approx(14*1024**3/1e9)
            assert self.Params.SoftMemLimit < self.Params.MemLimit
            return "solved"
    assert optimize_model(Model()) == "solved"
