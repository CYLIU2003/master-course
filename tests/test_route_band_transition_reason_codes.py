from __future__ import annotations

from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.dispatch.route_band import fragment_transition_diagnostic, required_deadhead_diagnostic


class _Context:
    def __init__(self, deadheads: dict[tuple[str, str], int] | None = None) -> None:
        self._deadheads = deadheads or {}

    def get_deadhead_min(self, from_stop: str, to_stop: str) -> int:
        return int(self._deadheads.get((from_stop, to_stop), 0))

    def get_turnaround_min(self, stop: str) -> int:
        return 0

    def locations_equivalent(self, left: str, right: str) -> bool:
        return left == right

    def has_location_data(self, stop: str) -> bool:
        return stop in {"A", "B", "C", "D", "DEPOT"}


def _duty(duty_id: str, trip_id: str, origin: str, destination: str, band: str) -> VehicleDuty:
    trip = Trip(
        trip_id=trip_id,
        route_id=band,
        origin=origin,
        destination=destination,
        departure_time="08:00" if trip_id == "t1" else "08:30",
        arrival_time="08:10" if trip_id == "t1" else "08:40",
        distance_km=1.0,
        allowed_vehicle_types=("ICE",),
        route_family_code=band,
    )
    return VehicleDuty(duty_id=duty_id, vehicle_type="ICE", legs=(DutyLeg(trip=trip),))


def test_transition_diagnostic_distinguishes_route_band_block() -> None:
    diagnostic = fragment_transition_diagnostic(
        _duty("d1", "t1", "A", "B", "FAM1"),
        _duty("d2", "t2", "C", "D", "FAM2"),
        home_depot_id="DEPOT",
        dispatch_context=_Context(),
        fixed_route_band_mode=True,
        allow_same_day_depot_cycles=False,
    )

    assert diagnostic.reason_code == "route_band_blocked"
    assert diagnostic.route_band_blocked is True


def test_required_deadhead_diagnostic_distinguishes_missing_deadhead() -> None:
    exists, _minutes, reason = required_deadhead_diagnostic(
        "B",
        "C",
        dispatch_context=_Context(),
    )

    assert exists is False
    assert reason == "deadhead_missing"
