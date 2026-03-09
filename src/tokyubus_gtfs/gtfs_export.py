"""
src.tokyubus_gtfs.gtfs_export — Layer C: GTFS feed writer.

Reads canonical JSONL tables and writes a standard GTFS feed
plus sidecar files for metadata that GTFS cannot represent.

Output directory::

    GTFS/TokyuBus-GTFS/
        agency.txt
        stops.txt
        routes.txt
        trips.txt
        stop_times.txt
        calendar.txt
        feed_info.txt
        # sidecar files
        sidecar_route_patterns.json
        sidecar_stop_metadata.json
        sidecar_odpt_provenance.json
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.feed_identity import (
    TOKYU_ODPT_GTFS_FEED_ID,
    build_dataset_id,
    build_feed_metadata,
)

from .constants import (
    GTFS_FEED_LANG,
    GTFS_FEED_PUBLISHER_NAME,
    GTFS_FEED_PUBLISHER_URL,
    GTFS_FEED_TIMEZONE,
    GTFS_OUTPUT_DIR,
    TOKYU_OPERATOR_ID,
    TOKYU_OPERATOR_NAME,
    TOKYU_OPERATOR_NAME_EN,
    TOKYU_OPERATOR_URL,
)

_log = logging.getLogger(__name__)


def _write_csv(rows: List[Dict[str, Any]], path: Path, fieldnames: List[str]) -> int:
    """Write a list of dicts as a CSV file (GTFS standard)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    items = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload if isinstance(payload, dict) else {}


def _is_truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return default


def _build_route_pattern_lookup(canonical_dir: Path) -> Dict[str, Dict[str, Any]]:
    return {
        str(item.get("pattern_id") or ""): item
        for item in _read_jsonl(canonical_dir / "route_patterns.jsonl")
        if item.get("pattern_id")
    }


def _select_public_trips(canonical_dir: Path) -> List[Dict[str, Any]]:
    route_patterns = _build_route_pattern_lookup(canonical_dir)
    public_trips: List[Dict[str, Any]] = []
    for trip in _read_jsonl(canonical_dir / "trips.jsonl"):
        trip_role = str(trip.get("trip_role") or "service").strip().lower()
        if trip_role == "deadhead":
            continue
        pattern_id = str(trip.get("pattern_id") or "")
        pattern = route_patterns.get(pattern_id, {})
        include_in_public_gtfs = _is_truthy(
            pattern.get("include_in_public_gtfs"),
            _is_truthy(trip.get("is_public_trip"), True),
        )
        if not include_in_public_gtfs:
            continue
        public_trips.append(trip)
    return public_trips


# ---------------------------------------------------------------------------
# GTFS file writers
# ---------------------------------------------------------------------------


def _write_agency(out_dir: Path) -> None:
    rows = [
        {
            "agency_id": TOKYU_OPERATOR_ID,
            "agency_name": TOKYU_OPERATOR_NAME,
            "agency_url": TOKYU_OPERATOR_URL,
            "agency_timezone": GTFS_FEED_TIMEZONE,
            "agency_lang": GTFS_FEED_LANG,
        }
    ]
    _write_csv(
        rows,
        out_dir / "agency.txt",
        [
            "agency_id",
            "agency_name",
            "agency_url",
            "agency_timezone",
            "agency_lang",
        ],
    )


def _write_feed_info(out_dir: Path) -> None:
    rows = [
        {
            "feed_publisher_name": GTFS_FEED_PUBLISHER_NAME,
            "feed_publisher_url": GTFS_FEED_PUBLISHER_URL,
            "feed_lang": GTFS_FEED_LANG,
        }
    ]
    _write_csv(
        rows,
        out_dir / "feed_info.txt",
        [
            "feed_publisher_name",
            "feed_publisher_url",
            "feed_lang",
        ],
    )


