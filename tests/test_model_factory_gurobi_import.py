from __future__ import annotations

import builtins
from types import SimpleNamespace

from src import model_factory


def test_build_model_by_mode_defers_gurobi_import_to_milp_builder(monkeypatch) -> None:
    sentinel_model = object()
    sentinel_vars = {"ok": True}
    monkeypatch.setattr(
        model_factory,
        "build_milp_model",
        lambda data, ms, dp, flags: (sentinel_model, sentinel_vars),
    )

    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "gurobipy":
            raise ImportError("simulated gurobi import failure")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    dummy_data = SimpleNamespace(
        enable_pv=False,
        enable_battery_degradation=False,
        enable_v2g=False,
        enable_demand_charge=False,
    )

    model, vars_ = model_factory.build_model_by_mode(
        "mode_milp_only",
        dummy_data,
        SimpleNamespace(),
        SimpleNamespace(),
    )

    assert model is sentinel_model
    assert vars_ == sentinel_vars
