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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .archive import archive_raw_snapshot
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
    paths: PipelinePaths = field(default_factory=PipelinePaths)


def run_pipeline(config: PipelineConfig) -> Dict[str, Any]:
    """
    Execute the full 4-layer pipeline.

    Returns a combined result dict with summaries from each layer.
    """
    results: Dict[str, Any] = {"warnings": []}

    # -- Layer A: Archive --
    if not config.skip_archive:
        _log.info("=== Layer A: Archiving raw snapshot ===")
        manifest = archive_raw_snapshot(
            config.source_dir,
            snapshot_id=config.snapshot_id,
            archive_root=config.paths.raw_archive_root,
        )
        results["archive"] = manifest
        snapshot_id = manifest["snapshot_id"]
        snapshot_dir = config.paths.raw_archive_root / snapshot_id
    else:
        _log.info("=== Layer A: Archive skipped ===")
        snapshot_dir = config.source_dir
        snapshot_id = config.source_dir.name

    # -- Layer B: Canonical --
    _log.info("=== Layer B: Building canonical model ===")
    canonical_dir = config.paths.canonical_root / snapshot_id
    summary = build_canonical(snapshot_dir, out_dir=canonical_dir)
    results["canonical"] = summary.model_dump(mode="json")

    # -- Layer C: GTFS Export --
    if not config.skip_gtfs:
        _log.info("=== Layer C: Exporting GTFS feed ===")
        gtfs_result = export_gtfs(canonical_dir, out_dir=config.paths.gtfs_output_root)
        results["gtfs"] = gtfs_result
    else:
        _log.info("=== Layer C: GTFS export skipped ===")

    # -- Layer D: Research Features --
    if not config.skip_features:
        _log.info("=== Layer D: Building research features ===")
        features_dir = config.paths.features_root / snapshot_id
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
        }
    else:
        _log.info("=== Layer D: Feature build skipped ===")

    _log.info("=== Pipeline complete ===")
    return results
