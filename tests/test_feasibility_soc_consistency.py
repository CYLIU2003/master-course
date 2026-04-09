from __future__ import annotations

import pytest

from src.dispatch.models import DispatchContext, DutyLeg, Trip, VehicleDuty, VehicleProfile
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
    ProblemVehicleType,
)
from src.optimization.common.soc_helpers import trip_active_slot_indices, trip_slot_energy_fraction


def _make_problem(*, dispatch_trip: Trip, problem_trip: ProblemTrip, initial_soc: float) -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="soc-consistency",
            horizon_start="00:00",
            timestep_min=60,
            objective_mode="total_cost",
        ),
        dispatch_context=DispatchContext(
            service_date="2026-03-23",
            trips=[dispatch_trip],
            turnaround_rules={},
            deadhead_rules={},
            vehicle_profiles={
                "BEV": VehicleProfile(
                    vehicle_type="BEV",
                    battery_capacity_kwh=300.0,
                    energy_consumption_kwh_per_km=1.2,
                )
            },
        ),
        trips=(problem_trip,),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                initial_soc=initial_soc,
                battery_capacity_kwh=300.0,
                reserve_soc=30.0,
            ),
        ),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="BEV",
                powertrain_type="BEV",
                battery_capacity_kwh=300.0,
                reserve_soc=30.0,
            ),
        ),
    )


@pytest.mark.parametrize(
    "dispatch_trip, problem_trip, initial_soc, expected_feasible",
    [
        (
            Trip(
                trip_id="day-long",
                route_id="r1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="11:00",
                distance_km=20.0,
                allowed_vehicle_types=("BEV",),
            ),
            ProblemTrip(
                trip_id="day-long",
                route_id="r1",
                origin="A",
                destination="B",
                departure_min=8 * 60,
                arrival_min=11 * 60,
                distance_km=20.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=45.0,
            ),
            250.0,
            True,
        ),
        (
            Trip(
                trip_id="overnight",
                route_id="r2",
                origin="C",
                destination="D",
                departure_time="23:00",
                arrival_time="01:00",
                distance_km=15.0,
                allowed_vehicle_types=("BEV",),
            ),
            ProblemTrip(
                trip_id="overnight",
                route_id="r2",
                origin="C",
                destination="D",
                departure_min=23 * 60,
                arrival_min=25 * 60,
                distance_km=15.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=30.0,
            ),
            250.0,
            True,
        ),
        (
            Trip(
                trip_id="short-low-soc",
                route_id="r3",
                origin="E",
                destination="F",
                departure_time="09:00",
                arrival_time="09:30",
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
            ),
            ProblemTrip(
                trip_id="short-low-soc",
                route_id="r3",
                origin="E",
                destination="F",
                departure_min=9 * 60,
                arrival_min=9 * 60 + 30,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=80.0,
            ),
            10.0,
            False,
        ),
    ],
)
def test_feasibility_checker_matches_slot_spread_soc_logic(
    dispatch_trip: Trip,
    problem_trip: ProblemTrip,
    initial_soc: float,
    expected_feasible: bool,
) -> None:
    problem = _make_problem(
        dispatch_trip=dispatch_trip,
        problem_trip=problem_trip,
        initial_soc=initial_soc,
    )
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="veh-1",
                vehicle_type="BEV",
                legs=(DutyLeg(trip=dispatch_trip),),
            ),
        ),
        served_trip_ids=(dispatch_trip.trip_id,),
        unserved_trip_ids=(),
    )

    slots = trip_active_slot_indices(problem, problem_trip.departure_min, problem_trip.arrival_min)
    fractions = [
        trip_slot_energy_fraction(
            problem,
            problem_trip.departure_min,
            problem_trip.arrival_min,
            slot_idx,
        )
        for slot_idx in slots
    ]

    report = FeasibilityChecker().evaluate(problem, plan)

    assert slots
    assert abs(sum(fractions) - 1.0) < 1.0e-9
    assert report.feasible is expected_feasible
    if expected_feasible:
        assert not report.errors
    else:
        assert any(message.startswith("[SOC]") for message in report.errors)
