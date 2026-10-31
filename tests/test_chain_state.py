import pytest

from tools.research.chain_state import boundary_state


def _plan():
    return {"vehicle_soc_kwh_by_vehicle_slot": {"B1": {"120": 100.0, "121": 110.0, "122": 120.0}},
            "bess_soc_kwh_by_depot_slot": {"d": {"120": 500.0, "121": 510.0}}}


def test_morning_boundary_uses_slot_start_for_buses_and_previous_slot_end_for_bess():
    state = boundary_state(_plan(), boundary_slot=121, depot_id="d", previous_soc_kwh={"B1": 1.0, "B2": 77.0},
                           fuel_l={"I1": 40.0})
    assert state["vehicle_soc_kwh"] == {"B1": 110.0, "B2": 77.0}
    assert state["bess_soc_kwh"] == 500.0
    assert state["vehicle_fuel_l"] == {"I1": 40.0}
    assert state["unused_bev_ids"] == ["B2"]


@pytest.mark.parametrize("plan_change", ["missing_slot", "unknown_bus"])
def test_incomplete_or_foreign_state_is_rejected(plan_change):
    plan = _plan()
    if plan_change == "missing_slot":
        del plan["vehicle_soc_kwh_by_vehicle_slot"]["B1"]["121"]
    else:
        plan["vehicle_soc_kwh_by_vehicle_slot"]["B9"] = {"121": 1.0}
    with pytest.raises(ValueError):
        boundary_state(plan, boundary_slot=121, depot_id="d", previous_soc_kwh={"B1": 1.0}, fuel_l={})
