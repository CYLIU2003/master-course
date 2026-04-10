from __future__ import annotations

from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.dispatch.route_band import (
    fragment_transition_allows_depot_reset,
    fragment_transition_is_feasible,
)


class _DepotResetContext:
    def __init__(self) -> None:
        self._deadheads = {
            ("DEPOT", "C"): 5,
            ("B", "DEPOT"): 5,
            ("B", "C"): 25,
        }

    def get_deadhead_min(self, from_stop: str, to_stop: str) -> int:
        return int(self._deadheads.get((str(from_stop), str(to_stop)), 0))

    def get_turnaround_min(self, stop: str) -> int:
        return 0

    def locations_equivalent(self, left: str, right: str) -> bool:
        return str(left) == str(right)

    def has_location_data(self, stop: str) -> bool:
        return True


def _duty(duty_id: str, trip_id: str, origin: str, destination: str, departure: str, arrival: str) -> VehicleDuty:
    trip = Trip(
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
    return VehicleDuty(duty_id=duty_id, vehicle_type="ICE", legs=(DutyLeg(trip=trip),))


def test_depot_reset_flag_controls_route_band_fragment_transition() -> None:
    context = _DepotResetContext()
    first = _duty("veh-1", "t1", "A", "B", "08:00", "08:10")
    second = _duty("veh-1__frag2", "t2", "C", "D", "08:30", "08:40")

    assert fragment_transition_allows_depot_reset(
        first,
        second,
        home_depot_id="DEPOT",
        dispatch_context=context,
        allow_same_day_depot_cycles=True,
    )
    assert not fragment_transition_allows_depot_reset(
        first,
        second,
        home_depot_id="DEPOT",
        dispatch_context=context,
        allow_same_day_depot_cycles=False,
    )
    assert fragment_transition_is_feasible(
        first,
        second,
        home_depot_id="DEPOT",
        dispatch_context=context,
        fixed_route_band_mode=True,
        allow_same_day_depot_cycles=True,
    )
    assert not fragment_transition_is_feasible(
        first,
        second,
        home_depot_id="DEPOT",
        dispatch_context=context,
        fixed_route_band_mode=True,
        allow_same_day_depot_cycles=False,
    )
