import hashlib
import json
import pathlib
import tempfile

import pandas as pd
from fastapi.testclient import TestClient


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _make_valid_built_dir(
    tmp: pathlib.Path,
    dataset_id: str = "tokyu_core",
) -> pathlib.Path:
    built_dir = tmp / dataset_id
    built_dir.mkdir(parents=True)

    pd.DataFrame(
        [{"id": "tokyu:meguro:route-01", "routeCode": "route-01", "routeLabel": "route-01", "name": "route-01"}]
    ).to_parquet(built_dir / "routes.parquet")
    pd.DataFrame(
        [{"trip_id": "t001", "route_id": "tokyu:meguro:route-01", "service_id": "weekday", "departure": "06:00:00", "arrival": "07:00:00"}]
    ).to_parquet(built_dir / "trips.parquet")
    pd.DataFrame(
        [{"trip_id": "t001", "route_id": "tokyu:meguro:route-01", "service_id": "weekday", "origin": "A", "destination": "B", "departure": "06:00:00", "arrival": "07:00:00"}]
    ).to_parquet(built_dir / "timetables.parquet")

    manifest = {
        "dataset_id": dataset_id,
        "dataset_version": "2026-03-13",
        "generated_at": "2026-03-13T00:00:00Z",
        "source": "test",
        "schema_version": "v1",
        "producer_version": "0.1.0",
        "min_runtime_version": "0.1.0",
        "included_depots": ["meguro"],
        "included_routes": ["route-01"],
        "seed_hash": "abc",
        "artifact_hashes": {
            "routes.parquet": _sha256(built_dir / "routes.parquet"),
            "trips.parquet": _sha256(built_dir / "trips.parquet"),
            "timetables.parquet": _sha256(built_dir / "timetables.parquet"),
        },
        "row_counts": {"routes": 1, "trips": 1, "timetables": 1},
        "schema_versions": {"routes": "v1", "trips": "v1", "timetables": "v1"},
    }
    (built_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return built_dir


def test_app_state_built_ready_when_valid_manifest(monkeypatch):
    from bff.main import app
    from bff.services import app_cache

    with tempfile.TemporaryDirectory() as tmp:
        _make_valid_built_dir(pathlib.Path(tmp))
        monkeypatch.setattr(app_cache, "BUILT_ROOT", pathlib.Path(tmp))
        monkeypatch.setattr(app_cache, "DEFAULT_DATASET_ID", "tokyu_core")
        app_cache.reload_state()

        client = TestClient(app)
        response = client.get("/api/app-state")

        assert response.status_code == 200
        body = response.json()
        assert body["built_ready"] is True
        assert body["contract_error_code"] is None
        assert body["integrity_error"] is None


def test_app_state_not_built_ready_when_manifest_missing(monkeypatch):
    from bff.main import app
    from bff.services import app_cache

    with tempfile.TemporaryDirectory() as tmp:
        built_dir = _make_valid_built_dir(pathlib.Path(tmp))
        (built_dir / "manifest.json").unlink()

        monkeypatch.setattr(app_cache, "BUILT_ROOT", pathlib.Path(tmp))
        monkeypatch.setattr(app_cache, "DEFAULT_DATASET_ID", "tokyu_core")
        app_cache.reload_state()

        client = TestClient(app)
        response = client.get("/api/app-state")

        assert response.status_code == 200
        body = response.json()
        assert body["built_ready"] is False
        assert body["contract_error_code"] == "ARTIFACT_MANIFEST_MISSING"


def test_app_state_contract_error_on_version_mismatch(monkeypatch):
    from bff.main import app
    from bff.services import app_cache

    with tempfile.TemporaryDirectory() as tmp:
        built_dir = _make_valid_built_dir(pathlib.Path(tmp))
        manifest = json.loads((built_dir / "manifest.json").read_text(encoding="utf-8"))
        manifest["min_runtime_version"] = "99.0.0"
        (built_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

        monkeypatch.setattr(app_cache, "BUILT_ROOT", pathlib.Path(tmp))
        monkeypatch.setattr(app_cache, "DEFAULT_DATASET_ID", "tokyu_core")
        app_cache.reload_state()

        client = TestClient(app)
        response = client.get("/api/app-state")

        assert response.status_code == 200
        body = response.json()
        assert body["built_ready"] is False
        assert body["contract_error_code"] == "RUNTIME_VERSION_TOO_OLD"


def test_app_state_contract_error_on_hash_mismatch(monkeypatch):
    from bff.main import app
    from bff.services import app_cache

    with tempfile.TemporaryDirectory() as tmp:
        built_dir = _make_valid_built_dir(pathlib.Path(tmp))
        (built_dir / "routes.parquet").write_bytes(b"corrupted data")

        monkeypatch.setattr(app_cache, "BUILT_ROOT", pathlib.Path(tmp))
        monkeypatch.setattr(app_cache, "DEFAULT_DATASET_ID", "tokyu_core")
        app_cache.reload_state()

        client = TestClient(app)
        response = client.get("/api/app-state")

        assert response.status_code == 200
        body = response.json()
        assert body["built_ready"] is False
        assert body["contract_error_code"] == "ARTIFACT_HASH_MISMATCH"


def test_run_endpoint_returns_503_when_not_built_ready(monkeypatch):
    from bff.main import app
    from bff.services import app_cache

    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setattr(app_cache, "BUILT_ROOT", pathlib.Path(tmp))
        monkeypatch.setattr(app_cache, "DEFAULT_DATASET_ID", "tokyu_core")
        app_cache.reload_state()

        client = TestClient(app)
        response = client.post("/api/scenarios/test-scenario-id/run-simulation")

        assert response.status_code == 503
        body = response.json()
        assert body["detail"]["error"] == "BUILT_DATASET_REQUIRED"


def test_app_master_data_endpoint_returns_preloaded_master_blueprint():
    from bff.main import app

    client = TestClient(app)
    response = client.get("/api/app/master-data")

    assert response.status_code == 200
    body = response.json()
    assert body["datasetId"] == "tokyu_dispatch_ready"
    assert {item["id"] for item in body["depots"]} == {
        "meguro",
        "seta",
        "awashima",
        "tsurumaki",
    }
    assert len(body["routes"]) == 46
    assert len(body["vehicleTemplates"]) >= 2
