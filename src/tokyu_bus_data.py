from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from src.tokyu_shard_loader import build_timetable_summary_from_rows


_REPO_ROOT = Path(__file__).resolve().parents[1]
TOKYU_BUS_DATA_ROOT = _REPO_ROOT / "data" / "catalog-fast" / "tokyu_bus_data"
_REQUIRED_FILES = (
    "summary.json",
    "route_index.json",
    "family_index.json",
    "routes.jsonl",
)
_DEFAULT_DATASET_ID = "tokyu_full"
_VN_TRIP_RE = re.compile(r"__v\d+$")


def _canonical_service_id(value: Any) -> str:
    raw = str(value or "").strip()
    upper = raw.upper()
    if upper in {"WEEKDAY", "WEEKDAYS"} or raw in {"weekday", "平日"}:
        return "WEEKDAY"
    if upper in {"SAT", "SATURDAY"} or raw in {"sat", "saturday", "土曜", "土曜日"}:
        return "SAT"
    if upper in {"SUN_HOL", "SUN_HOLIDAY", "HOLIDAY", "SUNDAY"} or raw in {
        "sun_hol",
        "holiday",
        "sunday",
        "日曜",
        "日曜・休日",
        "休日",
    }:
        return "SUN_HOL"
    return upper or "WEEKDAY"


def _normalize_dataset_id(dataset_id: str | None) -> str:
    return str(dataset_id or _DEFAULT_DATASET_ID).strip() or _DEFAULT_DATASET_ID


def tokyu_bus_data_root(dataset_id: str | None = None) -> Path | None:
    if _normalize_dataset_id(dataset_id) != _DEFAULT_DATASET_ID:
        return None
    return TOKYU_BUS_DATA_ROOT


def tokyu_bus_data_ready(dataset_id: str | None = None, *, root: Path | None = None) -> bool:
    base = root or tokyu_bus_data_root(dataset_id)
    if base is None:
        return False
    return all((base / name).exists() for name in _REQUIRED_FILES)


@lru_cache(maxsize=32)
def _read_json_cached(path_str: str) -> Any:
    return json.loads(Path(path_str).read_text(encoding="utf-8"))


