"""
bff/services/odpt_normalize.py

Normalize raw ODPT snapshot files into internal entity format.

Reads raw JSON files one resource at a time (never all at once),
converts them into internal entities (routes, stops, trips, stop_times),
writes JSONL output files, and produces quality / reconciliation summaries.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_NORMALIZED_DIR = _REPO_ROOT / "data" / "cache" / "odpt" / "normalized"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalized_base_dir() -> Path:
    configured = os.environ.get("ODPT_NORMALIZED_DIR")
    if configured:
        p = Path(configured)
        if not p.is_absolute():
            p = (_REPO_ROOT / p).resolve()
        return p
    return _DEFAULT_NORMALIZED_DIR


def _short_id(value: Optional[str], fallback: str = "") -> str:
    if not value:
        return fallback
    return value.split(":")[-1]


def _route_id_from_pattern(pattern_id: str) -> str:
    digest = hashlib.sha1(pattern_id.encode("utf-8")).hexdigest()[:12]
    return f"odpt-route-{digest}"


def _safe_time(value: Any) -> Optional[str]:
    if not isinstance(value, str) or ":" not in value:
        return None
    parts = value.split(":", 1)
    try:
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    except ValueError:
        return None


def _route_color(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    r = 64 + (int(digest[0:2], 16) % 128)
    g = 64 + (int(digest[2:4], 16) % 128)
    b = 64 + (int(digest[4:6], 16) % 128)
    return f"#{r:02x}{g:02x}{b:02x}"


def _service_id_from_odpt(value: Optional[str]) -> str:
    mapping = {
        "weekday": "WEEKDAY",
        "saturday": "SAT",
        "holiday": "SUN_HOL",
        "unknown": "WEEKDAY",
    }
    return mapping.get((value or "unknown").lower(), "WEEKDAY")


def _data_hash(obj: Any) -> str:
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_jsonl(items: list, out_path: Path) -> int:
    """Write a list of dicts as JSONL.  Returns the count written."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    """Read a JSONL file back into a list of dicts."""
    if not path.exists():
        return []
    items = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


# ---------------------------------------------------------------------------
# Each resource normalizer
# ---------------------------------------------------------------------------


def normalize_busroute_pattern(
    raw_data: list,
    out_dir: Path,
    stop_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Normalize odpt:BusroutePattern into routes, route_stops, and
    route_patterns JSONL files.
    """
    routes: List[Dict[str, Any]] = []
    route_patterns: List[Dict[str, Any]] = []
    route_stops: List[Dict[str, Any]] = []
    warnings: List[str] = []
    stops = stop_lookup or {}

    def _stop_label(stop_id: Optional[str]) -> str:
        if not stop_id:
            return ""
        stop = stops.get(stop_id, {})
        return str(stop.get("name", "")) or _short_id(stop_id, stop_id or "")

    for item in raw_data:
        if not isinstance(item, dict):
            continue

        pattern_id = str(item.get("owl:sameAs") or item.get("@id") or "")
        if not pattern_id:
            continue

        # Extract stop sequence
        busstop_order = item.get("odpt:busstopPoleOrder") or []
        stop_sequence: List[str] = []
        for bs in busstop_order:
            if isinstance(bs, dict):
                pole = bs.get("odpt:busstopPole")
                if pole:
                    stop_sequence.append(str(pole))

        if len(stop_sequence) < 2:
            warnings.append(f"Pattern {pattern_id} has < 2 stops, skipped")
            continue

        route_id = _route_id_from_pattern(pattern_id)
        title = str(item.get("dc:title") or "")
        start_stop = _stop_label(stop_sequence[0])
        end_stop = _stop_label(stop_sequence[-1])

        name = f"{title} ({start_stop} -> {end_stop})" if title else f"{start_stop} -> {end_stop}"

        # Total distance from pattern segments
        total_distance_km = 0.0
        for bs in busstop_order:
            if isinstance(bs, dict):
                dist = bs.get("odpt:distance")
                if dist is not None:
                    try:
                        total_distance_km += float(dist) / 1000.0
                    except (TypeError, ValueError):
                        pass

        route = {
            "id": route_id,
            "name": name,
            "startStop": start_stop,
            "endStop": end_stop,
            "distanceKm": round(total_distance_km, 3),
            "durationMin": 0,
            "color": _route_color(pattern_id),
            "enabled": True,
            "source": "odpt",
            "odptPatternId": pattern_id,
            "odptBusrouteId": str(item.get("odpt:busroute") or ""),
            "stopSequence": stop_sequence,
            "tripCount": 0,  # will be updated by timetable normalization
            "durationSource": "none",
            "distanceSource": "pattern_total" if total_distance_km > 0 else "none",
            "data_hash": "",
        }
        route["data_hash"] = _data_hash(route)
        routes.append(route)

        route_patterns.append(
            {
                "pattern_id": pattern_id,
                "route_id": route_id,
                "title": title,
                "busroute": str(item.get("odpt:busroute") or ""),
                "stop_count": len(stop_sequence),
                "total_distance_km": round(total_distance_km, 3),
                "data_hash": _data_hash({"pattern_id": pattern_id, "stops": stop_sequence}),
            }
        )

        for idx, stop_id in enumerate(stop_sequence):
            route_stops.append(
                {
                    "pattern_id": pattern_id,
                    "route_id": route_id,
                    "stop_id": stop_id,
                    "sequence": idx,
                    "stop_name": _stop_label(stop_id),
                }
            )

    # Write JSONL
    _write_jsonl(routes, out_dir / "routes.jsonl")
    _write_jsonl(route_patterns, out_dir / "route_patterns.jsonl")
    _write_jsonl(route_stops, out_dir / "route_stops.jsonl")

    return {
        "route_count": len(routes),
        "pattern_count": len(route_patterns),
        "route_stop_count": len(route_stops),
        "warnings": warnings,
    }


