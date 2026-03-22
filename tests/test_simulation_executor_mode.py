from __future__ import annotations

from unittest import mock

from bff.routers import simulation


def test_simulation_executor_defaults_to_thread_on_windows() -> None:
    with mock.patch.dict("os.environ", {}, clear=True):
        with mock.patch.object(simulation.os, "name", "nt"):
            assert simulation._simulation_executor_mode() == "thread"


def test_simulation_executor_respects_explicit_override() -> None:
    with mock.patch.dict("os.environ", {"BFF_SIM_EXECUTOR": "process"}, clear=True):
        with mock.patch.object(simulation.os, "name", "nt"):
            assert simulation._simulation_executor_mode() == "process"


def test_simulation_future_lock_is_reentrant() -> None:
    lock = simulation._SIMULATION_FUTURE_LOCK

    assert lock.acquire(timeout=0.1)
    try:
        assert lock.acquire(blocking=False)
        lock.release()
    finally:
        lock.release()
