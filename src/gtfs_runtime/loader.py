from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional

from src.gtfs_runtime.snapshot_registry import get_latest_tokyubus_snapshot_id
from src.tokyubus_gtfs.constants import CANONICAL_DIR, FEATURES_DIR


_FEATURE_FILES = {
    "trip_chains": "trip_chains.jsonl",
    "energy_estimates": "energy_estimates.jsonl",
    "depot_candidates": "depot_candidates.jsonl",
    "stop_distances": "stop_distances.jsonl",
    "charging_windows": "charging_windows.jsonl",
    "deadhead_candidates": "deadhead_candidates.jsonl",
}


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    items: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                payload = json.loads(line)
                if isinstance(payload, dict):
                    items.append(payload)
    return items


def _service_flags(service: Dict[str, Any]) -> Dict[str, int]:
    return {
        "mon": int(bool(service.get("monday"))),
        "tue": int(bool(service.get("tuesday"))),
        "wed": int(bool(service.get("wednesday"))),
        "thu": int(bool(service.get("thursday"))),
        "fri": int(bool(service.get("friday"))),
        "sat": int(bool(service.get("saturday"))),
        "sun": int(bool(service.get("sunday"))),
    }


def _build_stop_items(stops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "id": str(stop.get("stop_id") or ""),
            "code": str(stop.get("stop_code") or stop.get("stop_id") or ""),
            "name": str(stop.get("stop_name") or stop.get("stop_id") or ""),
            "lat": stop.get("lat"),
            "lon": stop.get("lon"),
            "poleNumber": stop.get("pole_number"),
            "parentStationId": stop.get("parent_station_id"),
            "source": "gtfs_runtime",
            "odptId": stop.get("odpt_id"),
        }
        for stop in stops
        if stop.get("stop_id")
    ]


