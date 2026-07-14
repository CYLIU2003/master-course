from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from src.dispatch.models import DutyLeg, VehicleDuty
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.milp.model_builder import MILPModelBuilder


def _problem(*, successor_cap: int | None = None) -> CanonicalOptimizationProblem:
    trips = tuple(
        ProblemTrip(
            trip_id=f"t{i}",
            route_id="r1",
            origin="A",
            destination="B",
            departure_min=480 + i * 10,
            arrival_min=485 + i * 10,
            distance_km=1.0,
            allowed_vehicle_types=("ICE",),
        )
        for i in range(12)
    )
    feasible_connections = {
        "t0": tuple(trip.trip_id for trip in trips[1:]),
    }
    metadata = {}
    if successor_cap is not None:
        metadata["milp_max_successors_per_trip"] = successor_cap
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="model-builder"),
        dispatch_context=SimpleNamespace(trips_by_id=lambda: {}),
        trips=trips,
        vehicles=(
            ProblemVehicle(vehicle_id="veh-available", vehicle_type="ICE", home_depot_id="DEPOT", available=True),
            ProblemVehicle(vehicle_id="veh-unavailable", vehicle_type="ICE", home_depot_id="DEPOT", available=False),
        ),
        feasible_connections=feasible_connections,
        metadata=metadata,
    )


def test_enumerate_assignment_pairs_excludes_unavailable_vehicle() -> None:
    pairs = MILPModelBuilder().enumerate_assignment_pairs(_problem())

    assert all(vehicle_id != "veh-unavailable" for vehicle_id, _trip_id in pairs)


def test_large_successor_cap_keeps_all_successors_for_benchmark_metadata() -> None:
    problem = _problem(successor_cap=100)
    trip_by_id = problem.trip_by_id()

    pairs = MILPModelBuilder().enumerate_arc_pairs(problem, trip_by_id)

    assert len([pair for pair in pairs if pair[1] == "t0"]) == 11


def test_default_successor_cap_keeps_full_feasible_graph() -> None:
    problem = _problem()
    trip_by_id = problem.trip_by_id()

    pairs = MILPModelBuilder().enumerate_arc_pairs(problem, trip_by_id)

    assert len([pair for pair in pairs if pair[1] == "t0"]) == 11


def test_explicit_successor_cap_limits_dense_graphs() -> None:
    problem = _problem(successor_cap=8)
    trip_by_id = problem.trip_by_id()

    pairs = MILPModelBuilder().enumerate_arc_pairs(problem, trip_by_id)

    assert len([pair for pair in pairs if pair[1] == "t0"]) == 8


def test_successor_cap_counts_only_vehicle_compatible_successors() -> None:
    problem = _problem(successor_cap=1)
    trips = (
        problem.trips[0],
        replace(problem.trips[1], allowed_vehicle_types=("BEV",)),
        *problem.trips[2:],
    )
    problem = replace(problem, trips=trips)
    builder = MILPModelBuilder()

    pairs = builder.enumerate_arc_pairs(problem, problem.trip_by_id())
    summary = builder.arc_pruning_summary(problem, problem.trip_by_id())

    assert ("veh-available", "t0", "t1") not in pairs
    assert ("veh-available", "t0", "t2") in pairs
    assert summary["arc_count_after_successor_pruning"] == len(pairs)


def test_successor_cap_preserves_representable_baseline_connection() -> None:
    problem = _problem(successor_cap=8)
    baseline_duty = VehicleDuty(
        duty_id="baseline-duty",
        vehicle_type="ICE",
        legs=(DutyLeg(trip=problem.trips[0]), DutyLeg(trip=problem.trips[-1])),
    )
    problem = replace(
        problem,
        baseline_plan=AssignmentPlan(
            duties=(baseline_duty,),
            served_trip_ids=("t0", "t11"),
            metadata={"duty_vehicle_map": {"baseline-duty": "veh-available"}},
        ),
    )
    builder = MILPModelBuilder()

    pairs = builder.enumerate_arc_pairs(problem, problem.trip_by_id())
    summary = builder.arc_pruning_summary(problem, problem.trip_by_id())

    assert ("veh-available", "t0", "t11") in pairs
    assert len([pair for pair in pairs if pair[0] == "veh-available" and pair[1] == "t0"]) == 9
    assert summary["baseline_preserved_arc_count"] == 1
