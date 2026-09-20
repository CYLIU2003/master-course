from types import SimpleNamespace

from src.optimization.milp.solver_adapter import _gurobi_memory_snapshot


def test_memory_snapshot_does_not_report_unavailable_as_zero():
    assert _gurobi_memory_snapshot(SimpleNamespace()) == {"used_gb": None, "peak_gb": None}
    assert _gurobi_memory_snapshot(SimpleNamespace(MemUsed=float("nan"), MaxMemUsed=18.25)) == {
        "used_gb": None, "peak_gb": 18.25,
    }
