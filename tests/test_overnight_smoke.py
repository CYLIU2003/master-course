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


def test_smoke_rejects_undeclared_duration():
    with pytest.raises(ValueError):
        scenario_for_days(3)
