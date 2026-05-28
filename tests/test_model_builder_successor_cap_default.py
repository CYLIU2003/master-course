from __future__ import annotations

from types import SimpleNamespace

from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.milp.model_builder import MILPModelBuilder


def test_model_builder_successor_cap_default_keeps_full_feasible_graph() -> None:
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
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="successor-cap"),
        dispatch_context=SimpleNamespace(trips_by_id=lambda: {}),
        trips=trips,
        vehicles=(ProblemVehicle("veh-1", "ICE", "DEPOT"),),
        feasible_connections={"t0": tuple(trip.trip_id for trip in trips[1:])},
    )

    pairs = MILPModelBuilder().enumerate_arc_pairs(problem, problem.trip_by_id())

    assert len([pair for pair in pairs if pair[1] == "t0"]) == 11


def test_model_builder_reports_explicit_successor_pruning() -> None:
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
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="successor-cap"),
        dispatch_context=SimpleNamespace(trips_by_id=lambda: {}),
        trips=trips,
        vehicles=(ProblemVehicle("veh-1", "ICE", "DEPOT"),),
        feasible_connections={"t0": tuple(trip.trip_id for trip in trips[1:])},
        metadata={"milp_max_successors_per_trip": 8},
    )

    summary = MILPModelBuilder().arc_pruning_summary(problem, problem.trip_by_id())

    assert summary["successor_pruning_enabled"] is True
    assert summary["candidate_arc_count_before_successor_pruning"] == 11
    assert summary["arc_count_after_successor_pruning"] == 8
    assert summary["pruned_arc_count"] == 3