def _write_feed_metadata(canonical_dir: Path, out_dir: Path) -> Dict[str, Any]:
    canonical_summary = _read_json(canonical_dir / "canonical_summary.json")
    snapshot_id = str(canonical_summary.get("snapshot_id") or canonical_dir.name)
    generated_at = datetime.now(timezone.utc).isoformat()
    metadata = build_feed_metadata(
        feed_id=TOKYU_ODPT_GTFS_FEED_ID,
        snapshot_id=snapshot_id,
        generated_at=generated_at,
        source_type="odpt_json",
        operator="TokyuBus",
        extra={
            "dataset_id": build_dataset_id(TOKYU_ODPT_GTFS_FEED_ID, snapshot_id),
            "canonical_dir": str(canonical_dir),
            "gtfs_dir": str(out_dir),
            "raw_archive_path": canonical_summary.get("raw_archive_path"),
        },
    )
    path = out_dir / "feed_metadata.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    _log.info("Wrote feed_metadata.json")
    return metadata


def _export_stops(canonical_dir: Path, out_dir: Path) -> int:
    stops = _read_jsonl(canonical_dir / "stops.jsonl")
    rows = []
    for s in stops:
        rows.append(
            {
                "stop_id": s.get("stop_id", ""),
                "stop_code": s.get("stop_code", ""),
                "stop_name": s.get("stop_name", ""),
                "stop_lat": s.get("lat") or "",
                "stop_lon": s.get("lon") or "",
            }
        )
    count = _write_csv(
        rows,
        out_dir / "stops.txt",
        [
            "stop_id",
            "stop_code",
            "stop_name",
            "stop_lat",
            "stop_lon",
        ],
    )
    _log.info("Exported %d stops to stops.txt", count)
    return count


def _export_routes(canonical_dir: Path, out_dir: Path) -> int:
    routes = _read_jsonl(canonical_dir / "routes.jsonl")
    public_route_ids = {
        str(trip.get("route_id") or "")
        for trip in _select_public_trips(canonical_dir)
        if trip.get("route_id")
    }
    rows = []
    for r in routes:
        route_id = str(r.get("route_id") or "")
        if route_id not in public_route_ids:
            continue
        color = (r.get("route_color") or "").lstrip("#")
        rows.append(
            {
                "route_id": route_id,
                "agency_id": TOKYU_OPERATOR_ID,
                "route_short_name": r.get("route_code", ""),
                "route_long_name": r.get("route_name", ""),
                "route_type": r.get("route_type", 3),
                "route_color": color,
            }
        )
    count = _write_csv(
        rows,
        out_dir / "routes.txt",
        [
            "route_id",
            "agency_id",
            "route_short_name",
            "route_long_name",
            "route_type",
            "route_color",
        ],
    )
    _log.info("Exported %d routes to routes.txt", count)
    return count


def _export_calendar(canonical_dir: Path, out_dir: Path) -> int:
    services = _read_jsonl(canonical_dir / "services.jsonl")
    rows = []
    for s in services:
        rows.append(
            {
                "service_id": s.get("service_id", ""),
                "monday": int(s.get("monday", False)),
                "tuesday": int(s.get("tuesday", False)),
                "wednesday": int(s.get("wednesday", False)),
                "thursday": int(s.get("thursday", False)),
                "friday": int(s.get("friday", False)),
                "saturday": int(s.get("saturday", False)),
                "sunday": int(s.get("sunday", False)),
                "start_date": (s.get("start_date") or "20250401").replace("-", ""),
                "end_date": (s.get("end_date") or "20260331").replace("-", ""),
            }
        )
    count = _write_csv(
        rows,
        out_dir / "calendar.txt",
        [
            "service_id",
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
            "start_date",
            "end_date",
        ],
    )
    _log.info("Exported %d service calendars to calendar.txt", count)
    return count


