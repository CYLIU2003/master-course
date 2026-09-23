"""Cooperative cancellation of the current owned execution only."""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable

_cancelled: ContextVar[Callable[[], bool] | None] = ContextVar("execution_cancelled", default=None)


class ExecutionCancelled(RuntimeError):
    pass


def check_cancelled():
    if is_cancelled():
        raise ExecutionCancelled("EXECUTION_CANCELLED")


def is_cancelled() -> bool:
    check = _cancelled.get()
    return check is not None and check()


def cancellation_checker():
    return _cancelled.get()


@contextmanager
def cancellation_scope(check: Callable[[], bool]):
    token = _cancelled.set(check)
    try:
        yield
    finally:
        _cancelled.reset(token)
