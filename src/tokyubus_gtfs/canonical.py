"""
src.tokyubus_gtfs.canonical — Layer B: Canonical transit model builder.

Orchestrates all normalizers and writes canonical JSONL tables to disk.
This is the main entry point for the normalization pipeline.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .archive import load_raw_resource
from src.feed_identity import TOKYU_ODPT_GTFS_FEED_ID, build_dataset_id
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
    CanonicalRoutePattern,
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

_RESOURCE_STOPS = "odpt:BusstopPole"
_RESOURCE_PATTERNS = "odpt:BusroutePattern"
_RESOURCE_TIMETABLES = "odpt:BusTimetable"
_RESOURCE_STOP_TIMETABLES = "odpt:BusstopPoleTimetable"


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
    by_pattern: Dict[str, List[CanonicalRouteStop]] = {}
    for route_stop in route_stops:
        by_pattern.setdefault(route_stop.pattern_id, []).append(route_stop)

    shape_points: List[CanonicalShapePoint] = []
    for pattern_id, items in by_pattern.items():
        shape_id = f"shape_{pattern_id}"
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
                    route_id=item.route_id,
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
        "route_patterns": "odpt:BusroutePattern",
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


def _copy_if_present(src_dir: Path, dst_dir: Path, filenames: List[str]) -> List[str]:
    copied: List[str] = []
    for filename in filenames:
        src = src_dir / filename
        if not src.exists():
            continue
        dst = dst_dir / filename
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(filename)
    return copied


def _stop_lookup_from_canonical(out_dir: Path) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for item in _read_jsonl(out_dir / "stops.jsonl"):
        stop_id = str(item.get("stop_id") or "")
        if not stop_id:
            continue
        lookup[stop_id] = {
            "name": item.get("stop_name"),
            "lat": item.get("lat"),
            "lon": item.get("lon"),
        }
    return lookup


def _route_models_from_canonical(out_dir: Path) -> List[CanonicalRoute]:
    return [CanonicalRoute.model_validate(item) for item in _read_jsonl(out_dir / "routes.jsonl")]


def _route_patterns_from_canonical(out_dir: Path) -> List[CanonicalRoutePattern]:
    return [
        CanonicalRoutePattern.model_validate(item)
        for item in _read_jsonl(out_dir / "route_patterns.jsonl")
    ]


def _route_stops_from_canonical(out_dir: Path) -> List[CanonicalRouteStop]:
    return [CanonicalRouteStop.model_validate(item) for item in _read_jsonl(out_dir / "route_stops.jsonl")]


def _pattern_lookup_from_canonical(out_dir: Path) -> Dict[str, Dict[str, Any]]:
    lookup: Dict[str, Dict[str, Any]] = {}
    for item in _read_jsonl(out_dir / "route_patterns.jsonl"):
        odpt_pattern_id = str(item.get("odpt_pattern_id") or "")
        if not odpt_pattern_id:
            continue
        lookup[odpt_pattern_id] = {
            "route_id": item.get("route_id"),
            "pattern_id": item.get("pattern_id"),
            "shape_id": item.get("shape_id"),
            "direction_bucket": item.get("direction_bucket"),
            "pattern_role": item.get("pattern_role"),
            "is_passenger_service": item.get("is_passenger_service"),
            "include_in_public_gtfs": item.get("include_in_public_gtfs"),
            "total_distance_km": item.get("distance_km"),
            "stop_count": item.get("stop_count"),
            "origin_name": item.get("first_stop_name"),
            "destination_name": item.get("last_stop_name"),
        }
    return lookup


def _trip_models_from_canonical(out_dir: Path) -> List[CanonicalTrip]:
    return [CanonicalTrip.model_validate(item) for item in _read_jsonl(out_dir / "trips.jsonl")]


def _service_models_from_canonical(out_dir: Path) -> List[CanonicalService]:
    return [CanonicalService.model_validate(item) for item in _read_jsonl(out_dir / "services.jsonl")]


def _stop_timetable_models_from_canonical(out_dir: Path) -> List[CanonicalStopTimetable]:
    return [
        CanonicalStopTimetable.model_validate(item)
        for item in _read_jsonl(out_dir / "stop_timetables.jsonl")
    ]


def _shape_models_from_canonical(out_dir: Path) -> List[CanonicalShapePoint]:
    return [CanonicalShapePoint.model_validate(item) for item in _read_jsonl(out_dir / "shapes.jsonl")]


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
    route_patterns_data = _read_jsonl(out_dir / "route_patterns.jsonl")
    trips_data = _read_jsonl(out_dir / "trips.jsonl")
    route_stops_data = _read_jsonl(out_dir / "route_stops.jsonl")

    stop_ids = {s["stop_id"] for s in stops_data if s.get("stop_id")}
    route_ids = {r["route_id"] for r in routes_data if r.get("route_id")}
    pattern_ids = {r["pattern_id"] for r in route_patterns_data if r.get("pattern_id")}

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

    # Public routes referenced in trips but missing from routes table
    trip_route_ids = {t.get("route_id") for t in trips_data if t.get("route_id")}
    orphan = trip_route_ids - route_ids
    if orphan:
        warnings.append(
            f"{len(orphan)} route family id(s) in trips not in routes table"
        )

    trip_pattern_ids = {t.get("pattern_id") for t in trips_data if t.get("pattern_id")}
    missing_patterns = trip_pattern_ids - pattern_ids
    if missing_patterns:
        warnings.append(
            f"{len(missing_patterns)} pattern id(s) in trips not in route_patterns table"
        )

    return {
        "route_count": len(routes_data),
        "route_pattern_count": len(route_patterns_data),
        "stop_count": len(stops_data),
        "trip_count": len(trips_data),
        "missing_stop_count": len(missing_stops),
        "orphan_route_count": len(orphan),
        "missing_pattern_count": len(missing_patterns),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Full canonical build
# ---------------------------------------------------------------------------


def build_canonical(
    snapshot_dir: Path,
    *,
    out_dir: Optional[Path] = None,
    previous_canonical_dir: Optional[Path] = None,
    changed_resources: Optional[Set[str]] = None,
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
    changed = set(changed_resources or set())
    reuse_enabled = previous_canonical_dir is not None and previous_canonical_dir.exists()
    rebuilt_tables: List[str] = []
    reused_tables: List[str] = []

    rebuild_stops = (not reuse_enabled) or (_RESOURCE_STOPS in changed)
    rebuild_routes = (not reuse_enabled) or bool(changed & {_RESOURCE_STOPS, _RESOURCE_PATTERNS})
    rebuild_trips = (not reuse_enabled) or bool(
        changed & {_RESOURCE_STOPS, _RESOURCE_PATTERNS, _RESOURCE_TIMETABLES}
    )
    rebuild_services = (not reuse_enabled) or (_RESOURCE_TIMETABLES in changed)
    rebuild_stop_timetables = (not reuse_enabled) or bool(
        changed & {_RESOURCE_STOPS, _RESOURCE_STOP_TIMETABLES}
    )
    rebuild_shapes = (not reuse_enabled) or bool(changed & {_RESOURCE_STOPS, _RESOURCE_PATTERNS})

    # -- 1. Stops --
    if rebuild_stops:
        _log.info("Step 1/6: Normalizing BusstopPole …")
        try:
            raw_stops = load_raw_resource(snapshot_dir, _RESOURCE_STOPS)
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
        rebuilt_tables.extend(["stops", "stop_poles"])
    else:
        assert previous_canonical_dir is not None
        _copy_if_present(previous_canonical_dir, out_dir, ["stops.jsonl", "stop_poles.jsonl"])
        stops = [CanonicalStop.model_validate(item) for item in _read_jsonl(out_dir / "stops.jsonl")]
        stop_poles = [CanonicalStopPole.model_validate(item) for item in _read_jsonl(out_dir / "stop_poles.jsonl")]
        stop_lookup = _stop_lookup_from_canonical(out_dir)
        reused_tables.extend(["stops", "stop_poles"])

    # -- 2. Routes --
    if rebuild_routes:
        _log.info("Step 2/6: Normalizing BusroutePattern …")
        try:
            raw_patterns = load_raw_resource(snapshot_dir, _RESOURCE_PATTERNS)
        except FileNotFoundError:
            raw_patterns = []
            all_warnings.append("BusroutePattern raw file not found")

        routes, route_patterns, route_stops, pattern_lookup, w = normalize_busroute_patterns(
            raw_patterns, stop_lookup
        )
        all_warnings.extend(w)
        _write_jsonl(routes, out_dir / "routes.jsonl")
        _write_jsonl(route_patterns, out_dir / "route_patterns.jsonl")
        _write_jsonl(route_stops, out_dir / "route_stops.jsonl")
        rebuilt_tables.extend(["routes", "route_patterns", "route_stops"])
    else:
        assert previous_canonical_dir is not None
        _copy_if_present(
            previous_canonical_dir,
            out_dir,
            ["routes.jsonl", "route_patterns.jsonl", "route_stops.jsonl"],
        )
        routes = _route_models_from_canonical(out_dir)
        route_patterns = _route_patterns_from_canonical(out_dir)
        route_stops = _route_stops_from_canonical(out_dir)
        pattern_lookup = _pattern_lookup_from_canonical(out_dir)
        reused_tables.extend(["routes", "route_patterns", "route_stops"])

    # -- 3. Trips --
    if rebuild_trips:
        _log.info("Step 3/6: Normalizing BusTimetable …")
        try:
            raw_timetable = load_raw_resource(snapshot_dir, _RESOURCE_TIMETABLES)
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
        for route in route_map.values():
            route.trip_count = 0
        for rid, cnt in trip_counts.items():
            if rid in route_map:
                route_map[rid].trip_count = cnt
        routes = list(route_map.values())
        _write_jsonl(routes, out_dir / "routes.jsonl")
        rebuilt_tables.extend(["trips", "stop_times"])
        if "routes" not in rebuilt_tables:
            rebuilt_tables.append("routes")
            reused_tables = [item for item in reused_tables if item != "routes"]
    else:
        assert previous_canonical_dir is not None
        _copy_if_present(previous_canonical_dir, out_dir, ["trips.jsonl", "stop_times.jsonl"])
        trips = _trip_models_from_canonical(out_dir)
        stop_times = [CanonicalTripStopTime.model_validate(item) for item in _read_jsonl(out_dir / "stop_times.jsonl")]
        reused_tables.extend(["trips", "stop_times"])

    # -- 4. Service calendars --
    if rebuild_services:
        _log.info("Step 4/6: Building service calendars …")
        calendar_keys = set()
        for trip in trips:
            if trip.odpt_calendar_raw:
                calendar_keys.add(trip.odpt_calendar_raw)
        services, w = build_service_calendars(calendar_keys)
        all_warnings.extend(w)
        _write_jsonl(services, out_dir / "services.jsonl")
        rebuilt_tables.append("services")
    else:
        assert previous_canonical_dir is not None
        _copy_if_present(previous_canonical_dir, out_dir, ["services.jsonl"])
        services = _service_models_from_canonical(out_dir)
        reused_tables.append("services")

    # -- 5. Stop timetables --
    if rebuild_stop_timetables:
        _log.info("Step 5/6: Normalizing BusstopPoleTimetable …")
        try:
            raw_stt = load_raw_resource(snapshot_dir, _RESOURCE_STOP_TIMETABLES)
        except FileNotFoundError:
            raw_stt = []
            all_warnings.append("BusstopPoleTimetable raw file not found")

        stop_timetables, w = normalize_busstop_pole_timetables(raw_stt, stop_lookup)
        all_warnings.extend(w)
        _write_jsonl(stop_timetables, out_dir / "stop_timetables.jsonl")
        rebuilt_tables.append("stop_timetables")
    else:
        assert previous_canonical_dir is not None
        _copy_if_present(previous_canonical_dir, out_dir, ["stop_timetables.jsonl"])
        stop_timetables = _stop_timetable_models_from_canonical(out_dir)
        reused_tables.append("stop_timetables")

    operators = [
        Operator(
            operator_id=TOKYU_OPERATOR_ID,
            name=TOKYU_OPERATOR_NAME,
            name_en=TOKYU_OPERATOR_NAME_EN,
            url=TOKYU_OPERATOR_URL,
        )
    ]
    _write_jsonl(operators, out_dir / "operators.jsonl")

    if rebuild_shapes:
        shape_points = _build_shape_points(route_stops, stop_lookup)
        _write_jsonl(shape_points, out_dir / "shapes.jsonl")
        rebuilt_tables.append("shapes")
    else:
        assert previous_canonical_dir is not None
        _copy_if_present(previous_canonical_dir, out_dir, ["shapes.jsonl"])
        shape_points = _shape_models_from_canonical(out_dir)
        reused_tables.append("shapes")

    # -- 6. Reconcile --
    _log.info("Step 6/6: Reconciling …")
    recon = reconcile(out_dir)
    all_warnings.extend(recon.get("warnings", []))

    # -- Summary --
    now_str = datetime.now(timezone.utc).isoformat()
    summary = NormalizationSummary(
        feed_id=TOKYU_ODPT_GTFS_FEED_ID,
        snapshot_id=snapshot_name,
        dataset_id=build_dataset_id(TOKYU_ODPT_GTFS_FEED_ID, snapshot_name),
        raw_archive_path=str(snapshot_dir),
        canonical_dir=str(out_dir),
        normalised_at=now_str,
        entity_counts={
            "operators": 1,
            "routes": len(routes),
            "route_patterns": len(route_patterns),
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
        rebuilt_tables=sorted(set(rebuilt_tables)),
        reused_tables=sorted(set(reused_tables)),
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
