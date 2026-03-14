from __future__ import annotations

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
