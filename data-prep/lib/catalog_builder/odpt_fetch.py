"""
bff/services/odpt_fetch.py

Streaming download of ODPT resources directly from api.odpt.org.
Saves raw JSON to the server-side snapshot directory and returns only
metadata (counts, hashes, file paths).  Never loads the full payload
into memory or returns it through an API response.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlencode

import httpx

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ODPT_API_BASE = "https://api.odpt.org/api/v4"
ODPT_OPERATOR_TOKYU = "odpt.Operator:TokyuBus"

# Map of ODPT resource type -> local filename
ODPT_RESOURCE_FILE_MAP: Dict[str, str] = {
    "odpt:BusroutePattern": "busroute_pattern.json",
    "odpt:BusstopPole": "busstop_pole.json",
    "odpt:BusTimetable": "bus_timetable.json",
    "odpt:BusstopPoleTimetable": "busstop_pole_timetable.json",
}

DEFAULT_ODPT_TOKYU_RESOURCES = list(ODPT_RESOURCE_FILE_MAP.keys())

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CACHE_DIR = _REPO_ROOT / "data" / "cache" / "odpt" / "raw"

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _consumer_key() -> str:
    """Read the ODPT consumer key from env vars or .env-style config."""
    key = get_runtime_secret(["ODPT_CONSUMER_KEY", "ODPT_API_KEY", "ODPT_TOKEN"])
    if not key:
        raise RuntimeError(
            "ODPT consumer key is not set. Configure ODPT_CONSUMER_KEY, "
            "ODPT_API_KEY, or ODPT_TOKEN in your environment or .env."
        )
    return key


def _cache_base_dir() -> Path:
    configured = os.environ.get("ODPT_CACHE_DIR")
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = (_REPO_ROOT / path).resolve()
        return path
    return _DEFAULT_CACHE_DIR


def build_odpt_url(
    resource_name: str,
    consumer_key: str,
    operator_id: str = ODPT_OPERATOR_TOKYU,
    extra_params: Optional[Dict[str, Any]] = None,
) -> str:
    """Build an ODPT API endpoint URL for a given resource."""
    params = {
        "odpt:operator": operator_id,
        "acl:consumerKey": consumer_key,
    }
    if extra_params:
        for key, value in extra_params.items():
            if value is None:
                continue
            params[str(key)] = str(value)
    return f"{ODPT_API_BASE}/{resource_name}?{urlencode(params)}"


def _safe_log_url(url: str) -> str:
    return url.split("acl:consumerKey=")[0] + "acl:consumerKey=***"


def _record_id(record: Any, fallback_index: int) -> str:
    if isinstance(record, dict):
        value = record.get("owl:sameAs") or record.get("@id")
        if value:
            return str(value)
    return f"__index__:{fallback_index}"


def _load_json_array(path: Path) -> List[Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return list(data)
    if data is None:
        return []
    return [data]


def _write_json_array(path: Path, records: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(list(records), f, ensure_ascii=False, indent=2)


def _file_metadata(path: Path) -> Dict[str, Any]:
    sha256 = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            if not chunk:
                continue
            sha256.update(chunk)
            size += len(chunk)
    return {
        "path": str(path),
        "size_bytes": size,
        "sha256": sha256.hexdigest(),
    }


def _load_chunk_keys(snapshot_dir: Path, filename: str, field_name: str) -> List[str]:
    path = snapshot_dir / filename
    if not path.exists():
        return []
    keys: List[str] = []
    seen = set()
    for item in _load_json_array(path):
        if not isinstance(item, dict):
            continue
        value = item.get("owl:sameAs") or item.get("@id") or item.get(field_name)
        if not value:
            continue
        value_str = str(value)
        if value_str in seen:
            continue
        seen.add(value_str)
        keys.append(value_str)
    return keys


def _chunk_query_params(resource_name: str, snapshot_dir: Path) -> List[Dict[str, str]]:
    if resource_name == "odpt:BusTimetable":
        pattern_ids = _load_chunk_keys(snapshot_dir, "busroute_pattern.json", "odpt:busroutePattern")
        return [{"odpt:busroutePattern": pattern_id} for pattern_id in pattern_ids]
    if resource_name == "odpt:BusstopPoleTimetable":
        stop_ids = _load_chunk_keys(snapshot_dir, "busstop_pole.json", "odpt:busstopPole")
        return [{"odpt:busstopPole": stop_id} for stop_id in stop_ids]
    return []


def fetch_odpt_records(url: str, timeout: float = 300.0) -> List[Any]:
    safe_url = _safe_log_url(url)
    _log.info("Fetching ODPT chunk from %s", safe_url)
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()
    if isinstance(payload, list):
        return payload
    if payload is None:
        return []
    return [payload]


def download_odpt_resource_chunked(
    resource_name: str,
    out_path: Path,
    *,
    consumer_key: str,
    operator_id: str,
    snapshot_dir: Path,
    timeout: float = 300.0,
    delay_sec: float = 0.0,
) -> Dict[str, Any]:
    chunk_params = _chunk_query_params(resource_name, snapshot_dir)
    if not chunk_params:
        url = build_odpt_url(resource_name, consumer_key, operator_id)
        result = download_odpt_resource(url, out_path, timeout=timeout)
        return {"chunk_count": 1, "truncated_chunk_count": 0, **result}

    merged: Dict[str, Any] = {}
    truncated_chunk_count = 0
    for index, params in enumerate(chunk_params):
        url = build_odpt_url(resource_name, consumer_key, operator_id, extra_params=params)
        records = fetch_odpt_records(url, timeout=timeout)
        if len(records) >= 1000:
            truncated_chunk_count += 1
        for item_index, record in enumerate(records):
            merged[_record_id(record, item_index)] = record
        if delay_sec > 0 and index + 1 < len(chunk_params):
            time.sleep(delay_sec)

    _write_json_array(out_path, merged.values())
    result = _file_metadata(out_path)
    return {
        "chunk_count": len(chunk_params),
        "truncated_chunk_count": truncated_chunk_count,
        **result,
    }


# ---------------------------------------------------------------------------
# Streaming download
# ---------------------------------------------------------------------------


def download_odpt_resource(url: str, out_path: Path, timeout: float = 300.0) -> Dict[str, Any]:
    """
    Stream-download an ODPT resource to a local file.

    Returns metadata dict with path, size, and sha256 hash, but never the
    actual payload content.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sha256 = hashlib.sha256()
    size = 0

    # Mask the consumer key from the logged URL
    safe_url = _safe_log_url(url)
    _log.info("Downloading ODPT resource to %s from %s", out_path, safe_url)

    with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as response:
        response.raise_for_status()
        with out_path.open("wb") as f:
            for chunk in response.iter_bytes(chunk_size=65536):
                if not chunk:
                    continue
                f.write(chunk)
                sha256.update(chunk)
                size += len(chunk)

    _log.info("Downloaded %s (%d bytes, sha256=%s)", out_path.name, size, sha256.hexdigest()[:16])
    return {
        "path": str(out_path),
        "size_bytes": size,
        "sha256": sha256.hexdigest(),
    }


