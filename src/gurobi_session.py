"""One explicit native Env per managed execution, disposed before releasing its grant."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Callable, Any

from src.solver_policy import require_gurobi, current_usage, SolverPolicyViolation


class GurobiLicenseUnavailable(RuntimeError):
    """License/admission failure is not a mathematical infeasibility certificate."""


@dataclass
class GurobiSession:
    acquire: Callable[[], None]
    release: Callable[[bool], None]
    env: Any = None
    models: list = field(default_factory=list)
    admitted: bool = False
    started: bool = False
    license_failed: bool = False

    def environment(self, module):
        require_gurobi("Env.start")
        if self.license_failed:
            raise GurobiLicenseUnavailable("GUROBI_LICENSE_UNAVAILABLE: acquisition already failed")
        if self.env is None:
            self.acquire()
            self.admitted = True
            self.env = module.Env(empty=True)
            self.env.setParam("OutputFlag", 0)
            # Academic WLS minimum token duration, with a separate broker tail.
            self.env.setParam("WLSTokenDuration", 5)
            usage = current_usage()
            if usage is not None:
                usage.environment_starts += 1
            self.started = True  # A failed start may still have issued a token.
            try:
                self.env.start()
            except Exception:
                self.license_failed = True
                raise GurobiLicenseUnavailable("GUROBI_LICENSE_UNAVAILABLE: Env start failed") from None
        return self.env

    def close(self):
        # Model references retain Env/license resources even after Env.dispose.
        for model in reversed(self.models):
            model.dispose()
        self.models.clear()
        if self.env is not None:
            self.env.dispose()
        if self.admitted:
            self.release(self.started)


_session: ContextVar[GurobiSession | None] = ContextVar("gurobi_session", default=None)


def current_session() -> GurobiSession | None:
    return _session.get()


@contextmanager
def managed_gurobi_session(acquire: Callable[[], None], release: Callable[[bool], None]):
    if current_session() is not None:
        yield current_session()
        return
    session = GurobiSession(acquire, release)
    token = _session.set(session)
    try:
        yield session
    finally:
        try:
            session.close()
        finally:
            _session.reset(token)


def track_model(model):
    session = current_session()
    if session is not None and all(item is not model for item in session.models):
        session.models.append(model)
    return model
