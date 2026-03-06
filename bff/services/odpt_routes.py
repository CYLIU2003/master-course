from __future__ import annotations

import hashlib
import json
import os
import statistics
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional

DEFAULT_ODPT_BFF_URL = "http://localhost:3001"
DEFAULT_OPERATOR = "odpt.Operator:TokyuBus"


def _odpt_bff_url() -> str:
    return os.environ.get("ODPT_BFF_URL", DEFAULT_ODPT_BFF_URL).rstrip("/")


def _post_json(
    url: str, payload: Dict[str, Any], timeout_sec: int = 60
) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as res:
            text = res.read().decode("utf-8")
            if not text.strip():
                raise RuntimeError("ODPT BFF returned an empty response body")
            return json.loads(text)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"ODPT BFF HTTP {exc.code}: {detail or '(empty body)'}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"ODPT BFF is unreachable at {_odpt_bff_url()}: {exc.reason}"
        ) from exc


def fetch_operational_dataset(
    *,
    operator: str = DEFAULT_OPERATOR,
    dump: bool = True,
    force_refresh: bool = False,
    ttl_sec: int = 3600,
    include_bus_timetables: bool = True,
    include_stop_timetables: bool = False,
    chunk_bus_timetables: bool = False,
    chunk_stop_timetables: bool = False,
    bus_timetable_cursor: int = 0,
    bus_timetable_batch_size: int = 25,
    stop_timetable_cursor: int = 0,
    stop_timetable_batch_size: int = 25,
) -> Dict[str, Any]:
    url = f"{_odpt_bff_url()}/api/odpt/export/operational"
    return _post_json(
        url,
        {
            "operator": operator,
            "dump": dump,
            "forceRefresh": force_refresh,
            "ttlSec": ttl_sec,
            "includeBusTimetables": include_bus_timetables,
            "includeStopTimetables": include_stop_timetables,
            "chunkBusTimetables": chunk_bus_timetables,
            "chunkStopTimetables": chunk_stop_timetables,
            "busTimetableCursor": bus_timetable_cursor,
            "busTimetableBatchSize": bus_timetable_batch_size,
            "stopTimetableCursor": stop_timetable_cursor,
            "stopTimetableBatchSize": stop_timetable_batch_size,
        },
        timeout_sec=300,
    )


def fetch_normalized_dataset(
    *,
    operator: str = DEFAULT_OPERATOR,
    dump: bool = True,
    force_refresh: bool = False,
    ttl_sec: int = 3600,
    include_bus_timetables: bool = True,
    include_stop_timetables: bool = False,
    chunk_bus_timetables: bool = False,
    chunk_stop_timetables: bool = False,
    bus_timetable_cursor: int = 0,
    bus_timetable_batch_size: int = 25,
    stop_timetable_cursor: int = 0,
    stop_timetable_batch_size: int = 25,
) -> Dict[str, Any]:
    url = f"{_odpt_bff_url()}/api/odpt/export/normalized"
    return _post_json(
        url,
        {
            "operator": operator,
            "dump": dump,
            "forceRefresh": force_refresh,
            "ttlSec": ttl_sec,
            "includeBusTimetables": include_bus_timetables,
            "includeStopTimetables": include_stop_timetables,
            "chunkBusTimetables": chunk_bus_timetables,
            "chunkStopTimetables": chunk_stop_timetables,
            "busTimetableCursor": bus_timetable_cursor,
            "busTimetableBatchSize": bus_timetable_batch_size,
            "stopTimetableCursor": stop_timetable_cursor,
            "stopTimetableBatchSize": stop_timetable_batch_size,
        },
        timeout_sec=300,
    )


def fetch_operational_stage_dataset(
    *,
    operator: str = DEFAULT_OPERATOR,
    dump: bool = False,
    force_refresh: bool = False,
    ttl_sec: int = 3600,
    bus_timetable_cursor: int = 0,
    bus_timetable_batch_size: int = 25,
) -> Dict[str, Any]:
    url = f"{_odpt_bff_url()}/api/odpt/export/operational-stage"
    return _post_json(
        url,
        {
            "operator": operator,
            "dump": dump,
            "forceRefresh": force_refresh,
            "ttlSec": ttl_sec,
            "includeBusTimetables": True,
            "includeStopTimetables": False,
            "chunkBusTimetables": True,
            "busTimetableCursor": bus_timetable_cursor,
            "busTimetableBatchSize": bus_timetable_batch_size,
        },
        timeout_sec=300,
    )


def fetch_stop_timetable_stage_dataset(
    *,
    operator: str = DEFAULT_OPERATOR,
    dump: bool = False,
    force_refresh: bool = False,
    ttl_sec: int = 3600,
    stop_timetable_cursor: int = 0,
    stop_timetable_batch_size: int = 50,
) -> Dict[str, Any]:
    url = f"{_odpt_bff_url()}/api/odpt/export/stop-timetables-stage"
    return _post_json(
        url,
        {
            "operator": operator,
            "dump": dump,
            "forceRefresh": force_refresh,
            "ttlSec": ttl_sec,
            "includeBusTimetables": False,
            "includeStopTimetables": True,
            "chunkStopTimetables": True,
            "stopTimetableCursor": stop_timetable_cursor,
            "stopTimetableBatchSize": stop_timetable_batch_size,
        },
        timeout_sec=300,
    )


