"""The monthly reader must not depend on live ODPT capture files."""

import hashlib
import json

import pytest

from scripts.benchmarks.shibu24_optimization_store import build_database, load_database


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(tmp_path):
    source = tmp_path / "raw_and_normalized"
    source.mkdir(parents=True)
    capture = source / "capture.json"
    capture_sha = _write_json(capture, [{"odpt:id": "original"}])
    records = {
        "selected_routes": [{"id": "route-24"}],
        "timetable_rows": [{"trip_id": "trip-1", "route_id": "route-24",
                            "operator_id": "tokyu", "service_id": "WEEKDAY",
                            "distance_km": 3.0, "distance_source": "geographic_proxy",
                            "source_provenance": {"path": str(capture), "sha256": capture_sha}}],
        "stop_sequences": [{"trip_id": "trip-1", "stop_id": "stop-1"}],
        "stops": [{"id": "stop-1"}],
    }
    artifact_sha = {f"{name}.json": {"sha256": _write_json(source / f"{name}.json", rows)}
                    for name, rows in records.items()}
    _write_json(source / "manifest.json", {
        "status": "SOURCE_CAPTURE_VALIDATED_BROWSER_COMPARISON_PENDING",
        "artifacts": artifact_sha,
        "capture_manifest": {"sources": [{"path": str(capture), "sha256": capture_sha}]},
        "source_validation": {"distance_semantics": "geographic_proxy"},
    })
    return source, capture, records


def test_build_once_then_read_database_without_raw_capture(tmp_path):
    source, capture, records = _source(tmp_path)
    destination = tmp_path / "optimization"
    manifest = build_database(source, destination)
    assert manifest["tables"]["timetable_rows"]["count"] == 1
    capture.unlink()
    for name in records:
        (source / f"{name}.json").unlink()
    (source / "manifest.json").unlink()
    loaded_manifest, loaded = load_database(destination)
    assert loaded == records
    assert loaded_manifest["raw_capture_provenance"][0]["sha256"] == manifest[
        "raw_capture_provenance"][0]["sha256"]
    with pytest.raises(FileExistsError, match="immutable"):
        build_database(source, destination)


def test_build_rejects_changed_capture_and_missing_operator(tmp_path):
    source, capture, _ = _source(tmp_path)
    capture.write_text("modified", encoding="utf-8")
    with pytest.raises(ValueError, match="capture changed"):
        build_database(source, tmp_path / "optimization")
    source, _, records = _source(tmp_path / "second")
    records["timetable_rows"][0]["operator_id"] = "UNKNOWN"
    changed_sha = _write_json(source / "timetable_rows.json", records["timetable_rows"])
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["timetable_rows.json"]["sha256"] = changed_sha
    _write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="operator or distance"):
        build_database(source, tmp_path / "second_optimization")


def test_database_hash_change_fails_closed(tmp_path):
    source, _, _ = _source(tmp_path)
    destination = tmp_path / "optimization"
    build_database(source, destination)
    with (destination / "source.sqlite3").open("ab") as stream:
        stream.write(b"tampered")
    with pytest.raises(ValueError, match="hash differs"):
        load_database(destination)


def test_nonfinite_distance_is_not_accepted_as_optimization_input(tmp_path):
    source, _, records = _source(tmp_path)
    records["timetable_rows"][0]["distance_km"] = float("nan")
    changed_sha = _write_json(source / "timetable_rows.json", records["timetable_rows"])
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifacts"]["timetable_rows.json"]["sha256"] = changed_sha
    _write_json(manifest_path, manifest)
    with pytest.raises(ValueError, match="operator or distance"):
        build_database(source, tmp_path / "optimization")
