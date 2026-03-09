from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from bff.services.odpt_fetch import build_odpt_url
from bff.services.odpt_normalize import normalize_odpt_snapshot
from bff.services.odpt_routes import DEFAULT_OPERATOR

try:
    import orjson  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    orjson = None

try:
    import resource
except Exception:  # pragma: no cover - Windows fallback
    resource = None


DEFAULT_GTFS_FEED_PATH = "GTFS/ToeiBus-GTFS"

ODPT_RESOURCE_SPECS: Dict[str, Dict[str, str]] = {
    "routePatterns": {
        "resource": "odpt:BusroutePattern",
        "json_name": "busroute_pattern.json",
        "ndjson_name": "busroute_pattern.ndjson",
    },
    "stops": {
        "resource": "odpt:BusstopPole",
        "json_name": "busstop_pole.json",
        "ndjson_name": "busstop_pole.ndjson",
    },
    "busTimetables": {
        "resource": "odpt:BusTimetable",
        "json_name": "bus_timetable.json",
        "ndjson_name": "bus_timetable.ndjson",
    },
    "stopTimetables": {
        "resource": "odpt:BusstopPoleTimetable",
        "json_name": "busstop_pole_timetable.json",
        "ndjson_name": "busstop_pole_timetable.ndjson",
    },
}


