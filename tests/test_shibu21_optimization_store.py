"""The offline Shibu21 source freeze must retain only audited route records."""

import hashlib
import json

import pytest

from scripts.benchmarks.shibu21_optimization_store import build_database, load_database


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_shibu21_database_excludes_other_routes_and_rejects_source_change(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    parent = tmp_path / "parent.json"
    parent_hash = _write(parent, {"status": "frozen"})
    routes = [{"id": f"route-{index}", "routeCode": "渋２１"} for index in range(6)]
    routes.append({"id": "route-22", "routeCode": "渋２２"})
    trips = [{"trip_id": f"trip-{index}", "route_id": f"route-{index % 6}",
              "routeCode": "渋２１", "service_id": "WEEKDAY", "operator_id": "tokyu",
              "distance_km": 1.0, "distance_source": "fixture"} for index in range(72)]
    trips.append({"trip_id": "trip-22", "route_id": "route-22", "routeCode": "渋２２",
                  "service_id": "WEEKDAY", "operator_id": "tokyu",
                  "distance_km": 1.0, "distance_source": "fixture"})
    sequences = [{"trip_id": row["trip_id"], "stop_id": "stop-a"} for row in trips]
    tables = {"selected_routes": routes, "timetable_rows": trips,
              "stop_sequences": sequences, "stops": [{"id": "stop-a"}]}
    artifact_hashes = {f"{name}.json": {"sha256": _write(source / f"{name}.json", rows)}
                       for name, rows in tables.items()}
    _write(source / "manifest.json", {
        "status": "DIAGNOSTIC_SOURCE_CAPTURE_VALIDATED_DISTANCE_PROXY_DECLARED",
        "route_codes": ["渋21", "渋22", "渋23"],
        "distance_semantics": "fixture distance",
        "artifacts": artifact_hashes,
        "input_source_sha256": {name: row["sha256"] for name, row in artifact_hashes.items()},
        "provenance": {"old_manifest": {"path": str(parent), "sha256": parent_hash}},
    })
    destination = tmp_path / "optimization"
    manifest = build_database(source, destination)
    loaded, rows = load_database(destination)
    assert loaded == manifest
    assert manifest["source_scope"]["route_codes"] == ["渋21"]
    assert len(rows["selected_routes"]) == 6
    assert len(rows["timetable_rows"]) == 72
    assert {row["routeCode"] for row in rows["timetable_rows"]} == {"渋２１"}
    _write(parent, {"status": "changed"})
    with pytest.raises(ValueError, match="Parent ODPT-derived source manifest changed"):
        build_database(source, tmp_path / "altered")
