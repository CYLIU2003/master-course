"""
src.tokyubus_gtfs.odpt_client — ODPT data source adapter.

Bridges the tokyubus-gtfs pipeline to the existing ODPT fetch
infrastructure in ``bff/services/odpt_fetch.py`` and
``tools/fast_catalog_ingest.py``.

This adapter does NOT reimplement ODPT HTTP calls.  It delegates to the
existing fetch functions and writes raw JSON into a staging directory that
can be consumed by ``archive_raw_snapshot()``.

Usage::

    from src.tokyubus_gtfs.odpt_client import fetch_raw_odpt

    staging_dir = fetch_raw_odpt(out_dir=Path("./data/staging"))
    manifest = archive_raw_snapshot(staging_dir)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .constants import ODPT_RESOURCE_TYPES, TOKYU_OPERATOR_ID
from .archive import _candidate_paths

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Resource type → ODPT API endpoint key mapping
# ---------------------------------------------------------------------------

_RESOURCE_TO_ENDPOINT: Dict[str, str] = {
    "odpt:BusstopPole": "odpt:BusstopPole",
    "odpt:BusroutePattern": "odpt:BusroutePattern",
    "odpt:BusTimetable": "odpt:BusTimetable",
    "odpt:BusstopPoleTimetable": "odpt:BusstopPoleTimetable",
}


def _resource_filename(resource_type: str) -> str:
    """Convert ``'odpt:BusstopPole'`` → ``'odpt_BusstopPole.json'``."""
    return resource_type.replace(":", "_") + ".json"


# ---------------------------------------------------------------------------
# Fetch via bff.services.odpt_fetch (sync, small-scale)
# ---------------------------------------------------------------------------


def _fetch_via_bff(
    resource_type: str,
    *,
    operator: str,
) -> List[Dict[str, Any]]:
    """
    Fetch a single ODPT resource using the BFF ODPT service.

    Falls back to an empty list if the BFF service is unavailable.
    """
    try:
        from bff.services.odpt_fetch import fetch_odpt_resource

        return fetch_odpt_resource(resource_type, operator=operator)
    except ImportError:
        _log.warning(
            "bff.services.odpt_fetch not available — cannot fetch %s",
            resource_type,
        )
        return []
    except Exception as exc:
        _log.error("Failed to fetch %s: %s", resource_type, exc)
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fetch_raw_odpt(
    *,
    out_dir: Path,
    operator: str = TOKYU_OPERATOR_ID,
    resource_types: tuple[str, ...] = ODPT_RESOURCE_TYPES,
    use_fast_ingest: bool = False,
    fast_ingest_concurrency: int = 32,
) -> Path:
    """
    Download raw ODPT JSON for all resource types into *out_dir*.

    Parameters
    ----------
    out_dir
        Directory to write raw JSON files into (staging area).
    operator
        ODPT operator identifier.
    resource_types
        Which ODPT resource types to fetch.
    use_fast_ingest
        If True, delegate to ``tools.fast_catalog_ingest`` for async download.
    fast_ingest_concurrency
        Concurrency level for fast_catalog_ingest.

    Returns
    -------
    Path
        The *out_dir* path (ready for ``archive_raw_snapshot``).
    """
    out_dir.mkdir(parents=True, exist_ok=True)

    if use_fast_ingest:
        return _fetch_via_fast_ingest(
            out_dir=out_dir,
            concurrency=fast_ingest_concurrency,
        )

    # Standard BFF fetch path
    for rtype in resource_types:
        _log.info("Fetching %s for %s …", rtype, operator)
        records = _fetch_via_bff(rtype, operator=operator)

        fname = _resource_filename(rtype)
        dest = out_dir / fname
        with dest.open("w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

        _log.info("Wrote %d records → %s", len(records), dest)

    return out_dir


def _fetch_via_fast_ingest(
    *,
    out_dir: Path,
    concurrency: int,
) -> Path:
    """
    Delegate to ``tools.fast_catalog_ingest`` for high-throughput download.

    The fast ingest tool writes NDJSON files, which ``archive_raw_snapshot``
    can read natively.
    """
    try:
        from tools import fast_catalog_ingest

        args = [
            "fetch-odpt",
            "--out-dir",
            str(out_dir),
            "--concurrency",
            str(concurrency),
            "--build-bundle",
        ]
        rc = fast_catalog_ingest.main(args)
        if rc != 0:
            _log.warning("fast_catalog_ingest returned non-zero: %d", rc)
    except ImportError:
        _log.error(
            "tools.fast_catalog_ingest not importable — falling back to bff fetch"
        )
        return fetch_raw_odpt(
            out_dir=out_dir,
            use_fast_ingest=False,
        )
    return out_dir


def check_raw_files(
    source_dir: Path,
    resource_types: tuple[str, ...] = ODPT_RESOURCE_TYPES,
) -> Dict[str, bool]:
    """
    Check which raw ODPT files exist in a directory.

    Returns a mapping of resource_type → exists bool.
    """
    result = {}
    for rtype in resource_types:
        result[rtype] = any(path.exists() for path in _candidate_paths(source_dir, rtype))
    return result
