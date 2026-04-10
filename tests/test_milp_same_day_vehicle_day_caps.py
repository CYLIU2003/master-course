from __future__ import annotations

import pytest

from src.dispatch.models import DeadheadRule, DispatchContext, Trip, VehicleProfile
from src.gurobi_runtime import is_gurobi_available
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import OptimizationConfig, OptimizationMode
from src.optimization.milp.engine import MILPOptimizer


def _context() -> DispatchContext:
    return DispatchContext(
        service_date="2026-04-09",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=5.0,
                allowed_vehicle_types=("ICE",),
            ),
            Trip(
                trip_id="t2",
                route_id="r1",
                origin="C",
                destination="D",
                departure_time="08:30",
                arrival_time="08:40",
                distance_km=5.0,
                allowed_vehicle_types=("ICE",),
            ),
        ],
        turnaround_rules={},
        deadhead_rules={
            ("DEPOT", "A"): DeadheadRule("DEPOT", "A", 5),
            ("B", "DEPOT"): DeadheadRule("B", "DEPOT", 5),
            ("DEPOT", "C"): DeadheadRule("DEPOT", "C", 5),
            ("B", "C"): DeadheadRule("B", "C", 25),
        },
        vehicle_profiles={
            "ICE": VehicleProfile(
                vehicle_type="ICE",
                fuel_tank_capacity_l=200.0,
                fuel_consumption_l_per_km=0.5,
            )
        },
    )


def _problem(*, daily_fragment_limit: int, vehicle_count: int):
    return ProblemBuilder().build_from_dispatch(
        _context(),
        scenario_id="milp-day-cap",
        vehicle_counts={"ICE": vehicle_count},
        canonical_depot_id="DEPOT",
        timestep_min=10,
        allow_same_day_depot_cycles=True,
        max_depot_cycles_per_vehicle_per_day=daily_fragment_limit,
        max_fragments_per_vehicle_per_day=daily_fragment_limit,
        max_start_fragments_per_vehicle=daily_fragment_limit,
        max_end_fragments_per_vehicle=daily_fragment_limit,
        fixed_route_band_mode=False,
        service_coverage_mode="strict",
    )


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi is required for exact MILP cap checks.")
def test_milp_can_use_two_fragments_on_one_vehicle_when_day_cap_is_two() -> None:
    result = MILPOptimizer().solve(
        _problem(daily_fragment_limit=2, vehicle_count=1),
        OptimizationConfig(mode=OptimizationMode.MILP, time_limit_sec=10, mip_gap=0.0),
    )

    assert result.feasible is True
    assert result.plan.max_fragments_observed() == 2


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi is required for exact MILP cap checks.")
def test_milp_uses_second_vehicle_when_day_cap_is_one() -> None:
    result = MILPOptimizer().solve(
        _problem(daily_fragment_limit=1, vehicle_count=2),
        OptimizationConfig(mode=OptimizationMode.MILP, time_limit_sec=10, mip_gap=0.0),
    )

    assert result.feasible is True
    assert len(result.plan.vehicle_fragment_counts()) == 2
    assert all(count == 1 for count in result.plan.vehicle_fragment_counts().values())
