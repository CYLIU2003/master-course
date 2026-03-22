from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import unicodedata


REPO_ROOT = Path(__file__).resolve().parents[1]
TOKYU_SHARD_ROOT = REPO_ROOT / "outputs" / "built" / "tokyu"

_DEFAULT_DAY_TYPES = ("weekday", "saturday", "holiday")
_DAY_TYPE_BY_SERVICE_ID = {
    "WEEKDAY": "weekday",
    "SAT": "saturday",
    "SAT_HOL": "saturday",
    "SAT_HOLIDAY": "saturday",
    "SUN_HOL": "holiday",
    "SUN_HOLIDAY": "holiday",
    "HOLIDAY": "holiday",
}
_SERVICE_ID_BY_DAY_TYPE = {
    "weekday": "WEEKDAY",
    "saturday": "SAT",
    "holiday": "SUN_HOL",
}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_token(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    return unicodedata.normalize("NFKC", raw)


def _artifact_path(root: Path, artifact_path: str) -> Path:
    path = Path(artifact_path)
    if path.is_absolute():
        return path
    return root / path


def route_code_from_scoped_route_id(route_id: str) -> str:
    parts = str(route_id or "").split(":")
    return _normalize_token(parts[-1] if parts else str(route_id or ""))


def depot_id_from_scoped_route_id(route_id: str) -> str:
    parts = str(route_id or "").split(":")
    return _normalize_token(parts[-2] if len(parts) >= 3 else "")


def service_id_to_day_type(service_id: str | None) -> str:
    normalized = str(service_id or "WEEKDAY").strip().upper() or "WEEKDAY"
    return _DAY_TYPE_BY_SERVICE_ID.get(normalized, "weekday")


def day_type_to_service_id(day_type: str | None) -> str:
    normalized = str(day_type or "weekday").strip().lower() or "weekday"
    return _SERVICE_ID_BY_DAY_TYPE.get(normalized, "WEEKDAY")


def _normalize_clock_string(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = raw.split(":")
    if len(parts) >= 2:
        return f"{parts[0]}:{parts[1]}"
    return raw


def selected_day_types(service_ids: Iterable[str] | None) -> List[str]:
    if not service_ids:
        return list(_DEFAULT_DAY_TYPES)
    seen: list[str] = []
    for service_id in service_ids:
        day_type = service_id_to_day_type(service_id)
        if day_type not in seen:
            seen.append(day_type)
    return seen or list(_DEFAULT_DAY_TYPES)


def load_manifest(
    dataset_id: str | None = None,
    *,
    shard_root: Path | None = None,
) -> Optional[Dict[str, Any]]:
    root = shard_root or TOKYU_SHARD_ROOT
    path = root / "manifest.json"
    if not path.exists():
        return None
    payload = _read_json(path)
    if not isinstance(payload, dict):
        return None
    if dataset_id and str(payload.get("dataset_id") or "") != str(dataset_id):
        return None
    payload["manifest_path"] = str(path)
    return payload


def shard_runtime_ready(
    dataset_id: str | None = None,
    *,
    shard_root: Path | None = None,
) -> bool:
    manifest = load_manifest(dataset_id, shard_root=shard_root)
    if not manifest:
        return False
    required_files = (
        "depots.json",
        "routes.json",
        "depot_route_index.json",
        "depot_route_summary.json",
        "shard_manifest.json",
    )
    root = shard_root or TOKYU_SHARD_ROOT
    return all((root / name).exists() for name in required_files)


def _load_named_artifact(
    name: str,
    *,
    dataset_id: str | None = None,
    shard_root: Path | None = None,
) -> Any:
    if not shard_runtime_ready(dataset_id, shard_root=shard_root):
        return None
    root = shard_root or TOKYU_SHARD_ROOT
    path = root / name
    if not path.exists():
        return None
    return _read_json(path)


def load_depots(
    dataset_id: str | None = None,
    *,
    shard_root: Path | None = None,
) -> List[Dict[str, Any]]:
    payload = _load_named_artifact("depots.json", dataset_id=dataset_id, shard_root=shard_root)
    if not isinstance(payload, dict):
        return []
    return [dict(item) for item in payload.get("depots") or [] if isinstance(item, dict)]


def load_routes(
    dataset_id: str | None = None,
    *,
    shard_root: Path | None = None,
) -> List[Dict[str, Any]]:
    payload = _load_named_artifact("routes.json", dataset_id=dataset_id, shard_root=shard_root)
    if not isinstance(payload, dict):
        return []
    return [dict(item) for item in payload.get("routes") or [] if isinstance(item, dict)]


def load_depot_route_index(
    dataset_id: str | None = None,
    *,
    shard_root: Path | None = None,
) -> Dict[str, Any]:
    payload = _load_named_artifact(
        "depot_route_index.json",
        dataset_id=dataset_id,
        shard_root=shard_root,
    )
    return dict(payload) if isinstance(payload, dict) else {"depots": [], "routes": []}


def load_depot_route_summary(
    dataset_id: str | None = None,
    *,
    shard_root: Path | None = None,
) -> List[Dict[str, Any]]:
    payload = _load_named_artifact(
        "depot_route_summary.json",
        dataset_id=dataset_id,
        shard_root=shard_root,
    )
    if not isinstance(payload, dict):
        return []
    return [dict(item) for item in payload.get("items") or [] if isinstance(item, dict)]


def load_shard_manifest_entries(
    dataset_id: str | None = None,
    *,
    shard_root: Path | None = None,
) -> List[Dict[str, Any]]:
    payload = _load_named_artifact(
        "shard_manifest.json",
        dataset_id=dataset_id,
        shard_root=shard_root,
    )
    if not isinstance(payload, dict):
        return []
    return [dict(item) for item in payload.get("items") or [] if isinstance(item, dict)]


def _route_pairs_for_scope(
    route_ids: Iterable[str] | None,
    depot_ids: Iterable[str] | None,
    *,
    index_payload: Dict[str, Any],
) -> List[Tuple[str, str]]:
    depots = [_normalize_token(item) for item in depot_ids or [] if str(item or "").strip()]
    route_id_list = [str(item) for item in route_ids or [] if str(item or "").strip()]

    route_index = {
        _normalize_token(item.get("route_id")): dict(item)
        for item in index_payload.get("routes") or []
        if isinstance(item, dict) and str(item.get("route_id") or "").strip()
    }
    depot_index = {
        _normalize_token(item.get("depot_id")): dict(item)
        for item in index_payload.get("depots") or []
        if isinstance(item, dict) and str(item.get("depot_id") or "").strip()
    }

    pairs: set[Tuple[str, str]] = set()
    if route_id_list:
        for scoped_id in route_id_list:
            route_id = route_code_from_scoped_route_id(scoped_id)
            scoped_depot = depot_id_from_scoped_route_id(scoped_id)
            if scoped_depot:
                pairs.add((scoped_depot, route_id))
                continue
            candidate_depots = [
                _normalize_token(item)
                for item in (route_index.get(route_id) or {}).get("depot_ids") or []
                if str(item or "").strip()
            ]
            if depots:
                candidate_depots = [depot for depot in candidate_depots if depot in depots]
            for depot_id in candidate_depots:
                pairs.add((depot_id, route_id))
    elif depots:
        for depot_id in depots:
            for route_id in (depot_index.get(depot_id) or {}).get("route_ids") or []:
                normalized_route_id = _normalize_token(route_id)
                if normalized_route_id:
                    pairs.add((depot_id, normalized_route_id))
    else:
        for item in index_payload.get("depots") or []:
            if not isinstance(item, dict):
                continue
            depot_id = str(item.get("depot_id") or "").strip()
            for route_id in item.get("route_ids") or []:
                normalized_route_id = _normalize_token(route_id)
                if depot_id and normalized_route_id:
                    pairs.add((_normalize_token(depot_id), normalized_route_id))
    return sorted(pairs)


def _selected_manifest_entries(
    *,
    dataset_id: str | None,
    route_ids: Iterable[str] | None,
    depot_ids: Iterable[str] | None,
    service_ids: Iterable[str] | None,
    artifact_kind: str,
    shard_root: Path | None = None,
) -> List[Dict[str, Any]]:
    index_payload = load_depot_route_index(dataset_id, shard_root=shard_root)
    route_pairs = set(_route_pairs_for_scope(route_ids, depot_ids, index_payload=index_payload))
    day_types = set(selected_day_types(service_ids))
    selected: List[Dict[str, Any]] = []
    for entry in load_shard_manifest_entries(dataset_id, shard_root=shard_root):
        if str(entry.get("artifact_kind") or "") != artifact_kind:
            continue
        route_pair = (
            str(entry.get("depot_id") or ""),
            str(entry.get("route_id") or ""),
        )
        if route_pairs and route_pair not in route_pairs:
            continue
        if str(entry.get("day_type") or "") not in day_types:
            continue
        selected.append(entry)
    return selected


def _load_shard_items(entries: Iterable[Dict[str, Any]], *, shard_root: Path | None = None) -> List[Dict[str, Any]]:
    root = shard_root or TOKYU_SHARD_ROOT
    items: List[Dict[str, Any]] = []
    for entry in entries:
        artifact_path = str(entry.get("artifact_path") or "").strip()
        if not artifact_path:
            continue
        payload = _read_json(_artifact_path(root, artifact_path))
        if not isinstance(payload, dict):
            continue
        for item in payload.get("items") or []:
            if isinstance(item, dict):
                items.append(dict(item))
    return items


def load_trip_rows_for_scope(
    *,
    dataset_id: str | None,
    route_ids: Iterable[str] | None,
    depot_ids: Iterable[str] | None,
    service_ids: Iterable[str] | None,
    shard_root: Path | None = None,
) -> List[Dict[str, Any]]:
    entries = _selected_manifest_entries(
        dataset_id=dataset_id,
        route_ids=route_ids,
        depot_ids=depot_ids,
        service_ids=service_ids,
        artifact_kind="trip_shard",
        shard_root=shard_root,
    )
    rows: List[Dict[str, Any]] = []
    for item in _load_shard_items(entries, shard_root=shard_root):
        depot_id = str(item.get("depot_id") or "").strip()
        route_id = str(item.get("route_id") or "").strip()
        departure = _normalize_clock_string(item.get("departure_time"))
        arrival = _normalize_clock_string(item.get("arrival_time"))
        rows.append(
            {
                "trip_id": str(item.get("trip_id") or "").strip(),
                "route_id": f"tokyu:{depot_id}:{route_id}",
                "route_code": route_id,
                "depot_id": depot_id,
                "service_id": day_type_to_service_id(item.get("day_type")),
                "direction": str(item.get("direction") or "outbound"),
                "trip_index": int(item.get("trip_index") or 0),
                "origin": str(item.get("origin_name") or item.get("origin_stop_id") or ""),
                "destination": str(
                    item.get("destination_name") or item.get("destination_stop_id") or ""
                ),
                "origin_stop_id": str(item.get("origin_stop_id") or ""),
                "destination_stop_id": str(item.get("destination_stop_id") or ""),
                "departure": departure,
                "arrival": arrival,
                "departure_time": departure,
                "arrival_time": arrival,
                "distance_km": float(item.get("distance_hint_km") or 0.0),
                "runtime_min": float(item.get("runtime_minutes") or 0.0),
                "allowed_vehicle_types": list(item.get("allowed_vehicle_types") or ["BEV", "ICE"]),
                "service_variant": str(item.get("service_variant") or "other"),
                "source": "tokyu_shard",
            }
        )
    rows.sort(
        key=lambda row: (
            str(row.get("service_id") or ""),
            str(row.get("departure") or ""),
            str(row.get("trip_id") or ""),
        )
    )
    return rows


def load_dispatch_trip_rows_for_scope(
    *,
    dataset_id: str | None,
    route_ids: Iterable[str] | None,
    depot_ids: Iterable[str] | None,
    service_ids: Iterable[str] | None,
    shard_root: Path | None = None,
) -> List[Dict[str, Any]]:
    rows = load_trip_rows_for_scope(
        dataset_id=dataset_id,
        route_ids=route_ids,
        depot_ids=depot_ids,
        service_ids=service_ids,
        shard_root=shard_root,
    )
    return [
        {
            "trip_id": row["trip_id"],
            "route_id": row["route_id"],
            "origin": row["origin"],
            "destination": row["destination"],
            "origin_stop_id": row.get("origin_stop_id"),
            "destination_stop_id": row.get("destination_stop_id"),
            "departure": row["departure"],
            "arrival": row["arrival"],
            "distance_km": row["distance_km"],
            "allowed_vehicle_types": list(row.get("allowed_vehicle_types") or ["BEV", "ICE"]),
            "direction": row["direction"],
            "source": "tokyu_shard",
        }
        for row in rows
    ]


def _stop_time_sequence(stop_time: Dict[str, Any]) -> int:
    raw_value = stop_time.get("seq")
    if raw_value in (None, ""):
        raw_value = stop_time.get("stop_sequence")
    try:
        return int(raw_value or 0)
    except (TypeError, ValueError):
        return 0


def _stop_time_clock(stop_time: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _normalize_clock_string(stop_time.get(key))
        if value:
            return value
    return ""


def load_stop_time_rows_for_scope(
    *,
    dataset_id: str | None,
    route_ids: Iterable[str] | None,
    depot_ids: Iterable[str] | None,
    service_ids: Iterable[str] | None,
    shard_root: Path | None = None,
) -> List[Dict[str, Any]]:
    entries = _selected_manifest_entries(
        dataset_id=dataset_id,
        route_ids=route_ids,
        depot_ids=depot_ids,
        service_ids=service_ids,
        artifact_kind="stop_time_shard",
        shard_root=shard_root,
    )
    rows: List[Dict[str, Any]] = []
    for trip in _load_shard_items(entries, shard_root=shard_root):
        depot_id = str(trip.get("depot_id") or "").strip()
        route_id = str(trip.get("route_id") or "").strip()
        trip_id = str(trip.get("trip_id") or "").strip()
        service_id = day_type_to_service_id(trip.get("day_type"))
        scoped_route_id = f"tokyu:{depot_id}:{route_id}"
        for stop_time in trip.get("stop_times") or []:
            if not isinstance(stop_time, dict):
                continue
            stop_sequence = _stop_time_sequence(stop_time)
            arrival = _stop_time_clock(stop_time, "arrival", "arrival_time")
            departure = _stop_time_clock(stop_time, "departure", "departure_time")
            rows.append(
                {
                    "trip_id": trip_id,
                    "route_id": scoped_route_id,
                    "route_code": route_id,
                    "depot_id": depot_id,
                    "service_id": service_id,
                    "direction": str(trip.get("direction") or "outbound"),
                    "stop_id": str(stop_time.get("stop_id") or "").strip(),
                    "stop_name": str(
                        stop_time.get("stop_name")
                        or stop_time.get("stop_id")
                        or ""
                    ).strip(),
                    "stop_sequence": stop_sequence,
                    "seq": stop_sequence,
                    "arrival": arrival,
                    "departure": departure,
                    "arrival_time": arrival,
                    "departure_time": departure,
                    "origin_stop_id": str(trip.get("origin_stop_id") or "").strip(),
                    "destination_stop_id": str(trip.get("destination_stop_id") or "").strip(),
                    "source": "tokyu_shard",
                }
            )
    rows.sort(
        key=lambda row: (
            str(row.get("service_id") or ""),
            str(row.get("trip_id") or ""),
            int(row.get("stop_sequence") or 0),
        )
    )
    return rows


def build_timetable_summary_from_rows(
    rows: Iterable[Dict[str, Any]],
    *,
    updated_at: str | None = None,
    imports: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    materialized_rows = [dict(row) for row in rows if isinstance(row, dict)]
    by_service: Dict[str, Dict[str, Any]] = {}
    by_route: Dict[str, Dict[str, Any]] = {}
    route_service_counts: Dict[str, Dict[str, int]] = {}
    stop_counts: Dict[str, int] = {}

    for row in materialized_rows:
        service_id = str(row.get("service_id") or "WEEKDAY")
        route_id = str(row.get("route_id") or "")
        departure = str(row.get("departure") or "")
        arrival = str(row.get("arrival") or "")
        origin = str(row.get("origin") or "")
        destination = str(row.get("destination") or "")
        trip_id = str(row.get("trip_id") or "")

        service_bucket = by_service.setdefault(
            service_id,
            {
                "serviceId": service_id,
                "rowCount": 0,
                "routeIds": set(),
                "departures": [],
                "arrivals": [],
            },
        )
        service_bucket["rowCount"] += 1
        if route_id:
            service_bucket["routeIds"].add(route_id)
        if departure:
            service_bucket["departures"].append(departure)
        if arrival:
            service_bucket["arrivals"].append(arrival)

        route_bucket = by_route.setdefault(
            route_id or "__unknown__",
            {
                "routeId": route_id,
                "rowCount": 0,
                "serviceIds": set(),
                "departures": [],
                "arrivals": [],
                "sampleTripIds": [],
            },
        )
        route_bucket["rowCount"] += 1
        route_bucket["serviceIds"].add(service_id)
        if departure:
            route_bucket["departures"].append(departure)
        if arrival:
            route_bucket["arrivals"].append(arrival)
        if trip_id and len(route_bucket["sampleTripIds"]) < 5:
            route_bucket["sampleTripIds"].append(trip_id)

        route_service_counts.setdefault(service_id, {})
        if route_id:
            route_service_counts[service_id][route_id] = (
                route_service_counts[service_id].get(route_id, 0) + 1
            )

        if origin:
            stop_counts[origin] = stop_counts.get(origin, 0) + 1
        if destination:
            stop_counts[destination] = stop_counts.get(destination, 0) + 1

    def _min_time(values: Iterable[str]) -> Optional[str]:
        usable = [value for value in values if value]
        return min(usable) if usable else None

    def _max_time(values: Iterable[str]) -> Optional[str]:
        usable = [value for value in values if value]
        return max(usable) if usable else None

    return {
        "totalRows": len(materialized_rows),
        "serviceCount": len(by_service),
        "routeCount": len([key for key in by_route.keys() if key != "__unknown__"]),
        "stopCount": len(stop_counts),
        "updatedAt": updated_at,
        "byService": sorted(
            [
                {
                    "serviceId": bucket["serviceId"],
                    "rowCount": bucket["rowCount"],
                    "routeCount": len(bucket["routeIds"]),
                    "firstDeparture": _min_time(bucket["departures"]),
                    "lastArrival": _max_time(bucket["arrivals"]),
                }
                for bucket in by_service.values()
            ],
            key=lambda item: str(item.get("serviceId") or ""),
        ),
        "byRoute": sorted(
            [
                {
                    "routeId": bucket["routeId"],
                    "rowCount": bucket["rowCount"],
                    "serviceCount": len(bucket["serviceIds"]),
                    "firstDeparture": _min_time(bucket["departures"]),
                    "lastArrival": _max_time(bucket["arrivals"]),
                    "sampleTripIds": bucket["sampleTripIds"],
                }
                for bucket in by_route.values()
                if bucket["routeId"]
            ],
            key=lambda item: (
                str(item.get("routeId") or ""),
                str(item.get("firstDeparture") or ""),
            ),
        )[:200],
        "routeServiceCounts": route_service_counts,
        "previewTripIds": [
            str(row.get("trip_id") or "")
            for row in materialized_rows[: min(100, len(materialized_rows))]
            if row.get("trip_id")
        ],
        "imports": imports or {},
    }


def build_timetable_summary_for_scope(
    *,
    dataset_id: str | None,
    route_ids: Iterable[str] | None,
    depot_ids: Iterable[str] | None,
    service_ids: Iterable[str] | None = None,
    shard_root: Path | None = None,
) -> Optional[Dict[str, Any]]:
    manifest = load_manifest(dataset_id, shard_root=shard_root)
    if manifest is None:
        return None
    rows = load_trip_rows_for_scope(
        dataset_id=dataset_id,
        route_ids=route_ids,
        depot_ids=depot_ids,
        service_ids=service_ids,
        shard_root=shard_root,
    )
    return build_timetable_summary_from_rows(
        rows,
        updated_at=str(manifest.get("build_timestamp") or manifest.get("generated_at") or ""),
        imports={},
    )


def build_stop_timetable_summary_for_scope(
    *,
    dataset_id: str | None,
    route_ids: Iterable[str] | None,
    depot_ids: Iterable[str] | None,
    service_ids: Iterable[str] | None = None,
    shard_root: Path | None = None,
) -> Optional[Dict[str, Any]]:
    manifest = load_manifest(dataset_id, shard_root=shard_root)
    if manifest is None:
        return None
    entries = _selected_manifest_entries(
        dataset_id=dataset_id,
        route_ids=route_ids,
        depot_ids=depot_ids,
        service_ids=service_ids,
        artifact_kind="stop_time_shard",
        shard_root=shard_root,
    )
    total_timetables = 0
    total_entries = 0
    by_service: Dict[str, Dict[str, Any]] = {}
    by_stop: Dict[str, Dict[str, Any]] = {}

    for trip in _load_shard_items(entries, shard_root=shard_root):
        service_id = day_type_to_service_id(trip.get("day_type"))
        stop_times = [dict(item) for item in trip.get("stop_times") or [] if isinstance(item, dict)]
        total_timetables += 1
        total_entries += len(stop_times)
        service_bucket = by_service.setdefault(
            service_id,
            {
                "serviceId": service_id,
                "timetableCount": 0,
                "entryCount": 0,
                "stopIds": set(),
            },
        )
        service_bucket["timetableCount"] += 1
        service_bucket["entryCount"] += len(stop_times)
        for stop_time in stop_times:
            stop_id = str(stop_time.get("stop_id") or "").strip()
            stop_name = str(stop_time.get("stop_name") or stop_id).strip()
            if stop_id:
                service_bucket["stopIds"].add(stop_id)
            stop_bucket = by_stop.setdefault(
                stop_id or "__unknown__",
                {
                    "stopId": stop_id,
                    "stopName": stop_name,
                    "timetableCount": 0,
                    "entryCount": 0,
                    "serviceIds": set(),
                },
            )
            stop_bucket["timetableCount"] += 1
            stop_bucket["entryCount"] += 1
            stop_bucket["serviceIds"].add(service_id)

    return {
        "totalTimetables": total_timetables,
        "totalEntries": total_entries,
        "serviceCount": len(by_service),
        "stopCount": len([key for key in by_stop.keys() if key != "__unknown__"]),
        "updatedAt": str(manifest.get("build_timestamp") or manifest.get("generated_at") or ""),
        "byService": sorted(
            [
                {
                    "serviceId": bucket["serviceId"],
                    "timetableCount": bucket["timetableCount"],
                    "entryCount": bucket["entryCount"],
                    "stopCount": len(bucket["stopIds"]),
                }
                for bucket in by_service.values()
            ],
            key=lambda item: item["serviceId"],
        ),
        "byStop": sorted(
            [
                {
                    "stopId": bucket["stopId"],
                    "stopName": bucket["stopName"],
                    "timetableCount": bucket["timetableCount"],
                    "entryCount": bucket["entryCount"],
                    "serviceCount": len(bucket["serviceIds"]),
                }
                for bucket in by_stop.values()
                if bucket["stopId"]
            ],
            key=lambda item: (item["stopName"], item["stopId"]),
        )[:200],
        "imports": {},
    }
