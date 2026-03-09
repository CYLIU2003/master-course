from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = _REPO_ROOT / "config" / "runtime_paths.json"


@lru_cache(maxsize=1)
def load_runtime_paths() -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "odpt_snapshot_dir": "./data/odpt/tokyu",
        "transit_catalog_db_path": "./outputs/transit_catalog.sqlite",
        "transit_db_tokyu": "./data/odpt_tokyu.db",
        "transit_db_toei": "./data/gtfs_toei.db",
        "catalog_fast_dir": "./data/catalog-fast",
    }
    if not _CONFIG_PATH.exists() or not _CONFIG_PATH.is_file():
        return defaults
    try:
        payload = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    if not isinstance(payload, dict):
        return defaults
    merged = dict(defaults)
    merged.update(payload)
    return merged


def resolve_runtime_path(key: str, fallback: str | Path) -> Path:
    value = load_runtime_paths().get(key, fallback)
    path = Path(value)
    if not path.is_absolute():
        path = (_REPO_ROOT / path).resolve()
    return path
