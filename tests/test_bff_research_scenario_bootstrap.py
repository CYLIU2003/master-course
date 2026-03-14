from pathlib import Path

import pytest

from bff.routers import scenarios
from bff.store import scenario_store


@pytest.fixture()
def temp_store_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store_dir = tmp_path / "scenarios"
    app_context_path = tmp_path / "app_context.json"
    monkeypatch.setattr(scenario_store, "_STORE_DIR", store_dir)
    monkeypatch.setattr(scenario_store, "_APP_CONTEXT_PATH", app_context_path)
    return store_dir


def test_create_scenario_bootstraps_tokyu_core_seed_dataset(temp_store_dir: Path):
    body = scenarios.CreateScenarioBody(name="Tokyu Core")

    meta = scenarios.create_scenario(body)
    scenario_id = meta["id"]
    doc = scenario_store._load(scenario_id)

    assert meta["operatorId"] == "tokyu"
    assert meta["datasetId"] == "tokyu_core"
    assert isinstance(meta["datasetVersion"], str) and meta["datasetVersion"]
    assert meta["randomSeed"] == 42
    assert doc["feed_context"]["source"] in {"seed_only", "built_dataset"}
    assert [depot["id"] for depot in doc["depots"]] == ["meguro"]
    assert len(doc["routes"]) == 11
    assert len(doc["vehicle_templates"]) >= 2
    assert len(doc["depot_route_permissions"]) == 11
    assert doc["dispatch_scope"]["depotId"] == "meguro"
    assert len(doc["scenario_overlay"]["route_ids"]) == 11
