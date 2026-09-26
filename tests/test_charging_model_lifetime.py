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


@pytest.mark.parametrize('phase', ['phase1_charging_only', 'phase2_assignment_only', 'phase3_two_stage', 'phase4_integrated'])
@pytest.mark.parametrize('fails', [False, True])
def test_public_solve_releases_all_exit_paths(monkeypatch, phase, fails):
    import src.optimization.milp.solver_adapter as module
    from src.optimization.common.problem import OptimizationConfig
    alive = []
    adapter = GurobiMILPAdapter()
    def body(*args, **kwargs):
        track_model(NativeModel(alive))
        if fails or phase == 'phase4_integrated':
            raise RuntimeError('intercept native construction')
        return 'saved outcome', 'saved plan'
    for name in ('_solve_charging_only', '_solve_assignment_only', '_solve_thesis_two_stage'):
        monkeypatch.setattr(adapter, name, body)
    monkeypatch.setattr(module, 'is_gurobi_available', body)
    with managed_gurobi_session(lambda: None, lambda _: None) as session:
        enclosing = track_model(NativeModel(alive))
        if fails or phase == 'phase4_integrated':
            with pytest.raises(RuntimeError, match='intercept'):
                adapter.solve(None, OptimizationConfig(phase=phase))
        else:
            assert adapter.solve(None, OptimizationConfig(phase=phase)) == ('saved outcome', 'saved plan')
        assert session.models == [enclosing] and alive == [enclosing]


def test_nested_retracking_keeps_original_owner():
    alive = []
    with scoped_gurobi_models():
        outer = track_model(NativeModel(alive))
        with scoped_gurobi_models():
            track_model(outer)
            track_model(NativeModel(alive))
        assert alive == [outer] and not outer.disposed
    assert alive == []


def test_scope_does_not_adopt_preexisting_session_model():
    alive = []
    with managed_gurobi_session(lambda: None, lambda _: None) as session:
        enclosing = track_model(NativeModel(alive))
        with scoped_gurobi_models():
            track_model(enclosing)
        assert session.models == [enclosing] and not enclosing.disposed
    assert alive == []


@pytest.mark.parametrize('fails', [False, True])
def test_feedback_releases_infeasible_model_before_retry(monkeypatch, fails):
    alive, events = [], []
    adapter = GurobiMILPAdapter()
    with managed_gurobi_session(lambda: None, lambda _: events.append('release')) as session:
        session.env = SimpleNamespace(dispose=lambda: events.append('env'))
        session.admitted = session.started = True
        with scoped_gurobi_models():
            model = track_model(NativeModel(alive))
            def retry(problem, config):
                assert model.disposed and not alive and session.models == []
                assert session.started and not events
                if fails:
                    raise RuntimeError('retry failed')
                return 'result', 'plan'
            monkeypatch.setattr(adapter, '_solve_thesis_two_stage', retry)
            if fails:
                with pytest.raises(RuntimeError, match='retry failed'):
                    adapter._retry_two_stage_after_charging_release(model, None, None)
            else:
                assert adapter._retry_two_stage_after_charging_release(model, None, None) == ('result', 'plan')
    assert events == ['env', 'release']


def test_cleanup_failure_still_attempts_other_models_and_holds_license():
    from src.gurobi_session import GurobiSession
    events = []
    def fail():
        events.append('failed-model')
        raise RuntimeError('dispose unavailable')
    failed = SimpleNamespace(dispose=fail)
    healthy = SimpleNamespace(dispose=lambda: events.append('healthy-model'))
    session = GurobiSession(lambda: None, lambda _: events.append('release'),
                            env=SimpleNamespace(dispose=lambda: events.append('env')),
                            models=[healthy, failed], admitted=True, started=True)
    with pytest.raises(ExceptionGroup, match='cleanup'):
        session.close()
    assert events == ['failed-model', 'healthy-model']
    assert session.models == [failed]


def test_scope_reports_body_failure_and_all_cleanup_errors():
    events = []
    def fail():
        events.append('failed-cleanup')
        raise RuntimeError('cleanup detail')
    with pytest.raises(BaseExceptionGroup) as error:
        with scoped_gurobi_models():
            track_model(SimpleNamespace(dispose=lambda: events.append('healthy-cleanup')))
            track_model(SimpleNamespace(dispose=fail))
            raise ValueError('original solve failure')
    assert events == ['failed-cleanup', 'healthy-cleanup']
    assert isinstance(error.value.exceptions[0], ValueError)
    assert 'original solve failure' in str(error.value.exceptions[0])


def test_failed_scope_cleanup_is_retried_at_close_without_losing_original_error():
    events = []
    def fail():
        events.append('dispose-attempt')
        raise RuntimeError('native cleanup unavailable')
    with pytest.raises(BaseExceptionGroup) as error:
        with managed_gurobi_session(lambda: None, lambda _: events.append('release')) as session:
            session.env = SimpleNamespace(dispose=lambda: events.append('env'))
            session.started = session.admitted = True
            with scoped_gurobi_models():
                track_model(SimpleNamespace(dispose=fail))
                raise ValueError('original execution error')
    assert events == ['dispose-attempt', 'dispose-attempt']
    def leaves(exc):
        return [child for nested in exc.exceptions for child in leaves(nested)] if isinstance(exc, BaseExceptionGroup) else [exc]
    assert any(isinstance(exc, ValueError) and str(exc) == 'original execution error' for exc in leaves(error.value))


def test_healthy_cleanup_preserves_cancellation_type():
    from src.execution_control import ExecutionCancelled
    with pytest.raises(ExecutionCancelled):
        with managed_gurobi_session(lambda: None, lambda _: None):
            with scoped_gurobi_models():
                track_model(SimpleNamespace(dispose=lambda: None))
                raise ExecutionCancelled('cancelled by user')


def test_facade_tracks_native_model_before_setting_limits(monkeypatch):
    from src.gurobi_runtime import GurobiFacade
    import src.solver_memory as memory
    alive = []
    def rejected(_):
        raise RuntimeError('invalid memory controls')
    monkeypatch.setattr(memory, 'apply_memory_limits', rejected)
    with pytest.raises(RuntimeError, match='invalid memory'):
        with scoped_gurobi_models():
            GurobiFacade(SimpleNamespace(Model=lambda: NativeModel(alive))).Model()
    assert alive == []
