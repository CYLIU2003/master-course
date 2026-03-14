from pathlib import Path

import pytest

from bff.routers import scenarios
from bff.services import research_catalog
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
    assert [depot["id"] for depot in doc["depots"]] == ["meguro", "seta", "awashima", "tsurumaki"]
    assert len(doc["vehicle_templates"]) >= 2
    assert len(doc["routes"]) > 0
    assert len(doc["depot_route_permissions"]) >= len(doc["routes"])
    assert {item["routeId"] for item in doc["depot_route_permissions"]} == {
        item["id"] for item in doc["routes"]
    }
    assert doc["dispatch_scope"]["depotId"] == "meguro"
    assert len(doc["scenario_overlay"]["route_ids"]) == len(doc["routes"])


def test_existing_scenario_is_bootstrapped_on_get(temp_store_dir: Path):
    body = scenarios.CreateScenarioBody(name="Tokyu Core")

    meta = scenarios.create_scenario(body)
    scenario_id = meta["id"]
    scenario_store.set_field(scenario_id, "depots", [])
    scenario_store.set_field(scenario_id, "routes", [])
    scenario_store.set_field(scenario_id, "timetable_rows", [])
    scenario_store.set_field(scenario_id, "trips", [])

    scenarios.get_scenario(scenario_id)
    hydrated = scenario_store._load(scenario_id)

    assert [depot["id"] for depot in hydrated["depots"]] == ["meguro", "seta", "awashima", "tsurumaki"]
    assert len(hydrated["routes"]) > 0
    assert hydrated["dispatch_scope"]["depotId"] == "meguro"


def test_create_scenario_persists_bootstrap_stops_and_stop_timetables(
    temp_store_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    real_bootstrap = research_catalog.bootstrap_scenario

    def fake_bootstrap_scenario(*, scenario_id: str, dataset_id: str = "tokyu_core", random_seed: int = 42):
        payload = real_bootstrap(
            scenario_id=scenario_id,
            dataset_id=dataset_id,
            random_seed=random_seed,
        )
        payload["stops"] = [
            {"id": "stop:A", "name": "A", "lat": 35.0, "lon": 139.0, "source": "test"}
        ]
        payload["stop_timetables"] = [
            {
                "id": "stop:A::WEEKDAY",
                "stopId": "stop:A",
                "calendar": "WEEKDAY",
                "service_id": "WEEKDAY",
                "source": "test",
                "items": [{"index": 0, "departure": "06:00", "busroutePattern": "R1"}],
            }
        ]
        return payload

    monkeypatch.setattr(scenarios.research_catalog, "bootstrap_scenario", fake_bootstrap_scenario)

    meta = scenarios.create_scenario(scenarios.CreateScenarioBody(name="Tokyu Core with stops"))
    doc = scenario_store._load(meta["id"])

    assert doc["stops"] == [{"id": "stop:A", "name": "A", "lat": 35.0, "lon": 139.0, "source": "test"}]
    assert doc["stop_timetables"][0]["stopId"] == "stop:A"