def normalize_busstop_pole(
    raw_data: list,
    out_dir: Path,
) -> Dict[str, Any]:
    """Normalize odpt:BusstopPole into stops JSONL."""
    stops: List[Dict[str, Any]] = []
    stop_lookup: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []

    for item in raw_data:
        if not isinstance(item, dict):
            continue
        stop_id = str(item.get("owl:sameAs") or item.get("@id") or "")
        if not stop_id:
            continue

        lat = item.get("geo:lat")
        lon = item.get("geo:long")

        try:
            lat = float(lat) if lat is not None else None
        except (TypeError, ValueError):
            lat = None
        try:
            lon = float(lon) if lon is not None else None
        except (TypeError, ValueError):
            lon = None

        pole_number = item.get("odpt:busstopPoleNumber")
        name = str(item.get("dc:title") or _short_id(stop_id, stop_id))

        stop = {
            "id": stop_id,
            "code": str(pole_number or stop_id.split(":")[-1]),
            "name": name,
            "lat": lat,
            "lon": lon,
            "poleNumber": pole_number,
            "source": "odpt",
            "data_hash": "",
        }
        stop["data_hash"] = _data_hash(stop)
        stops.append(stop)
        stop_lookup[stop_id] = {"name": name, "lat": lat, "lon": lon}

    _write_jsonl(stops, out_dir / "stops.jsonl")

    return {
        "stop_count": len(stops),
        "warnings": warnings,
        "stop_lookup": stop_lookup,
    }


