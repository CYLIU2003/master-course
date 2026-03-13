from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Dict, Optional

from bff.services import research_catalog

_log = logging.getLogger(__name__)
_LOCK = threading.RLock()
_CACHE: Dict[str, Dict[str, Any]] = {}
_DEFAULT_TTL_SEC = 3600


def default_ttl_sec() -> int:
    raw = os.environ.get("BFF_RUNTIME_CACHE_TTL_SEC", str(_DEFAULT_TTL_SEC))
    try:
        return max(int(raw), 1)
    except (TypeError, ValueError):
        return _DEFAULT_TTL_SEC


def get_cached(
    key: str,
    fetch_fn: Callable[[], Any],
    *,
    ttl_sec: Optional[int] = None,
) -> Any:
    ttl = ttl_sec or default_ttl_sec()
    now = time.time()
    with _LOCK:
        entry = _CACHE.get(key)
        if entry is not None and now - float(entry.get("ts") or 0.0) < ttl:
            return entry.get("data")

    data = fetch_fn()
    with _LOCK:
        _CACHE[key] = {"ts": time.time(), "data": data}
    return data


def set_cached(key: str, data: Any) -> Any:
    with _LOCK:
        _CACHE[key] = {"ts": time.time(), "data": data}
    return data


def invalidate(*, key: Optional[str] = None, prefix: Optional[str] = None) -> None:
    with _LOCK:
        if key is not None:
            _CACHE.pop(key, None)
        if prefix is not None:
            for cache_key in [item for item in _CACHE if item.startswith(prefix)]:
                _CACHE.pop(cache_key, None)


def warm_startup_cache() -> None:
    _log.info("Warming runtime cache")

    try:
        datasets = research_catalog.list_datasets()
        set_cached("app:datasets", datasets)
        _log.info("Research dataset catalog cached (%s datasets)", len(datasets))
    except Exception:
        _log.exception("Research dataset catalog warm-up failed")

    try:
        default_status = research_catalog.get_default_dataset_status()
        set_cached("app:data-status:default", default_status)
        _log.info(
            "Default research dataset status cached for %s",
            default_status.get("datasetId"),
        )
    except Exception:
        _log.exception("Default research dataset warm-up failed")


def get_app_state(dataset_id: str | None = None) -> Dict[str, Any]:
    target_dataset_id = dataset_id or research_catalog.default_dataset_id()
    status = research_catalog.get_dataset(target_dataset_id)
    return {
        "dataset_id": status.get("datasetId") or target_dataset_id,
        "dataset_version": status.get("datasetVersion"),
        "seed_ready": bool(status.get("seedReady")),
        "built_ready": bool(status.get("builtReady")),
        "missing_artifacts": list(status.get("missingArtifacts") or []),
        "integrity_error": status.get("integrityError"),
    }
