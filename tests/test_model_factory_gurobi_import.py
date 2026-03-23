from __future__ import annotations

import builtins
import site
from types import SimpleNamespace
import sys

from src.constraints import assignment as assignment_constraints
from src import model_factory
from src import milp_model
from src import objective


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


def test_configure_gurobipy_sys_path_adds_site_packages_candidate(tmp_path, monkeypatch) -> None:
    fake_site = tmp_path / "site-packages"
    (fake_site / "gurobipy").mkdir(parents=True)
    (fake_site / "gurobipy" / "__init__.py").write_text("", encoding="utf-8")

    monkeypatch.setattr(site, "getsitepackages", lambda: [str(fake_site)])
    monkeypatch.setattr(site, "getusersitepackages", lambda: "")
    while str(fake_site) in sys.path:
        sys.path.remove(str(fake_site))

    milp_model._configure_gurobipy_sys_path()

    assert str(fake_site) in sys.path


def test_assignment_constraints_resolve_gurobi_at_call_time(monkeypatch) -> None:
    class SentinelError(RuntimeError):
        pass

    class FakeGP:
        @staticmethod
        def quicksum(_items):
            raise SentinelError("late-bound gp used")

    monkeypatch.setattr(
        assignment_constraints,
        "ensure_gurobi",
        lambda: (FakeGP(), object()),
    )

    data = SimpleNamespace(allow_partial_service=False, delta_t_hour=1.0)
    ms = SimpleNamespace(
        K_ALL=["veh-1"],
        R=["trip-1"],
        vehicle_task_feasible={"veh-1": {"trip-1"}},
    )
    dp = SimpleNamespace(
        task_lut={"trip-1": SimpleNamespace(demand_cover=True)},
        overlap_pairs=[],
        vehicle_lut={"veh-1": SimpleNamespace(max_operating_time=1.0, max_distance=1.0)},
        task_duration_slot={"trip-1": 0.0},
        task_distance_km={"trip-1": 0.0},
    )
    vars_dict = {"x_assign": {("veh-1", "trip-1"): 1}}

    class DummyModel:
        def addConstr(self, *_args, **_kwargs):
            return None

    try:
        assignment_constraints.add_assignment_constraints(
            DummyModel(),
            data,
            ms,
            dp,
            vars_dict,
        )
    except SentinelError as exc:
        assert str(exc) == "late-bound gp used"
    else:
        raise AssertionError("assignment constraints did not resolve gp at call time")


def test_build_objective_resolves_gurobi_at_call_time(monkeypatch) -> None:
    class SentinelError(RuntimeError):
        pass

    class FakeGP:
        @staticmethod
        def LinExpr():
            raise SentinelError("late-bound objective gp used")

    monkeypatch.setattr(
        objective,
        "ensure_gurobi",
        lambda: (FakeGP(), SimpleNamespace(MINIMIZE=1)),
    )

    data = SimpleNamespace(objective_weights={}, delta_t_hour=1.0)
    ms = SimpleNamespace(K_ALL=[], K_BEV=[], K_ICE=[], R=[], T=[], C=[], I_CHARGE=[])
    dp = SimpleNamespace()
    vars_dict = {"x_assign": {}}

    class DummyModel:
        def setObjective(self, *_args, **_kwargs):
            return None

    try:
        objective.build_objective(DummyModel(), data, ms, dp, vars_dict)
    except SentinelError as exc:
        assert str(exc) == "late-bound objective gp used"
    else:
        raise AssertionError("objective builder did not resolve gp at call time")
