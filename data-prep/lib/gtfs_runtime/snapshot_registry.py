from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.feed_identity import TOKYU_ODPT_GTFS_FEED_ID, build_dataset_id
from src.tokyubus_gtfs.constants import CANONICAL_DIR, FEATURES_DIR, GTFS_OUTPUT_DIR


_FEATURE_FILES = {
    "trip_chains": "trip_chains.jsonl",
    "energy_estimates": "energy_estimates.jsonl",
    "depot_candidates": "depot_candidates.jsonl",
    "stop_distances": "stop_distances.jsonl",
    "charging_windows": "charging_windows.jsonl",
    "deadhead_candidates": "deadhead_candidates.jsonl",
}


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return payload if isinstance(payload, dict) else {}


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def _gtfs_manifest_snapshot_id(gtfs_root: Path) -> Optional[str]:
    manifest_path = gtfs_root / "sidecar_snapshot_manifest.json"
    payload = _read_json(manifest_path)
    canonical_summary = payload.get("canonical_summary") or {}
    snapshot_id = canonical_summary.get("snapshot_id")
    return str(snapshot_id) if snapshot_id else None


def list_tokyubus_snapshots(
    *,
    canonical_root: Path = CANONICAL_DIR,
    features_root: Path = FEATURES_DIR,
    gtfs_root: Path = GTFS_OUTPUT_DIR,
) -> List[Dict[str, Any]]:
    if not canonical_root.exists():
        return []

    gtfs_snapshot_id = _gtfs_manifest_snapshot_id(gtfs_root)
    items: List[Dict[str, Any]] = []
    for canonical_dir in sorted(
        (path for path in canonical_root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
        reverse=True,
    ):
        summary = _read_json(canonical_dir / "canonical_summary.json")
        snapshot_id = str(summary.get("snapshot_id") or canonical_dir.name)
        feature_dir = features_root / snapshot_id
        feature_counts = {
            key: _count_jsonl(feature_dir / filename)
            for key, filename in _FEATURE_FILES.items()
        }
        items.append(
            {
                "feed_id": str(summary.get("feed_id") or TOKYU_ODPT_GTFS_FEED_ID),
                "snapshot_id": snapshot_id,
                "dataset_id": str(
                    summary.get("dataset_id")
                    or build_dataset_id(TOKYU_ODPT_GTFS_FEED_ID, snapshot_id)
                ),
                "canonical_dir": str(canonical_dir),
                "feature_dir": str(feature_dir),
                "raw_archive_path": summary.get("raw_archive_path"),
                "normalised_at": summary.get("normalised_at"),
                "entity_counts": dict(summary.get("entity_counts") or {}),
                "warnings": list(summary.get("warnings") or []),
                "feature_counts": feature_counts,
                "gtfs_export_dir": str(gtfs_root)
                if gtfs_snapshot_id == snapshot_id
                else None,
                "gtfs_export_current": gtfs_snapshot_id == snapshot_id,
            }
        )
    return items


def get_latest_tokyubus_snapshot_id(
    *,
    canonical_root: Path = CANONICAL_DIR,
    features_root: Path = FEATURES_DIR,
    gtfs_root: Path = GTFS_OUTPUT_DIR,
) -> Optional[str]:
    items = list_tokyubus_snapshots(
        canonical_root=canonical_root,
        features_root=features_root,
        gtfs_root=gtfs_root,
    )
    if not items:
        return None
    return str(items[0]["snapshot_id"])
