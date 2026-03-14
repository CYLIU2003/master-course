from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bff.routers import catalog_local
from bff.services import local_db_catalog
from tests._local_catalog_fixture import create_local_catalog_db


def _client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    db_path = create_local_catalog_db(tmp_path / "tokyu_subset.sqlite")
    monkeypatch.setattr(local_db_catalog, "DB_PATH", db_path)
    app = FastAPI()
    app.include_router(catalog_local.router, prefix="/api")
    return TestClient(app)


def _append_higashi98_patterns(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.executemany(
        "INSERT INTO stops VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("stop:tokyo", "odpt.Operator:TokyuBus", "東京駅南口", "", 35.679, 139.767, "", "{}"),
            ("stop:todoroki", "odpt.Operator:TokyuBus", "等々力操車所", "", 35.610, 139.650, "", "{}"),
            ("stop:meguro", "odpt.Operator:TokyuBus", "目黒駅前", "", 35.633, 139.715, "", "{}"),
            ("stop:shimizu", "odpt.Operator:TokyuBus", "清水", "", 35.625, 139.700, "", "{}"),
            ("stop:meguro_post", "odpt.Operator:TokyuBus", "目黒郵便局", "", 35.626, 139.701, "", "{}"),
        ],
    )
    conn.execute(
        "INSERT INTO route_families VALUES (?, ?, ?, ?, ?, ?)",
        ("東98", "odpt.Operator:TokyuBus", "東98", "東98", 4, "tokyu:depot:meguro"),
    )
    conn.execute(
        "INSERT INTO route_family_depots VALUES (?, ?, ?, ?)",
        ("東98", "odpt.Operator:TokyuBus", "tokyu:depot:meguro", "authority_csv"),
    )
    pattern_rows = [
        ("pattern:h98-main", "odpt.Operator:TokyuBus", "東98", "東98", "東98 main", "", "outbound", "", "tokyu:depot:meguro", "stop:tokyo", "stop:todoroki", 30, "{}"),
        ("pattern:h98-split-a", "odpt.Operator:TokyuBus", "東98", "東98", "東98 split A", "", "outbound", "", "tokyu:depot:meguro", "stop:todoroki", "stop:meguro", 15, "{}"),
        ("pattern:h98-split-b", "odpt.Operator:TokyuBus", "東98", "東98", "東98 split B", "", "outbound", "", "tokyu:depot:meguro", "stop:shimizu", "stop:tokyo", 14, "{}"),
        ("pattern:h98-depot", "odpt.Operator:TokyuBus", "東98", "東98", "東98 depot", "", "outbound", "", "tokyu:depot:meguro", "stop:meguro_post", "stop:todoroki", 10, "{}"),
    ]
    conn.executemany("INSERT INTO route_patterns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", pattern_rows)
    conn.executemany(
        "INSERT INTO route_pattern_depots VALUES (?, ?, ?)",
        [(row[0], "tokyu:depot:meguro", "authority_csv") for row in pattern_rows],
    )
    conn.executemany(
        "INSERT INTO route_code_depots VALUES (?, ?, ?)",
        [("東98", "tokyu:depot:meguro", "authority_csv")],
    )
    pattern_stops = [
        ("pattern:h98-main", 1, "stop:tokyo"),
        ("pattern:h98-main", 2, "stop:todoroki"),
        ("pattern:h98-split-a", 1, "stop:todoroki"),
        ("pattern:h98-split-a", 2, "stop:meguro"),
        ("pattern:h98-split-b", 1, "stop:shimizu"),
        ("pattern:h98-split-b", 2, "stop:tokyo"),
        ("pattern:h98-depot", 1, "stop:meguro_post"),
        ("pattern:h98-depot", 2, "stop:todoroki"),
    ]
    conn.executemany("INSERT INTO pattern_stops VALUES (?, ?, ?)", pattern_stops)
    trip_rows = [
        ("trip:h98:001", "tt:h98", "pattern:h98-main", "東98", "平日", "outbound", "stop:tokyo", "stop:todoroki", "06:00", "07:00", 360, 420, 60, 2, 0),
        ("trip:h98:002", "tt:h98", "pattern:h98-split-a", "東98", "平日", "outbound", "stop:todoroki", "stop:meguro", "11:00", "11:30", 660, 690, 30, 2, 0),
        ("trip:h98:003", "tt:h98", "pattern:h98-split-b", "東98", "平日", "outbound", "stop:shimizu", "stop:tokyo", "11:45", "12:30", 705, 750, 45, 2, 0),
        ("trip:h98:004", "tt:h98", "pattern:h98-depot", "東98", "平日", "outbound", "stop:meguro_post", "stop:todoroki", "05:20", "05:45", 320, 345, 25, 2, 0),
    ]
    conn.executemany("INSERT INTO timetable_trips VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", trip_rows)
    conn.commit()
    conn.close()


