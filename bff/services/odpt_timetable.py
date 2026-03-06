from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Tuple

from bff.services.odpt_routes import _route_id_from_pattern, _stop_label


def _service_id_from_odpt(value: str | None) -> str:
    mapping = {
        "weekday": "WEEKDAY",
        "saturday": "SAT",
        "holiday": "SUN_HOL",
        "unknown": "WEEKDAY",
    }
    return mapping.get((value or "unknown").lower(), "WEEKDAY")


def _safe_time(value: Any) -> str | None:
    if not isinstance(value, str) or ":" not in value:
        return None
    hour, minute = value.split(":", 1)
    try:
        return f"{int(hour):02d}:{int(minute):02d}"
    except ValueError:
        return None


def _pattern_direction_map(
    route_patterns: Dict[str, Dict[str, Any]], stops: Dict[str, Dict[str, Any]]
) -> Dict[str, str]:
    by_route: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)

    for pattern_id, pattern in route_patterns.items():
        stop_sequence = pattern.get("stop_sequence") or []
        if len(stop_sequence) < 2:
            continue
        start_stop = _stop_label(stops, stop_sequence[0])
        end_stop = _stop_label(stops, stop_sequence[-1])
        route_id = _route_id_from_pattern(pattern_id)
        by_route[route_id].append((pattern_id, start_stop, end_stop))

    directions: Dict[str, str] = {}
    for patterns in by_route.values():
        terminal_pairs = {
            (start, end): pattern_id for pattern_id, start, end in patterns
        }
        for pattern_id, start_stop, end_stop in patterns:
            if start_stop == end_stop:
                directions[pattern_id] = "outbound"
                continue
            reverse_pattern_id = terminal_pairs.get((end_stop, start_stop))
            if reverse_pattern_id and pattern_id > reverse_pattern_id:
                directions[pattern_id] = "inbound"
            else:
                directions[pattern_id] = "outbound"
    return directions


def build_timetable_rows_from_operational(
    dataset: Dict[str, Any],
) -> List[Dict[str, Any]]:
    stops = dataset.get("stops") or {}
    route_patterns = dataset.get("routePatterns") or {}
    trips = dataset.get("trips") or {}
    direction_by_pattern = _pattern_direction_map(route_patterns, stops)

    grouped: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)

    for trip_id, trip in trips.items():
        if not isinstance(trip, dict):
            continue
        stop_times = trip.get("stop_times") or []
        if len(stop_times) < 2:
            continue

        first_stop = stop_times[0] if isinstance(stop_times[0], dict) else {}
        last_stop = stop_times[-1] if isinstance(stop_times[-1], dict) else {}
        departure = _safe_time(first_stop.get("departure") or first_stop.get("arrival"))
        arrival = _safe_time(last_stop.get("arrival") or last_stop.get("departure"))
        if departure is None or arrival is None:
            continue

        pattern_id = str(trip.get("pattern_id") or "")
        if not pattern_id:
            continue
        route_id = _route_id_from_pattern(pattern_id)
        service_id = _service_id_from_odpt(trip.get("service_id"))
        direction = direction_by_pattern.get(pattern_id, "outbound")
        pattern = route_patterns.get(pattern_id) or {}
        grouped[(route_id, service_id, direction)].append(
            {
                "trip_id": trip_id,
                "route_id": route_id,
                "service_id": service_id,
                "direction": direction,
                "origin": _stop_label(stops, first_stop.get("stop_id")),
                "destination": _stop_label(stops, last_stop.get("stop_id")),
                "departure": departure,
                "arrival": arrival,
                "distance_km": float(
                    trip.get("estimated_distance_km")
                    or pattern.get("total_distance_km")
                    or 0.0
                ),
                "allowed_vehicle_types": ["BEV", "ICE"],
                "source": "odpt",
            }
        )

    rows: List[Dict[str, Any]] = []
    for key in sorted(grouped.keys()):
        trips_in_group = sorted(
            grouped[key],
            key=lambda row: (row["departure"], row["arrival"], row["trip_id"]),
        )
        for trip_index, row in enumerate(trips_in_group):
            rows.append(
                {
                    "route_id": row["route_id"],
                    "service_id": row["service_id"],
                    "direction": row["direction"],
                    "trip_index": trip_index,
                    "trip_id": row["trip_id"],
                    "origin": row["origin"],
                    "destination": row["destination"],
                    "departure": row["departure"],
                    "arrival": row["arrival"],
                    "distance_km": round(float(row["distance_km"]), 3),
                    "allowed_vehicle_types": list(row["allowed_vehicle_types"]),
                    "source": row.get("source") or "odpt",
                }
            )

    return rows


def normalize_timetable_row_indexes(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)

    for row in rows:
        grouped[
            (
                str(row.get("route_id") or ""),
                str(row.get("service_id") or "WEEKDAY"),
                str(row.get("direction") or "outbound"),
            )
        ].append(dict(row))

    normalized: List[Dict[str, Any]] = []
    for key in sorted(grouped.keys()):
        items = sorted(
            grouped[key],
            key=lambda row: (
                str(row.get("departure") or ""),
                str(row.get("arrival") or ""),
                str(row.get("trip_id") or ""),
                str(row.get("origin") or ""),
                str(row.get("destination") or ""),
            ),
        )
        for trip_index, row in enumerate(items):
            row["trip_index"] = trip_index
            normalized.append(row)

    return normalized


def summarize_timetable_import(
    rows: List[Dict[str, Any]], dataset: Dict[str, Any]
) -> Dict[str, Any]:
    service_counts: Dict[str, int] = defaultdict(int)
    route_ids = set()
    for row in rows:
        service_counts[str(row.get("service_id") or "WEEKDAY")] += 1
        route_ids.add(str(row.get("route_id") or ""))

    stop_timetables = dataset.get("stopTimetables") or {}
    return {
        "rowCount": len(rows),
        "routeCount": len([route_id for route_id in route_ids if route_id]),
        "serviceCounts": dict(sorted(service_counts.items())),
        "stopTimetableCount": len(stop_timetables),
        "warningCount": len((dataset.get("meta") or {}).get("warnings") or []),
    }
