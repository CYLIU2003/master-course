from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


_REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists() or not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def get_runtime_secret(name_candidates: list[str]) -> Optional[str]:
    for name in name_candidates:
        value = os.getenv(name)
        if value:
            return value

    for dotenv_path in (_REPO_ROOT / ".env", _REPO_ROOT / ".env.local"):
        env_map = _load_dotenv_file(dotenv_path)
        for name in name_candidates:
            value = env_map.get(name)
            if value:
                return value

    for config_path in (
        _REPO_ROOT / "config" / "local.json",
        _REPO_ROOT / "config" / "runtime.json",
    ):
        if not config_path.exists() or not config_path.is_file():
            continue
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        for name in name_candidates:
            value = payload.get(name)
            if value:
                return str(value)

    return None
