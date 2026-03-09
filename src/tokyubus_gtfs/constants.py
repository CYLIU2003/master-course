"""
src.tokyubus_gtfs.constants — Pipeline-wide constants.

These are internal defaults for the pipeline.  Never modify at runtime.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Directory layout
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]

RAW_ARCHIVE_DIR = _REPO_ROOT / "data" / "tokyubus" / "raw"
CANONICAL_DIR = _REPO_ROOT / "data" / "tokyubus" / "canonical"
FEATURES_DIR = _REPO_ROOT / "data" / "tokyubus" / "features"
GTFS_OUTPUT_DIR = _REPO_ROOT / "GTFS" / "TokyuBus-GTFS"
SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"

# ---------------------------------------------------------------------------
# ODPT operator identifiers
# ---------------------------------------------------------------------------

TOKYU_OPERATOR_ID = "odpt.Operator:TokyuBus"
TOKYU_OPERATOR_NAME = "東急バス"
TOKYU_OPERATOR_NAME_EN = "Tokyu Bus"
TOKYU_OPERATOR_URL = "https://www.tokyubus.co.jp/"

# ---------------------------------------------------------------------------
# ODPT resource types consumed
# ---------------------------------------------------------------------------

ODPT_RESOURCE_TYPES = (
    "odpt:BusstopPole",
    "odpt:BusroutePattern",
    "odpt:BusTimetable",
    "odpt:BusstopPoleTimetable",
)

# ---------------------------------------------------------------------------
# Service-day mapping (ODPT calendar → GTFS service_id)
# ---------------------------------------------------------------------------

CALENDAR_MAP: dict[str, str] = {
    "weekday": "WEEKDAY",
    "saturday": "SAT",
    "holiday": "SUN_HOL",
    "sunday": "SUN_HOL",
    "unknown": "WEEKDAY",
}

# ---------------------------------------------------------------------------
# Default turnaround / dwell
# ---------------------------------------------------------------------------

DEFAULT_TURNAROUND_SEC = 180  # 3 min turnaround at terminals
DEFAULT_DWELL_SEC = 30  # 0.5 min per stop
DEFAULT_DEADHEAD_SPEED_KMH = 20.0  # assumed deadhead average speed

# ---------------------------------------------------------------------------
# Coordinate quality thresholds
# ---------------------------------------------------------------------------

TOKYO_LAT_RANGE = (35.0, 36.0)
TOKYO_LON_RANGE = (139.0, 140.5)

# ---------------------------------------------------------------------------
# GTFS feed metadata
# ---------------------------------------------------------------------------

GTFS_FEED_PUBLISHER_NAME = "master-course pipeline"
GTFS_FEED_PUBLISHER_URL = "https://github.com/master-course"
GTFS_FEED_LANG = "ja"
GTFS_FEED_TIMEZONE = "Asia/Tokyo"
