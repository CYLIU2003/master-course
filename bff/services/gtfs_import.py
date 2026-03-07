from __future__ import annotations

import csv
import hashlib
import math
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from statistics import median
from string import hexdigits
from typing import Any, DefaultDict, Dict, Iterable, List, Optional, Tuple, cast

DEFAULT_GTFS_FEED_PATH = "GTFS/ToeiBus-GTFS"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REQUIRED_FEED_FILES = (
    "agency.txt",
    "routes.txt",
    "stops.txt",
    "trips.txt",
    "stop_times.txt",
    "calendar.txt",
)
_OPTIONAL_FEED_FILES = ("calendar_dates.txt", "feed_info.txt")


def _resolve_feed_path(feed_path: str | Path) -> Path:
    path = Path(feed_path)
    if not path.is_absolute():
        path = (_REPO_ROOT / path).resolve()
    if not path.exists() or not path.is_dir():
        raise RuntimeError(f"GTFS feed directory not found: '{path}'")
    missing = [name for name in _REQUIRED_FEED_FILES if not (path / name).exists()]
    if missing:
        raise RuntimeError(
            "GTFS feed is missing required file(s): " + ", ".join(sorted(missing))
        )
    return path


def _feed_signature(feed_root: Path) -> Tuple[Tuple[str, int, int], ...]:
    signature: list[tuple[str, int, int]] = []
    for name in _REQUIRED_FEED_FILES + _OPTIONAL_FEED_FILES:
        file_path = feed_root / name
        if not file_path.exists():
            continue
        stat = file_path.stat()
        signature.append((name, stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


def _display_feed_path(feed_root: Path) -> str:
    try:
        return str(feed_root.relative_to(_REPO_ROOT))
    except ValueError:
        return str(feed_root)


def _generated_at(feed_root: Path) -> str:
    latest = max((feed_root / name).stat().st_mtime for name in _REQUIRED_FEED_FILES)
    return datetime.fromtimestamp(latest, tz=timezone.utc).isoformat()


def _as_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_time(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    parts = str(value).strip().split(":")
    if len(parts) < 2:
        return None
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return None
    return f"{hour:02d}:{minute:02d}"


def _time_to_min(value: Optional[str]) -> Optional[int]:
    normalized = _normalize_time(value)
    if normalized is None:
        return None
    hour, minute = normalized.split(":", 1)
    return int(hour) * 60 + int(minute)


def _median_or_zero(values: Iterable[float]) -> float:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return 0.0
    return float(median(numbers))


def _append_warning(warnings: list[str], message: str, limit: int = 24) -> None:
    if message in warnings:
        return
    if len(warnings) < limit:
        warnings.append(message)
    elif len(warnings) == limit:
        warnings.append(f"Additional GTFS warnings omitted after {limit} entries.")


def _service_id_from_calendar(row: Dict[str, str], warnings: list[str]) -> str:
    weekday_count = sum(int(row.get(key) or 0) for key in _WEEKDAY_KEYS)
    saturday = int(row.get("saturday") or 0)
    sunday = int(row.get("sunday") or 0)
    raw_service_id = str(row.get("service_id") or "unknown")

    if weekday_count > 0 and saturday == 0 and sunday == 0:
        return "WEEKDAY"
    if weekday_count == 0 and saturday == 1 and sunday == 0:
        return "SAT"
    if weekday_count == 0 and saturday == 0 and sunday == 1:
        return "SUN_HOL"
    if weekday_count == 0 and saturday == 1 and sunday == 1:
        _append_warning(
            warnings,
            f"GTFS service_id '{raw_service_id}' runs on both weekend days; mapped to SUN_HOL.",
        )
        return "SUN_HOL"

    _append_warning(
        warnings,
        f"GTFS service_id '{raw_service_id}' uses a non-standard weekday pattern; mapped to WEEKDAY.",
    )
    return "WEEKDAY"


def _service_id_from_calendar_dates(
    raw_service_id: str,
    weekday_indexes: Iterable[int],
    warnings: list[str],
) -> str:
    weekdays = {int(index) for index in weekday_indexes}
    if not weekdays:
        return "WEEKDAY"
    if weekdays.issubset({0, 1, 2, 3, 4}):
        return "WEEKDAY"
    if weekdays == {5}:
        return "SAT"
    if weekdays == {6}:
        return "SUN_HOL"
    if weekdays.issubset({5, 6}):
        _append_warning(
            warnings,
            f"GTFS service_id '{raw_service_id}' appears on both Saturday and Sunday exception dates; mapped to SUN_HOL.",
        )
        return "SUN_HOL"

    _append_warning(
        warnings,
        f"GTFS service_id '{raw_service_id}' only appears in calendar_dates.txt with mixed weekdays; mapped to WEEKDAY.",
    )
    return "WEEKDAY"


def _direction_from_gtfs(value: str | None) -> str:
    return "inbound" if str(value or "0") == "1" else "outbound"


def _route_color(seed: str, raw_color: str | None) -> str:
    value = str(raw_color or "").strip().lstrip("#")
    if len(value) == 6 and all(ch in hexdigits for ch in value):
        return f"#{value.lower()}"

    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    r = 64 + int(digest[0:2], 16) % 128
    g = 64 + int(digest[2:4], 16) % 128
    b = 64 + int(digest[4:6], 16) % 128
    return f"#{r:02x}{g:02x}{b:02x}"


def _route_pattern_key(
    raw_route_id: str,
    direction_id: str,
    shape_id: str,
    first_stop_id: str,
    last_stop_id: str,
) -> str:
    return "|".join(
        [
            raw_route_id,
            direction_id or "0",
            shape_id or "no-shape",
            first_stop_id,
            last_stop_id,
        ]
    )


def _route_id_from_pattern_key(pattern_key: str) -> str:
    digest = hashlib.sha1(pattern_key.encode("utf-8")).hexdigest()[:12]
    return f"gtfs-route-{digest}"


def _stop_timetable_id(stop_id: str, service_id: str) -> str:
    digest = hashlib.sha1(f"{stop_id}|{service_id}".encode("utf-8")).hexdigest()[:12]
    return f"gtfs-stop-timetable-{digest}"


def _haversine_km(
    lat_a: Optional[float],
    lon_a: Optional[float],
    lat_b: Optional[float],
    lon_b: Optional[float],
) -> float:
    if None in (lat_a, lon_a, lat_b, lon_b):
        return 0.0

    lat_a = cast(float, lat_a)
    lon_a = cast(float, lon_a)
    lat_b = cast(float, lat_b)
    lon_b = cast(float, lon_b)

    radius_km = 6371.0
    phi1 = math.radians(lat_a)
    phi2 = math.radians(lat_b)
    d_phi = math.radians(lat_b - lat_a)
    d_lambda = math.radians(lon_b - lon_a)

    a = (
        math.sin(d_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2.0) ** 2
    )
    return radius_km * (2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a)))


def _route_name(
    route_row: Dict[str, str],
    start_stop: str,
    end_stop: str,
    fallback: str,
) -> str:
    short_name = str(route_row.get("route_short_name") or "").strip()
    long_name = str(route_row.get("route_long_name") or "").strip()
    base = short_name or long_name or fallback
    if long_name and long_name != base:
        base = f"{base} {long_name}".strip()
    if start_stop and end_stop:
        return f"{base} ({start_stop} -> {end_stop})"
    return base


def _stream_rows(path: Path) -> Iterable[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        yield from csv.DictReader(fh)


_WEEKDAY_KEYS = ("monday", "tuesday", "wednesday", "thursday", "friday")


def load_gtfs_core_bundle(feed_path: str | Path = DEFAULT_GTFS_FEED_PATH) -> Dict[str, Any]:
    feed_root = _resolve_feed_path(feed_path)
    return _load_gtfs_core_bundle_cached(str(feed_root), _feed_signature(feed_root))


@lru_cache(maxsize=4)
def _load_gtfs_core_bundle_cached(
    feed_root_str: str, signature: Tuple[Tuple[str, int, int], ...]
) -> Dict[str, Any]:
    del signature

    feed_root = Path(feed_root_str)
    warnings: list[str] = []
    stats: DefaultDict[str, int] = defaultdict(int)
    unknown_service_ids: set[str] = set()

    agency_name = ""
    for agency_row in _stream_rows(feed_root / "agency.txt"):
        agency_name = str(agency_row.get("agency_name") or "").strip()
        if agency_name:
            break

    raw_routes: Dict[str, Dict[str, str]] = {}
    for row in _stream_rows(feed_root / "routes.txt"):
        route_id = str(row.get("route_id") or "").strip()
        if route_id:
            raw_routes[route_id] = row

    stop_name_by_id: Dict[str, str] = {}
    stop_coord_by_id: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
    stop_items: list[dict[str, Any]] = []
    seen_stop_ids: set[str] = set()
    for row in _stream_rows(feed_root / "stops.txt"):
        location_type = str(row.get("location_type") or "").strip()
        if location_type not in ("", "0"):
            continue

        stop_id = str(row.get("stop_id") or "").strip()
        if not stop_id or stop_id in seen_stop_ids:
            continue
        seen_stop_ids.add(stop_id)

        stop_name = str(row.get("stop_name") or stop_id).strip() or stop_id
        stop_name_by_id[stop_id] = stop_name
        stop_coord_by_id[stop_id] = (
            _as_float(row.get("stop_lat")),
            _as_float(row.get("stop_lon")),
        )
        stop_items.append(
            {
                "id": stop_id,
                "code": str(row.get("stop_code") or stop_id).strip() or stop_id,
                "name": stop_name,
                "lat": stop_coord_by_id[stop_id][0],
                "lon": stop_coord_by_id[stop_id][1],
                "source": "gtfs",
            }
        )

    service_id_map: Dict[str, str] = {}
    for row in _stream_rows(feed_root / "calendar.txt"):
        raw_service_id = str(row.get("service_id") or "").strip()
        if not raw_service_id:
            continue
        service_id_map[raw_service_id] = _service_id_from_calendar(row, warnings)

    calendar_dates_path = feed_root / "calendar_dates.txt"
    if calendar_dates_path.exists():
        service_dates: DefaultDict[str, set[int]] = defaultdict(set)
        for row in _stream_rows(calendar_dates_path):
            raw_service_id = str(row.get("service_id") or "").strip()
            date_str = str(row.get("date") or "").strip()
            exception_type = str(row.get("exception_type") or "").strip()
            if not raw_service_id or not date_str or exception_type != "1":
                continue
            try:
                weekday_index = datetime.strptime(date_str, "%Y%m%d").weekday()
            except ValueError:
                continue
            service_dates[raw_service_id].add(weekday_index)

        for raw_service_id, weekday_indexes in service_dates.items():
            if raw_service_id in service_id_map:
                continue
            service_id_map[raw_service_id] = _service_id_from_calendar_dates(
                raw_service_id,
                weekday_indexes,
                warnings,
            )

    trips_basic: Dict[str, Dict[str, str]] = {}
    for row in _stream_rows(feed_root / "trips.txt"):
        trip_id = str(row.get("trip_id") or "").strip()
        raw_route_id = str(row.get("route_id") or "").strip()
        raw_service_id = str(row.get("service_id") or "").strip()
        if not trip_id or not raw_route_id:
            continue

        canonical_service_id = service_id_map.get(raw_service_id)
        if canonical_service_id is None:
            canonical_service_id = "WEEKDAY"
            unknown_service_ids.add(raw_service_id)

        trips_basic[trip_id] = {
            "trip_id": trip_id,
            "raw_route_id": raw_route_id,
            "service_id": canonical_service_id,
            "direction": _direction_from_gtfs(row.get("direction_id")),
            "direction_id": str(row.get("direction_id") or "0"),
            "shape_id": str(row.get("shape_id") or "").strip(),
            "headsign": str(row.get("trip_headsign") or row.get("trip_short_name") or "").strip(),
        }

    current_trip_id: Optional[str] = None
    current_state: Optional[Dict[str, Any]] = None
    finalized_trip_ids: set[str] = set()
    trip_summaries: Dict[str, Dict[str, Any]] = {}
    stop_timetable_keys: set[tuple[str, str]] = set()

    def _start_trip_state(basic: Dict[str, str]) -> Dict[str, Any]:
        return {
            "trip_id": basic["trip_id"],
            "raw_route_id": basic["raw_route_id"],
            "service_id": basic["service_id"],
            "direction": basic["direction"],
            "direction_id": basic["direction_id"],
            "shape_id": basic["shape_id"],
            "headsign": basic["headsign"],
            "first_stop_id": None,
            "first_stop_name": "",
            "last_stop_id": None,
            "last_stop_name": "",
            "departure": None,
            "arrival": None,
            "stop_sequence": [],
            "distance_km": 0.0,
            "prev_coords": None,
        }

    def _finalize_trip_state(state: Optional[Dict[str, Any]]) -> None:
        if not state:
            return

        first_stop_id = state.get("first_stop_id")
        last_stop_id = state.get("last_stop_id")
        departure = state.get("departure")
        arrival = state.get("arrival")
        if not first_stop_id or not last_stop_id:
            stats["skipped_missing_stops"] += 1
            return
        if departure is None or arrival is None:
            stats["skipped_missing_times"] += 1
            return

        departure_min = _time_to_min(departure)
        arrival_min = _time_to_min(arrival)
        if departure_min is None or arrival_min is None or arrival_min < departure_min:
            stats["skipped_bad_time_order"] += 1
            return

        route_key = _route_pattern_key(
            str(state["raw_route_id"]),
            str(state["direction_id"]),
            str(state["shape_id"]),
            str(first_stop_id),
            str(last_stop_id),
        )
        trip_summaries[str(state["trip_id"])] = {
            "trip_id": str(state["trip_id"]),
            "route_key": route_key,
            "raw_route_id": str(state["raw_route_id"]),
            "service_id": str(state["service_id"]),
            "direction": str(state["direction"]),
            "direction_id": str(state["direction_id"]),
            "shape_id": str(state["shape_id"]),
            "headsign": str(state["headsign"]),
            "origin_id": str(first_stop_id),
            "origin_name": str(state["first_stop_name"]),
            "destination_id": str(last_stop_id),
            "destination_name": str(state["last_stop_name"]),
            "departure": str(departure),
            "arrival": str(arrival),
            "duration_min": int(arrival_min - departure_min),
            "distance_km": round(float(state["distance_km"]), 3),
            "stop_sequence": list(state["stop_sequence"]),
        }
        for stop_id in set(state["stop_sequence"]):
            stop_timetable_keys.add((str(stop_id), str(state["service_id"])))

    for row in _stream_rows(feed_root / "stop_times.txt"):
        trip_id = str(row.get("trip_id") or "").strip()
        if not trip_id:
            continue

        if trip_id != current_trip_id:
            _finalize_trip_state(current_state)
            if current_trip_id is not None:
                finalized_trip_ids.add(current_trip_id)
            current_trip_id = trip_id

            basic = trips_basic.get(trip_id)
            if basic is None:
                current_state = None
                stats["unknown_trip_ids"] += 1
                continue
            if trip_id in finalized_trip_ids:
                stats["revisited_trip_ids"] += 1
            current_state = _start_trip_state(basic)

        if current_state is None:
            continue

        stop_id = str(row.get("stop_id") or "").strip()
        if not stop_id:
            continue

        stop_name = stop_name_by_id.get(stop_id, stop_id)
        if stop_id not in stop_name_by_id:
            stats["missing_stop_refs"] += 1

        arrival = _normalize_time(row.get("arrival_time"))
        departure = _normalize_time(row.get("departure_time"))
        if current_state["first_stop_id"] is None:
            current_state["first_stop_id"] = stop_id
            current_state["first_stop_name"] = stop_name
            current_state["departure"] = departure or arrival

        current_state["last_stop_id"] = stop_id
        current_state["last_stop_name"] = stop_name
        current_state["arrival"] = arrival or departure or current_state["arrival"]
        current_state["stop_sequence"].append(stop_id)

        prev_lat, prev_lon = current_state["prev_coords"] or (None, None)
        lat, lon = stop_coord_by_id.get(stop_id, (None, None))
        current_state["distance_km"] += _haversine_km(prev_lat, prev_lon, lat, lon)
        current_state["prev_coords"] = (lat, lon)

    _finalize_trip_state(current_state)

    if unknown_service_ids:
        _append_warning(
            warnings,
            "GTFS trips referenced service_id value(s) missing from calendar.txt/calendar_dates.txt; "
            f"mapped to WEEKDAY ({', '.join(sorted(unknown_service_ids)[:5])}).",
        )
    if stats["unknown_trip_ids"]:
        _append_warning(
            warnings,
            f"GTFS stop_times.txt referenced {stats['unknown_trip_ids']} unknown trip_id value(s).",
        )
    if stats["missing_stop_refs"]:
        _append_warning(
            warnings,
            f"GTFS stop_times.txt referenced {stats['missing_stop_refs']} stop_id value(s) missing from stops.txt.",
        )
    if stats["revisited_trip_ids"]:
        _append_warning(
            warnings,
            "GTFS stop_times.txt does not appear to be grouped by trip_id; later entries may override earlier trip summaries.",
        )
    if stats["skipped_missing_stops"]:
        _append_warning(
            warnings,
            f"Skipped {stats['skipped_missing_stops']} GTFS trip(s) with incomplete stop sequences.",
        )
    if stats["skipped_missing_times"]:
        _append_warning(
            warnings,
            f"Skipped {stats['skipped_missing_times']} GTFS trip(s) with missing arrival/departure times.",
        )
    if stats["skipped_bad_time_order"]:
        _append_warning(
            warnings,
            f"Skipped {stats['skipped_bad_time_order']} GTFS trip(s) with arrival earlier than departure.",
        )

    patterns: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    for summary in trip_summaries.values():
        patterns[str(summary["route_key"])].append(summary)

    route_id_by_trip: Dict[str, str] = {}
    service_id_by_trip: Dict[str, str] = {}
    headsign_by_trip: Dict[str, str] = {}
    route_items: list[dict[str, Any]] = []
    grouped_rows: DefaultDict[tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)

    for pattern_key, summaries in sorted(patterns.items()):
        representative = max(
            summaries,
            key=lambda item: (
                len(item.get("stop_sequence") or []),
                int(item.get("duration_min") or 0),
                str(item.get("trip_id") or ""),
            ),
        )
        route_id = _route_id_from_pattern_key(pattern_key)
        raw_route_id = str(representative.get("raw_route_id") or "")
        raw_route = raw_routes.get(raw_route_id, {})
        distance_values = [
            float(summary.get("distance_km") or 0.0)
            for summary in summaries
            if float(summary.get("distance_km") or 0.0) > 0.0
        ]
        duration_values = [
            float(summary.get("duration_min") or 0)
            for summary in summaries
            if int(summary.get("duration_min") or 0) > 0
        ]
        distance_km = round(_median_or_zero(distance_values), 3)
        duration_min = int(round(_median_or_zero(duration_values)))

        route_items.append(
            {
                "id": route_id,
                "name": _route_name(
                    raw_route,
                    str(representative.get("origin_name") or ""),
                    str(representative.get("destination_name") or ""),
                    raw_route_id or route_id,
                ),
                "startStop": str(representative.get("origin_name") or ""),
                "endStop": str(representative.get("destination_name") or ""),
                "distanceKm": distance_km,
                "durationMin": duration_min,
                "color": _route_color(pattern_key, raw_route.get("route_color")),
                "enabled": True,
                "source": "gtfs",
                "tripCount": len(summaries),
                "durationSource": "stop_times_median" if duration_min > 0 else "none",
                "distanceSource": "stop_geometry_median" if distance_km > 0 else "none",
                "stopSequence": list(representative.get("stop_sequence") or []),
                "gtfsRouteId": raw_route_id,
                "gtfsShapeId": representative.get("shape_id"),
                "gtfsDirectionId": representative.get("direction_id"),
            }
        )

        for summary in summaries:
            trip_id = str(summary["trip_id"])
            route_id_by_trip[trip_id] = route_id
            service_id_by_trip[trip_id] = str(summary["service_id"])
            headsign_by_trip[trip_id] = str(summary.get("headsign") or "")
            grouped_rows[
                (
                    route_id,
                    str(summary["service_id"]),
                    str(summary["direction"]),
                )
            ].append(
                {
                    "trip_id": trip_id,
                    "route_id": route_id,
                    "service_id": str(summary["service_id"]),
                    "direction": str(summary["direction"]),
                    "origin": str(summary["origin_name"]),
                    "destination": str(summary["destination_name"]),
                    "departure": str(summary["departure"]),
                    "arrival": str(summary["arrival"]),
                    "distance_km": round(float(summary.get("distance_km") or 0.0), 3),
                    "allowed_vehicle_types": ["BEV", "ICE"],
                    "source": "gtfs",
                }
            )

    timetable_rows: list[dict[str, Any]] = []
    for key in sorted(grouped_rows.keys()):
        rows = sorted(
            grouped_rows[key],
            key=lambda row: (
                str(row.get("departure") or ""),
                str(row.get("arrival") or ""),
                str(row.get("trip_id") or ""),
            ),
        )
        for trip_index, row in enumerate(rows):
            row["trip_index"] = trip_index
            timetable_rows.append(row)

    return {
        "meta": {
            "source": "gtfs",
            "feedPath": _display_feed_path(feed_root),
            "agencyName": agency_name,
            "generatedAt": _generated_at(feed_root),
            "warnings": warnings,
        },
        "stops": stop_items,
        "routes": route_items,
        "timetable_rows": timetable_rows,
        "stop_timetable_count": len(stop_timetable_keys),
        "route_id_by_trip": route_id_by_trip,
        "service_id_by_trip": service_id_by_trip,
        "headsign_by_trip": headsign_by_trip,
        "stop_name_by_id": stop_name_by_id,
    }


def build_gtfs_stop_timetables(
    feed_path: str | Path = DEFAULT_GTFS_FEED_PATH,
) -> Dict[str, Any]:
    core = load_gtfs_core_bundle(feed_path)
    feed_root = _resolve_feed_path(feed_path)
    grouped_entries: DefaultDict[tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)

    route_id_by_trip = core.get("route_id_by_trip") or {}
    service_id_by_trip = core.get("service_id_by_trip") or {}
    headsign_by_trip = core.get("headsign_by_trip") or {}
    stop_name_by_id = core.get("stop_name_by_id") or {}

    for row in _stream_rows(feed_root / "stop_times.txt"):
        trip_id = str(row.get("trip_id") or "").strip()
        stop_id = str(row.get("stop_id") or "").strip()
        if not trip_id or not stop_id:
            continue

        service_id = service_id_by_trip.get(trip_id)
        if not service_id:
            continue

        grouped_entries[(stop_id, service_id)].append(
            {
                "trip_id": trip_id,
                "arrival": _normalize_time(row.get("arrival_time")),
                "departure": _normalize_time(row.get("departure_time")),
                "destinationSign": headsign_by_trip.get(trip_id) or "",
                "busroutePattern": route_id_by_trip.get(trip_id) or "",
            }
        )

    items: list[dict[str, Any]] = []
    for (stop_id, service_id), entries in sorted(grouped_entries.items()):
        sorted_entries = sorted(
            entries,
            key=lambda entry: (
                str(entry.get("departure") or entry.get("arrival") or ""),
                str(entry.get("arrival") or entry.get("departure") or ""),
                str(entry.get("trip_id") or ""),
            ),
        )
        items.append(
            {
                "id": _stop_timetable_id(stop_id, service_id),
                "source": "gtfs",
                "stopId": stop_id,
                "stopName": str(stop_name_by_id.get(stop_id) or stop_id),
                "calendar": service_id,
                "service_id": service_id,
                "items": [
                    {
                        "index": index,
                        "arrival": entry.get("arrival"),
                        "departure": entry.get("departure"),
                        "busroutePattern": entry.get("busroutePattern"),
                        "busTimetable": entry.get("trip_id"),
                        "destinationSign": entry.get("destinationSign"),
                    }
                    for index, entry in enumerate(sorted_entries)
                ],
            }
        )

    return {
        "meta": dict(core.get("meta") or {}),
        "stop_timetables": items,
    }


def summarize_gtfs_routes_import(
    routes: List[Dict[str, Any]], bundle: Dict[str, Any]
) -> Dict[str, Any]:
    warning_count = len((bundle.get("meta") or {}).get("warnings") or [])
    zero_duration_count = sum(1 for route in routes if not route.get("durationMin"))
    zero_distance_count = sum(1 for route in routes if not route.get("distanceKm"))
    no_trip_count = sum(1 for route in routes if not route.get("tripCount"))
    duration_sources: Dict[str, int] = {}
    distance_sources: Dict[str, int] = {}

    for route in routes:
        duration_source = str(route.get("durationSource") or "none")
        distance_source = str(route.get("distanceSource") or "none")
        duration_sources[duration_source] = duration_sources.get(duration_source, 0) + 1
        distance_sources[distance_source] = distance_sources.get(distance_source, 0) + 1

    return {
        "routeCount": len(routes),
        "warningCount": warning_count,
        "zeroDurationCount": zero_duration_count,
        "zeroDistanceCount": zero_distance_count,
        "noTripCount": no_trip_count,
        "durationSources": duration_sources,
        "distanceSources": distance_sources,
    }


def summarize_gtfs_stop_import(
    stops: List[Dict[str, Any]], bundle: Dict[str, Any]
) -> Dict[str, Any]:
    geo_count = 0
    named_count = 0
    code_count = 0

    for stop in stops:
        if stop.get("name"):
            named_count += 1
        if stop.get("code"):
            code_count += 1
        if stop.get("lat") is not None and stop.get("lon") is not None:
            geo_count += 1

    return {
        "stopCount": len(stops),
        "namedCount": named_count,
        "geoCount": geo_count,
        "poleNumberCount": code_count,
        "warningCount": len((bundle.get("meta") or {}).get("warnings") or []),
    }


def summarize_gtfs_timetable_import(
    rows: List[Dict[str, Any]], bundle: Dict[str, Any]
) -> Dict[str, Any]:
    service_counts: Dict[str, int] = defaultdict(int)
    route_ids = set()
    for row in rows:
        service_counts[str(row.get("service_id") or "WEEKDAY")] += 1
        route_ids.add(str(row.get("route_id") or ""))

    return {
        "rowCount": len(rows),
        "routeCount": len([route_id for route_id in route_ids if route_id]),
        "serviceCounts": dict(sorted(service_counts.items())),
        "stopTimetableCount": int(bundle.get("stop_timetable_count") or 0),
        "warningCount": len((bundle.get("meta") or {}).get("warnings") or []),
    }


def summarize_gtfs_stop_timetable_import(
    items: List[Dict[str, Any]], bundle: Dict[str, Any]
) -> Dict[str, Any]:
    service_counts: Dict[str, int] = {}
    total_entries = 0
    for item in items:
        service_id = str(item.get("service_id") or "unknown")
        service_counts[service_id] = service_counts.get(service_id, 0) + 1
        total_entries += len(item.get("items") or [])

    return {
        "stopTimetableCount": len(items),
        "entryCount": total_entries,
        "serviceCounts": dict(sorted(service_counts.items())),
        "warningCount": len((bundle.get("meta") or {}).get("warnings") or []),
    }
