from copy import deepcopy

import pytest

from tools.research.audit_charging_replay_bess import audit


def inputs():
    asset = {"depot_id": "d", "bess_enabled": True, "bess_charge_efficiency": .9,
             "bess_discharge_efficiency": .8, "bess_soc_min_kwh": 10,
             "bess_soc_max_kwh": 90, "bess_power_kw": 40, "allow_grid_to_bess": False}
    plan = {"metadata": {"rolling_start_slot_index": 4, "rolling_stop_slot_index": 6,
                         "timestep_min": 15, "bess_soc_start_kwh_by_depot_slot": {"d": {"4": 50, "5": 59}},
                         "bess_soc_end_kwh_by_depot_slot": {"d": {"4": 59, "5": 49}}},
            "bess_soc_kwh_by_depot_slot": {"d": {"4": 59, "5": 49}},
            "pv_to_bess_kwh_by_depot_slot": {"d": {"4": 10}},
            "grid_to_bess_kwh_by_depot_slot": {}, "bess_to_bus_kwh_by_depot_slot": {"d": {"5": 8}}}
    return plan, [asset], {"d": 50}


def test_uses_actual_boundary_inventory_and_both_efficiencies():
    report = audit(*inputs())
    assert report["depots"][0]["intervals"] == 2
    assert report["depots"][0]["end_kwh"] == 49
    assert report["depots"][0]["max_balance_residual_kwh"] == 0
    assert "vehicle SOC" in report["not_checked"]


@pytest.mark.parametrize("defect", ["initial", "missing_trace", "efficiency", "grid", "power", "nan", "end"])
def test_rejects_corrupt_or_unsupported_physical_evidence(defect):
    plan, assets, initial = deepcopy(inputs())
    if defect == "initial": initial["d"] = 51
    if defect == "missing_trace": del plan["bess_soc_kwh_by_depot_slot"]["d"]["5"]
    if defect == "efficiency": assets[0]["bess_discharge_efficiency"] = 0
    if defect == "grid": plan["grid_to_bess_kwh_by_depot_slot"] = {"d": {"4": 1}}
    if defect == "power": assets[0]["bess_power_kw"] = 20
    if defect == "nan": plan["pv_to_bess_kwh_by_depot_slot"]["d"]["4"] = float("nan")
    if defect == "end": plan["metadata"]["bess_soc_end_kwh_by_depot_slot"]["d"]["5"] = 48
    with pytest.raises((ValueError, KeyError)):
        audit(plan, assets, initial)
