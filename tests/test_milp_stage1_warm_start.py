from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from src.dispatch.models import DutyLeg, VehicleDuty
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.milp.solver_adapter import GurobiMILPAdapter


def _variable() -> SimpleNamespace:
    return SimpleNamespace(Start=None)


def _problem() -> CanonicalOptimizationProblem:
    trip = ProblemTrip(
        trip_id="t0",
        route_id="r1",
        origin="A",
        destination="B",
        departure_min=480,
        arrival_min=490,
        distance_km=1.0,
        allowed_vehicle_types=("ICE",),
    )
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="warm-start-test"),
        dispatch_context=SimpleNamespace(trips_by_id=lambda: {}),
        trips=(trip,),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-available",
                vehicle_type="ICE",
                home_depot_id="DEPOT",
                available=True,
            ),
        ),
    )


def test_stage1_warm_start_rejects_trip_assigned_to_two_vehicles() -> None:
    problem = _problem()
    trip = problem.trips[0]
    vehicles = (
        problem.vehicles[0],
        ProblemVehicle(
            vehicle_id="veh-second",
            vehicle_type="ICE",
            home_depot_id="DEPOT",
            available=True,
        ),
    )
    duties = (
        VehicleDuty(
            duty_id="duty-first",
            vehicle_type="ICE",
            legs=(DutyLeg(trip=trip),),
        ),
        VehicleDuty(
            duty_id="duty-second",
            vehicle_type="ICE",
            legs=(DutyLeg(trip=trip),),
        ),
    )
    problem = replace(
        problem,
        trips=(trip,),
        vehicles=vehicles,
        baseline_plan=AssignmentPlan(
            duties=duties,
            served_trip_ids=(trip.trip_id,),
            metadata={
                "source": "duplicate-test",
                "duty_vehicle_map": {
                    "duty-first": "veh-available",
                    "duty-second": "veh-second",
                },
            },
        ),
    )
    y = {
        ("veh-available", trip.trip_id): _variable(),
        ("veh-second", trip.trip_id): _variable(),
    }
    boundaries = {
        ("veh-available", trip.trip_id): _variable(),
        ("veh-second", trip.trip_id): _variable(),
    }

    applied, source, reason = GurobiMILPAdapter()._apply_stage1_assignment_warm_start(
        problem,
        enabled=True,
        y=y,
        x={},
        start_arc=boundaries,
        end_arc=boundaries,
        used_vehicle={vehicle.vehicle_id: _variable() for vehicle in vehicles},
        used_vehicle_day={(vehicle.vehicle_id, 0): _variable() for vehicle in vehicles},
        trip_day_index_by_trip_id={trip.trip_id: 0},
    )

    assert applied is False
    assert source == "duplicate-test"
    assert reason == (
        f"baseline_duplicate_assignment:{trip.trip_id}:veh-available:veh-second"
    )
    assert all(variable.Start is None for variable in y.values())


def test_stage1_warm_start_prefers_explicit_candidate_plan() -> None:
    problem = _problem()
    trip = problem.trips[0]
    candidate = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="candidate-duty",
                vehicle_type="ICE",
                legs=(DutyLeg(trip=trip),),
            ),
        ),
        served_trip_ids=(trip.trip_id,),
        metadata={
            "source": "stage1_restricted_candidate_warm_start",
            "duty_vehicle_map": {"candidate-duty": "veh-available"},
        },
    )
    y = {("veh-available", trip.trip_id): _variable()}
    start_arc = {("veh-available", trip.trip_id): _variable()}
    end_arc = {("veh-available", trip.trip_id): _variable()}
    used_vehicle = {"veh-available": _variable()}
    used_vehicle_day = {("veh-available", 0): _variable()}

    applied, source, reason = GurobiMILPAdapter()._apply_stage1_assignment_warm_start(
        problem,
        enabled=True,
        preferred_plan=candidate,
        y=y,
        x={},
        start_arc=start_arc,
        end_arc=end_arc,
        used_vehicle=used_vehicle,
        used_vehicle_day=used_vehicle_day,
        trip_day_index_by_trip_id={trip.trip_id: 0},
    )

    assert applied is True
    assert source == "stage1_restricted_candidate_warm_start"
    assert reason == ""
    assert y[("veh-available", trip.trip_id)].Start == 1.0
    assert start_arc[("veh-available", trip.trip_id)].Start == 1.0
    assert end_arc[("veh-available", trip.trip_id)].Start == 1.0
    assert used_vehicle["veh-available"].Start == 1.0
    assert used_vehicle_day[("veh-available", 0)].Start == 1.0
