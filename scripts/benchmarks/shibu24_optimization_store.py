"""Build and read the frozen Shibu24 optimization database.

The build command is the only entrypoint that opens ODPT captures or the
normalized source-audit JSON. Monthly Prepare reads the database in read-only
mode and retains the capture hashes as provenance, not as runtime inputs.
"""

from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "output/shibu21_24_seasonal_20260911/shibu24_source_audit"
DATABASE_DIR = ROOT / "data/optimization/shibu24_20260911"
ARTIFACTS = ("selected_routes", "timetable_rows", "stop_sequences", "stops")
SCHEMA_VERSION = "shibu24_optimization_store_v1"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rowset_sha(rows: list[dict]) -> str:
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_rows(data: dict[str, list[dict]]) -> None:
    routes = data["selected_routes"]
    route_ids = {row.get("id") for row in routes}
    if not routes or len(route_ids) != len(routes) or None in route_ids:
        raise ValueError("Shibu24 routes must have distinct nonempty IDs")
    trips = data["timetable_rows"]
    trip_ids = {row.get("trip_id") for row in trips}
    if not trips or len(trip_ids) != len(trips) or None in trip_ids:
        raise ValueError("Shibu24 trips must have distinct nonempty IDs")
    for row in trips:
        try:
            distance = float(row.get("distance_km"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Shibu24 timetable has a nonnumeric distance") from exc
        if (row.get("route_id") not in route_ids or
                str(row.get("operator_id") or "").strip().upper() in ("", "UNKNOWN") or
                not math.isfinite(distance) or distance <= 0 or
                not row.get("distance_source")):
            raise ValueError("Shibu24 timetable has an invalid route, operator or distance")
    if any(row.get("trip_id") not in trip_ids for row in data["stop_sequences"]):
        raise ValueError("Shibu24 stop sequence references an unknown trip")
    stop_ids = {row.get("id") for row in data["stops"]}
    if any(row.get("stop_id") not in stop_ids for row in data["stop_sequences"]):
        raise ValueError("Shibu24 stop sequence references an unknown stop")


def build_database(source: Path = SOURCE, destination: Path = DATABASE_DIR) -> dict:
    """Verify immutable capture inputs once and write a new database atomically."""
    database_path = destination / "source.sqlite3"
    manifest_path = destination / "manifest.json"
    if database_path.exists() or manifest_path.exists():
        raise FileExistsError("Optimization database is immutable; choose a new destination")
    source_manifest_path = source / "manifest.json"
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    if source_manifest.get("status") != "SOURCE_CAPTURE_VALIDATED_BROWSER_COMPARISON_PENDING":
        raise ValueError("Unexpected Shibu24 source audit status")
    data = {}
    for name in ARTIFACTS:
        path = source / f"{name}.json"
        if _sha(path) != source_manifest["artifacts"][path.name]["sha256"]:
            raise ValueError(f"Normalized Shibu24 source hash changed: {name}")
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError(f"Invalid normalized Shibu24 rows: {name}")
        data[name] = rows
    captures = []
    for capture in source_manifest["capture_manifest"]["sources"]:
        path = Path(capture["path"])
        if not path.is_file() or _sha(path) != capture["sha256"]:
            raise ValueError("Original Shibu24 ODPT capture changed or is missing")
        captures.append({"path": capture["path"], "sha256": capture["sha256"]})
    if not captures or source_manifest.get("route_code") not in (None, "渋24"):
        raise ValueError("Shibu24 source manifest has no ODPT captures or wrong route")
    _validate_rows(data)
    destination.mkdir(parents=True, exist_ok=True)
    temporary = destination / f"source.{uuid4().hex}.tmp"
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            connection.execute("PRAGMA journal_mode=DELETE")
            for name in ARTIFACTS:
                connection.execute(
                    f"CREATE TABLE {name} (position INTEGER PRIMARY KEY, "
                    "route_id TEXT, service_id TEXT, entity_id TEXT, payload_json TEXT NOT NULL)"
                )
                connection.executemany(
                    f"INSERT INTO {name} VALUES (?, ?, ?, ?, ?)",
                    ((index, row.get("route_id"), row.get("service_id"),
                      row.get("trip_id") or row.get("id"),
                      json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                     for index, row in enumerate(data[name])),
                )
            connection.execute("CREATE INDEX timetable_route_service ON timetable_rows(route_id, service_id)")
            connection.execute("CREATE INDEX sequence_trip ON stop_sequences(entity_id)")
            connection.commit()
        with closing(sqlite3.connect(f"file:{temporary.as_posix()}?mode=ro", uri=True)) as connection:
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("New Shibu24 database failed integrity check")
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "source_status": source_manifest["status"],
            "source_manifest_sha256": _sha(source_manifest_path),
            "distance_semantics": source_manifest["source_validation"]["distance_semantics"],
            "source_artifact_sha256": {
                name: source_manifest["artifacts"][f"{name}.json"]["sha256"]
                for name in ARTIFACTS
            },
            "raw_capture_provenance": captures,
            "tables": {name: {"count": len(data[name]), "rowset_sha256": _rowset_sha(data[name])}
                       for name in ARTIFACTS},
            "database_sha256": _sha(temporary),
            "research_status": "DIAGNOSTIC_BROWSER_COMPARISON_PENDING_DISTANCE_PROXY",
        }
        temporary.replace(database_path)
        manifest_tmp = destination / f"manifest.{uuid4().hex}.tmp"
        manifest_tmp.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                                encoding="utf-8")
        manifest_tmp.replace(manifest_path)
        return manifest
    finally:
        temporary.unlink(missing_ok=True)


def load_database(destination: Path = DATABASE_DIR) -> tuple[dict, dict[str, list[dict]]]:
    """Fail closed on missing/corrupt data without opening ODPT or source JSON."""
    manifest_path = destination / "manifest.json"
    database_path = destination / "source.sqlite3"
    if not manifest_path.is_file() or not database_path.is_file():
        raise FileNotFoundError(
            "Shibu24 optimization database is missing; run "
            "python scripts/benchmarks/shibu24_optimization_store.py build once"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != SCHEMA_VERSION or
            not manifest.get("distance_semantics") or
            _sha(database_path) != manifest.get("database_sha256")):
        raise ValueError("Shibu24 optimization database version or hash differs")
    data = {}
    with closing(sqlite3.connect(f"file:{database_path.resolve().as_posix()}?mode=ro", uri=True)) as connection:
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Shibu24 optimization database integrity check failed")
        for name in ARTIFACTS:
            rows = [json.loads(row[0]) for row in connection.execute(
                f"SELECT payload_json FROM {name} ORDER BY position")]
            expected = manifest["tables"][name]
            if len(rows) != expected["count"] or _rowset_sha(rows) != expected["rowset_sha256"]:
                raise ValueError(f"Shibu24 optimization table changed: {name}")
            data[name] = rows
    _validate_rows(data)
    return manifest, data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--destination", type=Path, default=DATABASE_DIR)
    args = parser.parse_args()
    if args.command == "build":
        manifest = build_database(args.source, args.destination)
    else:
        manifest, _ = load_database(args.destination)
    print(json.dumps({"status": "VERIFIED_OPTIMIZATION_DATABASE",
                      "database_sha256": manifest["database_sha256"],
                      "table_counts": {name: manifest["tables"][name]["count"] for name in ARTIFACTS}},
                     ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
