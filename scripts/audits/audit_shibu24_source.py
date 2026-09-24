"""Validate the captured official ODPT source for the Shibu24 route family.

This audit creates a new route24 input candidate.  It never edits the existing
three-route timetable or selected-route artifacts.  The candidate records the
official API hashes, stop-coordinate provenance, exact normalized route IDs,
positive polyline distance proxies, and the remaining browser-comparison gate.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.service_day_types import SERVICE_ID_BY_DAY_TYPE, normalize_service_day_type


ROUTE_CODE = "渋24"
OPERATOR_ID = "odpt.Operator:TokyuBus"
LOCAL_OPERATOR_ID = "tokyu"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_route_code(value: object) -> str:
    return "".join(unicodedata.normalize("NFKC", str(value or "")).split())


def parse_time(value: str) -> int:
    parts = str(value).split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError(f"Invalid service time: {value!r}")
    hour, minute = map(int, parts)
    if minute >= 60 or hour >= 48:
        raise ValueError(f"Invalid service time: {value!r}")
    return hour * 60 + minute


def route_stop_polyline_distance_km(
    stop_ids: tuple[str, ...], coordinates: dict[str, tuple[float, float]]
) -> tuple[float, int]:
    """Compute the declared geographic proxy without importing the BFF stack."""
    distance_km = 0.0
    segment_count = 0
    for origin_id, destination_id in zip(stop_ids, stop_ids[1:]):
        origin = coordinates.get(origin_id)
        destination = coordinates.get(destination_id)
        if origin is None or destination is None:
            continue
        lat1, lon1 = map(math.radians, origin)
        lat2, lon2 = map(math.radians, destination)
        d_lat, d_lon = lat2 - lat1, lon2 - lon1
        haversine = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
        distance_km += 2 * 6371.0 * math.asin(min(1.0, math.sqrt(max(haversine, 0.0))))
        segment_count += 1
    return distance_km, segment_count


def load_capture(capture_dir: Path) -> tuple[dict, list[dict], list[dict], dict[str, dict]]:
    """Load and hash-check the route pattern, timetable, and stop source files."""
    capture_manifest = read_json(capture_dir / "shibu24_capture_manifest.json")
    if capture_manifest.get("route_code") != ROUTE_CODE:
        raise ValueError("Capture manifest is not the Shibu24 source")
    sources = capture_manifest.get("sources") or []
    if not sources:
        raise ValueError("Capture manifest contains no sources")
    source_rows: dict[str, list[dict]] = defaultdict(list)
    provenance: dict[str, dict] = {}
    for source in sources:
        path = Path(source["path"])
        if sha256(path) != source["sha256"]:
            raise ValueError(f"Captured source hash mismatch: {path}")
        endpoint = source["request"]["endpoint"].rsplit("/", 1)[-1]
        rows = read_json(path)
        if not isinstance(rows, list):
            raise ValueError(f"Captured source is not a list: {path}")
        source_rows[endpoint].extend(rows)
        for row in rows:
            if row.get("owl:sameAs"):
                provenance[row["owl:sameAs"]] = {
                    "path": path.as_posix(),
                    "sha256": source["sha256"],
                    "dc_date": row.get("dc:date"),
                }
    patterns = [row for row in source_rows["odpt:BusroutePattern"]
                if ROUTE_CODE in normalize_route_code(row.get("dc:title"))
                and ".Shibu24." in str(row.get("owl:sameAs") or "")]
    timetables = [row for row in source_rows["odpt:BusTimetable"]
                  if str(row.get("odpt:busroutePattern") or "").startswith(
                      "odpt.BusroutePattern:TokyuBus.Shibu24.")]
    if len(patterns) != capture_manifest.get("pattern_count"):
        raise ValueError("Capture pattern count differs from its manifest")
    if len(timetables) != capture_manifest.get("timetable_count"):
        raise ValueError("Capture timetable count differs from its manifest")
    return capture_manifest, patterns, timetables, provenance


def load_stops(stop_source: Path) -> tuple[dict[str, dict], dict]:
    manifest_path = stop_source.with_suffix(".manifest.json")
    manifest = read_json(manifest_path)
    if sha256(stop_source) != manifest["sha256"]:
        raise ValueError("BusstopPole source hash mismatch")
    rows = read_json(stop_source)
    stops = {row["owl:sameAs"]: row for row in rows}
    if len(stops) != len(rows):
        raise ValueError("Duplicate official BusstopPole identifiers")
    return stops, {"path": stop_source.as_posix(), "sha256": sha256(stop_source),
                   "manifest_path": manifest_path.as_posix(),
                   "manifest_sha256": sha256(manifest_path),
                   "record_count": len(rows), "dc_date": manifest.get("dc_date")}


def load_route_catalog(route_catalog: Path, old_selected: Path) -> tuple[dict[str, dict], dict]:
    rows = [json.loads(line) for line in route_catalog.read_text(encoding="utf-8").splitlines() if line.strip()]
    candidates = {row["odptPatternId"]: row for row in rows
                  if normalize_route_code(row.get("routeCode")) == ROUTE_CODE}
    selected = read_json(old_selected)
    selected_patterns = {row.get("odptPatternId") for row in selected}
    comparison = {
        "route_code": ROUTE_CODE,
        "catalog_path": route_catalog.as_posix(),
        "catalog_sha256": sha256(route_catalog),
        "catalog_pattern_count": len(candidates),
        "catalog_pattern_ids": sorted(candidates),
        "pattern_to_normalized_route_id": {
            pattern_id: candidates[pattern_id]["id"] for pattern_id in sorted(candidates)
        },
        "previous_selected_path": old_selected.as_posix(),
        "previous_selected_sha256": sha256(old_selected),
        "previous_selected_route24_pattern_ids": sorted(selected_patterns & set(candidates)),
        "previous_selected_route24_pattern_count": len(selected_patterns & set(candidates)),
        "official_capture_pattern_ids": [],
        "selection_interpretation": "The previous selected source intentionally contains only Shibu21, Shibu22, and Shibu23.",
    }
    return candidates, comparison


def build_candidate(patterns: list[dict], timetables: list[dict], stops: dict[str, dict],
                    routes: dict[str, dict], provenance: dict[str, dict]) -> dict:
    pattern_by_id = {row["owl:sameAs"]: row for row in patterns}
    if set(pattern_by_id) != set(routes):
        raise ValueError("Official Shibu24 patterns and normalized route catalog do not match exactly")
    if any(row.get("odpt:operator") != OPERATOR_ID for row in patterns):
        raise ValueError("Official Shibu24 pattern has an unexpected operator")
    timetable_ids = [row.get("owl:sameAs") for row in timetables]
    if any(not value for value in timetable_ids) or len(set(timetable_ids)) != len(timetable_ids):
        raise ValueError("Official timetable identifiers are missing or duplicated")
    rows: list[dict] = []
    sequences: list[dict] = []
    used_stops: set[str] = set()
    route_distances: dict[str, float] = {}
    comparison_counts = Counter()
    for trip in sorted(timetables, key=lambda item: item["owl:sameAs"]):
        pattern_id = trip["odpt:busroutePattern"]
        route = routes[pattern_id]
        schedule = trip.get("odpt:busTimetableObject") or []
        if [item.get("odpt:index") for item in schedule] != list(range(1, len(schedule) + 1)):
            raise ValueError(f"Nonconsecutive official stop sequence: {trip['owl:sameAs']}")
        stop_ids = tuple(item.get("odpt:busstopPole") for item in schedule)
        if any(stop_id not in stops for stop_id in stop_ids):
            raise ValueError(f"Timetable references an unknown official stop: {trip['owl:sameAs']}")
        pattern_stop_ids = tuple(item.get("odpt:busstopPole")
                                 for item in pattern_by_id[pattern_id].get("odpt:busstopPoleOrder", []))
        if stop_ids != pattern_stop_ids:
            raise ValueError(f"Timetable stop order differs from its official pattern: {trip['owl:sameAs']}")
        day_type = normalize_service_day_type(trip.get("odpt:calendar"))
        if day_type not in SERVICE_ID_BY_DAY_TYPE or trip.get("odpt:operator") != OPERATOR_ID:
            raise ValueError(f"Unknown calendar or operator: {trip['owl:sameAs']}")
        times = [item.get("odpt:departureTime") if index == 0 else item.get("odpt:arrivalTime")
                 for index, item in enumerate(schedule)]
        if any(value is None for value in times):
            raise ValueError(f"Missing official stop time: {trip['owl:sameAs']}")
        minutes = [parse_time(value) for value in times]
        if any(next_value < value for value, next_value in zip(minutes, minutes[1:])):
            raise ValueError(f"Official trip times decrease: {trip['owl:sameAs']}")
        distance, segment_count = route_stop_polyline_distance_km(
            stop_ids,
            {stop_id: (float(stops[stop_id]["geo:lat"]), float(stops[stop_id]["geo:long"]))
             for stop_id in stop_ids},
        )
        if not math.isfinite(distance) or distance <= 0 or segment_count != len(stop_ids) - 1:
            raise ValueError(f"Missing positive distance evidence: {trip['owl:sameAs']}")
        previous_distance = route_distances.setdefault(route["id"], round(distance, 6))
        if not math.isclose(previous_distance, round(distance, 6), abs_tol=1e-6):
            raise ValueError(f"Distance differs within one route pattern: {pattern_id}")
        trip_id = trip["owl:sameAs"]
        rows.append({
            "trip_id": trip_id, "route_id": route["id"], "operator_id": LOCAL_OPERATOR_ID,
            "odpt_operator_id": OPERATOR_ID, "service_id": SERVICE_ID_BY_DAY_TYPE[day_type],
            "day_type": day_type, "direction": route.get("direction"),
            "routeCode": route.get("routeCode"), "origin": stops[stop_ids[0]]["dc:title"],
            "destination": stops[stop_ids[-1]]["dc:title"], "origin_stop_id": stop_ids[0],
            "destination_stop_id": stop_ids[-1], "departure": times[0], "arrival": times[-1],
            "runtime_min": minutes[-1] - minutes[0], "distance_km": round(distance, 6),
            "distance_source": "trip_stop_sequence_polyline_haversine",
            "distance_stop_count": len(stop_ids), "distance_segment_count": segment_count,
            "allowed_vehicle_types": ["BEV", "ICE"], "odptPatternId": pattern_id,
            "odptTimetableId": trip_id, "source": "odpt_current_20260901",
            "source_provenance": provenance[trip_id],
            "browser_verification": "BROWSER_COMPARISON_PENDING",
        })
        sequences.extend({"trip_id": trip_id, "stop_sequence": index, "stop_id": stop_id,
                          "arrival_time": schedule[index - 1].get("odpt:arrivalTime"),
                          "departure_time": schedule[index - 1].get("odpt:departureTime")}
                         for index, stop_id in enumerate(stop_ids, start=1))
        used_stops.update(stop_ids)
        comparison_counts["BROWSER_COMPARISON_PENDING"] += 1
    selected_routes = []
    by_route_day = Counter((row["route_id"], row["service_id"]) for row in rows)
    for pattern_id in sorted(routes):
        route = dict(routes[pattern_id])
        route["distanceKm"] = route_distances[route["id"]]
        route["distanceSource"] = "trip_stop_sequence_polyline_haversine"
        route["operator_id"] = LOCAL_OPERATOR_ID
        route["tripCount"] = sum(row["route_id"] == route["id"] for row in rows)
        route["tripCountsByDayType"] = {service: by_route_day[route["id"], service]
                                         for service in ("WEEKDAY", "SAT", "SUN_HOL")}
        selected_routes.append(route)
    stop_rows = [{"id": stop_id, "name": stops[stop_id]["dc:title"],
                  "lat": float(stops[stop_id]["geo:lat"]), "lon": float(stops[stop_id]["geo:long"]),
                  "operator_id": LOCAL_OPERATOR_ID}
                 for stop_id in sorted(used_stops)]
    return {"timetable_rows": rows, "stop_sequences": sequences, "stops": stop_rows,
            "selected_routes": selected_routes,
            "route_distances_km": route_distances,
            "comparison_counts": dict(comparison_counts),
            "service_counts": dict(Counter(row["service_id"] for row in rows)),
            "operator_unknown_count": sum(not row.get("operator_id") for row in rows),
            "pattern_stop_counts": {pattern_id: len(pattern_by_id[pattern_id]["odpt:busstopPoleOrder"])
                                    for pattern_id in sorted(pattern_by_id)}}


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def audit(capture_dir: Path, stop_source: Path, route_catalog: Path, old_selected: Path,
          output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"Shibu24 source audit is immutable; choose a new output directory: {output}")
    capture_manifest, patterns, timetables, provenance = load_capture(capture_dir)
    stops, stop_provenance = load_stops(stop_source)
    routes, route_comparison = load_route_catalog(route_catalog, old_selected)
    route_comparison["official_capture_pattern_ids"] = sorted(row["owl:sameAs"] for row in patterns)
    route_comparison["official_patterns_missing_from_catalog"] = sorted(
        set(route_comparison["official_capture_pattern_ids"]) - set(routes)
    )
    route_comparison["catalog_patterns_missing_from_official_capture"] = sorted(
        set(routes) - set(route_comparison["official_capture_pattern_ids"])
    )
    candidate = build_candidate(patterns, timetables, stops, routes, provenance)
    output.mkdir(parents=True)
    for name in ("timetable_rows", "stop_sequences", "stops", "selected_routes"):
        write_json(output / f"{name}.json", candidate[name])
    write_json(output / "route_id_comparison.json", route_comparison)
    source_validation = {
        "schema_version": "shibu24_source_validation_v1",
        "status": "SOURCE_CAPTURE_VALIDATED_BROWSER_COMPARISON_PENDING",
        "official_operator": OPERATOR_ID, "local_operator_id": LOCAL_OPERATOR_ID,
        "pattern_count": len(patterns), "timetable_count": len(timetables),
        "source_dc_dates": sorted({row.get("dc:date") for row in patterns + timetables}),
        "capture_manifest_sha256": sha256(capture_dir / "shibu24_capture_manifest.json"),
        "stop_source": stop_provenance, "route_id_comparison": route_comparison,
        "service_counts": candidate["service_counts"],
        "pattern_stop_counts": candidate["pattern_stop_counts"],
        "distance_km_by_pattern": candidate["route_distances_km"],
        "comparison_counts": candidate["comparison_counts"],
        "operator_unknown_count": candidate["operator_unknown_count"],
        "distance_semantics": "Sum of adjacent official stop-coordinate haversine segments; geographic proxy, not measured road-network distance.",
        "limits": [
            "Official API data is current scheduled service dated 2026-09-01, not historical 2025 actual operations.",
            "The route24 browser full-stop comparison has not been captured; this candidate must not be used by the verified date-series loader.",
            "This audit validates source shape and provenance only; solver, rolling, physical, accounting, and research gates remain unrun.",
        ],
    }
    write_json(output / "source_validation.json", source_validation)
    artifacts = {}
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name != "manifest.json":
            artifacts[path.name] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    manifest = {
        "schema_version": "shibu24_source_audit_v1",
        "status": source_validation["status"], "route_code": ROUTE_CODE,
        "capture_manifest": capture_manifest,
        "source_validation": source_validation,
        "artifacts": artifacts,
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--stop-source", type=Path, required=True)
    parser.add_argument("--route-catalog", type=Path, default=ROOT / "data/catalog-fast/normalized/routes.jsonl")
    parser.add_argument("--old-selected", type=Path,
                        default=ROOT / "data/derived/timetables/tsurumaki_20260901/selected_routes.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.capture_dir, args.stop_source, args.route_catalog, args.old_selected, args.output)
    print(json.dumps({key: result["source_validation"][key]
                      for key in ("status", "pattern_count", "timetable_count", "service_counts")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