def _json_dumps(value: Any) -> bytes:
    if orjson is not None:
        return orjson.dumps(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _json_dump(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if orjson is not None:
        path.write_bytes(orjson.dumps(value, option=orjson.OPT_INDENT_2))
        return
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _json_load(path: Path) -> Any:
    data = path.read_bytes()
    if orjson is not None:
        return orjson.loads(data)
    return json.loads(data.decode("utf-8"))


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not path.exists():
        return items
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            if orjson is not None:
                items.append(dict(orjson.loads(line)))
            else:
                items.append(dict(json.loads(line)))
    return items


def _write_jsonl(items: Iterable[Dict[str, Any]], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("wb") as fh:
        for item in items:
            fh.write(_json_dumps(item))
            fh.write(b"\n")
            count += 1
    return count


def _now() -> float:
    return time.perf_counter()


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _max_rss_mb() -> Optional[float]:
    if resource is None:
        return None
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss = float(usage.ru_maxrss)
    if os.name == "posix" and rss > 1024 * 1024:
        return round(rss / 1024.0 / 1024.0, 2)
    return round(rss / 1024.0, 2)


def _consumer_key() -> str:
    key = os.environ.get("ODPT_CONSUMER_KEY") or os.environ.get("ODPT_TOKEN")
    if not key:
        raise RuntimeError("ODPT_CONSUMER_KEY or ODPT_TOKEN is required for fast ingest.")
    return key


def _load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"version": 1, "resources": {}, "startedAt": _iso_now(), "updatedAt": _iso_now()}
    data = _json_load(path)
    if not isinstance(data, dict):
        return {"version": 1, "resources": {}, "startedAt": _iso_now(), "updatedAt": _iso_now()}
    data.setdefault("resources", {})
    return data


def _save_state(path: Path, state: Dict[str, Any]) -> None:
    state["updatedAt"] = _iso_now()
    _json_dump(state, path)


def _iter_json_array(path: Path, chunk_size: int = 1 << 20) -> Iterator[Any]:
    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8") as fh:
        buffer = ""
        started = False
        ended = False
        while True:
            chunk = fh.read(chunk_size)
            if chunk:
                buffer += chunk
            elif not buffer:
                break

            index = 0
            while True:
                while index < len(buffer) and buffer[index].isspace():
                    index += 1
                if not started:
                    if index >= len(buffer):
                        break
                    if buffer[index] != "[":
                        raise ValueError(f"{path} is not a JSON array")
                    started = True
                    index += 1
                    continue
                while index < len(buffer) and (buffer[index].isspace() or buffer[index] == ","):
                    index += 1
                if index >= len(buffer):
                    break
                if buffer[index] == "]":
                    ended = True
                    index += 1
                    break
                try:
                    value, next_index = decoder.raw_decode(buffer, index)
                except ValueError:
                    break
                yield value
                index = next_index

            if ended:
                break
            buffer = buffer[index:]
            if not chunk:
                if buffer.strip():
                    raise ValueError(f"Incomplete JSON array in {path}")
                break


def _convert_json_array_to_ndjson(json_path: Path, ndjson_path: Path) -> int:
    ndjson_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with ndjson_path.open("wb") as fh:
        for item in _iter_json_array(json_path):
            fh.write(_json_dumps(item))
            fh.write(b"\n")
            count += 1
    return count


def _group_by(items: Iterable[Dict[str, Any]], key: str) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        value = str(item.get(key) or "")
        grouped.setdefault(value, []).append(item)
    return grouped


def _service_id_from_odpt(value: str | None) -> str:
    mapping = {"weekday": "WEEKDAY", "saturday": "SAT", "holiday": "SUN_HOL", "unknown": "WEEKDAY"}
    return mapping.get((value or "unknown").lower(), "WEEKDAY")


def _safe_time(value: Any) -> Optional[str]:
    if not isinstance(value, str) or ":" not in value:
        return None
    hour, minute = value.split(":", 1)
    try:
        return f"{int(hour):02d}:{int(minute):02d}"
    except ValueError:
        return None


def _route_id_from_pattern(pattern_id: str) -> str:
    digest = hashlib.sha1(pattern_id.encode("utf-8")).hexdigest()[:12]
    return f"odpt-route-{digest}"


def _stop_name(stop_lookup: Dict[str, Dict[str, Any]], stop_id: str) -> str:
    stop = stop_lookup.get(stop_id) or {}
    return str(stop.get("name") or stop_id.split(":")[-1])


def _direction_by_pattern(patterns: Dict[str, Dict[str, Any]], stop_lookup: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    by_busroute: Dict[str, List[tuple[str, str, str]]] = {}
    for pattern_id, pattern in patterns.items():
        stop_sequence = list(pattern.get("stop_sequence") or [])
        if len(stop_sequence) < 2:
            continue
        start_name = _stop_name(stop_lookup, str(stop_sequence[0]))
        end_name = _stop_name(stop_lookup, str(stop_sequence[-1]))
        busroute = str(pattern.get("busroute") or _route_id_from_pattern(pattern_id))
        by_busroute.setdefault(busroute, []).append((pattern_id, start_name, end_name))

    result: Dict[str, str] = {}
    for pattern_rows in by_busroute.values():
        reverse_map = {(start, end): pid for pid, start, end in pattern_rows}
        for pattern_id, start_name, end_name in pattern_rows:
            reverse = reverse_map.get((end_name, start_name))
            if reverse and pattern_id > reverse:
                result[pattern_id] = "inbound"
            else:
                result[pattern_id] = "outbound"
    return result


def build_odpt_route_payloads_from_raw(raw_dir: Path) -> List[Dict[str, Any]]:
    patterns_raw = list(_iter_json_array(raw_dir / "busroute_pattern.json"))
    stops_raw = list(_iter_json_array(raw_dir / "busstop_pole.json"))
    timetables_raw = list(_iter_json_array(raw_dir / "bus_timetable.json"))

    stop_lookup: Dict[str, Dict[str, Any]] = {}
    for item in stops_raw:
        stop_id = str(item.get("owl:sameAs") or item.get("@id") or "")
        if not stop_id:
            continue
        stop_lookup[stop_id] = {
            "name": str(item.get("dc:title") or stop_id.split(":")[-1]),
        }

    patterns: Dict[str, Dict[str, Any]] = {}
    patterns_by_route: Dict[str, List[Dict[str, Any]]] = {}
    for item in patterns_raw:
        pattern_id = str(item.get("owl:sameAs") or item.get("@id") or "")
        if not pattern_id:
            continue
        stop_sequence = [
            str(entry.get("odpt:busstopPole"))
            for entry in list(item.get("odpt:busstopPoleOrder") or [])
            if isinstance(entry, dict) and entry.get("odpt:busstopPole")
        ]
        if len(stop_sequence) < 2:
            continue
        busroute_id = str(item.get("odpt:busroute") or _route_id_from_pattern(pattern_id))
        title = str(item.get("dc:title") or busroute_id)
        pattern = {
            "pattern_id": pattern_id,
            "busroute": busroute_id,
            "title": title,
            "stop_sequence": stop_sequence,
        }
        patterns[pattern_id] = pattern
        patterns_by_route.setdefault(busroute_id, []).append(pattern)

    direction_map = _direction_by_pattern(patterns, stop_lookup)
    trips_by_route: Dict[str, List[Dict[str, Any]]] = {}

    for timetable in timetables_raw:
        pattern_id = str(timetable.get("odpt:busroutePattern") or "")
        pattern = patterns.get(pattern_id)
        if pattern is None:
            continue
        busroute_id = str(pattern["busroute"])
        service_id = _service_id_from_odpt(str(timetable.get("odpt:calendar") or "").split(":")[-1])
        objects = sorted(
            [obj for obj in list(timetable.get("odpt:busTimetableObject") or []) if isinstance(obj, dict)],
            key=lambda obj: int(obj.get("odpt:index") or 0),
        )
        stop_times: List[Dict[str, Any]] = []
        for index, obj in enumerate(objects):
            stop_id = str(obj.get("odpt:busstopPole") or "")
            if not stop_id:
                continue
            departure = _safe_time(obj.get("odpt:departureTime"))
            arrival = _safe_time(obj.get("odpt:arrivalTime"))
            if not departure and not arrival:
                continue
            stop_times.append(
                {
                    "index": index,
                    "stop_id": stop_id,
                    "stop_name": _stop_name(stop_lookup, stop_id),
                    "departure": departure,
                    "arrival": arrival,
                    "time": departure or arrival,
                }
            )
        if len(stop_times) < 2:
            continue
        trip_id = str(timetable.get("owl:sameAs") or timetable.get("@id") or "")
        if not trip_id:
            continue
        trips_by_route.setdefault(busroute_id, []).append(
            {
                "trip_id": trip_id,
                "pattern_id": pattern_id,
                "service_id": service_id,
                "direction": direction_map.get(pattern_id, "outbound"),
                "origin_stop_name": stop_times[0]["stop_name"],
                "destination_stop_name": stop_times[-1]["stop_name"],
                "departure": stop_times[0]["departure"] or stop_times[0]["arrival"],
                "arrival": stop_times[-1]["arrival"] or stop_times[-1]["departure"],
                "estimated_distance_km": 0.0,
                "is_partial": False,
                "stop_times": stop_times,
            }
        )

    payloads: List[Dict[str, Any]] = []
    for busroute_id, route_patterns in sorted(patterns_by_route.items()):
        trips = sorted(
            trips_by_route.get(busroute_id) or [],
            key=lambda item: (str(item.get("departure") or ""), str(item.get("trip_id") or "")),
        )
        route_code = str(route_patterns[0].get("title") or busroute_id)
        route_label = route_code
        services_map = _group_by(trips, "service_id")
        services = []
        for service_id, service_trips in sorted(services_map.items()):
            departures = [str(item.get("departure") or "") for item in service_trips if item.get("departure")]
            arrivals = [str(item.get("arrival") or "") for item in service_trips if item.get("arrival")]
            services.append(
                {
                    "service_id": service_id,
                    "trip_count": len(service_trips),
                    "first_departure": min(departures) if departures else None,
                    "last_arrival": max(arrivals) if arrivals else None,
                }
            )
        pattern_payloads = []
        for pattern in route_patterns:
            sequence = [
                {"stop_id": stop_id, "stop_name": _stop_name(stop_lookup, stop_id)}
                for stop_id in list(pattern.get("stop_sequence") or [])
            ]
            pattern_payloads.append(
                {
                    "pattern_id": pattern["pattern_id"],
                    "title": pattern.get("title"),
                    "direction": direction_map.get(str(pattern["pattern_id"]), "outbound"),
                    "stop_sequence": sequence,
                }
            )
        departures = [str(item.get("departure") or "") for item in trips if item.get("departure")]
        arrivals = [str(item.get("arrival") or "") for item in trips if item.get("arrival")]
        payloads.append(
            {
                "busroute_id": busroute_id,
                "route_code": route_code,
                "route_label": route_label,
                "trip_count": len(trips),
                "first_departure": min(departures) if departures else None,
                "last_arrival": max(arrivals) if arrivals else None,
                "patterns": pattern_payloads,
                "services": services,
                "trips": trips,
            }
        )
    return payloads


def build_operational_dataset(raw_dir: Path, normalized_dir: Path) -> Dict[str, Any]:
    patterns_raw = list(_iter_json_array(raw_dir / "busroute_pattern.json"))
    timetables_raw = list(_iter_json_array(raw_dir / "bus_timetable.json"))
    stops = _read_jsonl(normalized_dir / "stops.jsonl")
    stop_timetables = _read_jsonl(normalized_dir / "busstop_pole_timetables.jsonl")
    route_patterns_jsonl = _read_jsonl(normalized_dir / "route_patterns.jsonl")

    stops_map = {
        str(item.get("id") or item.get("stopId") or ""): {
            "stop_id": item.get("id"),
            "name": item.get("name"),
            "lat": item.get("lat"),
            "lon": item.get("lon"),
            "poleNumber": item.get("poleNumber"),
        }
        for item in stops
        if item.get("id")
    }
    route_patterns_map = {
        str(item.get("pattern_id") or ""): {
            "pattern_id": item.get("pattern_id"),
            "title": item.get("title"),
            "busroute": item.get("busroute"),
            "stop_sequence": [
                str(entry.get("odpt:busstopPole"))
                for entry in list(next((raw.get("odpt:busstopPoleOrder") for raw in patterns_raw if str(raw.get("owl:sameAs") or raw.get("@id") or "") == str(item.get("pattern_id") or "")), []) or [])
                if isinstance(entry, dict) and entry.get("odpt:busstopPole")
            ],
            "total_distance_km": item.get("total_distance_km"),
            "distance_coverage_ratio": 1.0,
        }
        for item in route_patterns_jsonl
        if item.get("pattern_id")
    }

    trips_map: Dict[str, Dict[str, Any]] = {}
    trips_by_pattern: Dict[str, List[str]] = {}
    trips_by_service: Dict[str, List[str]] = {"weekday": [], "saturday": [], "holiday": [], "unknown": []}
    for timetable in timetables_raw:
        trip_id = str(timetable.get("owl:sameAs") or timetable.get("@id") or "")
        pattern_id = str(timetable.get("odpt:busroutePattern") or "")
        if not trip_id or not pattern_id:
            continue
        calendar = str(timetable.get("odpt:calendar") or "")
        service_key = (calendar.split(":")[-1] or "unknown").lower()
        stop_times = []
        for index, obj in enumerate(sorted(
            [entry for entry in list(timetable.get("odpt:busTimetableObject") or []) if isinstance(entry, dict)],
            key=lambda entry: int(entry.get("odpt:index") or 0),
        )):
            stop_id = str(obj.get("odpt:busstopPole") or "")
            if not stop_id:
                continue
            stop_times.append(
                {
                    "index": index,
                    "stop_id": stop_id,
                    "departure": _safe_time(obj.get("odpt:departureTime")),
                    "arrival": _safe_time(obj.get("odpt:arrivalTime")),
                }
            )
        trips_map[trip_id] = {
            "trip_id": trip_id,
            "pattern_id": pattern_id,
            "calendar": calendar,
            "service_id": service_key,
            "stop_times": stop_times,
            "estimated_distance_km": float(route_patterns_map.get(pattern_id, {}).get("total_distance_km") or 0.0),
            "distance_source": "pattern_segments",
            "is_partial": False,
        }
        trips_by_pattern.setdefault(pattern_id, []).append(trip_id)
        trips_by_service.setdefault(service_key, []).append(trip_id)

    stop_timetable_map = {
        str(item.get("id") or ""): {
            "stop_id": item.get("stopId"),
            "calendar": item.get("calendar"),
            "service_id": item.get("service_id"),
            "items": list(item.get("items") or []),
        }
        for item in stop_timetables
        if item.get("id")
    }

    payloads = build_odpt_route_payloads_from_raw(raw_dir)
    return {
        "meta": {
            "generatedAt": _iso_now(),
            "warnings": [],
            "cache": {
                "stops": True,
                "patterns": True,
                "timetables": True,
                "stopTimetables": True,
            },
        },
        "stops": stops_map,
        "routePatterns": route_patterns_map,
        "trips": trips_map,
        "stopTimetables": stop_timetable_map,
        "indexes": {
            "tripsByPattern": trips_by_pattern,
            "tripsByService": trips_by_service,
        },
        "routeTimetables": payloads,
    }


def build_bundle_artifacts(out_dir: Path, operator: str) -> Dict[str, Any]:
    raw_dir = out_dir / "raw"
    normalized_dir = out_dir / "normalized"
    normalized_summary = normalize_odpt_snapshot(raw_dir, normalized_dir)

    routes = _read_jsonl(normalized_dir / "routes.jsonl")
    stops = _read_jsonl(normalized_dir / "stops.jsonl")
    timetable_rows = _read_jsonl(normalized_dir / "trips.jsonl")
    stop_timetables = _read_jsonl(normalized_dir / "busstop_pole_timetables.jsonl")
    calendar_entries = _read_jsonl(normalized_dir / "service_calendars.jsonl")
    stop_times = _read_jsonl(normalized_dir / "stop_times.jsonl")
    route_payloads = build_odpt_route_payloads_from_raw(raw_dir)
    operational_dataset = build_operational_dataset(raw_dir, normalized_dir)

    bundle = {
        "meta": {
            "source": "odpt",
            "datasetRef": operator,
            "operator": operator,
            "generatedAt": _iso_now(),
            "warnings": list(normalized_summary.get("warnings") or []),
            "counts": {
                "routes": len(routes),
                "stops": len(stops),
                "timetableRows": len(timetable_rows),
                "stopTimetables": len(stop_timetables),
                "routePayloads": len(route_payloads),
            },
        },
        "snapshot": {"snapshotKey": f"fast-odpt::{operator}"},
        "routes": routes,
        "stops": stops,
        "timetable_rows": timetable_rows,
        "stop_timetables": stop_timetables,
        "calendar_entries": calendar_entries,
        "calendar_date_entries": [],
        "stop_times": stop_times,
        "route_payloads": route_payloads,
    }

    _json_dump(bundle, out_dir / "bundle.json")
    _json_dump(operational_dataset, out_dir / "operational_dataset.json")
    _json_dump({"items": route_payloads, "total": len(route_payloads)}, out_dir / "route_timetables_dataset.json")
    _json_dump(normalized_summary, out_dir / "normalize_summary.json")
    return bundle


@dataclass
class DownloadResult:
    name: str
    json_path: Path
    ndjson_path: Path
    item_count: int
    size_bytes: int
    elapsed_sec: float
    retries: int
    sha256: str


async def _download_odpt_resource(
    *,
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    state_path: Path,
    state: Dict[str, Any],
    out_dir: Path,
    operator: str,
    name: str,
    spec: Dict[str, str],
    resume: bool,
    timeout_sec: float,
    max_retries: int,
) -> DownloadResult:
    raw_dir = out_dir / "raw"
    json_path = raw_dir / spec["json_name"]
    ndjson_path = raw_dir / spec["ndjson_name"]
    resource_state = dict((state.get("resources") or {}).get(name) or {})
    if (
        resume
        and resource_state.get("status") == "complete"
        and json_path.exists()
        and ndjson_path.exists()
    ):
        print(
            f"[fast-ingest] {name} resume=hit records={resource_state.get('itemCount', 0)} "
            f"size={resource_state.get('sizeBytes', 0)}B"
        )
        return DownloadResult(
            name=name,
            json_path=json_path,
            ndjson_path=ndjson_path,
            item_count=int(resource_state.get("itemCount") or 0),
            size_bytes=int(resource_state.get("sizeBytes") or 0),
            elapsed_sec=float(resource_state.get("elapsedSec") or 0.0),
            retries=int(resource_state.get("retries") or 0),
            sha256=str(resource_state.get("sha256") or ""),
        )

    url = build_odpt_url(spec["resource"], _consumer_key(), operator)
    retries = 0
    for attempt in range(max_retries + 1):
        started = _now()
        try:
            async with semaphore:
                tmp_path = json_path.with_suffix(json_path.suffix + ".part")
                tmp_path.parent.mkdir(parents=True, exist_ok=True)
                sha256 = hashlib.sha256()
                size_bytes = 0
                async with client.stream("GET", url, timeout=timeout_sec) as response:
                    response.raise_for_status()
                    with tmp_path.open("wb") as fh:
                        async for chunk in response.aiter_bytes():
                            if not chunk:
                                continue
                            fh.write(chunk)
                            sha256.update(chunk)
                            size_bytes += len(chunk)
                tmp_path.replace(json_path)
                item_count = _convert_json_array_to_ndjson(json_path, ndjson_path)
                elapsed = max(_now() - started, 1e-6)
                resource_state = {
                    "status": "complete",
                    "jsonPath": str(json_path),
                    "ndjsonPath": str(ndjson_path),
                    "itemCount": item_count,
                    "sizeBytes": size_bytes,
                    "elapsedSec": round(elapsed, 3),
                    "retries": retries,
                    "sha256": sha256.hexdigest(),
                    "completedAt": _iso_now(),
                }
                state.setdefault("resources", {})[name] = resource_state
                _save_state(state_path, state)
                rate = item_count / elapsed if item_count else 0.0
                print(
                    f"[fast-ingest] {name} 1/1 ok={item_count} retry={retries} fail=0 "
                    f"rate={rate:.1f} rec/s size={size_bytes}B"
                )
                return DownloadResult(
                    name=name,
                    json_path=json_path,
                    ndjson_path=ndjson_path,
                    item_count=item_count,
                    size_bytes=size_bytes,
                    elapsed_sec=elapsed,
                    retries=retries,
                    sha256=sha256.hexdigest(),
                )
        except Exception as exc:
            retries += 1
            if attempt >= max_retries:
                state.setdefault("resources", {})[name] = {
                    "status": "error",
                    "error": str(exc),
                    "retries": retries,
                    "updatedAt": _iso_now(),
                }
                _save_state(state_path, state)
                raise
            backoff = min(5.0, 0.5 * math.pow(2, attempt))
            print(f"[fast-ingest] {name} retry={retries} backoff={backoff:.1f}s error={exc}")
            await asyncio.sleep(backoff)
    raise RuntimeError(f"download failed for {name}")


async def run_fetch_odpt(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "checkpoints" / "fetch_state.json"
    metrics_path = out_dir / "benchmarks" / "fast_ingest_metrics.json"
    state = _load_state(state_path)

    selected = set(ODPT_RESOURCE_SPECS.keys())
    if args.only:
        selected = {args.only}
    if args.skip_stop_timetables:
        selected.discard("stopTimetables")

    limits = httpx.Limits(max_keepalive_connections=max(4, args.concurrency), max_connections=max(4, args.concurrency))
    semaphore = asyncio.Semaphore(max(1, args.concurrency))
    started = _now()
    async with httpx.AsyncClient(http2=True, follow_redirects=True, limits=limits) as client:
        tasks = [
            _download_odpt_resource(
                client=client,
                semaphore=semaphore,
                state_path=state_path,
                state=state,
                out_dir=out_dir,
                operator=args.operator,
                name=name,
                spec=ODPT_RESOURCE_SPECS[name],
                resume=args.resume,
                timeout_sec=args.timeout_sec,
                max_retries=args.max_retries,
            )
            for name in sorted(selected)
        ]
        results = await asyncio.gather(*tasks)
    fetch_elapsed = _now() - started

    bundle_counts = None
    if args.build_bundle:
        build_started = _now()
        bundle = build_bundle_artifacts(out_dir, args.operator)
        build_elapsed = _now() - build_started
        bundle_counts = dict((bundle.get("meta") or {}).get("counts") or {})
        print(
            "[fast-ingest] build-bundle "
            f"routes={bundle_counts.get('routes', 0)} "
            f"stops={bundle_counts.get('stops', 0)} "
            f"timetableRows={bundle_counts.get('timetableRows', 0)} "
            f"stopTimetables={bundle_counts.get('stopTimetables', 0)} "
            f"elapsed={build_elapsed:.2f}s"
        )
    else:
        build_elapsed = 0.0

    metrics = {
        "mode": "fetch-odpt",
        "startedAt": state.get("startedAt"),
        "finishedAt": _iso_now(),
        "resources": [
            {
                "name": result.name,
                "itemCount": result.item_count,
                "sizeBytes": result.size_bytes,
                "elapsedSec": round(result.elapsed_sec, 3),
                "retries": result.retries,
                "sha256": result.sha256,
            }
            for result in results
        ],
        "summary": {
            "resourceCount": len(results),
            "fetchElapsedSec": round(fetch_elapsed, 3),
            "buildElapsedSec": round(build_elapsed, 3),
            "maxRssMb": _max_rss_mb(),
            "bundleCounts": bundle_counts,
        },
    }
    _json_dump(metrics, metrics_path)
    return 0


def run_sync_gtfs(args: argparse.Namespace) -> int:
    from catalog_update_app import _get_or_load_bundle, _parse_resources, _resolve_scenario_id, _sync_bundle_to_scenario

    scenario_id = _resolve_scenario_id(args.scenario, args.create_scenario_name, args.mode)
    resources = _parse_resources(args.resources)
    started = _now()
    bundle = _get_or_load_bundle(
        "gtfs",
        operator=DEFAULT_OPERATOR,
        feed_path=args.feed_path,
        refresh=args.refresh,
        force_refresh=args.force_refresh,
        ttl_sec=args.ttl_sec,
    )
    _sync_bundle_to_scenario(
        scenario_id=scenario_id,
        source="gtfs",
        bundle=bundle,
        operator=DEFAULT_OPERATOR,
        feed_path=args.feed_path,
        resources=resources,
        reset_existing=not args.keep_existing_source,
    )
    elapsed = _now() - started
    counts = {
        "routes": len(list(bundle.get("routes") or [])),
        "stops": len(list(bundle.get("stops") or [])),
        "timetableRows": len(list(bundle.get("timetable_rows") or [])),
        "stopTimetables": len(list(bundle.get("stop_timetables") or [])),
    }
    print(
        "[fast-ingest] sync-gtfs "
        f"scenario={scenario_id} routes={counts['routes']} stops={counts['stops']} "
        f"timetableRows={counts['timetableRows']} stopTimetables={counts['stopTimetables']} "
        f"elapsed={elapsed:.2f}s"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fast catalog ingest utilities.")
    subparsers = parser.add_subparsers(dest="command")

    fetch_odpt = subparsers.add_parser("fetch-odpt", help="Fast ODPT ingest with raw/ndjson/checkpoint outputs")
    fetch_odpt.add_argument("--out-dir", required=True)
    fetch_odpt.add_argument("--operator", default=DEFAULT_OPERATOR)
    fetch_odpt.add_argument("--concurrency", type=int, default=8)
    fetch_odpt.add_argument("--resume", action="store_true")
    fetch_odpt.add_argument("--only", choices=sorted(ODPT_RESOURCE_SPECS.keys()))
    fetch_odpt.add_argument("--skip-stop-timetables", action="store_true")
    fetch_odpt.add_argument("--build-bundle", action="store_true")
    fetch_odpt.add_argument("--timeout-sec", type=float, default=300.0)
    fetch_odpt.add_argument("--max-retries", type=int, default=3)

    sync_gtfs = subparsers.add_parser("sync-gtfs", help="GTFS scenario sync wrapper with benchmark output")
    sync_gtfs.add_argument("--scenario", default="latest")
    sync_gtfs.add_argument("--create-scenario-name")
    sync_gtfs.add_argument("--mode", default="mode_B_resource_assignment")
    sync_gtfs.add_argument("--feed-path", default=DEFAULT_GTFS_FEED_PATH)
    sync_gtfs.add_argument("--resources", default="all")
    sync_gtfs.add_argument("--ttl-sec", type=int, default=3600)
    sync_gtfs.add_argument("--refresh", action="store_true")
    sync_gtfs.add_argument("--force-refresh", action="store_true")
    sync_gtfs.add_argument("--keep-existing-source", action="store_true")
    sync_gtfs.add_argument("--out-dir")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "fetch-odpt":
        return asyncio.run(run_fetch_odpt(args))
    if args.command == "sync-gtfs":
        return run_sync_gtfs(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
