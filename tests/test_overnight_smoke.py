import pytest

from tools.cluster.overnight_smoke import scenario_for_days
from src.optimization.common.date_series import validate_dated_timetable


@pytest.mark.parametrize("days,trips", [(1, 4), (2, 8), (7, 25)])
def test_smoke_declares_continuous_dates_and_actual_weekend_templates(days, trips):
    scenario = scenario_for_days(days)
    config = scenario["simulation_config"]
    audit = validate_dated_timetable(scenario["timetable_rows"], config["date_series_contract"])
    assert audit["timetable_row_count"] == trips
    assert config["daily_return_depot_id"] == "SMOKE_DEPOT"
    assert len(config["depot_energy_assets"][0]["pv_capacity_factor_by_date"]) == days
    assert len(scenario["energy_price_profiles"][0]["values"]) == 48 * days
    assert not config["date_series_contract"]["source_provenance"]["research_eligible"]
    assert len({row["trip_id"] for row in scenario["timetable_rows"]}) == trips
    assert set(scenario["dispatch_scope"]["serviceSelection"]["serviceIds"]) == {
        row["service_id"] for row in scenario["timetable_rows"]}
    from src.optimization.common.cost_components import normalize_cost_component_flags
    flags = normalize_cost_component_flags(config["cost_component_flags"],
                                           legacy_enable_other_cost=config["enable_other_cost"])
    assert flags["electricity_cost"]
    assert all(not enabled for key, enabled in flags.items() if key != "electricity_cost")


def test_smoke_rejects_undeclared_duration():
    with pytest.raises(ValueError):
        scenario_for_days(3)


def test_week_scope_survives_store_normalization(monkeypatch):
    from bff.store import scenario_store
    document = scenario_for_days(7)
    monkeypatch.setattr(scenario_store, "_load", lambda *args, **kwargs: document)
    monkeypatch.setattr(scenario_store, "_save", lambda payload: None)
    scope = scenario_store.set_dispatch_scope(document["meta"]["id"], {
        key: value for key, value in document["dispatch_scope"].items() if key != "serviceId"})
    assert set(scope["serviceSelection"]["serviceIds"]) == {
        row["service_id"] for row in document["timetable_rows"]}
