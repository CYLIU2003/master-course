from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_FAST_ROOT = REPO_ROOT / "data" / "catalog-fast"
CATALOG_FAST_NORMALIZED_ROOT = CATALOG_FAST_ROOT / "normalized"
TOKYU_BUS_DATA_ROOT = CATALOG_FAST_ROOT / "tokyu_bus_data"
TOKYUBUS_CANONICAL_ROOT = REPO_ROOT / "data" / "tokyubus" / "canonical"
TOKYUBUS_RAW_ROOT = REPO_ROOT / "data" / "tokyubus" / "raw"
BUILT_DIR = REPO_ROOT / "data" / "built" / "tokyu_full"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_dump(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _iter_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if isinstance(payload, dict):
                yield dict(payload)


def _read_json(path: Path) -> Dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def _read_jsonl_rows(path: Path) -> list[Dict[str, Any]]:
    return [dict(item) for item in _iter_jsonl(path)]


def _write_jsonl_rows(path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False))
            fh.write("\n")
            count += 1
    return count


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


def _hhmm(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parts = raw.split(":")
    if len(parts) < 2:
        return raw
    return f"{int(parts[0]):02d}:{int(parts[1]):02d}"


def _float_or_zero(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _int_or_zero(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")


def _reset_output_root(output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    for rel in (
        "trips.jsonl",
        "stop_times.jsonl",
        "busstop_pole_timetables.jsonl",
        "routes.jsonl",
        "stops.jsonl",
        "route_index.json",
        "family_index.json",
        "summary.json",
    ):
        path = output_root / rel
        if path.exists():
            path.unlink()
    for rel in ("route_trips", "route_stop_times", "route_stop_timetables"):
        path = output_root / rel
        if path.exists():
            shutil.rmtree(path)


def _latest_complete_canonical_snapshot(base_dir: Path) -> Path:
    candidates: list[Path] = []
    for path in sorted(base_dir.iterdir(), reverse=True):
        if not path.is_dir():
            continue
        summary_path = path / "canonical_summary.json"
        if not summary_path.exists():
            continue
        summary = _read_json(summary_path)
        entity_counts = dict(summary.get("entity_counts") or {})
        if _int_or_zero(entity_counts.get("trips")) <= 1000:
            continue
        if _int_or_zero(entity_counts.get("stop_timetables")) <= 1000:
            continue
        candidates.append(path)
    if not candidates:
        raise RuntimeError("No complete Tokyu canonical snapshot was found under data/tokyubus/canonical")
    return candidates[0]


@dataclass
class JsonlWriterCache:
    root: Path
    max_open: int = 64

    def __post_init__(self) -> None:
        self._handles: "OrderedDict[str, Any]" = OrderedDict()

    def write(self, relative_path: str, row: Dict[str, Any]) -> None:
        path = self.root / relative_path
        key = str(path)
        handle = self._handles.pop(key, None)
        if handle is None:
            if len(self._handles) >= self.max_open:
                _, stale = self._handles.popitem(last=False)
                stale.close()
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.open("a", encoding="utf-8", newline="\n")
        self._handles[key] = handle
        handle.write(json.dumps(row, ensure_ascii=False))
        handle.write("\n")

    def close(self) -> None:
        while self._handles:
            _, handle = self._handles.popitem(last=False)
            handle.close()


def _route_file_path(kind: str, route_id: str) -> str:
    return f"{kind}/{route_id}.jsonl"


def build_tokyu_bus_data(
    *,
    canonical_snapshot_dir: Path,
    output_root: Path,
    rebuild_built: bool,
) -> Dict[str, Any]:
    summary = _read_json(canonical_snapshot_dir / "canonical_summary.json")
    snapshot_id = str(summary.get("snapshot_id") or canonical_snapshot_dir.name)
    raw_snapshot_dir = TOKYUBUS_RAW_ROOT / snapshot_id

    _reset_output_root(output_root)

    catalog_routes = _read_jsonl_rows(CATALOG_FAST_NORMALIZED_ROOT / "routes.jsonl")
    catalog_stops = _read_jsonl_rows(CATALOG_FAST_NORMALIZED_ROOT / "stops.jsonl")
    pattern_to_route = {
        str(route.get("odptPatternId") or "").strip(): dict(route)
        for route in catalog_routes
        if str(route.get("odptPatternId") or "").strip() and str(route.get("id") or "").strip()
    }
    routes_by_id = {
        str(route.get("id") or "").strip(): dict(route)
        for route in catalog_routes
        if str(route.get("id") or "").strip()
    }
    stops_by_id = {
        str(stop.get("id") or "").strip(): dict(stop)
        for stop in catalog_stops
        if str(stop.get("id") or "").strip()
    }

    route_stats: Dict[str, Dict[str, Any]] = {}
    family_stats: Dict[str, Dict[str, Any]] = {}
    trip_route_map: Dict[str, Dict[str, Any]] = {}
    trip_count = 0
    stop_time_count = 0
    route_stop_timetable_count = 0
    route_stop_timetable_item_count = 0

    def ensure_route_stat(route: Dict[str, Any]) -> Dict[str, Any]:
        route_id = str(route.get("id") or "").strip()
        stat = route_stats.get(route_id)
        if stat is not None:
            return stat
        route_code = str(route.get("routeCode") or "").strip()
        route_family_code = str(route.get("routeFamilyCode") or route_code).strip() or route_code
        route_family_label = str(
            route.get("routeFamilyLabel") or route.get("routeLabel") or route_code
        ).strip() or route_family_code
        trip_file = _route_file_path("route_trips", route_id)
        stop_time_file = _route_file_path("route_stop_times", route_id)
        stop_timetable_file = _route_file_path("route_stop_timetables", route_id)
        stat = {
            "routeId": route_id,
            "routeCode": route_code,
            "routeLabel": str(route.get("routeLabel") or route.get("name") or route_code).strip(),
            "routeFamilyCode": route_family_code,
            "routeFamilyLabel": route_family_label,
            "depotId": str(route.get("depotId") or "").strip(),
            "tripCountsByDayType": {"WEEKDAY": 0, "SAT": 0, "SUN_HOL": 0},
            "firstDepartureByDayType": {},
            "lastArrivalByDayType": {},
            "sampleTripIds": [],
            "tripFile": trip_file,
            "stopTimeFile": stop_time_file,
            "stopTimetableFile": stop_timetable_file,
            "stopTimetableCount": 0,
            "stopTimetableItemCount": 0,
        }
        route_stats[route_id] = stat
        family = family_stats.setdefault(
            route_family_code,
            {
                "routeFamilyCode": route_family_code,
                "routeFamilyLabel": route_family_label,
                "routeIds": [],
                "routeCodes": [],
                "depotIds": [],
                "tripCountsByDayType": {"WEEKDAY": 0, "SAT": 0, "SUN_HOL": 0},
                "tripFiles": [],
                "stopTimeFiles": [],
                "stopTimetableFiles": [],
            },
        )
        if route_id not in family["routeIds"]:
            family["routeIds"].append(route_id)
        if route_code and route_code not in family["routeCodes"]:
            family["routeCodes"].append(route_code)
        depot_id = str(route.get("depotId") or "").strip()
        if depot_id and depot_id not in family["depotIds"]:
            family["depotIds"].append(depot_id)
        file_value_by_key = {
            "tripFiles": stat["tripFile"],
            "stopTimeFiles": stat["stopTimeFile"],
            "stopTimetableFiles": stat["stopTimetableFile"],
        }
        for key, value in file_value_by_key.items():
            if value not in family[key]:
                family[key].append(value)
        return stat

    trip_writer = JsonlWriterCache(output_root)
    stop_time_writer = JsonlWriterCache(output_root)
    stop_timetable_writer = JsonlWriterCache(output_root)
    global_trips = (output_root / "trips.jsonl").open("w", encoding="utf-8", newline="\n")
    global_stop_times = (output_root / "stop_times.jsonl").open("w", encoding="utf-8", newline="\n")
    global_stop_timetables = (
        output_root / "busstop_pole_timetables.jsonl"
    ).open("w", encoding="utf-8", newline="\n")

    try:
        for row in _iter_jsonl(canonical_snapshot_dir / "trips.jsonl"):
            pattern_id = str(row.get("odpt_pattern_id") or row.get("pattern_id") or "").strip()
            route = pattern_to_route.get(pattern_id)
            if route is None:
                continue
            stat = ensure_route_stat(route)
            route_id = stat["routeId"]
            service_id = _canonical_service_id(row.get("service_id"))
            departure = _hhmm(row.get("departure_time"))
            arrival = _hhmm(row.get("arrival_time"))
            origin_stop_id = str(row.get("origin_stop_id") or "").strip()
            destination_stop_id = str(row.get("destination_stop_id") or "").strip()
            origin_stop = stops_by_id.get(origin_stop_id) or {}
            destination_stop = stops_by_id.get(destination_stop_id) or {}
            trip_id = str(row.get("trip_id") or "").strip()

            trip_row = {
                "trip_id": trip_id,
                "route_id": route_id,
                "routeCode": stat["routeCode"],
                "routeLabel": stat["routeLabel"],
                "routeFamilyCode": stat["routeFamilyCode"],
                "routeFamilyLabel": stat["routeFamilyLabel"],
                "routeVariantType": route.get("routeVariantType"),
                "canonicalDirection": route.get("canonicalDirection"),
                "service_id": service_id,
                "direction": str(row.get("direction") or route.get("canonicalDirection") or "outbound"),
                "trip_index": _int_or_zero(row.get("trip_index")),
                "origin": str(row.get("origin_name") or origin_stop.get("name") or origin_stop_id),
                "destination": str(
                    row.get("destination_name") or destination_stop.get("name") or destination_stop_id
                ),
                "origin_stop_id": origin_stop_id,
                "destination_stop_id": destination_stop_id,
                "origin_lat": origin_stop.get("lat"),
                "origin_lon": origin_stop.get("lon"),
                "destination_lat": destination_stop.get("lat"),
                "destination_lon": destination_stop.get("lon"),
                "departure": departure,
                "arrival": arrival,
                "distance_km": _float_or_zero(row.get("distance_km") or route.get("distanceKm")),
                "runtime_min": _float_or_zero(row.get("runtime_min")),
                "allowed_vehicle_types": list(row.get("allowed_vehicle_types") or ["BEV", "ICE"]),
                "odptPatternId": pattern_id,
                "odptTimetableId": row.get("odpt_timetable_id") or trip_id,
                "source": "tokyu_bus_data",
            }

            global_trips.write(json.dumps(trip_row, ensure_ascii=False))
            global_trips.write("\n")
            trip_writer.write(stat["tripFile"], trip_row)
            trip_count += 1

            trip_route_map[trip_id] = {
                "route_id": route_id,
                "service_id": service_id,
                "stop_time_file": stat["stopTimeFile"],
            }
            stat["tripCountsByDayType"][service_id] += 1
            if departure:
                current = stat["firstDepartureByDayType"].get(service_id)
                if current is None or departure < current:
                    stat["firstDepartureByDayType"][service_id] = departure
            if arrival:
                current = stat["lastArrivalByDayType"].get(service_id)
                if current is None or arrival > current:
                    stat["lastArrivalByDayType"][service_id] = arrival
            if trip_id and len(stat["sampleTripIds"]) < 5:
                stat["sampleTripIds"].append(trip_id)
            family_stats[stat["routeFamilyCode"]]["tripCountsByDayType"][service_id] += 1

        for row in _iter_jsonl(canonical_snapshot_dir / "stop_times.jsonl"):
            trip_id = str(row.get("trip_id") or "").strip()
            trip_meta = trip_route_map.get(trip_id)
            if trip_meta is None:
                continue
            stop_time_row = {
                "trip_id": trip_id,
                "route_id": trip_meta["route_id"],
                "service_id": trip_meta["service_id"],
                "stop_id": str(row.get("stop_id") or "").strip(),
                "stop_name": str(row.get("stop_name") or row.get("stop_id") or "").strip(),
                "sequence": _int_or_zero(row.get("stop_sequence")),
                "arrival": _hhmm(row.get("arrival_time")),
                "departure": _hhmm(row.get("departure_time")),
                "source": "tokyu_bus_data",
            }
            global_stop_times.write(json.dumps(stop_time_row, ensure_ascii=False))
            global_stop_times.write("\n")
            stop_time_writer.write(trip_meta["stop_time_file"], stop_time_row)
            stop_time_count += 1

        for row in _iter_jsonl(canonical_snapshot_dir / "stop_timetables.jsonl"):
            base_id = str(row.get("timetable_id") or row.get("id") or "").strip()
            if not base_id:
                continue
            service_id = _canonical_service_id(row.get("service_id"))
            calendar = str(row.get("odpt_calendar_raw") or row.get("calendar") or service_id).strip()
            stop_id = str(row.get("stop_id") or row.get("stopId") or "").strip()
            stop_name = str(row.get("stop_name") or row.get("stopName") or stop_id).strip()
            grouped_items: Dict[str, list[Dict[str, Any]]] = defaultdict(list)
            for item in list(row.get("items") or []):
                if not isinstance(item, dict):
                    continue
                pattern_id = str(
                    item.get("busroutePattern") or item.get("busroute_pattern") or ""
                ).strip()
                route = pattern_to_route.get(pattern_id)
                if route is None:
                    continue
                stat = ensure_route_stat(route)
                route_id = stat["routeId"]
                destination_id = str(item.get("destination") or "").strip()
                destination_stop = stops_by_id.get(destination_id) or {}
                grouped_items[route_id].append(
                    {
                        "departure": _hhmm(item.get("departure")),
                        "destination": destination_id,
                        "destinationName": str(destination_stop.get("name") or destination_id),
                        "busroutePattern": pattern_id,
                        "busroute": route.get("odptBusrouteId") or item.get("busroute") or "",
                        "route_id": route_id,
                        "routeCode": stat["routeCode"],
                        "routeFamilyCode": stat["routeFamilyCode"],
                        "isMidnight": bool(item.get("isMidnight", False)),
                        "note": str(item.get("note") or "").strip(),
                    }
                )

            for route_id, items in grouped_items.items():
                stat = route_stats[route_id]
                route_stop_timetable_row = {
                    "id": f"{base_id}::{route_id}",
                    "route_id": route_id,
                    "routeCode": stat["routeCode"],
                    "routeFamilyCode": stat["routeFamilyCode"],
                    "stopId": stop_id,
                    "stopName": stop_name,
                    "calendar": calendar,
                    "service_id": service_id,
                    "items": items,
                    "source": "tokyu_bus_data",
                }
                global_stop_timetables.write(json.dumps(route_stop_timetable_row, ensure_ascii=False))
                global_stop_timetables.write("\n")
                stop_timetable_writer.write(stat["stopTimetableFile"], route_stop_timetable_row)
                stat["stopTimetableCount"] += 1
                stat["stopTimetableItemCount"] += len(items)
                route_stop_timetable_count += 1
                route_stop_timetable_item_count += len(items)
    finally:
        global_trips.close()
        global_stop_times.close()
        global_stop_timetables.close()
        trip_writer.close()
        stop_time_writer.close()
        stop_timetable_writer.close()

    for route in catalog_routes:
        route_id = str(route.get("id") or "").strip()
        if not route_id:
            continue
        stat = ensure_route_stat(route)
        _touch(output_root / stat["tripFile"])
        _touch(output_root / stat["stopTimeFile"])
        _touch(output_root / stat["stopTimetableFile"])

    corrected_routes: list[Dict[str, Any]] = []
    route_index_items: list[Dict[str, Any]] = []
    routes_with_trips = 0
    for route in catalog_routes:
        route_id = str(route.get("id") or "").strip()
        if not route_id:
            continue
        stat = ensure_route_stat(route)
        trip_total = sum(int(value or 0) for value in stat["tripCountsByDayType"].values())
        if trip_total > 0:
            routes_with_trips += 1
        corrected = {
            **dict(route),
            "tripCount": trip_total,
            "tripCountsByDayType": dict(stat["tripCountsByDayType"]),
            "firstDepartureByDayType": dict(stat["firstDepartureByDayType"]),
            "lastArrivalByDayType": dict(stat["lastArrivalByDayType"]),
            "tripFile": stat["tripFile"],
            "stopTimeFile": stat["stopTimeFile"],
            "stopTimetableFile": stat["stopTimetableFile"],
            "tripCountSource": "tokyu_bus_data",
            "sourceSnapshotId": snapshot_id,
        }
        corrected_routes.append(corrected)
        route_index_items.append(
            {
                "routeId": route_id,
                "routeCode": stat["routeCode"],
                "routeLabel": stat["routeLabel"],
                "routeFamilyCode": stat["routeFamilyCode"],
                "routeFamilyLabel": stat["routeFamilyLabel"],
                "depotId": stat["depotId"],
                "tripCount": trip_total,
                "tripCountsByDayType": dict(stat["tripCountsByDayType"]),
                "firstDepartureByDayType": dict(stat["firstDepartureByDayType"]),
                "lastArrivalByDayType": dict(stat["lastArrivalByDayType"]),
                "sampleTripIds": list(stat["sampleTripIds"]),
                "tripFile": stat["tripFile"],
                "stopTimeFile": stat["stopTimeFile"],
                "stopTimetableFile": stat["stopTimetableFile"],
                "stopTimetableCount": stat["stopTimetableCount"],
                "stopTimetableItemCount": stat["stopTimetableItemCount"],
            }
        )

    family_index_items: list[Dict[str, Any]] = []
    for family_code, stat in sorted(family_stats.items()):
        family_index_items.append(
            {
                "routeFamilyCode": family_code,
                "routeFamilyLabel": stat["routeFamilyLabel"],
                "routeIds": sorted(stat["routeIds"]),
                "routeCodes": sorted(stat["routeCodes"]),
                "depotIds": sorted(stat["depotIds"]),
                "tripCount": sum(int(value or 0) for value in stat["tripCountsByDayType"].values()),
                "tripCountsByDayType": dict(stat["tripCountsByDayType"]),
                "tripFiles": sorted(stat["tripFiles"]),
                "stopTimeFiles": sorted(stat["stopTimeFiles"]),
                "stopTimetableFiles": sorted(stat["stopTimetableFiles"]),
            }
        )

    _write_jsonl_rows(output_root / "routes.jsonl", corrected_routes)
    _write_jsonl_rows(output_root / "stops.jsonl", catalog_stops)
    _json_dump(
        {
            "generatedAt": _iso_now(),
            "sourceSnapshotId": snapshot_id,
            "sourceCanonicalDir": str(canonical_snapshot_dir),
            "sourceRawDir": str(raw_snapshot_dir),
            "items": route_index_items,
        },
        output_root / "route_index.json",
    )
    _json_dump(
        {
            "generatedAt": _iso_now(),
            "sourceSnapshotId": snapshot_id,
            "items": family_index_items,
        },
        output_root / "family_index.json",
    )
    generation_summary = {
        "generatedAt": _iso_now(),
        "sourceSnapshotId": snapshot_id,
        "sourceCanonicalDir": str(canonical_snapshot_dir),
        "sourceRawDir": str(raw_snapshot_dir),
        "counts": {
            "routes": len(corrected_routes),
            "routesWithTrips": routes_with_trips,
            "families": len(family_index_items),
            "stops": len(catalog_stops),
            "trips": trip_count,
            "stopTimes": stop_time_count,
            "routeScopedStopTimetables": route_stop_timetable_count,
            "routeScopedStopTimetableItems": route_stop_timetable_item_count,
            "rawTrips": _int_or_zero((summary.get("entity_counts") or {}).get("trips")),
            "rawStopTimetables": _int_or_zero((summary.get("entity_counts") or {}).get("stop_timetables")),
        },
    }
    _json_dump(generation_summary, output_root / "summary.json")

    built_summary: Dict[str, Any] | None = None
    if rebuild_built:
        routes_df = pd.DataFrame(_read_jsonl_rows(output_root / "routes.jsonl"))
        trips_df = pd.DataFrame(_read_jsonl_rows(output_root / "trips.jsonl"))
        stops_df = pd.DataFrame(_read_jsonl_rows(output_root / "stops.jsonl"))
        stop_times_df = pd.DataFrame(_read_jsonl_rows(output_root / "stop_times.jsonl"))
        stop_timetables_df = pd.DataFrame(_read_jsonl_rows(output_root / "busstop_pole_timetables.jsonl"))

        BUILT_DIR.mkdir(parents=True, exist_ok=True)
        routes_df.to_parquet(BUILT_DIR / "routes.parquet", index=False)
        trips_df.to_parquet(BUILT_DIR / "trips.parquet", index=False)
        trips_df.to_parquet(BUILT_DIR / "timetables.parquet", index=False)
        stops_df.to_parquet(BUILT_DIR / "stops.parquet", index=False)
        stop_times_df.to_parquet(BUILT_DIR / "stop_times.parquet", index=False)
        stop_timetables_df.to_parquet(BUILT_DIR / "stop_timetables.parquet", index=False)

        built_summary = {
            "dataset_id": "tokyu_full",
            "source_dir": str(output_root),
            "sourceSnapshotId": snapshot_id,
            "counts": {
                "routes": len(routes_df),
                "trips": len(trips_df),
                "timetables": len(trips_df),
                "stops": len(stops_df),
                "stop_times": len(stop_times_df),
                "stop_timetables": len(stop_timetables_df),
            },
        }
        _json_dump(built_summary, BUILT_DIR / "summary.json")

        artifact_names = (
            "routes.parquet",
            "trips.parquet",
            "timetables.parquet",
            "stops.parquet",
            "stop_times.parquet",
            "stop_timetables.parquet",
            "summary.json",
        )
        manifest = {
            "schema_version": "v1",
            "dataset_id": "tokyu_full",
            "dataset_version": f"tokyu_bus_data:{snapshot_id}",
            "producer_version": "build_tokyu_bus_data",
            "min_runtime_version": "0.1.0",
            "artifact_hashes": {
                name: _sha256_file(BUILT_DIR / name)
                for name in artifact_names
                if (BUILT_DIR / name).exists()
            },
            "source": "tokyu_bus_data",
            "source_snapshot_id": snapshot_id,
        }
        _json_dump(manifest, BUILT_DIR / "manifest.json")

    result = dict(generation_summary)
    if built_summary is not None:
        result["built"] = built_summary
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build route-scoped tokyo bus data files from the latest complete Tokyu ODPT snapshot.",
    )
    parser.add_argument(
        "--canonical-snapshot",
        default="",
        help="Canonical snapshot directory under data/tokyubus/canonical. Defaults to the latest complete snapshot.",
    )
    parser.add_argument(
        "--output-root",
        default=str(TOKYU_BUS_DATA_ROOT),
        help=f"Output directory (default: {TOKYU_BUS_DATA_ROOT})",
    )
    parser.add_argument(
        "--rebuild-built",
        action="store_true",
        help="Also rebuild data/built/tokyu_full parquet artifacts from generated files.",
    )
    args = parser.parse_args()

    canonical_snapshot_dir = (
        Path(args.canonical_snapshot)
        if str(args.canonical_snapshot).strip()
        else _latest_complete_canonical_snapshot(TOKYUBUS_CANONICAL_ROOT)
    )
    if not canonical_snapshot_dir.is_absolute():
        canonical_snapshot_dir = (TOKYUBUS_CANONICAL_ROOT / canonical_snapshot_dir).resolve()

    result = build_tokyu_bus_data(
        canonical_snapshot_dir=canonical_snapshot_dir,
        output_root=Path(args.output_root).resolve(),
        rebuild_built=bool(args.rebuild_built),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
