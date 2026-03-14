"""Runtime app-state assembly and caching.

Sole responsibility:
- call artifact and dataset validation once during startup/reload
- assemble AppState from validation result plus lightweight loader state
- cache the assembled state and expose reload hooks for tests
- provide get_app_state() for FastAPI dependencies

Not responsible for:
- contract judgment implementation details
- parquet loading and normalization rules
- banner message text
- producer-side build operations or legacy feed import logic
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pandas as pd

from bff.services import research_catalog
from src.artifact_contract import ArtifactContractError, RUNTIME_VERSION, check_artifact_contract

_log = logging.getLogger(__name__)
_LOCK = threading.RLock()
_CACHE: Dict[str, Dict[str, Any]] = {}
_DEFAULT_TTL_SEC = 3600
_REPO_ROOT = Path(__file__).resolve().parents[2]
BUILT_ROOT = Path(os.environ.get("BUILT_ROOT", str(_REPO_ROOT / "data" / "built")))
DEFAULT_DATASET_ID = os.environ.get("DEFAULT_DATASET_ID", "tokyu_core")
_cached_state: Dict[str, Any] | None = None


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
        default_status = research_catalog.get_dataset(DEFAULT_DATASET_ID)
        set_cached("app:data-status:default", default_status)
        _log.info(
            "Default research dataset status cached for %s",
            default_status.get("datasetId"),
        )
    except Exception:
        _log.exception("Default research dataset warm-up failed")

    try:
        reload_state()
    except Exception:
        _log.exception("App state warm-up failed")


def _load_state(dataset_id: str | None = None) -> Dict[str, Any]:
    target_dataset_id = dataset_id or DEFAULT_DATASET_ID
    status = research_catalog.get_dataset(target_dataset_id)
    manifest = dict(status.get("manifest") or {})
    built_dir = BUILT_ROOT / target_dataset_id
    built_ready = False
    integrity_error = status.get("integrityError")
    contract_error_code = status.get("contractErrorCode")
    missing_artifacts = list(status.get("missingArtifacts") or [])

    if built_dir.exists():
        try:
            manifest = check_artifact_contract(built_dir, verify_hashes=True)
            built_ready = True
            integrity_error = None
            contract_error_code = None
            missing_artifacts = []
        except ArtifactContractError as exc:
            integrity_error = str(exc)
            contract_error_code = str(exc.code)
            missing_artifacts = list((exc.details or {}).get("missing_artifacts") or missing_artifacts)
            _log.error("Artifact contract violation: %s", exc)
    else:
        expected = [
            str(built_dir / "manifest.json"),
            str(built_dir / "routes.parquet"),
            str(built_dir / "trips.parquet"),
            str(built_dir / "timetables.parquet"),
        ]
        missing_artifacts = expected

    routes_df = pd.DataFrame()
    if built_ready:
        routes_path = built_dir / "routes.parquet"
        if routes_path.exists():
            routes_df = pd.read_parquet(routes_path)

    return {
        "dataset_id": status.get("datasetId") or target_dataset_id,
        "dataset_version": manifest.get("dataset_version") or status.get("datasetVersion"),
        "producer_version": manifest.get("producer_version"),
        "schema_version": manifest.get("schema_version"),
        "runtime_version": RUNTIME_VERSION,
        "seed_ready": bool(status.get("seedReady")),
        "built_ready": built_ready,
        "missing_artifacts": missing_artifacts,
        "integrity_error": integrity_error,
        "contract_error_code": contract_error_code,
        "built_dir": built_dir,
        "routes_df": routes_df,
    }


def reload_state() -> None:
    global _cached_state
    _cached_state = _load_state(DEFAULT_DATASET_ID)


def get_app_state(dataset_id: str | None = None) -> Dict[str, Any]:
    target_dataset_id = dataset_id or DEFAULT_DATASET_ID
    if target_dataset_id == DEFAULT_DATASET_ID:
        global _cached_state
        if _cached_state is None:
            reload_state()
        return dict(_cached_state or {})
    return _load_state(target_dataset_id)
