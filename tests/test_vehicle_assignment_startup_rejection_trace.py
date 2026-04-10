from __future__ import annotations

from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.optimization.common.problem import ProblemVehicle
from src.optimization.common.vehicle_assignment import assign_duty_fragments_to_vehicles


class _Context:
    def get_deadhead_min(self, from_stop: str, to_stop: str) -> int:
        return 5 if (from_stop, to_stop) == ("GOOD_DEPOT", "A") else 0

    def get_turnaround_min(self, stop: str) -> int:
        return 0

    def locations_equivalent(self, left: str, right: str) -> bool:
        return left == right

    def has_location_data(self, stop: str) -> bool:
        return stop in {"GOOD_DEPOT", "BAD_DEPOT", "A"}


def test_startup_rejected_vehicle_is_traced() -> None:
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
    debug: dict = {}

    _duties, duty_map, skipped = assign_duty_fragments_to_vehicles(
        (VehicleDuty("candidate-duty", "ICE", (DutyLeg(trip=trip),)),),
        vehicles=(
            ProblemVehicle("veh-bad", "ICE", "BAD_DEPOT"),
            ProblemVehicle("veh-good", "ICE", "GOOD_DEPOT"),
        ),
        max_fragments_per_vehicle=1,
        dispatch_context=_Context(),
        debug_metadata=debug,
    )

    assert skipped == ()
    assert duty_map == {"veh-good": "veh-good"}
    assert debug["startup_rejected_vehicle_ids_by_duty"] == {"candidate-duty": ["veh-bad"]}
