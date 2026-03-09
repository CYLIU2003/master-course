"""
src.tokyubus_gtfs.canonical — Layer B: Canonical transit model builder.

Orchestrates all normalizers and writes canonical JSONL tables to disk.
This is the main entry point for the normalization pipeline.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .archive import load_raw_resource
from .constants import (
    CANONICAL_DIR,
    TOKYU_OPERATOR_ID,
    TOKYU_OPERATOR_NAME,
    TOKYU_OPERATOR_NAME_EN,
    TOKYU_OPERATOR_URL,
)
from .models import (
    CanonicalShapePoint,
    CanonicalRoute,
    CanonicalRouteStop,
    CanonicalService,
    CanonicalStop,
    CanonicalStopPole,
    CanonicalStopTimetable,
    CanonicalTrip,
    CanonicalTripStopTime,
    NormalizationSummary,
    Operator,
    SourceLineage,
)
from .normalizers.routes import normalize_busroute_patterns
from .normalizers.services import build_service_calendars
from .normalizers.stop_timetables import normalize_busstop_pole_timetables
from .normalizers.stops import normalize_busstop_poles
from .normalizers.trips import normalize_bus_timetables

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSONL I/O helpers
# ---------------------------------------------------------------------------


def _write_jsonl(items: list, path: Path) -> int:
    """Serialise a list of Pydantic models (or dicts) to JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            if hasattr(item, "model_dump"):
                obj = item.model_dump(mode="json")
            elif hasattr(item, "dict"):
                obj = item.dict()
            else:
                obj = item
            f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


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


def _build_shape_points(
    route_stops: List[CanonicalRouteStop],
    stop_lookup: Dict[str, Dict[str, Any]],
) -> List[CanonicalShapePoint]:
    by_route: Dict[str, List[CanonicalRouteStop]] = {}
    for route_stop in route_stops:
        by_route.setdefault(route_stop.route_id, []).append(route_stop)

    shape_points: List[CanonicalShapePoint] = []
    for route_id, items in by_route.items():
        shape_id = f"shape_{route_id}"
        for item in sorted(items, key=lambda route_stop: route_stop.stop_sequence):
            stop_meta = stop_lookup.get(item.stop_id, {})
            lat = stop_meta.get("lat")
            lon = stop_meta.get("lon")
            if lat is None or lon is None:
                continue
            shape_points.append(
                CanonicalShapePoint(
                    shape_id=shape_id,
                    shape_pt_sequence=item.stop_sequence,
                    shape_pt_lat=float(lat),
                    shape_pt_lon=float(lon),
                    shape_dist_traveled_km=round(
                        float(item.distance_from_start_m or 0.0) / 1000.0, 3
                    ),
                    route_id=route_id,
                    stop_id=item.stop_id,
                )
            )
    return shape_points


