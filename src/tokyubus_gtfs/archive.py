"""
src.tokyubus_gtfs.archive — Layer A: Raw ODPT archive writer.

Copies raw ODPT JSON files into an immutable snapshot directory with a
manifest.  Snapshots are never modified after creation.

Directory layout::

    data/tokyubus/raw/
        {snapshot_id}/
            manifest.json
            odpt_BusstopPole.json
            odpt_BusroutePattern.json
            odpt_BusTimetable.json
            odpt_BusstopPoleTimetable.json
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .constants import ODPT_RESOURCE_TYPES, RAW_ARCHIVE_DIR

_log = logging.getLogger(__name__)


def _file_sha256(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _resource_filename(resource_type: str) -> str:
    """Convert 'odpt:BusstopPole' → 'odpt_BusstopPole.json'."""
    return resource_type.replace(":", "_") + ".json"


def create_snapshot_id() -> str:
    """Generate a timestamp-based snapshot ID."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def archive_raw_snapshot(
    source_dir: Path,
    *,
    snapshot_id: Optional[str] = None,
    archive_root: Optional[Path] = None,
    resource_types: tuple[str, ...] = ODPT_RESOURCE_TYPES,
) -> Dict[str, Any]:
    """
    Copy raw ODPT JSON files from *source_dir* into an archive snapshot.

    Parameters
    ----------
    source_dir
        Directory containing raw ODPT JSON files (e.g. from fast_catalog_ingest).
    snapshot_id
        Snapshot identifier.  Auto-generated if not provided.
    archive_root
        Root of the raw archive tree.  Defaults to ``data/tokyubus/raw/``.
    resource_types
        ODPT resource types to look for in *source_dir*.

    Returns
    -------
    dict
        Manifest data including file hashes and counts.
    """
    if snapshot_id is None:
        snapshot_id = create_snapshot_id()
    if archive_root is None:
        archive_root = RAW_ARCHIVE_DIR

    dest = archive_root / snapshot_id
    dest.mkdir(parents=True, exist_ok=True)

    files: List[Dict[str, Any]] = []
    warnings: List[str] = []

    for rtype in resource_types:
        fname = _resource_filename(rtype)
        src_path = source_dir / fname
        # Also try the name the fast_catalog_ingest uses
        if not src_path.exists():
            alt_name = rtype.split(":")[-1] + ".json"
            src_path = source_dir / alt_name
        if not src_path.exists():
            # Try NDJSON variant
            ndjson_name = rtype.split(":")[-1] + ".ndjson"
            src_path = source_dir / ndjson_name
        if not src_path.exists():
            warnings.append(f"Missing raw file for {rtype}")
            _log.warning("Raw file not found for %s in %s", rtype, source_dir)
            continue

        dst_path = dest / fname
        shutil.copy2(src_path, dst_path)
        sha = _file_sha256(dst_path)
        size = dst_path.stat().st_size
        files.append(
            {
                "resource_type": rtype,
                "filename": fname,
                "sha256": sha,
                "size_bytes": size,
            }
        )
        _log.info("Archived %s (%d bytes, sha256=%s…)", fname, size, sha[:12])

    manifest = {
        "snapshot_id": snapshot_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(source_dir),
        "files": files,
        "warnings": warnings,
    }

    manifest_path = dest / "manifest.json"
    with manifest_path.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    _log.info(
        "Archive snapshot %s: %d files, %d warnings",
        snapshot_id,
        len(files),
        len(warnings),
    )
    return manifest


def list_snapshots(archive_root: Optional[Path] = None) -> List[Dict[str, Any]]:
    """
    List all archived snapshots.

    Returns a list of manifest dicts sorted by creation time (newest first).
    """
    root = archive_root or RAW_ARCHIVE_DIR
    if not root.exists():
        return []

    manifests = []
    for manifest_path in sorted(root.glob("*/manifest.json"), reverse=True):
        try:
            with manifest_path.open("r", encoding="utf-8") as f:
                manifests.append(json.load(f))
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning("Cannot read manifest %s: %s", manifest_path, exc)
    return manifests


def load_raw_resource(snapshot_dir: Path, resource_type: str) -> list:
    """
    Load a single raw ODPT resource from a snapshot directory.

    Supports both JSON array files and NDJSON files.
    """
    fname = _resource_filename(resource_type)
    path = snapshot_dir / fname
    if not path.exists():
        alt = resource_type.split(":")[-1] + ".json"
        path = snapshot_dir / alt
    if not path.exists():
        ndjson = resource_type.split(":")[-1] + ".ndjson"
        path = snapshot_dir / ndjson
    if not path.exists():
        raise FileNotFoundError(f"No file for {resource_type} in {snapshot_dir}")

    with path.open("r", encoding="utf-8") as f:
        first_char = f.read(1)
        f.seek(0)
        if first_char == "[":
            return json.load(f)
        # NDJSON
        items = []
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
        return items
