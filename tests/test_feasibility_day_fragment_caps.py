from __future__ import annotations

from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)


class _DepotResetContext:
    def get_deadhead_min(self, from_stop: str, to_stop: str) -> int:
        deadheads = {
            ("DEPOT", "A"): 5,
            ("DEPOT", "C"): 5,
            ("DEPOT", "E"): 5,
            ("B", "DEPOT"): 5,
            ("D", "DEPOT"): 5,
        }
        return int(deadheads.get((str(from_stop), str(to_stop)), 0))

    def get_turnaround_min(self, stop: str) -> int:
        return 0

    def locations_equivalent(self, left: str, right: str) -> bool:
        return str(left) == str(right)

    def has_location_data(self, stop: str) -> bool:
        return True


def _dispatch_trip(trip_id: str, origin: str, destination: str, departure: str) -> Trip:
    return Trip(
        trip_id=trip_id,
        route_id="r1",
        origin=origin,
        destination=destination,
        departure_time=departure,
        arrival_time=f"{int(departure[:2]):02d}:{(int(departure[3:]) + 10):02d}",
        distance_km=5.0,
        allowed_vehicle_types=("ICE",),
    )


def _problem(cap: int) -> CanonicalOptimizationProblem:
    trips = (
        _dispatch_trip("t1", "A", "B", "08:00"),
        _dispatch_trip("t2", "C", "D", "08:30"),
        _dispatch_trip("t3", "E", "F", "09:00"),
    )
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="fragment-cap",
            allow_same_day_depot_cycles=True,
            max_depot_cycles_per_vehicle_per_day=cap,
        ),
        dispatch_context=_DepotResetContext(),
        trips=tuple(
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
            for trip in trips
        ),
        vehicles=(ProblemVehicle(vehicle_id="veh-1", vehicle_type="ICE", home_depot_id="DEPOT"),),
        metadata={
            "allow_same_day_depot_cycles": True,
            "max_depot_cycles_per_vehicle_per_day": cap,
            "max_start_fragments_per_vehicle": 3,
            "max_end_fragments_per_vehicle": 3,
        },
    )


def _plan() -> AssignmentPlan:
    duty_specs = (
        (_dispatch_trip("t1", "A", "B", "08:00"), 5),
        (_dispatch_trip("t2", "C", "D", "08:30"), 5),
        (_dispatch_trip("t3", "E", "F", "09:00"), 5),
    )
    duties = tuple(
        VehicleDuty(
            duty_id=f"veh-1__frag{index + 1}" if index else "veh-1",
            vehicle_type="ICE",
            legs=(DutyLeg(trip=trip, deadhead_from_prev_min=startup_deadhead),),
        )
        for index, (trip, startup_deadhead) in enumerate(duty_specs)
    )
    return AssignmentPlan(
        duties=duties,
        metadata={"duty_vehicle_map": {duty.duty_id: "veh-1" for duty in duties}},
    )


def test_day_fragment_cap_two_rejects_third_fragment() -> None:
    report = FeasibilityChecker().evaluate(_problem(2), _plan())

    assert report.feasible is False
    assert any("fragment_count=3" in error for error in report.errors)


def test_day_fragment_cap_three_allows_three_fragments() -> None:
    report = FeasibilityChecker().evaluate(_problem(3), _plan())

    assert report.feasible is True