def _build_route_items(
    routes: List[Dict[str, Any]],
    trips: List[Dict[str, Any]],
    route_stops: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    trip_counts: DefaultDict[str, int] = defaultdict(int)
    for trip in trips:
        route_id = str(trip.get("route_id") or "")
        if route_id:
            trip_counts[route_id] += 1

    stop_sequence_map: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    for route_stop in route_stops:
        route_id = str(route_stop.get("route_id") or "")
        if route_id:
            stop_sequence_map[route_id].append(route_stop)

    items: List[Dict[str, Any]] = []
    for route in routes:
        route_id = str(route.get("route_id") or "")
        if not route_id:
            continue
        ordered_stop_ids = [
            str(item.get("stop_id"))
            for item in sorted(
                stop_sequence_map.get(route_id) or [],
                key=lambda value: int(value.get("stop_sequence") or 0),
            )
            if item.get("stop_id")
        ]
        items.append(
            {
                "id": route_id,
                "routeCode": str(route.get("route_code") or route_id),
                "routeLabel": str(
                    route.get("route_name") or route.get("route_code") or route_id
                ),
                "name": str(
                    route.get("route_name") or route.get("route_code") or route_id
                ),
                "startStopId": route.get("origin_stop_id"),
                "startStop": str(route.get("origin_name") or ""),
                "endStopId": route.get("destination_stop_id"),
                "endStop": str(route.get("destination_name") or ""),
                "distanceKm": float(route.get("distance_km") or 0.0),
                "durationMin": 0,
                "color": str(route.get("route_color") or ""),
                "enabled": True,
                "source": "gtfs_runtime",
                "tripCount": int(
                    route.get("trip_count") or trip_counts.get(route_id) or 0
                ),
                "stopSequence": ordered_stop_ids,
                "odptPatternId": route.get("odpt_pattern_id"),
                "odptBusrouteId": route.get("odpt_busroute_id"),
                "routeFamilyCode": route.get("route_family_code"),
                "routeFamilyLabel": route.get("route_family_label"),
                "routeVariantType": route.get("route_variant_type"),
                "canonicalDirection": route.get("canonical_direction"),
                "isPrimaryVariant": route.get("is_primary_variant"),
                "familySortOrder": route.get("family_sort_order"),
                "classificationConfidence": route.get("classification_confidence"),
                "classificationReasons": list(
                    route.get("classification_reasons") or []
                ),
            }
        )
    return items


def _build_timetable_rows(trips: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: DefaultDict[tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for trip in trips:
        route_id = str(trip.get("route_id") or "")
        service_id = str(trip.get("service_id") or "WEEKDAY")
        direction = str(trip.get("direction") or "outbound")
        if not route_id:
            continue
        grouped[(route_id, service_id, direction)].append(
            {
                "trip_id": str(trip.get("trip_id") or ""),
                "route_id": route_id,
                "service_id": service_id,
                "direction": direction,
                "origin": str(
                    trip.get("origin_name") or trip.get("origin_stop_id") or ""
                ),
                "destination": str(
                    trip.get("destination_name")
                    or trip.get("destination_stop_id")
                    or ""
                ),
                "departure": str(trip.get("departure_time") or "")[:5],
                "arrival": str(trip.get("arrival_time") or "")[:5],
                "distance_km": float(trip.get("distance_km") or 0.0),
                "allowed_vehicle_types": list(
                    trip.get("allowed_vehicle_types") or ["BEV", "ICE"]
                ),
                "source": "gtfs_runtime",
            }
        )

    rows: List[Dict[str, Any]] = []
    for key in sorted(grouped):
        items = sorted(
            grouped[key],
            key=lambda item: (
                str(item.get("departure") or ""),
                str(item.get("arrival") or ""),
                str(item.get("trip_id") or ""),
            ),
        )
        for trip_index, item in enumerate(items):
            item["trip_index"] = trip_index
            rows.append(item)
    return rows


def _build_stop_timetables(
    stop_timetables: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for timetable in stop_timetables:
        timetable_id = timetable.get("timetable_id")
        stop_id = timetable.get("stop_id")
        if not timetable_id or not stop_id:
            continue
        normalized_items = []
        for index, item in enumerate(list(timetable.get("items") or [])):
            normalized_items.append(
                {
                    "index": index,
                    "arrival": item.get("arrival") or item.get("arrival_time"),
                    "departure": item.get("departure") or item.get("departure_time"),
                    "busroutePattern": item.get("busroutePattern")
                    or item.get("route_id"),
                    "busTimetable": item.get("busTimetable") or item.get("trip_id"),
                    "destinationSign": item.get("destinationSign")
                    or item.get("destination_name")
                    or "",
                }
            )
        items.append(
            {
                "id": str(timetable_id),
                "source": "gtfs_runtime",
                "stopId": str(stop_id),
                "stopName": str(timetable.get("stop_name") or stop_id),
                "calendar": str(timetable.get("service_id") or "WEEKDAY"),
                "service_id": str(timetable.get("service_id") or "WEEKDAY"),
                "items": normalized_items,
            }
        )
    return items


def _build_calendar_entries(services: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "service_id": str(service.get("service_id") or "WEEKDAY"),
            "name": str(service.get("service_name") or service.get("service_id") or ""),
            **_service_flags(service),
            "start_date": str(service.get("start_date") or "2026-01-01"),
            "end_date": str(service.get("end_date") or "2026-12-31"),
        }
        for service in services
        if service.get("service_id")
    ]


def _build_route_payloads(
    route_items: List[Dict[str, Any]],
    timetable_rows: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    route_index = {str(route.get("id") or ""): route for route in route_items}
    grouped: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in timetable_rows:
        route_id = str(row.get("route_id") or "")
        if route_id:
            grouped[route_id].append(row)

    payloads: List[Dict[str, Any]] = []
    for route_id, rows in sorted(grouped.items()):
        route = route_index.get(route_id, {})
        service_summary: DefaultDict[str, Dict[str, Any]] = defaultdict(
            lambda: {
                "service_id": "",
                "trip_count": 0,
                "first_departure": None,
                "last_arrival": None,
            }
        )
        for row in rows:
            service_id = str(row.get("service_id") or "WEEKDAY")
            summary = service_summary[service_id]
            summary["service_id"] = service_id
            summary["trip_count"] += 1
            departure = row.get("departure")
            arrival = row.get("arrival")
            if departure and (
                summary["first_departure"] is None
                or departure < summary["first_departure"]
            ):
                summary["first_departure"] = departure
            if arrival and (
                summary["last_arrival"] is None or arrival > summary["last_arrival"]
            ):
                summary["last_arrival"] = arrival

        ordered_rows = sorted(
            rows,
            key=lambda row: (
                str(row.get("departure") or ""),
                str(row.get("arrival") or ""),
                str(row.get("trip_id") or ""),
            ),
        )
        payloads.append(
            {
                "route_id": route_id,
                "route_code": route.get("routeCode") or route_id,
                "route_label": route.get("routeLabel") or route.get("name") or route_id,
                "trip_count": len(rows),
                "first_departure": ordered_rows[0].get("departure")
                if ordered_rows
                else None,
                "last_arrival": ordered_rows[-1].get("arrival")
                if ordered_rows
                else None,
                "patterns": [
                    {
                        "pattern_id": route_id,
                        "title": route.get("name") or route_id,
                        "direction": ordered_rows[0].get("direction")
                        if ordered_rows
                        else "outbound",
                        "stop_sequence": [
                            {"stop_id": stop_id}
                            for stop_id in list(route.get("stopSequence") or [])
                        ],
                    }
                ],
                "services": sorted(
                    service_summary.values(), key=lambda item: item["service_id"]
                ),
                "trips": [
                    {
                        "trip_id": row.get("trip_id"),
                        "pattern_id": route_id,
                        "service_id": row.get("service_id"),
                        "direction": row.get("direction"),
                        "origin_stop_name": row.get("origin"),
                        "destination_stop_name": row.get("destination"),
                        "departure": row.get("departure"),
                        "arrival": row.get("arrival"),
                        "estimated_distance_km": row.get("distance_km"),
                    }
                    for row in ordered_rows
                ],
            }
        )
    return payloads


def _load_features(feature_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
    return {
        key: _read_jsonl(feature_dir / filename)
        for key, filename in _FEATURE_FILES.items()
    }


def load_tokyubus_snapshot_bundle(
    snapshot_id: Optional[str] = None,
    *,
    canonical_root: Path = CANONICAL_DIR,
    features_root: Path = FEATURES_DIR,
) -> Dict[str, Any]:
    resolved_snapshot_id = snapshot_id or get_latest_tokyubus_snapshot_id(
        canonical_root=canonical_root,
        features_root=features_root,
    )
    if not resolved_snapshot_id:
        raise RuntimeError("No Tokyu GTFS runtime snapshot is available.")

    canonical_dir = canonical_root / resolved_snapshot_id
    if not canonical_dir.exists():
        raise RuntimeError(
            f"Tokyu GTFS runtime snapshot not found: '{resolved_snapshot_id}'"
        )
    feature_dir = features_root / resolved_snapshot_id

    summary = _read_json(canonical_dir / "canonical_summary.json")
    stops = _read_jsonl(canonical_dir / "stops.jsonl")
    routes = _read_jsonl(canonical_dir / "routes.jsonl")
    route_stops = _read_jsonl(canonical_dir / "route_stops.jsonl")
    trips = _read_jsonl(canonical_dir / "trips.jsonl")
    stop_timetables = _read_jsonl(canonical_dir / "stop_timetables.jsonl")
    services = _read_jsonl(canonical_dir / "services.jsonl")

    stop_items = _build_stop_items(stops)
    route_items = _build_route_items(routes, trips, route_stops)
    timetable_rows = _build_timetable_rows(trips)
    stop_timetable_items = _build_stop_timetables(stop_timetables)
    calendar_entries = _build_calendar_entries(services)
    route_payloads = _build_route_payloads(route_items, timetable_rows)
    features = _load_features(feature_dir)

    return {
        "snapshot": {
            "snapshotKey": f"gtfs_runtime::{resolved_snapshot_id}",
            "source": "gtfs_runtime",
            "datasetRef": resolved_snapshot_id,
        },
        "meta": {
            "source": "gtfs_runtime",
            "operator": "tokyu",
            "snapshotId": resolved_snapshot_id,
            "generatedAt": summary.get("normalised_at"),
            "snapshotMode": "layered-pipeline",
            "warnings": list(summary.get("warnings") or []),
            "canonicalDir": str(canonical_dir),
            "featuresDir": str(feature_dir),
            "counts": {
                "stops": len(stop_items),
                "routes": len(route_items),
                "timetableRows": len(timetable_rows),
                "stopTimetables": len(stop_timetable_items),
                "routePayloads": len(route_payloads),
            },
            "featureCounts": {key: len(value) for key, value in features.items()},
            "entityCounts": dict(summary.get("entity_counts") or {}),
        },
        "stops": stop_items,
        "routes": route_items,
        "timetable_rows": timetable_rows,
        "stop_timetables": stop_timetable_items,
        "calendar_entries": calendar_entries,
        "calendar_date_entries": [],
        "route_payloads": route_payloads,
        "features": features,
    }
