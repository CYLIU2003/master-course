from copy import deepcopy

import pytest

from bff.services import master_defaults
from bff.services.route_catalog_audit import audit_route_catalog_consistency
from bff.store import scenario_store
from src.optimization.common.date_series import validate_dated_timetable
from test_dated_operation_inputs import _dated_scenario


def _saved_dated_scenario(tmp_path, monkeypatch):
    monkeypatch.setattr(scenario_store, "_STORE_DIR", tmp_path / "scenarios")
    scenario = _dated_scenario()
    scenario["scenario_overlay"]["dataset_id"] = "tokyu_full"
    scenario["feed_context"] = {"datasetId": "tokyu_full"}
    scenario["routes"][0].update(
        routeCode="渋21", routeFamilyCode="渋21", canonicalDirection="outbound",
        distanceSource="verified_test_distance", tripCount=6,
        tripCountsByDayType={"WEEKDAY": 2, "SAT": 1, "SUN_HOL": 3},
    )
    scenario_store._save(scenario)
    return scenario


@pytest.mark.parametrize("accessor", ["full", "shallow", "field"])
def test_saved_dated_routes_survive_public_reads_without_global_replacement(
    tmp_path, monkeypatch, accessor,
):
    scenario = _saved_dated_scenario(tmp_path, monkeypatch)
    expected_routes = deepcopy(scenario["routes"])

    def reject_global_catalog(*args, **kwargs):
        raise AssertionError("A dated source must not consult an unrelated preload")

    monkeypatch.setattr(master_defaults, "get_preloaded_master_data", reject_global_catalog)
    scenario_id = scenario["meta"]["id"]
    if accessor == "full":
        loaded = scenario_store.get_scenario_document(scenario_id)
        routes = loaded["routes"]
        assert loaded["timetable_rows"] == scenario["timetable_rows"]
        assert audit_route_catalog_consistency(loaded)["issueCount"] == 0
    elif accessor == "shallow":
        routes = scenario_store.get_scenario_document_shallow(scenario_id)["routes"]
    else:
        routes = scenario_store.get_field(scenario_id, "routes")

    assert routes == expected_routes


def test_missing_dated_artifacts_remain_missing_instead_of_using_global_templates(
    tmp_path, monkeypatch,
):
    scenario = _saved_dated_scenario(tmp_path, monkeypatch)
    scenario["timetable_rows"] = []
    scenario["routes"] = []
    scenario_store._save(scenario)

    def reject_global_catalog(*args, **kwargs):
        raise AssertionError("Missing dated input must not be silently regenerated")

    monkeypatch.setattr(master_defaults, "get_preloaded_master_data", reject_global_catalog)
    monkeypatch.setattr("src.tokyu_bus_data.load_trip_rows_for_scope", reject_global_catalog)
    loaded = scenario_store.get_scenario_document(scenario["meta"]["id"])
    assert loaded["routes"] == []
    assert loaded["timetable_rows"] == []
    with pytest.raises(ValueError):
        validate_dated_timetable([], loaded["simulation_config"]["date_series_contract"])


def test_dated_fallback_helpers_do_not_replace_declared_scope_or_master_data(monkeypatch):
    scenario = _dated_scenario()
    scenario["scenario_overlay"]["dataset_id"] = "tokyu_full"
    before = deepcopy(scenario)

    def reject_global_catalog(*args, **kwargs):
        raise AssertionError("Dated data must stay attached to its declared source")

    monkeypatch.setattr(master_defaults, "get_preloaded_master_data", reject_global_catalog)
    assert scenario_store._repair_route_metadata_from_preload(scenario) is False
    assert scenario_store._repair_missing_master_defaults(scenario) is False
    assert scenario_store._needs_runtime_master_alignment(scenario) is False
    assert scenario_store._tokyu_bus_timetable_summary_for_doc(scenario) is None
    assert scenario_store._tokyu_bus_timetable_rows_for_doc(scenario) == []
    assert scenario_store._tokyu_bus_route_service_count_rows_for_doc(scenario) == []
    assert scenario == before
