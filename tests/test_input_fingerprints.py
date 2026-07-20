from __future__ import annotations

from dataclasses import replace

from src.optimization.common.input_fingerprints import (
    canonical_trip_input_hash,
    canonical_vehicle_input_hash,
)
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)


def _problem() -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="fingerprint"),
        dispatch_context=None,
        trips=(
            ProblemTrip(
                trip_id="trip-1",
                route_id="route-1",
                origin="A",
                destination="B",
                departure_min=60,
                arrival_min=120,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=12.0,
                route_family_code="family-1",
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev-1",
                vehicle_type="BEV",
                home_depot_id="depot-1",
                initial_soc=80.0,
                battery_capacity_kwh=100.0,
            ),
        ),
    )


def test_trip_fingerprint_changes_when_model_input_changes() -> None:
    problem = _problem()
    changed = replace(
        problem,
        trips=(replace(problem.trips[0], distance_km=11.0),),
    )

    assert canonical_trip_input_hash(problem) != canonical_trip_input_hash(changed)


def test_vehicle_fingerprint_changes_when_initial_inventory_changes() -> None:
    problem = _problem()
    changed = replace(
        problem,
        vehicles=(replace(problem.vehicles[0], initial_soc=70.0),),
    )

    assert canonical_vehicle_input_hash(problem) != canonical_vehicle_input_hash(
        changed
    )