def _export_trips(canonical_dir: Path, out_dir: Path) -> int:
    trips = _select_public_trips(canonical_dir)
    rows = []
    for t in trips:
        direction_id = t.get("direction_id")
        if direction_id is None:
            direction_id = 0 if t.get("direction") == "outbound" else 1
        rows.append(
            {
                "route_id": t.get("route_id", ""),
                "service_id": t.get("service_id", ""),
                "trip_id": t.get("trip_id", ""),
                "direction_id": direction_id,
                "trip_headsign": t.get("destination_name", ""),
                "shape_id": t.get("shape_id", ""),
            }
        )
    count = _write_csv(
        rows,
        out_dir / "trips.txt",
        [
            "route_id",
            "service_id",
            "trip_id",
            "direction_id",
            "trip_headsign",
            "shape_id",
        ],
    )
    _log.info("Exported %d trips to trips.txt", count)
    return count


def _export_stop_times(canonical_dir: Path, out_dir: Path) -> int:
    public_trip_ids = {
        str(trip.get("trip_id") or "")
        for trip in _select_public_trips(canonical_dir)
    }
    stop_times = _read_jsonl(canonical_dir / "stop_times.jsonl")
    rows = []
    for st in stop_times:
        if str(st.get("trip_id") or "") not in public_trip_ids:
            continue
        rows.append(
            {
                "trip_id": st.get("trip_id", ""),
                "arrival_time": st.get("arrival_time")
                or st.get("departure_time")
                or "",
                "departure_time": st.get("departure_time")
                or st.get("arrival_time")
                or "",
                "stop_id": st.get("stop_id", ""),
                "stop_sequence": st.get("stop_sequence", 0),
            }
        )
    count = _write_csv(
        rows,
        out_dir / "stop_times.txt",
        [
            "trip_id",
            "arrival_time",
            "departure_time",
            "stop_id",
            "stop_sequence",
        ],
    )
    _log.info("Exported %d stop_times to stop_times.txt", count)
    return count


def _export_calendar_dates(canonical_dir: Path, out_dir: Path) -> int:
    """
    Export ``calendar_dates.txt`` for service exceptions.

    Currently ODPT does not provide per-date exceptions, so this generates
    a minimal placeholder file.  Future versions may populate it from
    BusTimetable calendar annotations.
    """
    # Placeholder: no exceptions yet — write header-only CSV
    rows: List[Dict[str, Any]] = []
    count = _write_csv(
        rows,
        out_dir / "calendar_dates.txt",
        ["service_id", "date", "exception_type"],
    )
    _log.info("Exported %d calendar_dates to calendar_dates.txt", count)
    return count


def _export_shapes(canonical_dir: Path, out_dir: Path) -> int:
    """
    Export ``shapes.txt`` from route stop sequences.

    Approximates shapes from the ordered stop coordinates of each route.
    This is a basic stop-to-stop polyline; proper shapes would require
    GTFS shapes or GPS trace data that ODPT does not provide.
    """
    shape_points = _read_jsonl(canonical_dir / "shapes.jsonl")
    public_shape_ids = {
        str(trip.get("shape_id") or "")
        for trip in _select_public_trips(canonical_dir)
        if trip.get("shape_id")
    }
    rows: List[Dict[str, Any]] = []
    for point in sorted(
        [point for point in shape_points if point.get("shape_id") in public_shape_ids],
        key=lambda item: (
            str(item.get("shape_id") or ""),
            int(item.get("shape_pt_sequence") or 0),
        ),
    ):
        rows.append(
            {
                "shape_id": point.get("shape_id", ""),
                "shape_pt_lat": point.get("shape_pt_lat", ""),
                "shape_pt_lon": point.get("shape_pt_lon", ""),
                "shape_pt_sequence": point.get("shape_pt_sequence", 0),
                "shape_dist_traveled": point.get("shape_dist_traveled_km", ""),
            }
        )

    count = _write_csv(
        rows,
        out_dir / "shapes.txt",
        [
            "shape_id",
            "shape_pt_lat",
            "shape_pt_lon",
            "shape_pt_sequence",
            "shape_dist_traveled",
        ],
    )
    _log.info("Exported %d shape points to shapes.txt", count)
    return count