def _hhmm_to_min(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    try:
        hour_str, min_str = value.split(":", 1)
        return int(hour_str) * 60 + int(min_str)
    except (TypeError, ValueError):
        return None


def _trip_duration_minutes(trip: Dict[str, Any]) -> Optional[int]:
    stop_times = trip.get("stop_times") or []
    if not isinstance(stop_times, list) or not stop_times:
        return None

    start_min: Optional[int] = None
    end_min: Optional[int] = None

    for stop_time in stop_times:
        if not isinstance(stop_time, dict):
            continue
        candidate = _hhmm_to_min(stop_time.get("departure") or stop_time.get("arrival"))
        if candidate is not None:
            start_min = candidate
            break

    for stop_time in reversed(stop_times):
        if not isinstance(stop_time, dict):
            continue
        candidate = _hhmm_to_min(stop_time.get("arrival") or stop_time.get("departure"))
        if candidate is not None:
            end_min = candidate
            break

    if start_min is None or end_min is None or end_min < start_min:
        return None
    return end_min - start_min


def _median_or_none(values: Iterable[Optional[float]]) -> Optional[float]:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    return float(statistics.median(nums))


def _route_color(seed: str) -> str:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    r = int(digest[0:2], 16)
    g = int(digest[2:4], 16)
    b = int(digest[4:6], 16)
    # Lift the colors so they do not end up too dark in the table/map.
    r = 64 + (r % 128)
    g = 64 + (g % 128)
    b = 64 + (b % 128)
    return f"#{r:02x}{g:02x}{b:02x}"


def _route_id_from_pattern(pattern_id: str) -> str:
    digest = hashlib.sha1(pattern_id.encode("utf-8")).hexdigest()[:12]
    return f"odpt-route-{digest}"


def _short_id(value: Optional[str], fallback: str) -> str:
    if not value:
        return fallback
    return value.split(":")[-1]


def _stop_label(stops: Dict[str, Any], stop_id: Optional[str]) -> str:
    if not stop_id:
        return ""
    stop = stops.get(stop_id) or {}
    if isinstance(stop, dict) and stop.get("name"):
        return str(stop["name"])
    return _short_id(stop_id, stop_id)


def build_routes_from_operational(dataset: Dict[str, Any]) -> List[Dict[str, Any]]:
    stops = dataset.get("stops") or {}
    route_patterns = dataset.get("routePatterns") or {}
    trips = dataset.get("trips") or {}
    indexes = dataset.get("indexes") or {}
    trips_by_pattern = indexes.get("tripsByPattern") or {}

    routes: List[Dict[str, Any]] = []

    for pattern_id, pattern_value in sorted(route_patterns.items()):
        if not isinstance(pattern_value, dict):
            continue

        stop_sequence = pattern_value.get("stop_sequence") or []
        if not isinstance(stop_sequence, list) or len(stop_sequence) < 2:
            continue

        start_stop_id = str(stop_sequence[0])
        end_stop_id = str(stop_sequence[-1])
        start_stop = _stop_label(stops, start_stop_id)
        end_stop = _stop_label(stops, end_stop_id)

        trip_ids = trips_by_pattern.get(pattern_id) or []
        full_trip_durations: List[Optional[float]] = []
        any_trip_durations: List[Optional[float]] = []
        fallback_distances: List[Optional[float]] = []

        for trip_id in trip_ids:
            trip = trips.get(trip_id)
            if not isinstance(trip, dict):
                continue
            duration = _trip_duration_minutes(trip)
            any_trip_durations.append(duration)
            if trip.get("distance_source") == "pattern_segments":
                full_trip_durations.append(duration)
            fallback_distances.append(trip.get("estimated_distance_km"))

        duration_min = _median_or_none(full_trip_durations)
        duration_source = "pattern_segments_median"
        if duration_min is None:
            duration_min = _median_or_none(any_trip_durations)
            duration_source = "trip_median" if duration_min is not None else "none"

        distance_km = pattern_value.get("total_distance_km")
        distance_source = "pattern_total"
        if distance_km is None:
            distance_km = _median_or_none(fallback_distances)
            distance_source = (
                "trip_estimate_median" if distance_km is not None else "none"
            )

        title = str(pattern_value.get("title") or "").strip()
        if title:
            name = f"{title} ({start_stop} -> {end_stop})"
        else:
            name = f"{start_stop} -> {end_stop}"

        routes.append(
            {
                "id": _route_id_from_pattern(pattern_id),
                "name": name,
                "startStop": start_stop,
                "endStop": end_stop,
                "distanceKm": round(float(distance_km or 0.0), 3),
                "durationMin": int(round(duration_min or 0)),
                "color": _route_color(pattern_id),
                "enabled": True,
                "source": "odpt",
                "odptPatternId": pattern_id,
                "odptBusrouteId": pattern_value.get("busroute"),
                "distanceCoverageRatio": float(
                    pattern_value.get("distance_coverage_ratio") or 0.0
                ),
                "stopSequence": stop_sequence,
                "tripCount": len(trip_ids),
                "durationSource": duration_source,
                "distanceSource": distance_source,
            }
        )

    return routes


def summarize_routes_import(
    routes: List[Dict[str, Any]], dataset: Dict[str, Any]
) -> Dict[str, Any]:
    warning_count = len((dataset.get("meta") or {}).get("warnings") or [])
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
