from __future__ import annotations

from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.dispatch.route_band import fragment_transition_is_feasible
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.common.vehicle_assignment import assign_duty_fragments_to_vehicles


class _DepotResetContext:
    def __init__(self) -> None:
        self._deadheads = {
            ("DEPOT", "A"): 5,
            ("DEPOT", "C"): 5,
            ("B", "DEPOT"): 5,
            ("B", "C"): 25,
            ("A", "B"): 25,
            ("B", "A"): 25,
            ("DEPOT", "DEPOT"): 0,
        }

    def get_deadhead_min(self, from_stop: str, to_stop: str) -> int:
        return int(self._deadheads.get((str(from_stop), str(to_stop)), 0))

    def get_turnaround_min(self, stop: str) -> int:
        return 0

    def locations_equivalent(self, left: str, right: str) -> bool:
        return str(left) == str(right)

    def has_location_data(self, stop: str) -> bool:
        return True


def _dispatch_trip(trip_id: str, origin: str, destination: str, departure: str, arrival: str) -> Trip:
    return Trip(
        trip_id=trip_id,
        route_id="route-1",
        origin=origin,
        destination=destination,
        departure_time=departure,
        arrival_time=arrival,
        distance_km=5.0,
        allowed_vehicle_types=("ICE",),
        route_family_code="FAM01",
    )


def _problem_trip(dispatch_trip: Trip) -> ProblemTrip:
    return ProblemTrip(
        trip_id=dispatch_trip.trip_id,
        route_id=dispatch_trip.route_id,
        origin=dispatch_trip.origin,
        destination=dispatch_trip.destination,
        departure_min=dispatch_trip.departure_min,
        arrival_min=dispatch_trip.arrival_min,
        distance_km=dispatch_trip.distance_km,
        allowed_vehicle_types=dispatch_trip.allowed_vehicle_types,
    )


def _make_duty(duty_id: str, trip: Trip) -> VehicleDuty:
    return VehicleDuty(
        duty_id=duty_id,
        vehicle_type="ICE",
        legs=(DutyLeg(trip=trip, deadhead_from_prev_min=0),),
    )


def _make_problem(
    *,
    allow_same_day_depot_cycles: bool,
    max_depot_cycles_per_vehicle_per_day: int,
) -> CanonicalOptimizationProblem:
    trip_1 = _dispatch_trip("t1", "A", "B", "08:00", "08:10")
    trip_2 = _dispatch_trip("t2", "C", "D", "08:30", "08:40")
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="same-day-cycles",
            horizon_start="08:00",
            horizon_end="18:00",
            timestep_min=30,
            planning_days=1,
            allow_same_day_depot_cycles=allow_same_day_depot_cycles,
            max_depot_cycles_per_vehicle_per_day=max_depot_cycles_per_vehicle_per_day,
            objective_mode="total_cost",
        ),
        dispatch_context=_DepotResetContext(),
        trips=(
            _problem_trip(trip_1),
            _problem_trip(trip_2),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh_1",
                vehicle_type="ICE",
                home_depot_id="DEPOT",
            ),
        ),
        metadata={
            "allow_partial_service": False,
            "fixed_route_band_mode": False,
            "allow_same_day_depot_cycles": allow_same_day_depot_cycles,
            "max_depot_cycles_per_vehicle_per_day": max_depot_cycles_per_vehicle_per_day,
            "max_start_fragments_per_vehicle": 3,
            "max_end_fragments_per_vehicle": 3,
        },
    )


