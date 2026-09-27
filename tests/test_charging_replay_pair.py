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


@pytest.mark.parametrize("candidate_text,expected_calls", [("same constraints", 2), ("changed bounds", 1)])
def test_native_mismatch_stops_before_candidate_optimize(monkeypatch, tmp_path, candidate_text, expected_calls):
    from dataclasses import dataclass, field
    from pathlib import Path
    import sys
    from types import SimpleNamespace
    from tools.research.run_charging_replay_pair import solve_profile
    from src.optimization.engine import OptimizationEngine
    from src.optimization.milp import solver_adapter

    @dataclass
    class Problem:
        metadata: dict = field(default_factory=dict)

    @dataclass
    class Result:
        feasible: bool = True
        solver_status: str = "optimal"
        objective_value: float = 10
        infeasibility_reasons: tuple = ()

    class Model:
        NumVars = 2
        NumConstrs = 3
        NumNZs = 4
        Status = 2
        SolCount = 1
        Runtime = .1
        MaxMemUsed = .01
        ObjVal = ObjBound = 10
        MIPGap = 0

        def update(self):
            pass

        def write(self, path):
            Path(path).write_text(self.content)

    calls = []
    monkeypatch.setitem(sys.modules, "gurobipy", SimpleNamespace(GurobiError=RuntimeError))
    monkeypatch.setattr(solver_adapter, "optimize_model", lambda *a, **k: calls.append("optimize"))

    def solve(self, problem, config):
        model = Model()
        model.content = "same constraints" if config.stage2_charging_start_policy == "none" else candidate_text
        solver_adapter.optimize_model(model)
        return Result()

    monkeypatch.setattr(OptimizationEngine, "solve", solve)
    baseline = solve_profile(Problem(), SimpleNamespace(stage2_charging_start_policy="none"), tmp_path / "none")
    if candidate_text != "same constraints":
        with pytest.raises(ValueError, match="Native MPS differs"):
            solve_profile(Problem(), SimpleNamespace(stage2_charging_start_policy="candidate"),
                          tmp_path / "candidate", baseline["native_models"])
    else:
        candidate = solve_profile(Problem(), SimpleNamespace(stage2_charging_start_policy="candidate"),
                                 tmp_path / "candidate", baseline["native_models"])
        assert candidate["native_models"][0]["mps_sha256"] == baseline["native_models"][0]["mps_sha256"]
    assert len(calls) == expected_calls
