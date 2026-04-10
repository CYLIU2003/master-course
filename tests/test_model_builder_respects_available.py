from __future__ import annotations

from types import SimpleNamespace

from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.milp.model_builder import MILPModelBuilder


def test_model_builder_respects_available_in_assignment_pairs() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="available-model"),
        dispatch_context=SimpleNamespace(trips_by_id=lambda: {}),
        trips=(
            ProblemTrip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_min=480,
                arrival_min=490,
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
        ),
        vehicles=(
            ProblemVehicle("veh-ok", "ICE", "DEPOT", available=True),
            ProblemVehicle("veh-no", "ICE", "DEPOT", available=False),
        ),
    )

    pairs = MILPModelBuilder().enumerate_assignment_pairs(problem)

    assert pairs == [("veh-ok", "t1")]
