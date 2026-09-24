import math
import json
import sqlite3

import pandas as pd
import pytest

from bff.services.catalog_trip_distance import trip_path_distance, validate_catalog_trip_path
from bff.services import local_db_catalog
from scripts.catalog import manual_tokyu_company_snapshot as snapshot
from scripts.catalog import export_tokyu_sqlite_to_built as exporter
from test_manual_tokyu_company_snapshot import _fixture, STOP_A, STOP_B
from scripts.catalog.audit_optimizer_trip_paths import audit, file_sha256
from src.artifact_contract import check_artifact_contract


def _path():
    return [
        {"seq": 1, "stop_id": "a", "lat": 35, "lon": 139},
        {"seq": 2, "stop_id": "b", "lat": 35.01, "lon": 139.01},
        {"seq": 3, "stop_id": "a", "lat": 35, "lon": 139},
    ]


def test_loop_distance_keeps_actual_trip_path_and_hash():
    path = _path()
    result = validate_catalog_trip_path(
        {"trip_id": "loop", "origin_stop_id": "a", "dest_stop_id": "a", "stop_count": 3}, path)
    assert result["distance_km"] > 2
    assert result == trip_path_distance(list(reversed(path)))
    assert len(result["distance_path_sha256"]) == 64
    from bff.services.run_preparation import _enrich_trip_distances_from_stop_sequences
    trips = [{"trip_id": "loop", "distance_km": 0}]
    _enrich_trip_distances_from_stop_sequences(trips,
        stops=[{"id": row["stop_id"], "lat": row["lat"], "lon": row["lon"]} for row in path],
        stop_sequences=[{"trip_id": "loop", "sequence": row["seq"], "stop_id": row["stop_id"]} for row in path])
    assert trips[0]["distance_km"] == result["distance_km"]


@pytest.mark.parametrize("value", [None, "", float("nan"), float("inf"), 91])
def test_no_invented_or_partial_distance_for_invalid_coordinates(value):
    path = _path()
    path[1]["lat"] = value
    with pytest.raises(ValueError, match="COORDINATE"):
        trip_path_distance(path)


def test_short_turn_uses_trip_endpoint_and_rejects_corrupt_endpoint():
    path = _path()[:2]
    assert validate_catalog_trip_path(
        {"trip_id": "short", "origin_stop_id": "a", "dest_stop_id": "b"}, path)["distance_km"] > 0
    with pytest.raises(ValueError, match="ENDPOINT_MISMATCH"):
        validate_catalog_trip_path(
            {"trip_id": "bad", "origin_stop_id": "a", "dest_stop_id": "c"}, path)
    path[1]["seq"] = 3
    with pytest.raises(ValueError, match="SEQUENCE_INVALID"):
        trip_path_distance(path)


def _loop_database(tmp_path):
    _fixture(tmp_path)
    snapshot.build(tmp_path)
    database = tmp_path / snapshot.DATABASE
    with sqlite3.connect(database) as connection:
        trip_id = connection.execute("SELECT trip_id FROM timetable_trips").fetchone()[0]
        connection.execute("UPDATE timetable_trips SET dest_stop_id=?, stop_count=3", (STOP_A,))
        connection.execute("INSERT INTO trip_stops(trip_id,seq,stop_id,arrival_hhmm,arr_min) VALUES (?,3,?,'10:30',630)", (trip_id, STOP_A))
        connection.execute("UPDATE route_patterns SET depot_id='tokyu:depot:test'")
        connection.execute("UPDATE route_families SET depot_id='tokyu:depot:test'")
    return database


def test_sqlite_reader_uses_trip_path_not_zero_length_loop_endpoints(tmp_path, monkeypatch):
    database = _loop_database(tmp_path)
    monkeypatch.setenv("TOKYU_DB_PATH", str(database))
    records = local_db_catalog.build_milp_trips()
    assert len(records) == 1
    assert records[0]["distance_km"] > 20
    assert records[0]["operator_id"] == snapshot.OPERATOR
    assert records[0]["dispatch_trip"]["distance_km"] == records[0]["distance_km"]
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM trip_stops WHERE seq=2")
    with pytest.raises(ValueError, match="SEQUENCE_INVALID"):
        local_db_catalog.build_milp_trips()


def test_export_preserves_trip_path_and_operator_for_prepare(tmp_path, monkeypatch):
    database = _loop_database(tmp_path)
    before = file_sha256(database)
    destination = exporter.export_sqlite_to_built(database, "test", tmp_path / "built", [])
    trips = pd.read_parquet(destination / "trips.parquet")
    times = pd.read_parquet(destination / "stop_times.parquet")
    assert trips.iloc[0]["distance_km"] > 20
    assert trips.iloc[0]["operator_id"] == snapshot.OPERATOR
    assert times["stop_id"].tolist() == [STOP_A, STOP_B, STOP_A]
    assert trips.iloc[0]["distance_source"] == "trip_stop_sequence_polyline_haversine"
    manifest = check_artifact_contract(destination)
    assert manifest["source_database_sha256"] == before == file_sha256(database)
    assert trips.iloc[0]["route_id"].startswith("odpt.BusroutePattern:")
    assert set(times["stop_id"]) <= set(pd.read_parquet(destination / "stops.parquet")["id"])
    with pytest.raises(FileExistsError):
        exporter.export_sqlite_to_built(database, "test", tmp_path / "built", [])


def test_audit_keeps_failures_and_source_unmodified(tmp_path):
    database = _loop_database(tmp_path)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE stops SET lat=NULL WHERE stop_id=?", (STOP_B,))
    before = file_sha256(database)
    report = audit(database, tmp_path / "audit")
    assert report["status"] == "TRIP_PATHS_BLOCKED"
    assert report["trip_count"] == report["failure_count"] == 1
    assert file_sha256(database) == before
    assert json.loads((tmp_path / "audit/summary.json").read_text(encoding="utf-8"))["failures"]


def test_invalid_catalog_trip_is_a_structured_http_error(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from bff.routers.catalog_local import router

    def invalid(**_):
        raise ValueError("trip-1: TRIP_COORDINATE_MISSING: stop-a")

    monkeypatch.setattr(local_db_catalog, "build_milp_trips", invalid)
    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/catalog/milp-trips")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "OPTIMIZATION_CATALOG_INPUT_INVALID"
    assert "trip-1" in response.json()["detail"]["message"]


@pytest.mark.parametrize("distance", [0, -1, math.nan, math.inf])
def test_dispatch_conversion_rejects_invalid_distance(distance):
    with pytest.raises(ValueError, match="TRIP_DISTANCE_INVALID"):
        local_db_catalog.milp_trip_to_dispatch_trip({"trip_id": "bad", "distance_km": distance})
