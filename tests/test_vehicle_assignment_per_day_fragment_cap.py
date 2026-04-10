from __future__ import annotations

from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.optimization.common.problem import ProblemVehicle
from src.optimization.common.vehicle_assignment import assign_duty_fragments_to_vehicles


class _DepotResetContext:
    def __init__(self) -> None:
        self._deadheads = {
            ("DEPOT", "A"): 5,
            ("DEPOT", "C"): 5,
            ("DEPOT", "E"): 5,
            ("B", "DEPOT"): 5,
            ("D", "DEPOT"): 5,
            ("B", "C"): 25,
            ("D", "E"): 25,
        }

    def get_deadhead_min(self, from_stop: str, to_stop: str) -> int:
        return int(self._deadheads.get((str(from_stop), str(to_stop)), 0))

    def get_turnaround_min(self, stop: str) -> int:
        return 0

    def locations_equivalent(self, left: str, right: str) -> bool:
        return str(left) == str(right)

    def has_location_data(self, stop: str) -> bool:
        return True


def _trip(trip_id: str, origin: str, destination: str, departure: str, arrival: str) -> Trip:
    return Trip(
        trip_id=trip_id,
        route_id="r1",
        origin=origin,
        destination=destination,
        departure_time=departure,
        arrival_time=arrival,
        distance_km=5.0,
        allowed_vehicle_types=("ICE",),
    )


def _duty(duty_id: str, trip: Trip) -> VehicleDuty:
    return VehicleDuty(
        duty_id=duty_id,
        vehicle_type="ICE",
        legs=(DutyLeg(trip=trip),),
    )


def test_same_day_cap_two_allows_two_fragments_on_one_vehicle() -> None:
    assigned_duties, _map, skipped = assign_duty_fragments_to_vehicles(
        (
            _duty("d1", _trip("t1", "A", "B", "08:00", "08:10")),
            _duty("d2", _trip("t2", "C", "D", "08:30", "08:40")),
        ),
        vehicles=(ProblemVehicle(vehicle_id="veh-1", vehicle_type="ICE", home_depot_id="DEPOT"),),
        max_fragments_per_vehicle=3,
        max_fragments_per_vehicle_per_day=2,
        allow_same_day_depot_cycles=True,
        horizon_start_min=8 * 60,
        dispatch_context=_DepotResetContext(),
        fixed_route_band_mode=False,
    )

    assert [duty.duty_id for duty in assigned_duties] == ["veh-1", "veh-1__frag2"]
    assert skipped == ()


def test_same_day_disabled_rejects_second_fragment_after_depot_reset() -> None:
    assigned_duties, _map, skipped = assign_duty_fragments_to_vehicles(
        (
            _duty("d1", _trip("t1", "A", "B", "08:00", "08:10")),
            _duty("d2", _trip("t2", "C", "D", "08:30", "08:40")),
        ),
        vehicles=(ProblemVehicle(vehicle_id="veh-1", vehicle_type="ICE", home_depot_id="DEPOT"),),
        max_fragments_per_vehicle=3,
        max_fragments_per_vehicle_per_day=2,
        allow_same_day_depot_cycles=False,
        horizon_start_min=8 * 60,
        dispatch_context=_DepotResetContext(),
        fixed_route_band_mode=False,
    )

    assert [duty.duty_id for duty in assigned_duties] == ["veh-1"]
    assert skipped == ("t2",)


def test_per_day_fragment_cap_rejects_third_fragment() -> None:
    assigned_duties, _map, skipped = assign_duty_fragments_to_vehicles(
        (
            _duty("d1", _trip("t1", "A", "B", "08:00", "08:10")),
            _duty("d2", _trip("t2", "C", "D", "08:30", "08:40")),
            _duty("d3", _trip("t3", "E", "F", "09:00", "09:10")),
        ),
        vehicles=(ProblemVehicle(vehicle_id="veh-1", vehicle_type="ICE", home_depot_id="DEPOT"),),
        max_fragments_per_vehicle=4,
        max_fragments_per_vehicle_per_day=2,
        allow_same_day_depot_cycles=True,
        horizon_start_min=8 * 60,
        dispatch_context=_DepotResetContext(),
        fixed_route_band_mode=False,
    )

    assert [duty.duty_id for duty in assigned_duties] == ["veh-1", "veh-1__frag2"]
    assert skipped == ("t3",)
