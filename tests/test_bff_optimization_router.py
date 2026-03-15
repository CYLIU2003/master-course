import threading

import bff.routers.optimization as optimization_router
from bff.routers.optimization import _OPTIMIZATION_FUTURE_LOCK, _parse_mode
from src.optimization import OptimizationMode


def test_parse_mode_maps_supported_aliases():
    assert _parse_mode("milp") == OptimizationMode.MILP
    assert _parse_mode("ALNS") == OptimizationMode.ALNS
    assert _parse_mode("heuristic") == OptimizationMode.ALNS
    assert _parse_mode("hybrid") == OptimizationMode.HYBRID
    assert _parse_mode("unknown") == OptimizationMode.HYBRID


def test_optimization_future_lock_is_reentrant():
    assert isinstance(_OPTIMIZATION_FUTURE_LOCK, type(threading.RLock()))


def test_submit_optimization_job_does_not_deadlock_on_nested_lock(monkeypatch):
    class DummyFuture:
        def done(self) -> bool:
            return False

    class DummyExecutor:
        def submit(self, _fn, *_args):
            return DummyFuture()

    monkeypatch.setattr(optimization_router, "_OPTIMIZATION_EXECUTOR", DummyExecutor())
    monkeypatch.setattr(optimization_router, "_OPTIMIZATION_FUTURE", None)
    monkeypatch.setattr(
        optimization_router,
        "_register_optimization_future",
        lambda *_args, **_kwargs: None,
    )

    result_holder: dict[str, object] = {}

    def _invoke_submit() -> None:
        result_holder["value"] = optimization_router._submit_optimization_job(
            fn=lambda *_a: None,
            args=(),
            job_id="job-test",
            scenario_id="scenario-test",
            service_id="WEEKDAY",
            depot_id="meguro",
            mode="hybrid",
            stage="queued",
        )

    thread = threading.Thread(target=_invoke_submit, daemon=True)
    thread.start()
    thread.join(timeout=1.0)

    assert not thread.is_alive(), "submit call deadlocked"
    assert result_holder.get("value") is True
