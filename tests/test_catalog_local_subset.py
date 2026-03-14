from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bff.routers import catalog_local
from bff.services import local_db_catalog
from tests._local_catalog_fixture import create_local_catalog_db


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    db_path = create_local_catalog_db(tmp_path / "tokyu_subset.sqlite")
    monkeypatch.setattr(local_db_catalog, "DB_PATH", db_path)
    app = FastAPI()
    app.include_router(catalog_local.router, prefix="/api")
    return TestClient(app)


def test_catalog_health(client: TestClient):
    response = client.get("/api/catalog/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_catalog_operators(client: TestClient):
    response = client.get("/api/catalog/operators")

    assert response.status_code == 200
    assert response.json()[0]["operator_id"] == "odpt.Operator:TokyuBus"


def test_catalog_milp_trips_single_depot(client: TestClient):
    response = client.get("/api/catalog/milp-trips", params={"depot_id": "meguro", "calendar_type": "平日"})

    assert response.status_code == 200
    body = response.json()
    assert body["trip_count"] == 1
    assert body["depot_ids"] == ["tokyu:depot:meguro"]


def test_catalog_milp_trips_multiple_depots(client: TestClient):
    response = client.get("/api/catalog/milp-trips", params={"depot_ids": "meguro,seta", "calendar_type": "平日"})

    assert response.status_code == 200
    body = response.json()
    assert body["trip_count"] == 3
    assert set(body["depot_ids"]) == {"tokyu:depot:meguro", "tokyu:depot:seta"}
