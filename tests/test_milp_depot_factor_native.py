"""Native differential checks for the exact multi-day connection formulation."""
from dataclasses import replace

import pytest

from src.dispatch.feasibility import FeasibilityEngine
from src.optimization.common.problem import OptimizationConfig, OptimizationMode
from src.optimization.common.result import ResultSerializer
from src.optimization.engine import OptimizationEngine
from src.optimization.validation.physical_event_schedule import validate_physical_event_schedule
from test_daily_return_policy import daily_problem


def factor_native_problem():
    problem = daily_problem()
    canonical = []
    dispatch = []
    for day in range(2):
        for index in range(3):
            trip_id = f"d{day}-t{index}"
            departure = 480 + index * 240 + day * 1440
            canonical.append(replace(
                problem.trips[day], trip_id=trip_id, departure_min=departure,
                arrival_min=departure + 60,
            ))
            dispatch.append(replace(
                problem.dispatch_context.trips[day], trip_id=trip_id,
                departure_time=f"{departure // 60:02d}:00",
                arrival_time=f"{departure // 60 + 1:02d}:00",
            ))
    context = replace(problem.dispatch_context, trips=dispatch)
    engine = FeasibilityEngine()
    connections = {
        origin.trip_id: tuple(target.trip_id for target in dispatch
                              if origin.trip_id != target.trip_id
                              and engine.can_connect(origin, target, context, "BEV").feasible)
        for origin in dispatch
    }
    return replace(
        problem, trips=tuple(canonical), dispatch_context=context,
        vehicles=tuple(replace(vehicle, battery_capacity_kwh=300.0,
                               initial_soc=240.0, soc_input_unit="kwh")
                       for vehicle in problem.vehicles),
        vehicle_types=tuple(replace(kind, battery_capacity_kwh=300.0)
                            for kind in problem.vehicle_types),
        feasible_connections=connections, metadata={
            **problem.metadata, "planning_days": 2, "daily_fragment_limit": 3,
            "max_start_fragments_per_vehicle": 100, "max_end_fragments_per_vehicle": 100,
        },
    )


@pytest.mark.parametrize("fragment_limit", [1, 100])
def test_native_factored_and_explicit_phase3_match_cost_and_physical_gates(fragment_limit):
    pytest.importorskip("gurobipy")
    original = factor_native_problem()
    results = []
    for factored in (False, True):
        problem = replace(original, metadata={
            **original.metadata, "stage1_exact_depot_connection_factors": factored,
            "max_start_fragments_per_vehicle": fragment_limit,
            "max_end_fragments_per_vehicle": fragment_limit,
        })
        result = OptimizationEngine().solve(problem, OptimizationConfig(
            mode=OptimizationMode.MILP, phase="phase3_two_stage", time_limit_sec=30,
            stage1_time_limit_sec=20, stage2_time_limit_sec=10, mip_gap=0,
            gurobi_threads=1, random_seed=42, warm_start=False, allow_postsolve_repair=False,
        ))
        assert result.feasible, result.infeasibility_reasons
        assert set(result.plan.served_trip_ids) == {trip.trip_id for trip in problem.trips}
        physical = validate_physical_event_schedule(
            problem=problem, serialized_result=ResultSerializer.serialize_plan(result.plan)
        )
        assert physical["accepted"], physical["violations"]
        if factored:
            audit = result.solver_metadata["depot_connection_factor_audit"]
            assert audit["applied"] and audit["factor_count"] > 0
            assert audit["successor_candidates_removed"] == 0
            assert audit["complete_candidate_arc_count"] == (
                audit["explicit_arc_variable_count"] + audit["represented_arc_count"]
            )
        results.append(result)
    assert results[0].cost_breakdown["total_cost"] == pytest.approx(
        results[1].cost_breakdown["total_cost"], abs=1e-6
    )