def count_json_array_items(path: Path) -> int:
    """
    Count top-level items in a JSON array file without loading entire content.
    Falls back to full load for small files, uses streaming count for large ones.
    """
    file_size = path.stat().st_size
    # For files under 50MB, just load and count
    if file_size < 50 * 1024 * 1024:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            return len(data)
        return 1

    # For large files, stream-count top-level array elements by tracking bracket depth
    count = 0
    depth = 0
    in_string = False
    escape_next = False
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            for ch in line:
                if escape_next:
                    escape_next = False
                    continue
                if ch == "\\":
                    if in_string:
                        escape_next = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue
                if ch == "[":
                    depth += 1
                elif ch == "]":
                    depth -= 1
                elif ch == "{":
                    depth += 1
                    if depth == 2:  # top-level array element starts
                        count += 1
                elif ch == "}":
                    depth -= 1
    return count


# ---------------------------------------------------------------------------
# Bundle fetch  —  4 resources at once
# ---------------------------------------------------------------------------


def fetch_tokyu_odpt_bundle(
    *,
    resources: Optional[List[str]] = None,
    operator_id: str = ODPT_OPERATOR_TOKYU,
) -> Dict[str, Any]:
    """
    Fetch all target ODPT resources for Tokyu Bus.

    Downloads each resource via streaming to the local cache directory,
    then returns a manifest (metadata only, NO raw payload).
    """
    consumer_key = _consumer_key()
    resource_list = resources or DEFAULT_ODPT_TOKYU_RESOURCES

    now = datetime.now(timezone.utc)
    snapshot_id = f"odpt-tokyu-{now.strftime('%Y%m%d-%H%M%S')}"
    snapshot_dir = _cache_base_dir() / snapshot_id

    _log.info(
        "Starting ODPT bundle fetch: snapshot_id=%s, resources=%s",
        snapshot_id,
        resource_list,
    )

    resource_results: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for resource_name in resource_list:
        filename = ODPT_RESOURCE_FILE_MAP.get(resource_name)
        if filename is None:
            warnings.append(f"Unknown ODPT resource type skipped: {resource_name}")
            continue

        url = build_odpt_url(resource_name, consumer_key, operator_id)
        out_path = snapshot_dir / filename

        try:
            if resource_name in {"odpt:BusTimetable", "odpt:BusstopPoleTimetable"}:
                result = download_odpt_resource_chunked(
                    resource_name,
                    out_path,
                    consumer_key=consumer_key,
                    operator_id=operator_id,
                    snapshot_dir=snapshot_dir,
                    delay_sec=0.02,
                )
                if int(result.get("truncated_chunk_count") or 0) > 0:
                    warnings.append(
                        f"{resource_name} still hit ODPT cap in {result.get('truncated_chunk_count')} chunk(s)"
                    )
            else:
                result = download_odpt_resource(url, out_path)
            item_count = count_json_array_items(out_path)
            resource_results.append(
                {
                    "resource_name": resource_name,
                    "filename": filename,
                    "count": item_count,
                    **result,
                }
            )
        except httpx.HTTPStatusError as exc:
            msg = f"ODPT HTTP {exc.response.status_code} for {resource_name}"
            _log.error(msg)
            warnings.append(msg)
        except Exception as exc:
            msg = f"Failed to fetch {resource_name}: {exc}"
            _log.exception(msg)
            warnings.append(msg)

    # Build manifest
    manifest = build_manifest(
        snapshot_id=snapshot_id,
        snapshot_dir=snapshot_dir,
        operator_id=operator_id,
        resources=resource_results,
        warnings=warnings,
        started_at=now,
    )

    # Save manifest file
    manifest_path = snapshot_dir / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    _log.info(
        "ODPT bundle fetch complete: snapshot_id=%s, %d resources, %d warnings",
        snapshot_id,
        len(resource_results),
        len(warnings),
    )

    return manifest


