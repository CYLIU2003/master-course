from __future__ import annotations

from types import SimpleNamespace

from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.milp.model_builder import MILPModelBuilder


def test_model_builder_successor_cap_default_is_eight() -> None:
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

    assert len([pair for pair in pairs if pair[1] == "t0"]) == 8
