from __future__ import annotations

from types import SimpleNamespace

from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemVehicle,
)


def test_feasibility_rejects_unavailable_vehicle_usage() -> None:
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
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="availability"),
        dispatch_context=SimpleNamespace(),
        trips=(),
        vehicles=(ProblemVehicle("veh-1", "ICE", "DEPOT", available=False),),
    )
    plan = AssignmentPlan(duties=(VehicleDuty("veh-1", "ICE", (DutyLeg(trip=trip),)),))

    report = FeasibilityChecker().evaluate(problem, plan)

    assert report.feasible is False
    assert any("[AVAILABILITY]" in error for error in report.errors)
