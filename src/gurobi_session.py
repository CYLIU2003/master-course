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
        self.dispose_models()
        if self.env is not None:
            self.env.dispose()
        if self.admitted:
            self.release(self.started)

    def dispose_models(self):
        """Release completed models while retaining one admitted Env for a campaign."""
        # Model references retain Env/license resources even after Env.dispose.
        _dispose_all(tuple(self.models), self.models)


_session: ContextVar[GurobiSession | None] = ContextVar("gurobi_session", default=None)
_model_scopes: ContextVar[tuple[list[Any], ...]] = ContextVar("gurobi_model_scopes", default=())


def current_session() -> GurobiSession | None:
    return _session.get()


@contextmanager
def managed_gurobi_session(acquire: Callable[[], None], release: Callable[[bool], None]):
    if current_session() is not None:
        yield current_session()
        return
    session = GurobiSession(acquire, release)
    token = _session.set(session)
    body_error = None
    try:
        yield session
    except BaseException as exc:
        body_error = exc
        raise
    finally:
        try:
            session.close()
        except Exception as cleanup_error:
            if body_error is not None:
                raise BaseExceptionGroup("Execution and session cleanup failed", [body_error, cleanup_error]) from None
            raise
        finally:
            _session.reset(token)


def track_model(model):
    session = current_session()
    already_tracked = session is not None and any(item is model for item in session.models)
    if session is not None and not already_tracked:
        session.models.append(model)
    scopes = _model_scopes.get()
    # Re-optimizing an enclosing model must not transfer its ownership inward.
    if scopes and not already_tracked and not any(item is model for scope in scopes for item in scope):
        scopes[-1].append(model)
    return model


def dispose_model(model: Any) -> None:
    """Release one finished model without releasing the shared Env or grant."""
    model.dispose()
    session = current_session()
    if session is not None:
        session.models[:] = [item for item in session.models if item is not model]
    for scope in _model_scopes.get():
        scope[:] = [item for item in scope if item is not model]


def _dispose_all(models: tuple[Any, ...], retained: list[Any] | None = None) -> None:
    errors = []
    for model in reversed(models):
        try:
            dispose_model(model)
            if retained is not None:
                retained[:] = [item for item in retained if item is not model]
        except Exception as exc:
            errors.append(exc)
    if errors:
        # Failed models stay tracked; do not release an uncertain Env/grant.
        raise ExceptionGroup("Native model cleanup failed", errors)


@contextmanager
def scoped_gurobi_models():
    """Dispose models created by one solve after its result/diagnostics are copied.

    Keep the admitted Env, license reservation, and any enclosing candidate
    models alive. Also bound model lifetime for standalone adapter calls.
    """
    owned: list[Any] = []
    token = _model_scopes.set((*_model_scopes.get(), owned))
    body_error = None
    try:
        yield
    except BaseException as exc:
        body_error = exc
        raise
    finally:
        try:
            _dispose_all(tuple(owned))
        except Exception as cleanup_error:
            if body_error is not None:
                raise BaseExceptionGroup("Solve and cleanup failed", [body_error, cleanup_error]) from None
            raise
        finally:
            _model_scopes.reset(token)
