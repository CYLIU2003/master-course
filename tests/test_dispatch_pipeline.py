"""
tests/test_dispatch_pipeline.py

Integration-level checks for TimetableDispatchPipeline coverage guarantees.
"""

from src.dispatch.models import (
    DispatchContext,
    DutyLeg,
    Trip,
    VehicleDuty,
    VehicleProfile,
)
from src.dispatch.pipeline import TimetableDispatchPipeline


def _make_trip(
    trip_id: str,
    origin: str,
    destination: str,
    dep: str,
    arr: str,
    allowed: tuple[str, ...] = ("BEV",),
) -> Trip:
    return Trip(
        trip_id=trip_id,
        route_id="R1",
        origin=origin,
        destination=destination,
        departure_time=dep,
        arrival_time=arr,
        distance_km=10.0,
        allowed_vehicle_types=allowed,
    )


def _make_context(trips: list[Trip]) -> DispatchContext:
    return DispatchContext(
        service_date="2024-06-01",
        trips=trips,
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={"BEV": VehicleProfile(vehicle_type="BEV")},
        default_turnaround_min=10,
    )


def test_pipeline_marks_full_coverage_as_valid():
    ctx = _make_context(
        [
            _make_trip("T1", "A", "A", "07:00", "07:30"),
            _make_trip("T2", "A", "A", "08:00", "08:30"),
            _make_trip("T3", "A", "A", "09:00", "09:30"),
        ]
    )
    result = TimetableDispatchPipeline().run(ctx, vehicle_type="BEV")

    assigned = []
    for duty in result.duties:
        assigned.extend(duty.trip_ids)

    assert sorted(assigned) == ["T1", "T2", "T3"]
    assert result.uncovered_trip_ids == []
    assert result.duplicate_trip_ids == []
    assert result.all_valid


def test_pipeline_duplicate_trip_detection_flips_all_valid():
    class _DuplicateDispatcher:
        def generate_greedy_duties_from_graph(self, context, vehicle_type, graph):
            trip = context.trips[0]
            return [
                VehicleDuty(
                    duty_id="D-1",
                    vehicle_type=vehicle_type,
                    legs=(DutyLeg(trip=trip),),
                ),
                VehicleDuty(
                    duty_id="D-2",
                    vehicle_type=vehicle_type,
                    legs=(DutyLeg(trip=trip),),
                ),
            ]

    ctx = _make_context([_make_trip("T1", "A", "A", "07:00", "07:30")])
    pipeline = TimetableDispatchPipeline()
    pipeline._dispatcher = _DuplicateDispatcher()

    result = pipeline.run(ctx, vehicle_type="BEV")

    assert result.uncovered_trip_ids == []
    assert result.duplicate_trip_ids == ["T1"]
    assert not result.all_valid
