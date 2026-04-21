from __future__ import annotations

from types import SimpleNamespace

from src.optimization.common.problem import (
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


def test_default_successor_cap_limits_dense_graphs() -> None:
    problem = _problem()
    trip_by_id = problem.trip_by_id()

    pairs = MILPModelBuilder().enumerate_arc_pairs(problem, trip_by_id)

    assert len([pair for pair in pairs if pair[1] == "t0"]) == 8
