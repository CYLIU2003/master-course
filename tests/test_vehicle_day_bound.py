from dataclasses import replace
import pytest

from src.optimization.common.vehicle_day_bound import vehicle_day_overlap_lower_bounds
from test_daily_return_policy import daily_problem


def trip(name, start, end):
    return replace(daily_problem().trips[0], trip_id=name, departure_min=start, arrival_min=end)


def test_daily_overlap_bound_counts_vehicle_days_and_arrival_departure_ties():
    trips = [trip("a", 10, 20), trip("b", 15, 25), trip("c", 20, 30),
             trip("d", 1450, 1460)]
    assert vehicle_day_overlap_lower_bounds(trips, {"a": 0, "b": 0, "c": 0, "d": 1}) == {0: 2, 1: 1}


def test_overnight_trip_belongs_to_its_departure_day_cost_bucket():
    trips = [trip("a", 1430, 1460), trip("b", 1440, 1470)]
    assert vehicle_day_overlap_lower_bounds(trips, {"a": 0, "b": 1}) == {0: 1, 1: 1}


def test_invalid_duration_cannot_strengthen_a_certificate():
    with pytest.raises(ValueError, match="positive absolute"):
        vehicle_day_overlap_lower_bounds([trip("a", 10, 10)], {"a": 0})


def test_bounded_presolve_controls_are_exposed_by_api_and_native_configuration():
    from bff.routers.optimization import RunOptimizationBody
    from src.optimization.common.problem import OptimizationConfig
    from src.optimization.milp.solver_adapter import _configured_stage1_gurobi_search_controls
    request = RunOptimizationBody(stage1_gurobi_search_profile="bounded_presolve")
    controls = _configured_stage1_gurobi_search_controls(OptimizationConfig(
        stage1_gurobi_search_profile=request.stage1_gurobi_search_profile))
    assert controls["presolve"] == 1
    assert controls["pre_passes"] == 3
    assert controls["mip_focus"] == 1