# ---------------------------------------------------------------------------
# Manifest builder
# ---------------------------------------------------------------------------


def build_manifest(
    *,
    snapshot_id: str,
    snapshot_dir: Path,
    operator_id: str,
    resources: List[Dict[str, Any]],
    warnings: List[str],
    started_at: datetime,
) -> Dict[str, Any]:
    """Build a snapshot manifest from fetch results."""
    fetched_counts: Dict[str, int] = {}
    stored_files: List[str] = []
    resource_entries: List[Dict[str, Any]] = []

    for res in resources:
        name = res["resource_name"]
        fetched_counts[name] = res.get("count", 0)
        stored_files.append(res["filename"])
        resource_entries.append(
            {
                "name": name,
                "path": res["path"],
                "count": res.get("count", 0),
                "size_bytes": res.get("size_bytes", 0),
                "hash": f"sha256:{res.get('sha256', '')}",
            }
        )

    completed_at = datetime.now(timezone.utc)

    return {
        "snapshot_id": snapshot_id,
        "source_type": "odpt",
        "operator_id": operator_id,
        "operator_odpt_id": operator_id,
        "snapshot_dir": str(snapshot_dir),
        "stored_files": stored_files,
        "fetched_counts": fetched_counts,
        "resources": resource_entries,
        "warnings": warnings,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Load raw snapshot from file  (used by normalize step)
# ---------------------------------------------------------------------------


def load_raw_resource(snapshot_dir: Path, resource_name: str) -> Any:
    """
    Load a raw ODPT resource from the snapshot directory.
    Returns the parsed JSON (list or dict).  Use only for normalize step,
    never to build API responses.
    """
    filename = ODPT_RESOURCE_FILE_MAP.get(resource_name)
    if filename is None:
        raise ValueError(f"Unknown ODPT resource: {resource_name}")
    path = snapshot_dir / filename
    if not path.exists():
        raise FileNotFoundError(f"Raw snapshot file not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_manifest(snapshot_dir: Path) -> Dict[str, Any]:
    """Load the manifest.json from a snapshot directory."""
    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    with manifest_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def list_snapshots() -> List[Dict[str, Any]]:
    """List all raw ODPT snapshots from the cache directory."""
    cache_dir = _cache_base_dir()
    if not cache_dir.exists():
        return []

    snapshots: List[Dict[str, Any]] = []
    for entry in sorted(cache_dir.iterdir(), reverse=True):
        if not entry.is_dir():
            continue
        manifest_path = entry / "manifest.json"
        if manifest_path.exists():
            try:
                with manifest_path.open("r", encoding="utf-8") as f:
                    manifest = json.load(f)
                snapshots.append(manifest)
            except Exception:
                _log.warning("Failed to read manifest: %s", manifest_path)
    return snapshots