def test_health_check_reports_missing_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(local_db_catalog, "DB_PATH", tmp_path / "missing.sqlite")
    app = FastAPI()
    app.include_router(catalog_local.router, prefix="/api")
    client = TestClient(app)

    response = client.get("/api/catalog/health")

    assert response.status_code == 200
    assert response.json()["status"] == "db_not_found"


def test_milp_trips_supports_single_depot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    client = _client(monkeypatch, tmp_path)

    response = client.get(
        "/api/catalog/milp-trips",
        params={"depot_id": "meguro", "calendar_type": "平日"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["trip_count"] == 1
    assert body["depot_ids"] == ["tokyu:depot:meguro"]
    assert body["trips"][0]["distance_km"] > 0.0


def test_milp_trips_supports_multiple_depots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    client = _client(monkeypatch, tmp_path)

    response = client.get(
        "/api/catalog/milp-trips",
        params={
            "depot_ids": "meguro,seta",
            "calendar_type": "平日",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["trip_count"] == 3
    assert set(body["depot_ids"]) == {"tokyu:depot:meguro", "tokyu:depot:seta"}


def test_route_families_filter_is_applied(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    client = _client(monkeypatch, tmp_path)

    response = client.get(
        "/api/catalog/milp-trips",
        params={
            "depot_ids": "meguro,seta",
            "route_families": "園01",
            "calendar_type": "平日",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["trip_count"] == 2
    assert {trip["route_family"] for trip in body["trips"]} == {"園01"}


def test_departure_time_window_is_applied(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    client = _client(monkeypatch, tmp_path)

    response = client.get(
        "/api/catalog/milp-trips",
        params={
            "depot_ids": "meguro,seta",
            "calendar_type": "平日",
            "min_dep_min": 400,
            "max_dep_min": 500,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["trip_count"] == 1
    assert body["trips"][0]["trip_id"] == "trip:garden:001"
    assert body["trips"][0]["distance_km"] > 0.0


def test_catalog_depot_summary_endpoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    client = _client(monkeypatch, tmp_path)

    response = client.get("/api/catalog/depots", params={"calendar_type": "平日"})

    assert response.status_code == 200
    body = response.json()
    meguro = next(item for item in body if item["depot_id"] == "tokyu:depot:meguro")
    assert meguro["route_count"] == 1
    assert meguro["trip_count"] == 1


def test_catalog_route_summary_classifies_higashi98_patterns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    db_path = create_local_catalog_db(tmp_path / "tokyu_subset.sqlite")
    _append_higashi98_patterns(db_path)
    monkeypatch.setattr(local_db_catalog, "DB_PATH", db_path)
    app = FastAPI()
    app.include_router(catalog_local.router, prefix="/api")
    client = TestClient(app)

    summary_response = client.get(
        "/api/catalog/depots/meguro/routes",
        params={"include_depot_moves": "true"},
    )
    assert summary_response.status_code == 200
    summary_body = summary_response.json()
    higashi98 = next(item for item in summary_body if item["route_code"] == "東98")
    assert higashi98["dominant_pattern_type"] == "mainline"
    assert any(item["patternType"] == "short_turn" for item in higashi98["pattern_summary"])
    assert any(item["isDepotRelated"] for item in higashi98["pattern_summary"])

    patterns_response = client.get(
        "/api/catalog/route-families/東98/patterns",
        params={"depot_id": "meguro"},
    )
    assert patterns_response.status_code == 200
    patterns_body = patterns_response.json()
    assert {item["patternType"] for item in patterns_body} >= {"mainline", "short_turn", "depot_move"}
