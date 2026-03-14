from __future__ import annotations

import importlib


def test_main_bff_excludes_catalog_and_public_data_routes_by_default(monkeypatch):
    monkeypatch.delenv("CATALOG_BACKEND", raising=False)
    import bff.main as main_module

    reloaded = importlib.reload(main_module)
    paths = {route.path for route in reloaded.app.routes}

    assert "/api/app/datasets" in paths
    assert "/api/app/data-status" in paths
    assert "/api/catalog/operators" not in paths
    assert "/api/scenarios/{scenario_id}/public-data/fetch" not in paths


def test_main_bff_mounts_local_catalog_when_enabled(monkeypatch):
    monkeypatch.setenv("CATALOG_BACKEND", "local_sqlite")
    import bff.main as main_module

    reloaded = importlib.reload(main_module)
    paths = {route.path for route in reloaded.app.routes}

    assert "/api/catalog/health" in paths
    assert "/api/catalog/operators" in paths
