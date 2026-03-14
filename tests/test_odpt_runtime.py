from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_runtime_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = repo_root / "scripts" / "_odpt_runtime.py"
    spec = importlib.util.spec_from_file_location("odpt_runtime_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_odpt_api_key_prefers_explicit_value(monkeypatch: pytest.MonkeyPatch):
    module = _load_runtime_module()
    monkeypatch.setattr(module, "get_runtime_secret", lambda names: "env-key")

    assert module.resolve_odpt_api_key(" cli-key ") == "cli-key"


def test_resolve_odpt_api_key_uses_runtime_secret(monkeypatch: pytest.MonkeyPatch):
    module = _load_runtime_module()
    monkeypatch.setattr(module, "get_runtime_secret", lambda names: "env-key")

    assert module.resolve_odpt_api_key(None) == "env-key"


def test_resolve_odpt_api_key_raises_when_missing(monkeypatch: pytest.MonkeyPatch):
    module = _load_runtime_module()
    monkeypatch.setattr(module, "get_runtime_secret", lambda names: None)

    with pytest.raises(RuntimeError, match="ODPT consumer key is missing"):
        module.resolve_odpt_api_key(None)
