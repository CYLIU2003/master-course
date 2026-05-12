from __future__ import annotations

import pytest

from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationObjectiveWeights,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
    ProblemVehicleType,
)


def test_cost_evaluator_uses_vehicle_type_specific_co2_factor() -> None:
    trip = Trip(
        trip_id="trip-1",
        route_id="route-1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=10.0,
        allowed_vehicle_types=("ICE",),
    )
    duty = VehicleDuty(
        duty_id="duty-1",
        vehicle_type="ICE",
        legs=(DutyLeg(trip=trip),),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="scenario-1",
            objective_mode="co2",
            diesel_price_yen_per_l=0.0,
            co2_price_per_kg=1.0,
            ice_co2_kg_per_l=1.0,
        ),
        dispatch_context=None,
        trips=(
            ProblemTrip(
                trip_id="trip-1",
                route_id="route-1",
                origin="A",
                destination="B",
                departure_min=480,
                arrival_min=510,
                distance_km=10.0,
                allowed_vehicle_types=("ICE",),
                fuel_l=2.0,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-1",
                vehicle_type="ICE",
                home_depot_id="dep-1",
                fuel_consumption_l_per_km=0.2,
            ),
        ),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="ICE",
                powertrain_type="ICE",
                fuel_consumption_l_per_km=0.2,
                co2_emission_kg_per_l=2.67,
                fixed_use_cost_jpy=0.0,
            ),
        ),
        objective_weights=OptimizationObjectiveWeights(
            energy=0.0,
            demand=0.0,
            vehicle=0.0,
            unserved=10000.0,
        ),
    )
    plan = AssignmentPlan(
        duties=(duty,),
        served_trip_ids=("trip-1",),
    )

    breakdown = CostEvaluator().evaluate(problem, plan)

    assert breakdown.ice_co2_kg == pytest.approx(5.34)
    assert breakdown.total_co2_kg == pytest.approx(5.34)
    assert breakdown.objective_value == pytest.approx(breakdown.total_co2_kg)
