from __future__ import annotations

from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.optimization.common.problem import ProblemVehicle
from src.optimization.common.vehicle_assignment import assign_duty_fragments_to_vehicles


def _duty() -> VehicleDuty:
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
    return VehicleDuty(duty_id="d1", vehicle_type="ICE", legs=(DutyLeg(trip=trip),))


def test_vehicle_assignment_excludes_unavailable_vehicle() -> None:
    duties, duty_map, skipped = assign_duty_fragments_to_vehicles(
        (_duty(),),
        vehicles=(
            ProblemVehicle("veh-000", "ICE", "DEPOT", available=False),
            ProblemVehicle("veh-001", "ICE", "DEPOT", available=True),
        ),
        max_fragments_per_vehicle=1,
    )

    assert skipped == ()
    assert [duty.duty_id for duty in duties] == ["veh-001"]
    assert duty_map == {"veh-001": "veh-001"}
