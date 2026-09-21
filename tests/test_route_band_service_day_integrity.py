"""Route-band acceptance must not depend on native duty fragmentation."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.dispatch.models import DutyLeg, Trip, VehicleDuty
from src.optimization.common.feasibility import FeasibilityChecker
from src.optimization.common.problem import AssignmentPlan


def trip(identifier, band, departure, *, date="", day=0):
    return Trip(identifier, band, "A", "A", departure, departure, 1.0,
                ("ICE",), route_family_code=band, service_date=date, day_index=day)


def errors(trips, *, split=False, cycles=False, enabled=True, horizon="00:00"):
    groups = [(item,) for item in trips] if split else [trips]
    duties = tuple(VehicleDuty(str(i), "ICE", tuple(DutyLeg(t) for t in group))
                   for i, group in enumerate(groups))
    plan = AssignmentPlan(duties=duties, metadata={
        "duty_vehicle_map": {d.duty_id: "vehicle" for d in duties}})
    problem = SimpleNamespace(metadata={"fixed_route_band_mode": enabled},
                              scenario=SimpleNamespace(horizon_start=horizon,
                                  allow_same_day_depot_cycles=cycles))
    return FeasibilityChecker()._evaluate_route_band_integrity(problem, plan)


@pytest.mark.parametrize("split", [False, True])
@pytest.mark.parametrize("cycles", [False, True])
def test_next_service_day_can_use_another_band(split, cycles):
    trips = [trip("a", "渋21", "08:00", date="2025-05-12", day=0),
             trip("b", "渋23", "32:00", date="2025-05-13", day=1)]
    assert errors(trips, split=split, cycles=cycles) == []


@pytest.mark.parametrize("split", [False, True])
@pytest.mark.parametrize("cycles", [False, True])
def test_same_day_band_change_is_rejected_in_either_representation(split, cycles):
    trips = [trip("a", "渋21", "08:00"), trip("b", "渋23", "10:00")]
    messages = errors(trips, split=split, cycles=cycles)
    assert len(messages) == 1
    assert "[ROUTE_BAND]" in messages[0] and "within day 0" in messages[0]


def test_dated_post_midnight_trip_keeps_its_service_day():
    trips = [trip("a", "渋21", "23:00", date="2025-05-12"),
             trip("b", "渋23", "25:00", date="2025-05-12")]
    assert errors(trips)
    # Identical clock times on different declared service days are not a
    # route-band violation (time overlap remains a separate physical check).
    assert not errors([trips[0], replace(trips[1], service_date="2025-05-13", day_index=1)])


def test_undated_trips_use_horizon_offset_and_route_family_normalization():
    assert errors([trip("a", "渋21", "26:00"), trip("b", "渋23", "28:00")],
                  horizon="03:00") == []
    assert errors([trip("a", "黒07", "08:00"), trip("b", "黒07(入出庫便)", "09:00")]) == []
    assert errors([trip("a", "渋21", "08:00"), trip("b", "渋23", "09:00")], enabled=False) == []


def test_second_day_conflict_across_multiday_duties_is_not_hidden():
    trips = [trip("a", "渋21", "08:00"), trip("b", "渋21", "32:00"),
             trip("c", "渋23", "34:00")]
    messages = errors(trips, split=True)
    assert len(messages) == 1 and "within day 1" in messages[0]
