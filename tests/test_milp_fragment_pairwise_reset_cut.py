from __future__ import annotations

import pytest

from src.dispatch.models import DeadheadRule, DispatchContext, Trip, VehicleProfile
from src.gurobi_runtime import is_gurobi_available
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import OptimizationConfig, OptimizationMode
from src.optimization.milp.engine import MILPOptimizer


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_milp_fragment_pairwise_reset_cut_blocks_impossible_two_fragment_reuse() -> None:
    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
            Trip(
                trip_id="t2",
                route_id="r1",
                origin="C",
                destination="D",
                departure_time="08:30",
                arrival_time="08:40",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
        ],
        turnaround_rules={},
        deadhead_rules={
            ("DEPOT", "A"): DeadheadRule("DEPOT", "A", 5),
            ("DEPOT", "C"): DeadheadRule("DEPOT", "C", 5),
        },
        vehicle_profiles={"ICE": VehicleProfile(vehicle_type="ICE")},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="milp-reset-cut",
        vehicle_counts={"ICE": 1},
        canonical_depot_id="DEPOT",
        allow_same_day_depot_cycles=True,
        max_depot_cycles_per_vehicle_per_day=2,
        max_fragments_per_vehicle_per_day=2,
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=2,
        service_coverage_mode="strict",
    )

    result = MILPOptimizer().solve(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, time_limit_sec=10),
    )

    assert result.feasible is False
    assert result.plan.unserved_trip_ids == ("t1", "t2")