@lru_cache(maxsize=32)
def _read_jsonl_cached(path_str: str) -> tuple[Dict[str, Any], ...]:
    path = Path(path_str)
    if not path.exists():
        return ()
    items: list[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if isinstance(payload, dict):
                items.append(dict(payload))
    return tuple(items)


def _resolve_root(dataset_id: str | None = None, *, root: Path | None = None) -> Path:
    base = root or tokyu_bus_data_root(dataset_id)
    if base is None:
        raise ValueError(f"tokyu_bus_data is unsupported for dataset_id={dataset_id!r}")
    return base


def load_summary(dataset_id: str | None = None, *, root: Path | None = None) -> Dict[str, Any]:
    base = _resolve_root(dataset_id, root=root)
    payload = _read_json_cached(str(base / "summary.json"))
    return dict(payload) if isinstance(payload, dict) else {}


def load_route_index(dataset_id: str | None = None, *, root: Path | None = None) -> List[Dict[str, Any]]:
    base = _resolve_root(dataset_id, root=root)
    payload = _read_json_cached(str(base / "route_index.json"))
    if not isinstance(payload, dict):
        return []
    return [dict(item) for item in payload.get("items") or [] if isinstance(item, dict)]


def load_family_index(dataset_id: str | None = None, *, root: Path | None = None) -> List[Dict[str, Any]]:
    base = _resolve_root(dataset_id, root=root)
    payload = _read_json_cached(str(base / "family_index.json"))
    if not isinstance(payload, dict):
        return []
    return [dict(item) for item in payload.get("items") or [] if isinstance(item, dict)]


def load_routes(dataset_id: str | None = None, *, root: Path | None = None) -> List[Dict[str, Any]]:
    base = _resolve_root(dataset_id, root=root)
    return [dict(item) for item in _read_jsonl_cached(str(base / "routes.jsonl"))]


def load_stops(dataset_id: str | None = None, *, root: Path | None = None) -> List[Dict[str, Any]]:
    base = _resolve_root(dataset_id, root=root)
    return [dict(item) for item in _read_jsonl_cached(str(base / "stops.jsonl"))]


def _selected_route_entries(
    *,
    dataset_id: str | None,
    route_ids: Iterable[str] | None,
    depot_ids: Iterable[str] | None,
    root: Path | None = None,
) -> List[Dict[str, Any]]:
    entries = load_route_index(dataset_id, root=root)
    if not entries:
        return []

    normalized_route_ids = {
        str(route_id).strip()
        for route_id in route_ids or []
        if str(route_id).strip()
    }
    normalized_depot_ids = {
        str(depot_id).strip()
        for depot_id in depot_ids or []
        if str(depot_id).strip()
    }

    if normalized_route_ids:
        entries = [
            dict(entry)
            for entry in entries
            if str(entry.get("routeId") or "").strip() in normalized_route_ids
        ]
    if normalized_depot_ids:
        entries = [
            dict(entry)
            for entry in entries
            if str(entry.get("depotId") or "").strip() in normalized_depot_ids
        ]
    return entries


def route_trip_counts_by_day_type(
    *,
    dataset_id: str | None,
    route_ids: Iterable[str] | None,
    depot_ids: Iterable[str] | None = None,
    root: Path | None = None,
) -> Dict[str, Dict[str, int]]:
    result: Dict[str, Dict[str, int]] = {}
    for entry in _selected_route_entries(
        dataset_id=dataset_id,
        route_ids=route_ids,
        depot_ids=depot_ids,
        root=root,
    ):
        route_id = str(entry.get("routeId") or "").strip()
        if not route_id:
            continue
        result[route_id] = {
            _canonical_service_id(service_id): int(value or 0)
            for service_id, value in dict(entry.get("tripCountsByDayType") or {}).items()
        }
    return result


def _service_filter(service_ids: Iterable[str] | None) -> set[str] | None:
    normalized = {
        _canonical_service_id(service_id)
        for service_id in service_ids or []
        if str(service_id or "").strip()
    }
    return normalized or None


def _is_vn_duplicate_trip_id(value: Any) -> bool:
    return bool(_VN_TRIP_RE.search(str(value or "").strip()))


def _read_selected_jsonl(
    *,
    dataset_id: str | None,
    route_ids: Iterable[str] | None,
    depot_ids: Iterable[str] | None,
    file_key: str,
    service_ids: Iterable[str] | None = None,
    root: Path | None = None,
) -> List[Dict[str, Any]]:
    base = _resolve_root(dataset_id, root=root)
    selected_services = _service_filter(service_ids)
    rows: List[Dict[str, Any]] = []
    for entry in _selected_route_entries(
        dataset_id=dataset_id,
        route_ids=route_ids,
        depot_ids=depot_ids,
        root=root,
    ):
        relative_path = str(entry.get(file_key) or "").strip()
        if not relative_path:
            continue
        for row in _read_jsonl_cached(str(base / relative_path)):
            if _is_vn_duplicate_trip_id(row.get("trip_id")):
                continue
            normalized_service_id = _canonical_service_id(row.get("service_id"))
            if selected_services and normalized_service_id not in selected_services:
                continue
            materialized = dict(row)
            materialized["service_id"] = normalized_service_id
            rows.append(materialized)
    return rows


def load_trip_rows_for_scope(
    *,
    dataset_id: str | None,
    route_ids: Iterable[str] | None,
    depot_ids: Iterable[str] | None,
    service_ids: Iterable[str] | None = None,
    root: Path | None = None,
) -> List[Dict[str, Any]]:
    rows = _read_selected_jsonl(
        dataset_id=dataset_id,
        route_ids=route_ids,
        depot_ids=depot_ids,
        service_ids=service_ids,
        file_key="tripFile",
        root=root,
    )
    rows.sort(
        key=lambda row: (
            str(row.get("service_id") or ""),
            str(row.get("departure") or row.get("departure_time") or ""),
            str(row.get("trip_id") or ""),
        )
    )
    return rows


def load_stop_time_rows_for_scope(
    *,
    dataset_id: str | None,
    route_ids: Iterable[str] | None,
    depot_ids: Iterable[str] | None,
    service_ids: Iterable[str] | None = None,
    root: Path | None = None,
) -> List[Dict[str, Any]]:
    rows = _read_selected_jsonl(
        dataset_id=dataset_id,
        route_ids=route_ids,
        depot_ids=depot_ids,
        service_ids=service_ids,
        file_key="stopTimeFile",
        root=root,
    )
    rows.sort(
        key=lambda row: (
            str(row.get("service_id") or ""),
            str(row.get("trip_id") or ""),
            int(row.get("sequence") or row.get("stop_sequence") or 0),
        )
    )
    return rows


def load_stop_timetable_rows_for_scope(
    *,
    dataset_id: str | None,
    route_ids: Iterable[str] | None,
    depot_ids: Iterable[str] | None,
    service_ids: Iterable[str] | None = None,
    root: Path | None = None,
) -> List[Dict[str, Any]]:
    rows = _read_selected_jsonl(
        dataset_id=dataset_id,
        route_ids=route_ids,
        depot_ids=depot_ids,
        service_ids=service_ids,
        file_key="stopTimetableFile",
        root=root,
    )
    rows.sort(
        key=lambda row: (
            str(row.get("service_id") or ""),
            str(row.get("stopId") or ""),
            str(row.get("id") or ""),
        )
    )
    return rows


def build_timetable_summary_for_scope(
    *,
    dataset_id: str | None,
    route_ids: Sequence[str] | None,
    depot_ids: Sequence[str] | None,
    service_ids: Sequence[str] | None = None,
    root: Path | None = None,
) -> Dict[str, Any] | None:
    if not tokyu_bus_data_ready(dataset_id, root=root):
        return None

    selected_services = _service_filter(service_ids)
    by_service: Dict[str, Dict[str, Any]] = {}
    by_route: List[Dict[str, Any]] = []
    preview_trip_ids: List[str] = []
    route_service_counts: Dict[str, Dict[str, int]] = {}

    for entry in _selected_route_entries(
        dataset_id=dataset_id,
        route_ids=route_ids,
        depot_ids=depot_ids,
        root=root,
    ):
        route_id = str(entry.get("routeId") or "").strip()
        if not route_id:
            continue
        counts = {
            _canonical_service_id(service_id): int(value or 0)
            for service_id, value in dict(entry.get("tripCountsByDayType") or {}).items()
        }
        departures = {
            _canonical_service_id(service_id): str(value or "")
            for service_id, value in dict(entry.get("firstDepartureByDayType") or {}).items()
        }
        arrivals = {
            _canonical_service_id(service_id): str(value or "")
            for service_id, value in dict(entry.get("lastArrivalByDayType") or {}).items()
        }
        active_service_ids: list[str] = []
        route_first_departures: list[str] = []
        route_last_arrivals: list[str] = []
        route_total = 0

        for service_id, count in sorted(counts.items()):
            if selected_services and service_id not in selected_services:
                continue
            if count <= 0:
                continue
            bucket = by_service.setdefault(
                service_id,
                {
                    "serviceId": service_id,
                    "rowCount": 0,
                    "routeIds": set(),
                    "departures": [],
                    "arrivals": [],
                },
            )
            bucket["rowCount"] += count
            bucket["routeIds"].add(route_id)
            if departures.get(service_id):
                bucket["departures"].append(departures[service_id])
                route_first_departures.append(departures[service_id])
            if arrivals.get(service_id):
                bucket["arrivals"].append(arrivals[service_id])
                route_last_arrivals.append(arrivals[service_id])
            route_service_counts.setdefault(service_id, {})[route_id] = count
            active_service_ids.append(service_id)
            route_total += count

        if route_total <= 0:
            continue

        sample_trip_ids = [
            str(value).strip()
            for value in list(entry.get("sampleTripIds") or [])
            if str(value).strip() and not _is_vn_duplicate_trip_id(value)
        ]
        for trip_id in sample_trip_ids:
            if trip_id not in preview_trip_ids and len(preview_trip_ids) < 100:
                preview_trip_ids.append(trip_id)

        by_route.append(
            {
                "routeId": route_id,
                "rowCount": route_total,
                "serviceCount": len(active_service_ids),
                "firstDeparture": min(route_first_departures) if route_first_departures else None,
                "lastArrival": max(route_last_arrivals) if route_last_arrivals else None,
                "sampleTripIds": sample_trip_ids[:5],
            }
        )

    summary = load_summary(dataset_id, root=root)
    return {
        "totalRows": sum(bucket["rowCount"] for bucket in by_service.values()),
        "serviceCount": len(by_service),
        "routeCount": len(by_route),
        "stopCount": int((summary.get("counts") or {}).get("stops") or 0),
        "updatedAt": str(summary.get("generatedAt") or ""),
        "byService": sorted(
            [
                {
                    "serviceId": bucket["serviceId"],
                    "rowCount": bucket["rowCount"],
                    "routeCount": len(bucket["routeIds"]),
                    "firstDeparture": min(bucket["departures"]) if bucket["departures"] else None,
                    "lastArrival": max(bucket["arrivals"]) if bucket["arrivals"] else None,
                }
                for bucket in by_service.values()
            ],
            key=lambda item: str(item.get("serviceId") or ""),
        ),
        "byRoute": sorted(
            by_route,
            key=lambda item: (
                str(item.get("routeId") or ""),
                str(item.get("firstDeparture") or ""),
            ),
        )[:200],
        "routeServiceCounts": route_service_counts,
        "previewTripIds": preview_trip_ids,
        "imports": {},
    }


def build_timetable_summary_from_trip_files(
    *,
    dataset_id: str | None,
    route_ids: Sequence[str] | None,
    depot_ids: Sequence[str] | None,
    service_ids: Sequence[str] | None = None,
    root: Path | None = None,
) -> Dict[str, Any] | None:
    if not tokyu_bus_data_ready(dataset_id, root=root):
        return None
    rows = load_trip_rows_for_scope(
        dataset_id=dataset_id,
        route_ids=route_ids,
        depot_ids=depot_ids,
        service_ids=service_ids,
        root=root,
    )
    return build_timetable_summary_from_rows(
        rows,
        updated_at=str(load_summary(dataset_id, root=root).get("generatedAt") or ""),
        imports={},
    )
