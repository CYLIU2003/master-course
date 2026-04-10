from __future__ import annotations

import pytest

from src.dispatch.models import DispatchContext, Trip, VehicleProfile
from src.gurobi_runtime import is_gurobi_available
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import OptimizationConfig, OptimizationMode
from src.optimization.milp.engine import MILPOptimizer


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_milp_strict_coverage_metadata_is_exported() -> None:
    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="DEPOT",
                destination="A",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            )
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={"ICE": VehicleProfile(vehicle_type="ICE")},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="milp-metadata",
        vehicle_counts={"ICE": 1},
        canonical_depot_id="DEPOT",
        service_coverage_mode="strict",
    )

    result = MILPOptimizer().solve(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, time_limit_sec=10),
    )

    assert result.solver_metadata["service_coverage_mode"] == "strict"
    assert result.solver_metadata["allow_partial_service"] is False
    assert result.solver_metadata["strict_coverage_enforced"] is True
