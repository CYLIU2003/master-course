"""
src.tokyubus_gtfs.config — Central path and runtime configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .constants import CANONICAL_DIR, FEATURES_DIR, GTFS_OUTPUT_DIR, RAW_ARCHIVE_DIR


@dataclass(frozen=True)
class PipelinePaths:
    """Filesystem roots used by the Tokyu Bus layered pipeline."""

    raw_archive_root: Path = field(default_factory=lambda: RAW_ARCHIVE_DIR)
    canonical_root: Path = field(default_factory=lambda: CANONICAL_DIR)
    gtfs_output_root: Path = field(default_factory=lambda: GTFS_OUTPUT_DIR)
    features_root: Path = field(default_factory=lambda: FEATURES_DIR)
