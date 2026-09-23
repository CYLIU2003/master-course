from datetime import date
import pytest
from tools.cluster.monthly_smoke import scenario_for_month
from src.optimization.common.date_series import validate_dated_timetable


def test_twelve_months_preserve_declared_scope_and_calendar():
    scenarios = [scenario_for_month(2025, month) for month in range(1, 13)]
    assert len({s["meta"]["id"] for s in scenarios}) == 12
    for month, scenario in enumerate(scenarios, 1):
        config = scenario["simulation_config"]
        day = date.fromisoformat(config["service_date"])
        assert day.month == month and day.weekday() == 1
        assert config["planning_days"] == 1
        assert config["allow_same_day_depot_cycles"] is False
        assert scenario["vehicles"][0]["batteryKwh"] == 200
        assert len(scenario["vehicles"]) == 2
        rows = scenario["timetable_rows"]
        assert len(rows) == 4 and sum(row["distance_km"] for row in rows) == 40
        assert {row["operator_id"] for row in rows} == {"synthetic_cluster"}
        validate_dated_timetable(rows, config["date_series_contract"])


def test_timetable_tampering_is_rejected():
    scenario = scenario_for_month(2025, 1)
    scenario["timetable_rows"][0]["distance_km"] = 0
    with pytest.raises(ValueError, match="changed"):
        validate_dated_timetable(scenario["timetable_rows"], scenario["simulation_config"]["date_series_contract"])


def test_shibu24_dummy_has_explicit_synthetic_provenance():
    scenario = scenario_for_month(2025, 1, route_id="渋24")
    assert scenario["scenario_overlay"]["route_ids"] == ["渋24"]
    assert scenario["dispatch_scope"]["effectiveRouteIds"] == ["渋24"]
    assert {row["route_id"] for row in scenario["timetable_rows"]} == {"渋24"}
    assert {row["distance_source"] for row in scenario["timetable_rows"]} == {"declared_synthetic_fixture"}
    assert scenario["simulation_config"]["date_series_contract"]["source_provenance"]["research_eligible"] is False
    validate_dated_timetable(scenario["timetable_rows"], scenario["simulation_config"]["date_series_contract"])


def test_batch_generator_persists_scope_before_prepare_and_preserves_output_directory(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    from tools.cluster import synthetic_batch, serve_controller
    from bff.services.cluster import contracts
    from bff.services import run_preparation
    from bff.store import scenario_store, output_paths
    release = tmp_path / "frozen"
    release.mkdir()
    monkeypatch.chdir(tmp_path)
    def configure(path):
        assert path == tmp_path / "settings.json"
        monkeypatch.chdir(release)
        return {"release": str(release), "git_sha": "a" * 40}
    monkeypatch.setattr(serve_controller, "configure", configure)
    monkeypatch.setattr(contracts, "read_config", lambda: SimpleNamespace(workers=[]))
    documents = {}
    normalized = set()
    def get_document(scenario_id):
        return documents[scenario_id]
    def persist_scope(scenario_id, scope):
        assert scope == {"depotId": "SMOKE_DEPOT", "serviceId": "WEEKDAY"}
        normalized.add(scenario_id)
    def prepare(document, *args):
        assert document["meta"]["id"] in normalized
        assert document["simulation_config"]["execution_profile"] == "alns_no_gurobi_v1"
        return SimpleNamespace(is_valid=True, prepared_input_id="prepared-" + document["meta"]["id"])
    monkeypatch.setattr(scenario_store, "_save", lambda document: documents.update({document["meta"]["id"]: document}))
    monkeypatch.setattr(scenario_store, "get_scenario_document_shallow", get_document)
    monkeypatch.setattr(scenario_store, "get_scenario_document", get_document)
    monkeypatch.setattr(scenario_store, "set_dispatch_scope", persist_scope)
    monkeypatch.setattr(run_preparation, "get_or_build_run_preparation", prepare)
    monkeypatch.setattr(output_paths, "outputs_root", lambda: tmp_path / "outputs")
    monkeypatch.setattr(synthetic_batch.sys, "argv", ["synthetic_batch.py", "--settings", "settings.json",
        "--output", "requested/batch.json", "--batch-id", "scope-check", "--dummy-route", "渋24"])
    synthetic_batch.main()
    manifest = json.loads((tmp_path / "requested/batch.json").read_bytes())
    assert len(manifest["tasks"]) == len(normalized) == 12
    assert all(document["scenario_overlay"]["route_ids"] == ["渋24"] for document in documents.values())
    assert all(document["simulation_config"]["bev_terminal_soc_policy"] == "return_to_initial" for document in documents.values())
    assert not (release / "requested/batch.json").exists()
