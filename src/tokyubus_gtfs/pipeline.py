"""
src.tokyubus_gtfs.pipeline — Full pipeline orchestrator.

Runs all four layers in sequence:
  A. Archive raw ODPT snapshot
  B. Build canonical model
  C. Export GTFS feed
  D. Build research features
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .archive import (
    archive_raw_snapshot,
    diff_resource_types,
    find_previous_snapshot_manifest,
)
from .canonical import build_canonical
from .config import PipelinePaths
from .constants import CANONICAL_DIR, FEATURES_DIR, GTFS_OUTPUT_DIR, RAW_ARCHIVE_DIR
from .features.depot import build_depot_candidates
from .features.energy import build_energy_features
from .features.trip_chains import build_trip_chains
from .features.stop_distances import build_stop_distance_matrix
from .features.charging_windows import build_charging_windows
from .features.deadhead_candidates import build_deadhead_candidates
from .gtfs_export import export_gtfs

_log = logging.getLogger(__name__)

_GTFS_RELEVANT_RESOURCES = {
    "odpt:BusstopPole",
    "odpt:BusroutePattern",
    "odpt:BusTimetable",
}
_FEATURE_RELEVANT_RESOURCES = {
    "odpt:BusstopPole",
    "odpt:BusroutePattern",
    "odpt:BusTimetable",
}


@dataclass
class PipelineConfig:
    """Configuration for a full pipeline run."""

    source_dir: Path
    snapshot_id: Optional[str] = None
    archive_root: Path = field(default_factory=lambda: RAW_ARCHIVE_DIR)
    canonical_root: Path = field(default_factory=lambda: CANONICAL_DIR)
    gtfs_out_dir: Path = field(default_factory=lambda: GTFS_OUTPUT_DIR)
    features_root: Path = field(default_factory=lambda: FEATURES_DIR)
    skip_archive: bool = False
    skip_gtfs: bool = False
    skip_features: bool = False
    profile: str = "full"
    paths: PipelinePaths = field(default_factory=PipelinePaths)


def _copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(src)
    shutil.copytree(src, dst, dirs_exist_ok=True)


def run_pipeline(config: PipelineConfig) -> Dict[str, Any]:
    """
    Execute the full 4-layer pipeline.

    Returns a combined result dict with summaries from each layer.
    """
    results: Dict[str, Any] = {"warnings": []}

    changed_resources: set[str] = set()
    previous_snapshot_manifest: Optional[Dict[str, Any]] = None
    previous_snapshot_id: Optional[str] = None
    previous_snapshot_dir: Optional[Path] = None

    # -- Layer A: Archive --
    if not config.skip_archive:
        _log.info("=== Layer A: Archiving raw snapshot ===")
        manifest = archive_raw_snapshot(
            config.source_dir,
            snapshot_id=config.snapshot_id,
            archive_root=config.archive_root,
        )
        results["archive"] = manifest
        snapshot_id = manifest["snapshot_id"]
        snapshot_dir = config.archive_root / snapshot_id
        previous_snapshot_manifest = find_previous_snapshot_manifest(
            snapshot_id,
            archive_root=config.archive_root,
        )
        if previous_snapshot_manifest is not None:
            previous_snapshot_id = str(previous_snapshot_manifest.get("snapshot_id") or "")
            previous_snapshot_dir = config.archive_root / previous_snapshot_id
            changed_resources = diff_resource_types(manifest, previous_snapshot_manifest)
        else:
            changed_resources = {
                str(item.get("resource_type") or "")
                for item in manifest.get("files") or []
                if item.get("resource_type")
            }
        results["resource_diff"] = {
            "previous_snapshot_id": previous_snapshot_id,
            "changed_resources": sorted(changed_resources),
            "unchanged": len(changed_resources) == 0,
        }
    else:
        _log.info("=== Layer A: Archive skipped ===")
        snapshot_dir = config.source_dir
        snapshot_id = config.source_dir.name
        changed_resources = set()

    # -- Layer B: Canonical --
    _log.info("=== Layer B: Building canonical model ===")
    canonical_dir = config.canonical_root / snapshot_id
    previous_canonical_dir = (
        config.canonical_root / previous_snapshot_id
        if previous_snapshot_id
        else None
    )
    summary = build_canonical(
        snapshot_dir,
        out_dir=canonical_dir,
        previous_canonical_dir=previous_canonical_dir,
        changed_resources=changed_resources,
    )
    results["canonical"] = summary.model_dump(mode="json")

    # -- Layer C: GTFS Export --
    if not config.skip_gtfs:
        gtfs_changed = bool(changed_resources & _GTFS_RELEVANT_RESOURCES) or previous_snapshot_id is None
        if gtfs_changed or not config.gtfs_out_dir.exists():
            _log.info("=== Layer C: Exporting GTFS feed ===")
            gtfs_result = export_gtfs(canonical_dir, out_dir=config.gtfs_out_dir)
            gtfs_result["skipped"] = False
        else:
            _log.info("=== Layer C: GTFS export skipped (no relevant resource changes) ===")
            gtfs_result = {
                "skipped": True,
                "reason": "no relevant resource changes",
                "changed_resources": sorted(changed_resources),
            }
        results["gtfs"] = gtfs_result
    else:
        _log.info("=== Layer C: GTFS export skipped ===")
        results["gtfs"] = {"skipped": True, "reason": "skip_gtfs"}

    # -- Layer D: Research Features --
    if config.profile == "fast":
        _log.info("=== Layer D: Feature build skipped by fast profile ===")
        results["features"] = {"skipped": True, "reason": "profile=fast"}
    elif not config.skip_features:
        features_dir = config.features_root / snapshot_id
        features_changed = bool(changed_resources & _FEATURE_RELEVANT_RESOURCES) or previous_snapshot_id is None
        if (not features_changed) and previous_snapshot_id:
            previous_features_dir = config.features_root / previous_snapshot_id
            if previous_features_dir.exists():
                _log.info("=== Layer D: Reusing previous feature snapshot ===")
                features_dir.mkdir(parents=True, exist_ok=True)
                _copy_tree(previous_features_dir, features_dir)
                results["features"] = {
                    "skipped": True,
                    "reason": "no relevant resource changes",
                    "reused_from_snapshot": previous_snapshot_id,
                }
            else:
                features_changed = True
        if features_changed:
            _log.info("=== Layer D: Building research features ===")
            features_dir.mkdir(parents=True, exist_ok=True)

            chains = build_trip_chains(canonical_dir, features_dir)
            energy = build_energy_features(canonical_dir, features_dir)
            depot = build_depot_candidates(canonical_dir, features_dir)
            distances = build_stop_distance_matrix(canonical_dir, features_dir)
            charging = build_charging_windows(canonical_dir, features_dir)
            deadhead = build_deadhead_candidates(canonical_dir, features_dir)

            results["features"] = {
                "trip_chains": chains,
                "energy": energy,
                "depot_candidates": depot,
                "stop_distances": distances,
                "charging_windows": charging,
                "deadhead_candidates": deadhead,
                "skipped": False,
            }
    else:
        _log.info("=== Layer D: Feature build skipped ===")
        results["features"] = {"skipped": True, "reason": "skip_features"}

    _log.info("=== Pipeline complete ===")
    return results