def test_same_day_cycles_allow_multiple_fragments_on_one_vehicle() -> None:
    trip_1 = _dispatch_trip("t1", "A", "B", "08:00", "08:10")
    trip_2 = _dispatch_trip("t2", "C", "D", "08:30", "08:40")
    duties = (
        _make_duty("morning", trip_1),
        _make_duty("afternoon", trip_2),
    )
    assigned_duties, duty_vehicle_map, skipped_trip_ids = assign_duty_fragments_to_vehicles(
        duties,
        vehicles=(
            ProblemVehicle(vehicle_id="veh_1", vehicle_type="ICE", home_depot_id="DEPOT"),
        ),
        max_fragments_per_vehicle=3,
        max_fragments_per_vehicle_per_day=2,
        allow_same_day_depot_cycles=True,
        horizon_start_min=8 * 60,
        dispatch_context=_DepotResetContext(),
        fixed_route_band_mode=False,
    )

    assert [duty.duty_id for duty in assigned_duties] == ["veh_1", "veh_1__frag2"]
    assert skipped_trip_ids == ()

    plan = AssignmentPlan(
        duties=assigned_duties,
        metadata={"duty_vehicle_map": duty_vehicle_map},
    )
    assert plan.vehicle_fragment_counts() == {"veh_1": 2}
    assert plan.vehicles_with_multiple_fragments() == ("veh_1",)
    assert plan.max_fragments_observed() == 2

    report = FeasibilityChecker().evaluate(
        _make_problem(
            allow_same_day_depot_cycles=True,
            max_depot_cycles_per_vehicle_per_day=2,
        ),
        plan,
    )
    assert report.feasible is True


def test_same_day_cycle_cap_blocks_second_fragment_assignment() -> None:
    trip_1 = _dispatch_trip("t1", "A", "B", "08:00", "08:10")
    trip_2 = _dispatch_trip("t2", "C", "D", "08:30", "08:40")
    assigned_duties, _duty_vehicle_map, skipped_trip_ids = assign_duty_fragments_to_vehicles(
        (
            _make_duty("morning", trip_1),
            _make_duty("afternoon", trip_2),
        ),
        vehicles=(
            ProblemVehicle(vehicle_id="veh_1", vehicle_type="ICE", home_depot_id="DEPOT"),
        ),
        max_fragments_per_vehicle=3,
        max_fragments_per_vehicle_per_day=1,
        allow_same_day_depot_cycles=True,
        horizon_start_min=0,
        dispatch_context=_DepotResetContext(),
        fixed_route_band_mode=False,
    )

    assert [duty.duty_id for duty in assigned_duties] == ["veh_1"]
    assert skipped_trip_ids == ("t2",)


def test_feasibility_reports_cap_and_disabled_cycle_errors() -> None:
    problem_enabled = _make_problem(
        allow_same_day_depot_cycles=True,
        max_depot_cycles_per_vehicle_per_day=1,
    )
    plan = AssignmentPlan(
        duties=(
            _make_duty("veh_1", _dispatch_trip("t1", "A", "B", "08:00", "08:10")),
            _make_duty("veh_1__frag2", _dispatch_trip("t2", "C", "D", "08:30", "08:40")),
        ),
        metadata={"duty_vehicle_map": {"veh_1": "veh_1", "veh_1__frag2": "veh_1"}},
    )

    enabled_report = FeasibilityChecker().evaluate(problem_enabled, plan)
    assert enabled_report.feasible is False
    assert any(
        "exceeds max_depot_cycles_per_vehicle_per_day=1" in error
        for error in enabled_report.errors
    )

    problem_disabled = _make_problem(
        allow_same_day_depot_cycles=False,
        max_depot_cycles_per_vehicle_per_day=3,
    )
    disabled_report = FeasibilityChecker().evaluate(problem_disabled, plan)
    assert disabled_report.feasible is False
    assert any(
        "same-day depot cycles are disabled" in error
        for error in disabled_report.errors
    )


def test_fragment_transition_depot_reset_flag_controls_feasibility() -> None:
    first = _make_duty("veh_1", _dispatch_trip("t1", "A", "B", "08:00", "08:10"))
    second = _make_duty("veh_1__frag2", _dispatch_trip("t2", "C", "D", "08:30", "08:40"))
    context = _DepotResetContext()

    assert (
        fragment_transition_is_feasible(
            first,
            second,
            home_depot_id="DEPOT",
            dispatch_context=context,
            fixed_route_band_mode=False,
            allow_same_day_depot_cycles=True,
        )
        is True
    )
    assert (
        fragment_transition_is_feasible(
            first,
            second,
            home_depot_id="DEPOT",
            dispatch_context=context,
            fixed_route_band_mode=False,
            allow_same_day_depot_cycles=False,
        )
        is False
    )
