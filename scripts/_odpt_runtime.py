from __future__ import annotations

import importlib.util
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    from tools._config_runtime import get_runtime_secret
except ModuleNotFoundError:  # pragma: no cover - direct path fallback
    _config_runtime_path = _REPO_ROOT / "tools" / "_config_runtime.py"
    _config_runtime_spec = importlib.util.spec_from_file_location(
        "tools._config_runtime",
        _config_runtime_path,
    )
    if _config_runtime_spec is None or _config_runtime_spec.loader is None:
        raise
    _config_runtime_module = importlib.util.module_from_spec(_config_runtime_spec)
    _config_runtime_spec.loader.exec_module(_config_runtime_module)
    get_runtime_secret = _config_runtime_module.get_runtime_secret


ODPT_KEY_CANDIDATES = ["ODPT_CONSUMER_KEY", "ODPT_API_KEY", "ODPT_TOKEN"]


def resolve_odpt_api_key(explicit_key: str | None) -> str:
    value = (explicit_key or "").strip()
    if value:
        return value

    resolved = get_runtime_secret(ODPT_KEY_CANDIDATES)
    if resolved:
        return resolved

    raise RuntimeError(
        "ODPT consumer key is missing. Set one of "
        "ODPT_CONSUMER_KEY / ODPT_API_KEY / ODPT_TOKEN in the environment or .env, "
        "or pass --api-key explicitly."
    )
