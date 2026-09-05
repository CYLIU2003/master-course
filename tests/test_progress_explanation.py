"""Regression checks for the new descriptive measures, without solver calls."""
import pytest

from tools.thesis_authoring.build_progress_explanation import (
    charging_by_slot, dispatch_rows, dispatch_statistics,
)


def test_charging_source_splits_count_one_port():
    rows = [dict(slot_index=0, charger_id="c", vehicle_id="v", charge_kw=p,
                 energy_kwh=p / 4) for p in (10, 20)]
    result = charging_by_slot(rows, ["c"])
    assert len(result) == 96
    assert result[0]["charging_sessions_gt_1e_minus6_kw"] == 1
    assert result[0]["charging_kw"] == 30


def test_two_vehicles_on_one_port_are_rejected():
    rows = [dict(slot_index=0, charger_id="c", vehicle_id=v, charge_kw=30,
                 energy_kwh=7.5) for v in ("v1", "v2")]
    with pytest.raises(ValueError, match="one-port"):
        charging_by_slot(rows, ["c"])


def test_tiny_solver_power_is_disclosed_separately():
    rows = [dict(slot_index=0, charger_id="c", vehicle_id="v", charge_kw=.0002,
                 energy_kwh=.00005)]
    result = charging_by_slot(rows, ["c"])[0]
    assert result["charging_sessions_gt_1e_minus6_kw"] == 1
    assert result["charging_sessions_ge_1_kw"] == 0


def test_distance_share_is_not_trip_share():
    rows = [dict(scenario="fixture", powertrain=p, vehicle_id=p,
                 service_distance_km=d, service_minutes=t)
            for p, d, t in [("BEV", 10, 20), ("ICE", 30, 60)]]
    bev = dispatch_statistics(rows)[0]
    assert bev["trip_share"] == .5
    assert bev["service_distance_share"] == .25
    assert bev["service_time_share"] == .25


@pytest.mark.parametrize("paths", [{"v": ["t", "t"]}, {"v": []}])
def test_duplicate_or_missing_trips_block_derivation(paths):
    prepared = {"trips": [{"trip_id": "t"}], "vehicles": [{"id": "v"}]}
    with pytest.raises(RuntimeError):
        dispatch_rows(prepared, paths, "fixture")