# ---------------------------------------------------------------------------
# Sidecar files (ODPT metadata GTFS cannot represent)
# ---------------------------------------------------------------------------


def _write_sidecar_route_patterns(canonical_dir: Path, out_dir: Path) -> int:
    """Sidecar: full route pattern / variant metadata."""
    route_patterns = _read_jsonl(canonical_dir / "route_patterns.jsonl")
    route_stops = _read_jsonl(canonical_dir / "route_stops.jsonl")

    stops_by_pattern: Dict[str, List[Dict[str, Any]]] = {}
    for rs in route_stops:
        pattern_id = rs.get("pattern_id", "")
        stops_by_pattern.setdefault(pattern_id, []).append(rs)

    patterns = []
    for r in route_patterns:
        pattern_id = r.get("pattern_id", "")
        patterns.append(
            {
                "pattern_id": pattern_id,
                "route_id": r.get("route_id", ""),
                "odpt_pattern_id": r.get("odpt_pattern_id", ""),
                "odpt_busroute_id": r.get("odpt_busroute_id", ""),
                "route_short_name_hint": r.get("route_short_name_hint", ""),
                "route_long_name_hint": r.get("route_long_name_hint", ""),
                "pattern_role": r.get("pattern_role", "unknown"),
                "direction_bucket": r.get("direction_bucket"),
                "shape_id": r.get("shape_id", ""),
                "include_in_public_gtfs": r.get("include_in_public_gtfs", True),
                "classification_confidence": r.get("classification_confidence", 0.0),
                "classification_reasons": r.get("classification_reasons", []),
                "stop_sequence": [
                    s.get("stop_id")
                    for s in sorted(
                        stops_by_pattern.get(pattern_id, []),
                        key=lambda x: x.get("stop_sequence", 0),
                    )
                ],
            }
        )

    path = out_dir / "sidecar_route_patterns.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(patterns, f, ensure_ascii=False, indent=2)
    _log.info("Wrote sidecar_route_patterns.json (%d entries)", len(patterns))
    return len(patterns)


def _write_sidecar_stop_metadata(canonical_dir: Path, out_dir: Path) -> int:
    """Sidecar: stop coordinate provenance and ODPT metadata."""
    stops = _read_jsonl(canonical_dir / "stops.jsonl")
    meta = []
    for s in stops:
        meta.append(
            {
                "stop_id": s.get("stop_id", ""),
                "odpt_id": s.get("odpt_id", ""),
                "coord_source_type": s.get("coord_source_type", "unknown"),
                "coord_confidence": s.get("coord_confidence", 0.0),
                "pole_number": s.get("pole_number"),
            }
        )

    path = out_dir / "sidecar_stop_metadata.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    _log.info("Wrote sidecar_stop_metadata.json (%d entries)", len(meta))
    return len(meta)


def _write_sidecar_trip_odpt_extra(canonical_dir: Path, out_dir: Path) -> int:
    trips = _read_jsonl(canonical_dir / "trips.jsonl")
    payload = []
    for trip in trips:
        payload.append(
            {
                "trip_id": trip.get("trip_id", ""),
                "pattern_id": trip.get("pattern_id", ""),
                "odpt_timetable_id": trip.get("odpt_timetable_id", ""),
                "odpt_pattern_id": trip.get("odpt_pattern_id", ""),
                "odpt_calendar_raw": trip.get("odpt_calendar_raw", ""),
                "allowed_vehicle_types": trip.get("allowed_vehicle_types") or [],
                "trip_category": trip.get("trip_category", "revenue"),
                "trip_role": trip.get("trip_role", "service"),
                "is_public_trip": trip.get("is_public_trip", True),
            }
        )
    path = out_dir / "sidecar_trip_odpt_extra.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    _log.info("Wrote sidecar_trip_odpt_extra.json (%d entries)", len(payload))
    return len(payload)


