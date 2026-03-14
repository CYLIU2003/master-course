import hashlib
import json
import pathlib
import tempfile

import pandas as pd
from fastapi.testclient import TestClient

from bff.services import research_catalog
from bff.store import scenario_store


def _make_minimal_built(tmp: pathlib.Path) -> pathlib.Path:
    built_dir = tmp / "tokyu_core"
    built_dir.mkdir()
    for name, frame in [
        (
            "routes.parquet",
            pd.DataFrame(
                [
                    {
                        "id": "tokyu:meguro:route-01",
                        "routeCode": "route-01",
                        "routeLabel": "route-01",
                        "name": "route-01",
                    }
                ]
            ),
        ),
        (
            "trips.parquet",
            pd.DataFrame(
                [
                    {
                        "trip_id": "t001",
                        "route_id": "tokyu:meguro:route-01",
                        "service_id": "weekday",
                        "departure": "06:00:00",
                        "arrival": "07:00:00",
                    }
                ]
            ),
        ),
        (
            "timetables.parquet",
            pd.DataFrame(
                [
                    {
                        "trip_id": "t001",
                        "route_id": "tokyu:meguro:route-01",
                        "service_id": "weekday",
                        "origin": "A",
                        "destination": "B",
                        "departure": "06:00:00",
                        "arrival": "07:00:00",
                    }
                ]
            ),
        ),
    ]:
        frame.to_parquet(built_dir / name)

    def sha(path: pathlib.Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = {
        "dataset_id": "tokyu_core",
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
            name: sha(built_dir / name)
            for name in ["routes.parquet", "trips.parquet", "timetables.parquet"]
        },
        "row_counts": {"routes": 1, "trips": 1, "timetables": 1},
        "schema_versions": {"routes": "v1", "trips": "v1", "timetables": "v1"},
    }
    (built_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return built_dir


def test_app_state_response_is_small(monkeypatch):
    from bff.main import app
    from bff.services import app_cache

    with tempfile.TemporaryDirectory() as tmp:
        _make_minimal_built(pathlib.Path(tmp))
        monkeypatch.setattr(app_cache, "BUILT_ROOT", pathlib.Path(tmp))
        monkeypatch.setattr(app_cache, "DEFAULT_DATASET_ID", "tokyu_core")
        app_cache.reload_state()

        client = TestClient(app)
        response = client.get("/api/app-state")
        assert response.status_code == 200
        assert len(response.content) < 10_000


def test_depot_list_does_not_embed_trips(monkeypatch):
    from bff.main import app
    from bff.services import app_cache

    with tempfile.TemporaryDirectory() as tmp:
        _make_minimal_built(pathlib.Path(tmp))
        monkeypatch.setattr(app_cache, "BUILT_ROOT", pathlib.Path(tmp))
        monkeypatch.setattr(app_cache, "DEFAULT_DATASET_ID", "tokyu_core")
        app_cache.reload_state()

        meta = scenario_store.create_scenario("Perf depot list", "", "mode_B_resource_assignment")
        bootstrap = research_catalog.bootstrap_scenario(
            scenario_id=meta["id"],
            dataset_id="tokyu_core",
            random_seed=42,
        )
        scenario_store.apply_dataset_bootstrap(meta["id"], bootstrap)

        client = TestClient(app)
        response = client.get(f"/api/scenarios/{meta['id']}/depots")
        assert response.status_code == 200
        body_str = json.dumps(response.json())
        assert "stop_times" not in body_str
        assert "timetable_rows" not in body_str
        assert len(response.content) < 100_000


def test_scenario_list_does_not_embed_full_overlay(monkeypatch):
    from bff.main import app
    from bff.services import app_cache

    with tempfile.TemporaryDirectory() as tmp:
        _make_minimal_built(pathlib.Path(tmp))
        monkeypatch.setattr(app_cache, "BUILT_ROOT", pathlib.Path(tmp))
        monkeypatch.setattr(app_cache, "DEFAULT_DATASET_ID", "tokyu_core")
        app_cache.reload_state()

        client = TestClient(app)
        response = client.get("/api/scenarios")
        assert response.status_code == 200
        body = response.json()
        items = body.get("items") if isinstance(body, dict) else body
        if isinstance(items, list) and items:
            first = json.dumps(items[0])
            assert len(first) < 2000
            assert "scenarioOverlay" not in first


def test_performance_budget_is_documented():
    path = pathlib.Path("docs/notes/performance_baseline.md")
    assert path.exists(), "docs/notes/performance_baseline.md must exist"
    text = path.read_text(encoding="utf-8")
    assert "Budget" in text or "budget" in text
    import re

    assert bool(re.search(r"\d+\s*(ms|KB|MB|s\b)", text)), (
        "performance_baseline.md must contain numeric performance targets "
        "(e.g., '< 200ms', '< 300KB')"
    )
