"""Test native-test admission without ever obtaining a Gurobi license."""
from types import SimpleNamespace

import pytest

from conftest import admitted_gurobi_session
from src import gurobi_runtime, gurobi_session


def test_native_fixture_skips_before_license_probe_when_not_managed(monkeypatch):
    monkeypatch.setattr(gurobi_session, "current_session", lambda: None)
    def forbidden():
        pytest.fail("Unmanaged tests must not probe a license")
    monkeypatch.setattr(gurobi_runtime, "is_gurobi_available", forbidden)
    with pytest.raises(pytest.skip.Exception, match="shared license admission"):
        admitted_gurobi_session.__wrapped__()


def test_native_fixture_probes_inside_existing_managed_scope(monkeypatch):
    session = SimpleNamespace()
    calls = []
    monkeypatch.setattr(gurobi_session, "current_session", lambda: session)
    monkeypatch.setattr(gurobi_runtime, "is_gurobi_available", lambda: calls.append(session) or True)
    assert admitted_gurobi_session.__wrapped__() is session
    assert calls == [session]


def test_native_fixture_does_not_hide_failed_admission(monkeypatch):
    monkeypatch.setattr(gurobi_session, "current_session", lambda: SimpleNamespace())
    def unavailable():
        raise RuntimeError("Shared license slot unavailable")
    monkeypatch.setattr(gurobi_runtime, "is_gurobi_available", unavailable)
    with pytest.raises(RuntimeError, match="Shared license slot unavailable"):
        admitted_gurobi_session.__wrapped__()
