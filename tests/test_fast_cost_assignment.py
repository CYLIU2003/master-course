from __future__ import annotations

from dataclasses import replace

import pytest

from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.optimization.common.fast_cost_assignment import (
    build_fast_cost_aware_assignment,
)
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    DepotEnergyAsset,
    EnergyPriceSlot,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
    ProblemVehicleType,
)


def _problem(*, short_distance_km: float = 10.0) -> CanonicalOptimizationProblem:
    long_trip = Trip(
        trip_id="long",
        route_id="r",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="09:00",
        distance_km=100.0,
        allowed_vehicle_types=("BEV", "ICE"),
        operator_id="operator",
    )
    short_trip = Trip(
        trip_id="short",
        route_id="r",
        origin="B",
        destination="C",
        departure_time="10:00",
        arrival_time="10:30",
        distance_km=short_distance_km,
        allowed_vehicle_types=("BEV", "ICE"),
        operator_id="operator",
    )
    baseline = AssignmentPlan(
        duties=(
            VehicleDuty("baseline_ice_1", "ICE", (DutyLeg(long_trip),)),
            VehicleDuty("baseline_ice_2", "ICE", (DutyLeg(short_trip),)),
        ),
        served_trip_ids=("long", "short"),
        metadata={
            "source": "dispatch_pooled_shared_path_cover_baseline",
            "duty_vehicle_map": {
                "baseline_ice_1": "ice-1",
                "baseline_ice_2": "ice-2",
            },
        },
    )
    problem_trips = tuple(
        ProblemTrip(
            trip_id=trip.trip_id,
            route_id=trip.route_id,
            origin=trip.origin,
            destination=trip.destination,
            departure_min=trip.departure_min,
            arrival_min=trip.arrival_min,
            distance_km=trip.distance_km,
            allowed_vehicle_types=trip.allowed_vehicle_types,
        )
        for trip in (long_trip, short_trip)
    )
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="fast-test",
            diesel_price_yen_per_l=100.0,
            co2_price_per_kg=0.0,
        ),
        dispatch_context=None,
        trips=problem_trips,
        vehicles=(
            ProblemVehicle(
                vehicle_id="bev-1",
                vehicle_type="BEV",
                home_depot_id="depot",
                initial_soc=250.0,
                battery_capacity_kwh=300.0,
                reserve_soc=30.0,
                energy_consumption_kwh_per_km=1.0,
            ),
            ProblemVehicle(
                vehicle_id="ice-1",
                vehicle_type="ICE",
                home_depot_id="depot",
                fuel_consumption_l_per_km=0.25,
            ),
            ProblemVehicle(
                vehicle_id="ice-2",
                vehicle_type="ICE",
                home_depot_id="depot",
                fuel_consumption_l_per_km=0.25,
            ),
        ),
        vehicle_types=(
            ProblemVehicleType(
                vehicle_type_id="BEV",
                powertrain_type="BEV",
                battery_capacity_kwh=300.0,
                reserve_soc=0.1,
                energy_consumption_kwh_per_km=1.0,
            ),
            ProblemVehicleType(
                vehicle_type_id="ICE",
                powertrain_type="ICE",
                fuel_consumption_l_per_km=0.25,
                co2_emission_kg_per_l=2.64,
            ),
        ),
        price_slots=(EnergyPriceSlot(0, grid_buy_yen_per_kwh=10.0),),
        baseline_plan=baseline,
        metadata={
            "charging_efficiency": 1.0,
            "deadhead_speed_kmh": 18.0,
        },
    )


def test_fast_assignment_preserves_chains_and_assigns_cheaper_bev_to_long_duty() -> None:
    problem = _problem()

    plan, audit = build_fast_cost_aware_assignment(
        problem, requested_bev_count=1
    )

    assert plan.unserved_trip_ids == ()
    assert set(plan.served_trip_ids) == {"long", "short"}
    assert sorted(tuple(duty.trip_ids) for duty in plan.duties) == [
        ("long",),
        ("short",),
    ]
    duty_by_vehicle = plan.duties_by_vehicle()
    assert set(duty_by_vehicle) == {"bev-1", "ice-1"}
    assert duty_by_vehicle["bev-1"][0].trip_ids == ["long"]
    assert audit["actual_bev_count"] == 1
    assert audit["timetable_chains_modified"] is False
    assert plan.metadata["assignment_global_optimality"] is False


def test_fast_assignment_rejects_nonpositive_trip_distance() -> None:
    problem = _problem(short_distance_km=0.0)

    with pytest.raises(ValueError, match="nonpositive distance"):
        build_fast_cost_aware_assignment(problem, requested_bev_count=1)


def test_fast_assignment_prefers_duty_that_can_access_midday_pv() -> None:
    problem = _problem()
    solar_trip = replace(
        problem.baseline_plan.duties[0].legs[0].trip,
        trip_id="solar-accessible",
        arrival_time="10:00",
        distance_km=50.0,
    )
    daylong_trip = replace(
        problem.baseline_plan.duties[1].legs[0].trip,
        trip_id="daylong",
        departure_time="08:00",
        arrival_time="18:00",
        distance_km=50.0,
    )
    baseline = AssignmentPlan(
        duties=(
            VehicleDuty("solar-duty", "ICE", (DutyLeg(solar_trip),)),
            VehicleDuty("daylong-duty", "ICE", (DutyLeg(daylong_trip),)),
        ),
        served_trip_ids=("solar-accessible", "daylong"),
        metadata={
            "source": "dispatch_pooled_shared_path_cover_baseline",
            "duty_vehicle_map": {
                "solar-duty": "ice-1",
                "daylong-duty": "ice-2",
            },
        },
    )
    problem_trips = tuple(
        replace(
            problem.trips[index],
            trip_id=trip.trip_id,
            departure_min=trip.departure_min,
            arrival_min=trip.arrival_min,
            distance_km=trip.distance_km,
        )
        for index, trip in enumerate((solar_trip, daylong_trip))
    )
    pv_profile = tuple(100.0 if hour == 12 else 0.0 for hour in range(24))
    problem = replace(
        problem,
        trips=problem_trips,
        baseline_plan=baseline,
        price_slots=tuple(
            EnergyPriceSlot(hour, grid_buy_yen_per_kwh=10.0)
            for hour in range(24)
        ),
        depot_energy_assets={
            "depot": DepotEnergyAsset(
                depot_id="depot",
                pv_enabled=True,
                pv_generation_kwh_by_slot=pv_profile,
            )
        },
        scenario=replace(
            problem.scenario,
            timestep_min=60,
            horizon_duration_min=24 * 60,
            demand_charge_on_peak_yen_per_kw=1200.0,
        ),
    )

    plan, _ = build_fast_cost_aware_assignment(problem, requested_bev_count=1)

    assert plan.duties_by_vehicle()["bev-1"][0].trip_ids == ["solar-accessible"]
