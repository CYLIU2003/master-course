import pytest

from tools.research.chain_state import boundary_state


def _state(**changes):
    return {"current_min": 1440, "in_progress_events": {}, "actual_vehicle_soc_kwh": {"B1": 110.0},
            "actual_vehicle_fuel_l": {"I1": 40.0}, "actual_bess_soc_kwh": {"d": 500.0}, **changes}


def _boundary(state):
    return boundary_state(state, days=1, depot_id="d", previous_soc_kwh={"B1": 1.0, "B2": 77.0},
                          previous_fuel_l={"I1": 90.0})


def test_used_vehicles_update_and_unused_vehicles_keep_their_state():
    result = _boundary(_state())
    assert result["vehicle_soc_kwh"] == {"B1": 110.0, "B2": 77.0}
    assert result["vehicle_fuel_l"] == {"I1": 40.0} and result["bess_soc_kwh"] == 500.0
    assert result["unused_bev_ids"] == ["B2"]


@pytest.mark.parametrize("change", [{"current_min": 1380}, {"in_progress_events": {"B1": {}}},
                                    {"actual_vehicle_soc_kwh": {"B9": 1.0}}])
def test_wrong_time_running_vehicle_or_foreign_bus_is_rejected(change):
    with pytest.raises(ValueError):
        _boundary(_state(**change))
