"""Offline, read-only audit of all trip paths; no solver or ODPT requests.

Outputs diagnostic geographic proxies plus source hashes. This audit is not a
fleet, energy, depot-attribution, or road-distance approval.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sqlite3

from bff.services.catalog_trip_distance import load_trip_paths, validate_catalog_trip_path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(database: Path, output: Path) -> dict:
    source_sha = file_sha256(database)
    output.mkdir(parents=True, exist_ok=False)
    failures, variants = [], []
    operators = Counter()
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        trips = [dict(row) for row in connection.execute("""
            SELECT t.*, rp.operator_id, rp.origin_stop_id AS pattern_origin,
                   rp.dest_stop_id AS pattern_destination
            FROM timetable_trips t LEFT JOIN route_patterns rp ON t.pattern_id=rp.pattern_id
            ORDER BY t.trip_id
        """)]
        empty_patterns = [row[0] for row in connection.execute("""
            SELECT rp.pattern_id FROM route_patterns rp LEFT JOIN timetable_trips t
            ON t.pattern_id=rp.pattern_id WHERE t.trip_id IS NULL ORDER BY rp.pattern_id
        """)]
        paths = load_trip_paths(connection, [trip["trip_id"] for trip in trips])
    fields = ["trip_id", "pattern_id", "route_family", "calendar_type", "operator_id",
              "origin_stop_id", "dest_stop_id", "distance_km", "distance_source",
              "distance_stop_count", "distance_segment_count", "distance_path_sha256"]
    with (output / "trip_distances.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for trip in trips:
            operators[str(trip.get("operator_id"))] += 1
            try:
                if not trip.get("operator_id") or trip["operator_id"] == "UNKNOWN":
                    raise ValueError("TRIP_OPERATOR_MISSING")
                evidence = validate_catalog_trip_path(trip, paths.get(trip["trip_id"], []))
                writer.writerow({**trip, **evidence})
                if (trip["origin_stop_id"] != trip["pattern_origin"]
                        or trip["dest_stop_id"] != trip["pattern_destination"]):
                    variants.append({key: trip[key] for key in (
                        "trip_id", "pattern_id", "route_family", "origin_stop_id", "dest_stop_id",
                        "pattern_origin", "pattern_destination")})
            except ValueError as exc:
                failures.append({"trip_id": trip["trip_id"], "reason": str(exc)})
    if file_sha256(database) != source_sha:
        raise ValueError("SOURCE_CHANGED_DURING_AUDIT")
    result = {
        "schema_version": "optimizer_trip_path_audit_v1",
        "status": "TRIP_PATHS_VALID" if trips and not failures else "TRIP_PATHS_BLOCKED",
        "database": str(database.resolve()), "database_sha256": source_sha,
        "trip_count": len(trips), "valid_trip_count": len(trips) - len(failures),
        "failure_count": len(failures), "failures": failures,
        "trip_endpoints_differ_from_pattern_count": len(variants),
        "source_trip_endpoint_variants": variants,
        "empty_patterns": empty_patterns, "operator_counts": dict(operators),
        "distance_csv": "trip_distances.csv",
        "distance_csv_sha256": file_sha256(output / "trip_distances.csv"),
        "formal_research_ready": False,
        "limitations": ["Adjacent-stop geographic proxy; road distance is not verified.",
                        "Trip endpoints are retained even when different from the route pattern.",
                        "Depot/fleet/energy/cost/calendar contracts require separate Prepare checks.",
                        "No input, scenario, or existing Prepared artifact was modified."],
    }
    (output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.database, args.output)
    print(json.dumps({key: result[key] for key in (
        "status", "trip_count", "valid_trip_count", "failure_count",
        "trip_endpoints_differ_from_pattern_count", "database_sha256")}, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "TRIP_PATHS_VALID" else 2)


if __name__ == "__main__":
    main()
