"""Freeze the audited Shibu21 subset of the existing three-route snapshot.

This is an explicit, offline researcher action. Runtime Prepare reads only the
hash-checked SQLite database; it never requests or reparses ODPT captures.
"""

from __future__ import annotations

from contextlib import closing
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import unicodedata
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.benchmarks.shibu24_optimization_store import (
    ARTIFACTS, SCHEMA_VERSION, _rowset_sha, _validate_rows, load_database,
)

SOURCE = ROOT / "output/shibu21_23_exact_20260911/source_candidate"
DATABASE_DIR = ROOT / "data/optimization/shibu21_20260924_v2"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_shibu21(row: dict) -> bool:
    return unicodedata.normalize("NFKC", str(row.get("routeCode") or "")).strip() == "渋21"


def build_database(source: Path = SOURCE, destination: Path = DATABASE_DIR) -> dict:
    """Validate frozen normalized artifacts and create an immutable route-only DB."""
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("status") != "DIAGNOSTIC_SOURCE_CAPTURE_VALIDATED_DISTANCE_PROXY_DECLARED"
            or manifest.get("route_codes") != ["渋21", "渋22", "渋23"]):
        raise ValueError("Unexpected frozen three-route source contract")
    parent = manifest.get("provenance", {}).get("old_manifest", {})
    if not parent.get("path") or _sha(Path(parent["path"])) != parent.get("sha256"):
        raise ValueError("Parent ODPT-derived source manifest changed")
    raw = {}
    for name in ARTIFACTS:
        path = source / f"{name}.json"
        expected = manifest["artifacts"][path.name]["sha256"]
        if _sha(path) != expected:
            raise ValueError(f"Frozen source artifact changed: {name}")
        raw[name] = json.loads(path.read_text(encoding="utf-8"))
    routes = [row for row in raw["selected_routes"] if _is_shibu21(row)]
    route_ids = {row["id"] for row in routes}
    trips = [row for row in raw["timetable_rows"] if row["route_id"] in route_ids]
    trip_ids = {row["trip_id"] for row in trips}
    sequences = [row for row in raw["stop_sequences"] if row["trip_id"] in trip_ids]
    stop_ids = {row["stop_id"] for row in sequences}
    stops = [row for row in raw["stops"] if row["id"] in stop_ids]
    data = dict(selected_routes=routes, timetable_rows=trips,
                stop_sequences=sequences, stops=stops)
    if len(routes) != 6 or len(trips) != 72 or len(trip_ids) != 72:
        raise ValueError("Shibu21 six-pattern/72-template source audit changed")
    if any(not _is_shibu21(row) for row in routes + trips):
        raise ValueError("A non-Shibu21 route entered the isolated database")
    _validate_rows(data)
    database_path = destination / "source.sqlite3"
    target_manifest = destination / "manifest.json"
    if database_path.exists() or target_manifest.exists():
        raise FileExistsError("Optimization database is immutable; choose a new destination")
    destination.mkdir(parents=True, exist_ok=True)
    temporary = destination / f"source.{uuid4().hex}.tmp"
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            connection.execute("PRAGMA journal_mode=DELETE")
            for name in ARTIFACTS:
                connection.execute(
                    f"CREATE TABLE {name} (position INTEGER PRIMARY KEY, route_id TEXT, "
                    "service_id TEXT, entity_id TEXT, payload_json TEXT NOT NULL)"
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
                raise ValueError("Shibu21 database failed integrity check")
        result = {
            "schema_version": SCHEMA_VERSION,
            "source_status": manifest["status"],
            "source_manifest_sha256": _sha(manifest_path),
            "distance_semantics": manifest["distance_semantics"],
            "source_artifact_sha256": manifest["input_source_sha256"],
            "source_scope": {"route_codes": ["渋21"], "route_count": 6, "template_count": 72},
            "tables": {name: {"count": len(data[name]), "rowset_sha256": _rowset_sha(data[name])}
                       for name in ARTIFACTS},
            "database_sha256": _sha(temporary),
            "research_status": "DIAGNOSTIC_DISTANCE_PROXY",
        }
        temporary.replace(database_path)
        target_manifest.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                                   encoding="utf-8")
        loaded, rows = load_database(destination)
        if loaded != result or any(not _is_shibu21(row) for row in rows["timetable_rows"]):
            raise ValueError("Frozen Shibu21 database readback differs")
        return result
    finally:
        temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--destination", type=Path, default=DATABASE_DIR)
    arguments = parser.parse_args()
    print(json.dumps(build_database(arguments.source, arguments.destination), ensure_ascii=False))
