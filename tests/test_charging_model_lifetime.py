"""Repeated charging calls must not accumulate native models in the weekly Env."""
from types import SimpleNamespace

import pytest

from src.gurobi_session import managed_gurobi_session, scoped_gurobi_models, track_model
from src.optimization.milp.solver_adapter import GurobiMILPAdapter


class NativeModel:
    def __init__(self, alive):
        self.alive = alive
        alive.append(self)
        self.disposed = False

    def dispose(self):
        assert not self.disposed
        self.disposed = True
        self.alive.remove(self)


@pytest.mark.parametrize("managed", [True, False])
@pytest.mark.parametrize("outcome", ["feasible", "no_incumbent", "exception"])
def test_real_charging_entry_disposes_each_window(monkeypatch, managed, outcome):
    from contextlib import nullcontext
    import src.optimization.milp.solver_adapter as adapter_module

    alive, events = [], []
    # Exercise the actual decorated entry, intercepting the large model body
    # at its runtime boundary. No license is acquired by this regression.
    def runtime():
        track_model(NativeModel(alive))
        if outcome == "exception":
            raise RuntimeError("native failure")
        raise StopIteration(outcome)

    monkeypatch.setattr(adapter_module, "ensure_gurobi", runtime)
    scope = managed_gurobi_session(lambda: None, lambda _: events.append("release")) if managed else nullcontext()
    with scope as session:
        enclosing = track_model(NativeModel(alive)) if managed else None
        if managed:
            session.admitted = session.started = True
            session.env = SimpleNamespace(dispose=lambda: events.append("env"))
        for _ in range(174):
            error = RuntimeError if outcome == "exception" else StopIteration
            with pytest.raises(error):
                GurobiMILPAdapter()._solve_thesis_stage2_charging_dispatch(
                    None, None, None, stage1_status="fixed", stage1_gap=None,
                    stage1_bound=None, stage1_objective_value=None,
                    stage1_runtime_sec=0, slots_per_day=96,
                )
            assert alive == ([enclosing] if managed else [])
            assert events == []
            if managed:
                assert session.models == [enclosing]
    assert alive == []
    assert events == (["env", "release"] if managed else [])


def test_result_copied_before_release_and_nested_scope_retains_parent():
    alive = []

    @scoped_gurobi_models()
    def solve():
        model = track_model(NativeModel(alive))
        with scoped_gurobi_models():
            track_model(NativeModel(alive))
        assert alive == [model] and not model.disposed
        return {"energy_kwh": 12.5, "gap": 0.25}

    assert solve() == {"energy_kwh": 12.5, "gap": 0.25}
    assert alive == []
