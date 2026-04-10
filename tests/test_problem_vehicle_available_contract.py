from __future__ import annotations

from types import SimpleNamespace

from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemVehicle,
)


def _duty(vehicle_id: str) -> VehicleDuty:
    trip = Trip(
        trip_id="t1",
        route_id="r1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="08:10",
        distance_km=1.0,
        allowed_vehicle_types=("ICE",),
    )
    return VehicleDuty(duty_id=vehicle_id, vehicle_type="ICE", legs=(DutyLeg(trip=trip),))


def test_assignment_plan_available_vehicle_helpers() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="available-contract"),
        dispatch_context=SimpleNamespace(),
        trips=(),
        vehicles=(
            ProblemVehicle("veh-used", "ICE", "DEPOT", available=True),
            ProblemVehicle("veh-unavailable", "ICE", "DEPOT", available=False),
            ProblemVehicle("veh-unused", "ICE", "DEPOT", available=True),
        ),
    )
    plan = AssignmentPlan(duties=(_duty("veh-used"),))

    assert plan.count_used_available_vehicles(problem) == 1
    assert plan.unused_available_vehicle_ids(problem) == ("veh-unused",)