def _build_source_lineage(
    snapshot_dir: Path,
    snapshot_name: str,
    entity_counts: Dict[str, int],
) -> List[SourceLineage]:
    manifest_path = snapshot_dir / "manifest.json"
    generated_at = datetime.now(timezone.utc).isoformat()
    manifest = {}
    if manifest_path.exists():
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
    files = manifest.get("files") or []
    file_by_resource = {
        str(item.get("resource_type") or ""): item
        for item in files
        if item.get("resource_type")
    }
    table_to_resource = {
        "stops": "odpt:BusstopPole",
        "stop_poles": "odpt:BusstopPole",
        "routes": "odpt:BusroutePattern",
        "route_stops": "odpt:BusroutePattern",
        "trips": "odpt:BusTimetable",
        "stop_times": "odpt:BusTimetable",
        "services": "odpt:BusTimetable",
        "stop_timetables": "odpt:BusstopPoleTimetable",
    }
    lineage: List[SourceLineage] = []
    for table_name, resource_type in table_to_resource.items():
        resource_meta = file_by_resource.get(resource_type, {})
        source_filename = str(resource_meta.get("filename") or "")
        lineage.append(
            SourceLineage(
                table_name=table_name,
                source_type="odpt_raw",
                source_path=str(snapshot_dir / source_filename) if source_filename else "",
                resource_type=resource_type,
                snapshot_id=snapshot_name,
                record_count=int(entity_counts.get(table_name, 0)),
                sha256=str(resource_meta.get("sha256") or ""),
                generated_at=generated_at,
            )
        )
    return lineage


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def reconcile(out_dir: Path) -> Dict[str, Any]:
    """
    Cross-check canonical entities for referential consistency.
    """
    warnings: List[str] = []

    stops_data = _read_jsonl(out_dir / "stops.jsonl")
    routes_data = _read_jsonl(out_dir / "routes.jsonl")
    trips_data = _read_jsonl(out_dir / "trips.jsonl")
    route_stops_data = _read_jsonl(out_dir / "route_stops.jsonl")

    stop_ids = {s["stop_id"] for s in stops_data if s.get("stop_id")}
    route_ids = {r["route_id"] for r in routes_data if r.get("route_id")}

    # Stops referenced in route_stops but missing from stops table
    missing_stops = set()
    for rs in route_stops_data:
        sid = rs.get("stop_id")
        if sid and sid not in stop_ids:
            missing_stops.add(sid)
    if missing_stops:
        warnings.append(
            f"{len(missing_stops)} stop(s) in route patterns not in BusstopPole data"
        )

    # Routes referenced in trips but missing from routes table
    trip_route_ids = {t.get("route_id") for t in trips_data if t.get("route_id")}
    orphan = trip_route_ids - route_ids
    if orphan:
        warnings.append(
            f"{len(orphan)} route(s) in timetables not in BusroutePattern data"
        )

    return {
        "route_count": len(routes_data),
        "stop_count": len(stops_data),
        "trip_count": len(trips_data),
        "missing_stop_count": len(missing_stops),
        "orphan_route_count": len(orphan),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Full canonical build
# ---------------------------------------------------------------------------


def build_canonical(
    snapshot_dir: Path,
    *,
    out_dir: Optional[Path] = None,
) -> NormalizationSummary:
    """
    Run the complete ODPT → Canonical pipeline for a single snapshot.

    Steps:
      1. Normalize BusstopPole → stops
      2. Normalize BusroutePattern → routes, route_stops
      3. Normalize BusTimetable → trips, stop_times
      4. Build service calendars
      5. Normalize BusstopPoleTimetable → stop_timetables
      6. Reconcile
      7. Write summary

    Parameters
    ----------
    snapshot_dir
        Directory containing raw ODPT JSON files (Layer A snapshot).
    out_dir
        Output directory for canonical JSONL.  Defaults to
        ``data/tokyubus/canonical/{snapshot_name}/``.

    Returns
    -------
    NormalizationSummary
        Summary including entity counts, warnings, and paths.
    """
    snapshot_name = snapshot_dir.name
    if out_dir is None:
        out_dir = CANONICAL_DIR / snapshot_name
    out_dir.mkdir(parents=True, exist_ok=True)

    all_warnings: List[str] = []

    # -- 1. Stops --
    _log.info("Step 1/6: Normalizing BusstopPole …")
    try:
        raw_stops = load_raw_resource(snapshot_dir, "odpt:BusstopPole")
    except FileNotFoundError:
        raw_stops = []
        all_warnings.append("BusstopPole raw file not found")

    stops, stop_lookup, w = normalize_busstop_poles(raw_stops)
    all_warnings.extend(w)
    _write_jsonl(stops, out_dir / "stops.jsonl")
    stop_poles = [
        CanonicalStopPole(
            stop_pole_id=stop.stop_id,
            stop_id=stop.stop_id,
            stop_name=stop.stop_name,
            pole_number=stop.pole_number,
            lat=stop.lat,
            lon=stop.lon,
            odpt_id=stop.odpt_id,
        )
        for stop in stops
    ]
    _write_jsonl(stop_poles, out_dir / "stop_poles.jsonl")

    # -- 2. Routes --
    _log.info("Step 2/6: Normalizing BusroutePattern …")
    try:
        raw_patterns = load_raw_resource(snapshot_dir, "odpt:BusroutePattern")
    except FileNotFoundError:
        raw_patterns = []
        all_warnings.append("BusroutePattern raw file not found")

    routes, route_stops, pattern_lookup, w = normalize_busroute_patterns(
        raw_patterns, stop_lookup
    )
    all_warnings.extend(w)
    _write_jsonl(routes, out_dir / "routes.jsonl")
    _write_jsonl(route_stops, out_dir / "route_stops.jsonl")

    # -- 3. Trips --
    _log.info("Step 3/6: Normalizing BusTimetable …")
    try:
        raw_timetable = load_raw_resource(snapshot_dir, "odpt:BusTimetable")
    except FileNotFoundError:
        raw_timetable = []
        all_warnings.append("BusTimetable raw file not found")

    trips, stop_times, trip_counts, w = normalize_bus_timetables(
        raw_timetable, pattern_lookup, stop_lookup
    )
    all_warnings.extend(w)
    _write_jsonl(trips, out_dir / "trips.jsonl")
    _write_jsonl(stop_times, out_dir / "stop_times.jsonl")

    # Update route trip counts
    route_map = {r.route_id: r for r in routes}
    for rid, cnt in trip_counts.items():
        if rid in route_map:
            route_map[rid].trip_count = cnt
    _write_jsonl(list(route_map.values()), out_dir / "routes.jsonl")

    # -- 4. Service calendars --
    _log.info("Step 4/6: Building service calendars …")
    calendar_keys = set()
    for trip in trips:
        if trip.odpt_calendar_raw:
            calendar_keys.add(trip.odpt_calendar_raw)
    services, w = build_service_calendars(calendar_keys)
    all_warnings.extend(w)
    _write_jsonl(services, out_dir / "services.jsonl")

    # -- 5. Stop timetables --
    _log.info("Step 5/6: Normalizing BusstopPoleTimetable …")
    try:
        raw_stt = load_raw_resource(snapshot_dir, "odpt:BusstopPoleTimetable")
    except FileNotFoundError:
        raw_stt = []
        all_warnings.append("BusstopPoleTimetable raw file not found")

    stop_timetables, w = normalize_busstop_pole_timetables(raw_stt, stop_lookup)
    all_warnings.extend(w)
    _write_jsonl(stop_timetables, out_dir / "stop_timetables.jsonl")

    operators = [
        Operator(
            operator_id=TOKYU_OPERATOR_ID,
            name=TOKYU_OPERATOR_NAME,
            name_en=TOKYU_OPERATOR_NAME_EN,
            url=TOKYU_OPERATOR_URL,
        )
    ]
    _write_jsonl(operators, out_dir / "operators.jsonl")

    shape_points = _build_shape_points(route_stops, stop_lookup)
    _write_jsonl(shape_points, out_dir / "shapes.jsonl")

    # -- 6. Reconcile --
    _log.info("Step 6/6: Reconciling …")
    recon = reconcile(out_dir)
    all_warnings.extend(recon.get("warnings", []))

    # -- Summary --
    now_str = datetime.now(timezone.utc).isoformat()
    summary = NormalizationSummary(
        snapshot_id=snapshot_name,
        raw_archive_path=str(snapshot_dir),
        canonical_dir=str(out_dir),
        normalised_at=now_str,
        entity_counts={
            "operators": 1,
            "routes": len(routes),
            "route_stops": len(route_stops),
            "stops": len(stops),
            "stop_poles": len(stop_poles),
            "services": len(services),
            "trips": len(trips),
            "stop_times": len(stop_times),
            "stop_timetables": len(stop_timetables),
            "shapes": len(shape_points),
        },
        reconciliation=recon,
        warnings=list(dict.fromkeys(all_warnings)),
    )

    summary_path = out_dir / "canonical_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary.model_dump(mode="json"), f, ensure_ascii=False, indent=2)

    source_lineage = _build_source_lineage(
        snapshot_dir,
        snapshot_name,
        summary.entity_counts,
    )
    _write_jsonl(source_lineage, out_dir / "source_lineage.jsonl")

    _log.info(
        "Canonical build complete: %d routes, %d stops, %d trips, %d warnings",
        len(routes),
        len(stops),
        len(trips),
        len(summary.warnings),
    )
    return summary
