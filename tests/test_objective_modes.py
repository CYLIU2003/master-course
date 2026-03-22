from __future__ import annotations

from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.objective_modes import (
    effective_co2_price_per_kg,
    legacy_objective_weights_for_mode,
    normalize_objective_mode,
)
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


def test_legacy_objective_weights_for_co2_mode_reset_base_cost_terms() -> None:
    weights = legacy_objective_weights_for_mode(
        objective_mode="co2",
        unserved_penalty=12345.0,
        explicit_weights={
            "electricity_cost": 9.0,
            "vehicle_fixed_cost": 8.0,
            "degradation": 7.0,
        },
    )

    assert normalize_objective_mode("cost") == "total_cost"
    assert effective_co2_price_per_kg("co2", 0.0) == 1.0
    assert weights["electricity_cost"] == 0.0
    assert weights["vehicle_fixed_cost"] == 0.0
    assert weights["emission_cost"] == 1.0
    assert weights["battery_degradation_cost"] == 7.0
    assert weights["unserved_penalty"] == 12345.0


def test_cost_evaluator_uses_total_cost_objective_by_default() -> None:
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
            objective_mode="total_cost",
            diesel_price_yen_per_l=100.0,
            co2_price_per_kg=0.0,
            ice_co2_kg_per_l=2.0,
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
                fixed_use_cost_jpy=500.0,
            ),
        ),
        objective_weights=OptimizationObjectiveWeights(
            energy=1.0,
            demand=1.0,
            vehicle=1.0,
            unserved=10000.0,
        ),
    )
    plan = AssignmentPlan(
        duties=(duty,),
        served_trip_ids=("trip-1",),
    )

    breakdown = CostEvaluator().evaluate(problem, plan)

    assert breakdown.total_co2_kg == 4.0
    assert breakdown.total_cost > breakdown.total_co2_kg
    assert breakdown.objective_value == breakdown.total_cost


def test_cost_evaluator_uses_co2_objective_when_requested() -> None:
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
            diesel_price_yen_per_l=100.0,
            co2_price_per_kg=0.0,
            ice_co2_kg_per_l=2.0,
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
                fixed_use_cost_jpy=500.0,
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

    assert breakdown.total_co2_kg == 4.0
    assert breakdown.objective_value == breakdown.total_co2_kg
    assert breakdown.total_cost > breakdown.objective_value
