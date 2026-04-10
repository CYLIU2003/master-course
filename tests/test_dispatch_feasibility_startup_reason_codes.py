from __future__ import annotations

from src.dispatch.feasibility import evaluate_startup_feasibility
from src.dispatch.models import Trip


class _StartupContext:
    def __init__(self, *, known_locations: set[str], deadheads: dict[tuple[str, str], int]) -> None:
        self._known_locations = {str(item) for item in known_locations}
        self._deadheads = {
            (str(from_stop), str(to_stop)): int(minutes)
            for (from_stop, to_stop), minutes in deadheads.items()
        }

    def get_deadhead_min(self, from_stop: str, to_stop: str) -> int:
        return int(self._deadheads.get((str(from_stop), str(to_stop)), 0))

    def locations_equivalent(self, left: str, right: str) -> bool:
        return str(left) == str(right)

    def has_location_data(self, stop: str) -> bool:
        return str(stop) in self._known_locations


def _trip(origin: str) -> Trip:
    return Trip(
        trip_id="t1",
        route_id="r1",
        origin=origin,
        destination="B",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=5.0,
        allowed_vehicle_types=("ICE",),
    )


def test_startup_alias_missing_reason_code() -> None:
    result = evaluate_startup_feasibility(
        _trip("UNKNOWN_ORIGIN"),
        _StartupContext(known_locations={"DEPOT"}, deadheads={}),
        "DEPOT",
    )

    assert result.feasible is False
    assert result.reason_code == "startup_alias_missing"


def test_startup_deadhead_missing_reason_code() -> None:
    result = evaluate_startup_feasibility(
        _trip("KNOWN_ORIGIN"),
        _StartupContext(known_locations={"DEPOT", "KNOWN_ORIGIN"}, deadheads={}),
        "DEPOT",
    )

    assert result.feasible is False
    assert result.reason_code == "startup_deadhead_missing"
