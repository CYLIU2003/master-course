"""
src.tokyubus_gtfs — Tokyu Bus ODPT-to-GTFS pipeline.

4-layer architecture:
  Layer A: Raw ODPT archive (immutable snapshots)
  Layer B: Canonical transit model (normalised internal schema)
  Layer C: GTFS export (standard feed + sidecar files)
  Layer D: Research feature store (trip chains, energy, deadhead)

Usage:
    python -m src.tokyubus_gtfs --help
"""

__version__ = "0.1.0"
