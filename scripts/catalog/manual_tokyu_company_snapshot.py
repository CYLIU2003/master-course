"""Build a Tokyu Bus catalog offline from a Go-captured ODPT snapshot.

This command never calls ODPT. The matching Go capture is a separate explicit
manual step; neither command is called by Prepare or job submission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.catalog import build_tokyu_full_db as catalog


RESOURCES = ("odpt:BusroutePattern", "odpt:BusstopPole", "odpt:BusTimetable", "odpt:BusstopPoleTimetable")
OPERATOR = catalog.OPERATOR_ID
MANIFEST = "capture_manifest.json"
DATABASE = "tokyu_company.sqlite3"
BUILD_MANIFEST = "build_manifest.json"


def _write_new_json(path: Path, payload: dict) -> None:
    if path.exists():
        raise FileExistsError(f"Immutable artifact already exists: {path}")
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _validate_rows(resource: str, rows: list[dict], *, allow_empty: bool = False) -> None:
    if not rows and not allow_empty:
        raise ValueError(f"{resource}: empty ODPT response; capture remains incomplete")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{resource}: non-object response row")
    identifiers = [row.get("owl:sameAs") for row in rows]
    if any(not identifier for identifier in identifiers):
        raise ValueError(f"{resource}: missing object ID")
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{resource}: duplicate object ID")
    if any(OPERATOR not in (value if isinstance(value, list) else [value])
           for value in (row.get("odpt:operator") for row in rows)):
        raise ValueError(f"{resource}: operator mismatch")


def _read_verified_capture(output: Path) -> tuple[dict, dict[str, list[dict]]]:
    manifest = json.loads((output / MANIFEST).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "tokyu_company_odpt_capture_v1" or manifest.get("operator_id") != OPERATOR:
        raise ValueError("Unexpected capture manifest")
    sources = manifest.get("sources") or []
    if not sources or set(source.get("resource") for source in sources) != set(RESOURCES):
        raise ValueError("All four ODPT resources are required")
    collected: dict[str, dict[str, dict]] = {resource: {} for resource in RESOURCES}
    for source in sources:
        # Only read a file within the selected snapshot, even if the original
        # capture manifest carries an absolute path from another computer.
        path = output / Path(source["path"]).name
        if not path.is_file() or path.parent.resolve() != output.resolve():
            raise ValueError(f"Raw source path is missing from snapshot: {path}")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["sha256"]:
            raise ValueError(f"Raw source SHA mismatch: {path.name}")
        rows = json.loads(raw)
        if not isinstance(rows, list) or len(rows) != source["record_count"]:
            raise ValueError(f"Raw source count mismatch: {path.name}")
        query = source.get("request", {}).get("query", {})
        if query.get("odpt:operator") != OPERATOR or "acl:consumerKey" in query:
            raise ValueError(f"Invalid or secret-bearing request manifest: {path.name}")
        resource = source["resource"]
        if source["request"].get("endpoint") != f"https://api.odpt.org/api/v4/{resource}":
            raise ValueError(f"ODPT endpoint mismatch: {path.name}")
        _validate_rows(resource, rows, allow_empty=len(query) > 1)
        field = "odpt:busroutePattern" if resource == RESOURCES[2] else "odpt:busstopPole"
        selected = query.get(field)
        if selected and any(selected not in (row.get(field) if isinstance(row.get(field), list)
                                            else [row.get(field)]) for row in rows):
            raise ValueError(f"Partition filter mismatch: {path.name}")
        for row in rows:
            identifier = row["owl:sameAs"]
            existing = collected[resource].get(identifier)
            if existing is not None and existing != row:
                raise ValueError(f"Conflicting ODPT object versions: {identifier}")
            collected[resource][identifier] = row
    result = {resource: list(rows.values()) for resource, rows in collected.items()}
    if len(result[RESOURCES[0]]) != manifest.get("pattern_count") or len(result[RESOURCES[2]]) != manifest.get("timetable_object_count") or len(result[RESOURCES[3]]) != manifest.get("stop_timetable_object_count"):
        raise ValueError("Captured object counts do not match the manifest")
    if any(not rows for rows in result.values()):
        raise ValueError("Captured resource is empty")
    pattern_ids = {row["owl:sameAs"] for row in result[RESOURCES[0]]}
    stop_ids = {row["owl:sameAs"] for row in result[RESOURCES[1]]}
    route_ids = {route for row in result[RESOURCES[0]]
                 for route in ([row.get("odpt:busroute")] if isinstance(row.get("odpt:busroute"), str)
                               else row.get("odpt:busroute") or [])}
    for resource in RESOURCES[:2]:
        master_sources = [source for source in sources if source["resource"] == resource]
        if len(master_sources) != 1 or master_sources[0]["request"]["query"] != {"odpt:operator": OPERATOR}:
            raise ValueError(f"Invalid ODPT master source for {resource}")
    for resource, field, expected in ((RESOURCES[2], "odpt:busroutePattern", pattern_ids),
                                      (RESOURCES[3], "odpt:busstopPole", stop_ids)):
        actual = [source["request"]["query"].get(field) for source in sources if source["resource"] == resource]
        if actual.count(None) != 1 or len(actual) != len(expected) + 1 or set(actual) - {None} != expected:
            raise ValueError(f"Incomplete or duplicate ODPT partitions for {resource}")
    if manifest.get("route_count") != len(route_ids):
        raise ValueError("Route count does not match captured patterns")
    if manifest.get("stop_partition_count") != len(stop_ids):
        raise ValueError("Stop partition count does not match captured stops")
    referenced_stop_timetables = {identifier for stop in result[RESOURCES[1]]
                                  for identifier in stop.get("odpt:busstopPoleTimetable") or []}
    if referenced_stop_timetables != set(collected[RESOURCES[3]]):
        raise ValueError("Stop timetable objects differ from the stop master references")
    return manifest, result


def _smoke_catalog_reader(database: Path) -> dict:
    """Exercise the existing optimization-facing reader without starting a solve."""
    from bff.services import local_db_catalog

    prior = os.environ.get("TOKYU_DB_PATH")
    os.environ["TOKYU_DB_PATH"] = str(database)
    try:
        health = local_db_catalog.health_check()
        if health.get("status") != "ok":
            raise ValueError(f"Optimization catalog reader failed: {health.get('status')}")
        with local_db_catalog.get_conn() as connection:
            sample = connection.execute(
                "SELECT route_family, calendar_type FROM timetable_trips GROUP BY route_family, calendar_type ORDER BY COUNT(*) DESC LIMIT 1"
            ).fetchone()
        if sample is None:
            raise ValueError("No route/calendar pair for optimization reader")
        trips = local_db_catalog.build_milp_trips(route_families=[sample[0]], calendar_type=sample[1])
        if not trips:
            raise ValueError("Optimization reader returned no trips for a populated route/calendar")
        return {
            "status": "DIAGNOSTIC_CATALOG_READ_OK",
            "route_family": sample[0], "calendar_type": sample[1],
            "trip_count": len(trips),
            "nonpositive_proxy_distance_count": sum(float(trip["distance_km"]) <= 0 for trip in trips),
        }
    finally:
        if prior is None:
            os.environ.pop("TOKYU_DB_PATH", None)
        else:
            os.environ["TOKYU_DB_PATH"] = prior


def build(output: Path) -> dict:
    if (output / DATABASE).exists() or (output / BUILD_MANIFEST).exists():
        raise FileExistsError(f"Built snapshot is immutable; choose a new directory: {output}")
    manifest, resources = _read_verified_capture(output)
    pattern_ids = {row["owl:sameAs"] for row in resources["odpt:BusroutePattern"]}
    unknown = {row.get("odpt:busroutePattern") for row in resources[RESOURCES[2]]} - pattern_ids
    if unknown:
        raise ValueError(f"BusTimetable: {len(unknown)} unknown route patterns")
    db_path = output / DATABASE
    temporary_db = output / (DATABASE + ".building")
    if temporary_db.exists():
        raise FileExistsError(f"Unresolved previous build remains: {temporary_db}")
    catalog.SEED_ROUTE_TO_DEPOT = catalog.load_seed_route_map()
    connection = catalog.init_db(temporary_db)
    try:
        catalog.insert_operator(connection)
        catalog.seed_all_depots(connection)
        catalog.insert_stops(connection, resources["odpt:BusstopPole"])
        pattern_map = catalog.insert_patterns(connection, resources["odpt:BusroutePattern"])
        # The historical full-DB builder predates the BFF catalog reader's
        # route_code column; preserve its exact route-family value here.
        connection.execute("ALTER TABLE route_patterns ADD COLUMN route_code TEXT")
        connection.execute("UPDATE route_patterns SET route_code=route_family")
        catalog.rebuild_route_families(connection)
        for row in resources["odpt:BusTimetable"]:
            catalog.insert_timetable(connection, row, pattern_map)
        connection.execute("ALTER TABLE stop_timetables ADD COLUMN source_id TEXT")
        connection.execute("ALTER TABLE stop_timetables ADD COLUMN busroute_ids_json TEXT")
        for row in resources[RESOURCES[3]]:
            route_ids = row.get("odpt:busroute") or []
            if isinstance(route_ids, str):
                route_ids = [route_ids]
            if not route_ids or not row.get("odpt:busstopPole"):
                raise ValueError(f"Stop timetable lacks route/stop: {row['owl:sameAs']}")
            for item in row.get("odpt:busstopPoleTimetableObject") or []:
                departure = item.get("odpt:departureTime")
                minute = catalog.hhmm_to_min(departure)
                if minute is None:
                    raise ValueError(f"Stop timetable has invalid departure time: {row['owl:sameAs']}")
                connection.execute(
                    "INSERT INTO stop_timetables(stop_id, pattern_id, calendar_type, direction, departure_hhmm, dep_min, note, source_id, busroute_ids_json) VALUES (?,?,?,?,?,?,?,?,?)",
                    (row["odpt:busstopPole"], "", catalog.calendar_label(row.get("odpt:calendar") or ""),
                     row.get("odpt:busDirection") or "", departure, minute,
                     str(item.get("odpt:note") or ""), row["owl:sameAs"], json.dumps(route_ids, ensure_ascii=False)),
                )
        connection.executemany(
            "INSERT INTO pipeline_meta(key, value) VALUES (?, ?)",
            (("source", "manual_frozen_odpt_capture"),
             ("capture_manifest_sha256", hashlib.sha256((output / MANIFEST).read_bytes()).hexdigest()),
             ("operator_id", OPERATOR),
             ("synthetic_stop_timetable_entries", "0"),
             ("stop_timetable_pattern_mapping", "unavailable_in_odpt_source; use busroute_ids_json")),
        )
        connection.commit()
        counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                  for table in ("stops", "route_patterns", "timetable_trips", "trip_stops", "stop_timetables")}
        if any(count == 0 for count in counts.values()):
            raise ValueError(f"Incomplete optimization catalog: {counts}")
        unknown_stops = connection.execute(
            "SELECT COUNT(*) FROM trip_stops t LEFT JOIN stops s ON t.stop_id=s.stop_id WHERE s.stop_id IS NULL"
        ).fetchone()[0]
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ValueError(f"SQLite integrity check failed: {integrity}")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except BaseException:
        connection.close()
        for path in (temporary_db, Path(str(temporary_db) + "-wal"), Path(str(temporary_db) + "-shm")):
            if path.parent.resolve() == output.resolve():
                path.unlink(missing_ok=True)
        raise
    connection.close()
    os.replace(temporary_db, db_path)
    reader_smoke = _smoke_catalog_reader(db_path)
    result = {
        "schema_version": "tokyu_company_catalog_build_v1",
        "status": "BUILT_CATALOG_NOT_FORMAL_PREPARED_INPUT",
        "database": DATABASE,
        "database_sha256": hashlib.sha256(db_path.read_bytes()).hexdigest(),
        "capture_manifest_sha256": hashlib.sha256((output / MANIFEST).read_bytes()).hexdigest(),
        "counts": counts,
        "trip_stop_ids_absent_from_stop_master": unknown_stops,
        "source_record_counts": {resource: len(rows) for resource, rows in resources.items()},
        "optimizer_reader_smoke": reader_smoke,
        "limitations": [
            "This catalog is a source snapshot, not a formal fleet/depot/distance/energy scenario.",
            "Depot attribution in the legacy catalog builder may include inferred mappings.",
            "No missing stop time or route distance is synthesized by this command.",
        ],
    }
    _write_new_json(output / BUILD_MANIFEST, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.command == "build":
        result = build(output)
    else:
        result = _read_verified_capture(output)[0]
    print(json.dumps({"status": result["status"], "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