def normalize_bus_timetable(
    raw_data: list,
    out_dir: Path,
    route_patterns_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
    stop_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Normalize odpt:BusTimetable into trips and stop_times JSONL."""
    trips: List[Dict[str, Any]] = []
    stop_times: List[Dict[str, Any]] = []
    service_calendars: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []
    stops = stop_lookup or {}
    patterns = route_patterns_lookup or {}

    # Track trip counts per route for updating routes later
    trip_counts_by_route: Dict[str, int] = {}

    def _stop_label(stop_id: Optional[str]) -> str:
        if not stop_id:
            return ""
        info = stops.get(stop_id, {})
        return str(info.get("name", "")) or _short_id(stop_id, stop_id or "")

    for timetable in raw_data:
        if not isinstance(timetable, dict):
            continue

        pattern_id = str(timetable.get("odpt:busroutePattern") or "")
        calendar_raw = str(timetable.get("odpt:calendar") or "")
        timetable_objects = timetable.get("odpt:busTimetableObject") or []

        if not pattern_id or not timetable_objects:
            continue

        route_id = _route_id_from_pattern(pattern_id)

        # Determine service
        service_key = _short_id(calendar_raw, "unknown")
        service_id = _service_id_from_odpt(service_key)

        if service_id not in service_calendars:
            service_calendars[service_id] = {
                "service_id": service_id,
                "name": service_id,
                "source": "odpt",
                "calendar_raw": calendar_raw,
            }

        # Each timetable object represents one trip
        for trip_idx, tt_obj in enumerate(timetable_objects):
            if not isinstance(tt_obj, list):
                continue

            trip_id_base = f"{_short_id(pattern_id)}_{service_key}_{trip_idx}"
            trip_id = f"odpt-trip-{hashlib.sha1(trip_id_base.encode()).hexdigest()[:12]}"

            trip_stop_times: List[Dict[str, Any]] = []
            for st_idx, st in enumerate(tt_obj):
                if not isinstance(st, dict):
                    continue
                stop_id = str(st.get("odpt:busstopPole") or "")
                departure = _safe_time(st.get("odpt:departureTime"))
                arrival = _safe_time(st.get("odpt:arrivalTime"))

                st_entry = {
                    "trip_id": trip_id,
                    "stop_id": stop_id,
                    "stop_name": _stop_label(stop_id),
                    "sequence": st_idx,
                    "departure": departure or arrival,
                    "arrival": arrival or departure,
                    "source": "odpt",
                }
                stop_times.append(st_entry)
                trip_stop_times.append(st_entry)

            if len(trip_stop_times) < 2:
                continue

            first_st = trip_stop_times[0]
            last_st = trip_stop_times[-1]

            # Calculate direction
            direction = "outbound"  # default

            trip = {
                "trip_id": trip_id,
                "route_id": route_id,
                "service_id": service_id,
                "direction": direction,
                "trip_index": trip_idx,
                "origin": first_st.get("stop_name", ""),
                "destination": last_st.get("stop_name", ""),
                "departure": first_st.get("departure", ""),
                "arrival": last_st.get("arrival", ""),
                "distance_km": 0.0,
                "allowed_vehicle_types": ["BEV", "ICE"],
                "source": "odpt",
                "data_hash": "",
            }
            trip["data_hash"] = _data_hash(trip)
            trips.append(trip)

            trip_counts_by_route[route_id] = trip_counts_by_route.get(route_id, 0) + 1

    cal_list = list(service_calendars.values())

    _write_jsonl(trips, out_dir / "trips.jsonl")
    _write_jsonl(stop_times, out_dir / "stop_times.jsonl")
    _write_jsonl(cal_list, out_dir / "service_calendars.jsonl")

    return {
        "trip_count": len(trips),
        "stop_time_count": len(stop_times),
        "service_calendar_count": len(cal_list),
        "trip_counts_by_route": trip_counts_by_route,
        "warnings": warnings,
    }


def normalize_busstop_pole_timetable(
    raw_data: list,
    out_dir: Path,
    stop_lookup: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Normalize odpt:BusstopPoleTimetable for stop-level timetable
    reconciliation and supplementary stop_times.
    """
    stop_timetables: List[Dict[str, Any]] = []
    warnings: List[str] = []
    stops = stop_lookup or {}

    def _stop_label(stop_id: Optional[str]) -> str:
        if not stop_id:
            return ""
        info = stops.get(stop_id, {})
        return str(info.get("name", "")) or _short_id(stop_id, stop_id or "")

    for item in raw_data:
        if not isinstance(item, dict):
            continue
        timetable_id = str(item.get("owl:sameAs") or item.get("@id") or "")
        stop_id = str(item.get("odpt:busstopPole") or "")
        calendar_raw = str(item.get("odpt:calendar") or "")
        service_key = _short_id(calendar_raw, "unknown")
        service_id = _service_id_from_odpt(service_key)

        tt_objects = item.get("odpt:busstopPoleTimetableObject") or []
        entries: List[Dict[str, Any]] = []
        for obj in tt_objects:
            if not isinstance(obj, dict):
                continue
            entries.append(
                {
                    "departure": _safe_time(obj.get("odpt:departureTime")),
                    "destination": str(obj.get("odpt:destinationBusstopPole") or ""),
                    "busroute": str(obj.get("odpt:busroute") or ""),
                    "note": str(obj.get("odpt:note") or ""),
                }
            )

        stop_timetables.append(
            {
                "id": timetable_id,
                "source": "odpt",
                "stopId": stop_id,
                "stopName": _stop_label(stop_id),
                "calendar": calendar_raw,
                "service_id": service_id,
                "items": entries,
            }
        )

    _write_jsonl(stop_timetables, out_dir / "busstop_pole_timetables.jsonl")

    return {
        "stop_timetable_count": len(stop_timetables),
        "total_entries": sum(len(st.get("items", [])) for st in stop_timetables),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def reconcile_normalized_entities(out_dir: Path) -> Dict[str, Any]:
    """
    Cross-check the four normalized entity sets for consistency.
    Returns warnings and patch suggestions.
    """
    warnings: List[str] = []

    routes = _read_jsonl(out_dir / "routes.jsonl")
    stops = _read_jsonl(out_dir / "stops.jsonl")
    trips = _read_jsonl(out_dir / "trips.jsonl")

    stop_ids = {s["id"] for s in stops if s.get("id")}
    route_ids = {r["id"] for r in routes if r.get("id")}

    # Check: route stop sequences reference valid stops
    route_stops_data = _read_jsonl(out_dir / "route_stops.jsonl")
    missing_stops = set()
    for rs in route_stops_data:
        sid = rs.get("stop_id")
        if sid and sid not in stop_ids:
            missing_stops.add(sid)
    if missing_stops:
        warnings.append(
            f"{len(missing_stops)} stop(s) referenced in route patterns not found in BusstopPole data"
        )

    # Check: trips reference valid routes
    trip_route_ids = {t.get("route_id") for t in trips if t.get("route_id")}
    orphan_routes = trip_route_ids - route_ids
    if orphan_routes:
        warnings.append(
            f"{len(orphan_routes)} route(s) referenced in timetables not found in BusroutePattern data"
        )

    # Summary counts
    return {
        "route_count": len(routes),
        "stop_count": len(stops),
        "trip_count": len(trips),
        "missing_stop_count": len(missing_stops),
        "orphan_route_count": len(orphan_routes),
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# High-level normalize pipeline
# ---------------------------------------------------------------------------


def normalize_odpt_snapshot(
    raw_snapshot_dir: Path,
    out_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Full normalization pipeline for a raw ODPT snapshot.

    1. Normalize BusstopPole (stops first, to build stop lookup)
    2. Normalize BusroutePattern (using stop lookup)
    3. Normalize BusTimetable (using stop + pattern lookups)
    4. Normalize BusstopPoleTimetable
    5. Reconcile all entities
    6. Return summary
    """
    if out_dir is None:
        # Use the same snapshot ID as the raw directory name
        snapshot_name = raw_snapshot_dir.name
        out_dir = _normalized_base_dir() / snapshot_name

    out_dir.mkdir(parents=True, exist_ok=True)
    all_warnings: List[str] = []

    # -- 1. Stops --
    _log.info("Normalizing BusstopPole...")
    try:
        from bff.services.odpt_fetch import load_raw_resource
        raw_stops = load_raw_resource(raw_snapshot_dir, "odpt:BusstopPole")
    except FileNotFoundError:
        raw_stops = []
        all_warnings.append("BusstopPole raw file not found")

    stop_result = normalize_busstop_pole(raw_stops, out_dir)
    stop_lookup = stop_result.get("stop_lookup", {})
    all_warnings.extend(stop_result.get("warnings", []))

    # -- 2. Route patterns --
    _log.info("Normalizing BusroutePattern...")
    try:
        from bff.services.odpt_fetch import load_raw_resource
        raw_patterns = load_raw_resource(raw_snapshot_dir, "odpt:BusroutePattern")
    except FileNotFoundError:
        raw_patterns = []
        all_warnings.append("BusroutePattern raw file not found")

    pattern_result = normalize_busroute_pattern(raw_patterns, out_dir, stop_lookup)
    all_warnings.extend(pattern_result.get("warnings", []))

    # Build pattern lookup for timetable normalization
    patterns_jsonl = _read_jsonl(out_dir / "route_patterns.jsonl")
    pattern_lookup = {p["pattern_id"]: p for p in patterns_jsonl if p.get("pattern_id")}

    # -- 3. Bus timetable --
    _log.info("Normalizing BusTimetable...")
    try:
        from bff.services.odpt_fetch import load_raw_resource
        raw_timetable = load_raw_resource(raw_snapshot_dir, "odpt:BusTimetable")
    except FileNotFoundError:
        raw_timetable = []
        all_warnings.append("BusTimetable raw file not found")

    tt_result = normalize_bus_timetable(
        raw_timetable, out_dir, pattern_lookup, stop_lookup
    )
    all_warnings.extend(tt_result.get("warnings", []))

    # Update route trip counts
    trip_counts = tt_result.get("trip_counts_by_route", {})
    routes = _read_jsonl(out_dir / "routes.jsonl")
    updated_routes = []
    for route in routes:
        rid = route.get("id", "")
        if rid in trip_counts:
            route["tripCount"] = trip_counts[rid]
            route["data_hash"] = _data_hash(route)
        updated_routes.append(route)
    _write_jsonl(updated_routes, out_dir / "routes.jsonl")

    # -- 4. BusstopPoleTimetable --
    _log.info("Normalizing BusstopPoleTimetable...")
    try:
        from bff.services.odpt_fetch import load_raw_resource
        raw_stt = load_raw_resource(raw_snapshot_dir, "odpt:BusstopPoleTimetable")
    except FileNotFoundError:
        raw_stt = []
        all_warnings.append("BusstopPoleTimetable raw file not found")

    stt_result = normalize_busstop_pole_timetable(raw_stt, out_dir, stop_lookup)
    all_warnings.extend(stt_result.get("warnings", []))

    # -- 5. Reconcile --
    _log.info("Reconciling normalized entities...")
    reconcile_result = reconcile_normalized_entities(out_dir)
    all_warnings.extend(reconcile_result.get("warnings", []))

    # -- Build summary --
    now = datetime.now(timezone.utc)
    summary = {
        "snapshot_dir": str(raw_snapshot_dir),
        "normalized_dir": str(out_dir),
        "normalized_at": now.isoformat(),
        "entity_counts": {
            "routes": pattern_result.get("route_count", 0),
            "stops": stop_result.get("stop_count", 0),
            "trips": tt_result.get("trip_count", 0),
            "stop_times": tt_result.get("stop_time_count", 0),
            "service_calendars": tt_result.get("service_calendar_count", 0),
            "stop_timetables": stt_result.get("stop_timetable_count", 0),
        },
        "reconciliation": {
            "route_count": reconcile_result.get("route_count", 0),
            "stop_count": reconcile_result.get("stop_count", 0),
            "trip_count": reconcile_result.get("trip_count", 0),
            "missing_stop_count": reconcile_result.get("missing_stop_count", 0),
            "orphan_route_count": reconcile_result.get("orphan_route_count", 0),
        },
        "warnings": list(dict.fromkeys(all_warnings)),
    }

    # Save normalize summary
    summary_path = out_dir / "normalize_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    _log.info(
        "Normalization complete: %d routes, %d stops, %d trips, %d stop_times, %d warnings",
        summary["entity_counts"]["routes"],
        summary["entity_counts"]["stops"],
        summary["entity_counts"]["trips"],
        summary["entity_counts"]["stop_times"],
        len(summary["warnings"]),
    )

    return summary


# ---------------------------------------------------------------------------
# Load normalized entities for catalog insertion
# ---------------------------------------------------------------------------


def load_normalized_bundle(normalized_dir: Path) -> Dict[str, Any]:
    """
    Load all normalized JSONL entities from a normalized snapshot directory.
    Used by the catalog/transit_catalog layer to insert into the DB.
    """
    return {
        "routes": _read_jsonl(normalized_dir / "routes.jsonl"),
        "stops": _read_jsonl(normalized_dir / "stops.jsonl"),
        "trips": _read_jsonl(normalized_dir / "trips.jsonl"),
        "stop_times": _read_jsonl(normalized_dir / "stop_times.jsonl"),
        "service_calendars": _read_jsonl(normalized_dir / "service_calendars.jsonl"),
        "stop_timetables": _read_jsonl(normalized_dir / "busstop_pole_timetables.jsonl"),
    }
