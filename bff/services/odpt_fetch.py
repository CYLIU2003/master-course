"""
bff/services/odpt_fetch.py

Streaming download of ODPT resources directly from api.odpt.org.
Saves raw JSON to the server-side snapshot directory and returns only
metadata (counts, hashes, file paths).  Never loads the full payload
into memory or returns it through an API response.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _consumer_key() -> str:
    """Read the ODPT consumer key from environment variables only."""
    key = os.environ.get("ODPT_CONSUMER_KEY") or os.environ.get("ODPT_TOKEN")
    if not key:
        raise RuntimeError(
            "ODPT_CONSUMER_KEY (or ODPT_TOKEN) environment variable is not set. "
            "Set it in your .env or system environment."
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
) -> str:
    """Build an ODPT API endpoint URL for a given resource."""
    params = {
        "odpt:operator": operator_id,
        "acl:consumerKey": consumer_key,
    }
    return f"{ODPT_API_BASE}/{resource_name}?{urlencode(params)}"


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
    safe_url = url.split("acl:consumerKey=")[0] + "acl:consumerKey=***"
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
