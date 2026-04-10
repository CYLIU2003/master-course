from __future__ import annotations

from src.dispatch.feasibility import evaluate_startup_feasibility
from src.dispatch.models import Trip


class _Context:
    def __init__(self, *, deadheads: dict[tuple[str, str], int], known: set[str]) -> None:
        self._deadheads = deadheads
        self._known = known

    def get_deadhead_min(self, from_stop: str, to_stop: str) -> int:
        return int(self._deadheads.get((from_stop, to_stop), 0))

    def locations_equivalent(self, left: str, right: str) -> bool:
        return left == right

    def has_location_data(self, stop: str) -> bool:
        return stop in self._known


def _trip() -> Trip:
    return Trip(
        trip_id="t1",
        route_id="r1",
        origin="A",
        destination="B",
        departure_time="08:00",
        arrival_time="08:10",
        distance_km=1.0,
        allowed_vehicle_types=("ICE",),
        route_family_code="FAM1",
    )


def test_startup_reason_alias_missing() -> None:
    result = evaluate_startup_feasibility(
        _trip(),
        _Context(deadheads={}, known={"DEPOT"}),
        "DEPOT",
    )

    assert result.reason_code == "startup_alias_missing"


def test_startup_reason_deadhead_missing() -> None:
    result = evaluate_startup_feasibility(
        _trip(),
        _Context(deadheads={}, known={"DEPOT", "A"}),
        "DEPOT",
    )

    assert result.reason_code == "startup_deadhead_missing"


def test_startup_reason_time_insufficient() -> None:
    result = evaluate_startup_feasibility(
        _trip(),
        _Context(deadheads={("DEPOT", "A"): 20}, known={"DEPOT", "A"}),
        "DEPOT",
        earliest_available_min=8 * 60 - 10,
    )

    assert result.reason_code == "startup_time_insufficient"


def test_startup_reason_route_band_blocked() -> None:
    result = evaluate_startup_feasibility(
        _trip(),
        _Context(deadheads={("DEPOT", "A"): 5}, known={"DEPOT", "A"}),
        "DEPOT",
        allowed_route_band_ids=("OTHER",),
    )

    assert result.reason_code == "startup_route_band_blocked"