def _write_sidecar_stop_pole_map(canonical_dir: Path, out_dir: Path) -> int:
    stop_poles = _read_jsonl(canonical_dir / "stop_poles.jsonl")
    payload = []
    for stop_pole in stop_poles:
        payload.append(
            {
                "stop_pole_id": stop_pole.get("stop_pole_id", ""),
                "stop_id": stop_pole.get("stop_id", ""),
                "stop_name": stop_pole.get("stop_name", ""),
                "pole_number": stop_pole.get("pole_number"),
                "odpt_id": stop_pole.get("odpt_id", ""),
            }
        )
    path = out_dir / "sidecar_stop_pole_map.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    _log.info("Wrote sidecar_stop_pole_map.json (%d entries)", len(payload))
    return len(payload)


def _write_sidecar_snapshot_manifest(canonical_dir: Path, out_dir: Path) -> int:
    summary_path = canonical_dir / "canonical_summary.json"
    payload: Dict[str, Any] = {
        "canonical_summary": {},
        "raw_snapshot_manifest": {},
    }
    if summary_path.exists():
        with summary_path.open("r", encoding="utf-8") as f:
            payload["canonical_summary"] = json.load(f)
        raw_archive_path = payload["canonical_summary"].get("raw_archive_path")
        if raw_archive_path:
            manifest_path = Path(raw_archive_path) / "manifest.json"
            if manifest_path.exists():
                with manifest_path.open("r", encoding="utf-8") as f:
                    payload["raw_snapshot_manifest"] = json.load(f)
    path = out_dir / "sidecar_snapshot_manifest.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    _log.info("Wrote sidecar_snapshot_manifest.json")
    return 1


# ---------------------------------------------------------------------------
# Main export function
# ---------------------------------------------------------------------------


def export_gtfs(
    canonical_dir: Path,
    *,
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Export canonical tables to a GTFS feed directory.

    Parameters
    ----------
    canonical_dir
        Directory containing canonical JSONL files.
    out_dir
        Output directory for the GTFS feed.
        Defaults to ``GTFS/TokyuBus-GTFS/``.

    Returns
    -------
    dict
        Export summary with file counts.
    """
    if out_dir is None:
        out_dir = GTFS_OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    _log.info("Exporting GTFS feed to %s …", out_dir)

    _write_agency(out_dir)
    _write_feed_info(out_dir)
    feed_metadata = _write_feed_metadata(canonical_dir, out_dir)
    n_stops = _export_stops(canonical_dir, out_dir)
    n_routes = _export_routes(canonical_dir, out_dir)
    n_cal = _export_calendar(canonical_dir, out_dir)
    n_trips = _export_trips(canonical_dir, out_dir)
    n_st = _export_stop_times(canonical_dir, out_dir)

    n_cd = _export_calendar_dates(canonical_dir, out_dir)
    n_shapes = _export_shapes(canonical_dir, out_dir)

    # Sidecar files
    sidecars = {
        "route_patterns": _write_sidecar_route_patterns(canonical_dir, out_dir),
        "stop_metadata": _write_sidecar_stop_metadata(canonical_dir, out_dir),
        "trip_odpt_extra": _write_sidecar_trip_odpt_extra(canonical_dir, out_dir),
        "stop_pole_map": _write_sidecar_stop_pole_map(canonical_dir, out_dir),
        "snapshot_manifest": _write_sidecar_snapshot_manifest(canonical_dir, out_dir),
    }

    summary = {
        "gtfs_dir": str(out_dir),
        "stops": n_stops,
        "routes": n_routes,
        "calendars": n_cal,
        "calendar_dates": n_cd,
        "trips": n_trips,
        "stop_times": n_st,
        "shapes": n_shapes,
        "sidecars": sidecars,
        "feed_metadata": feed_metadata,
    }
    _log.info("GTFS export complete: %s", summary)
    return summary
