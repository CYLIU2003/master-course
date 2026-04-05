from __future__ import annotations

from src.dispatch.dispatcher import DispatchGenerator
from src.dispatch.models import (
    DeadheadRule,
    DispatchContext,
    Trip,
    TurnaroundRule,
    VehicleProfile,
)


def _context() -> DispatchContext:
    trips = [
        Trip(
            trip_id="t1",
            route_id="r1",
            origin="Depot Bay",
            destination="Station Bay 1",
            departure_time="08:00",
            arrival_time="08:30",
            distance_km=6.0,
            allowed_vehicle_types=("BEV",),
            origin_stop_id="stop-a",
            destination_stop_id="stop-b-out",
            route_family_code="r1",
            direction="outbound",
            route_variant_type="main_outbound",
        ),
        Trip(
            trip_id="t2",
            route_id="r1",
            origin="Station Bay 2",
            destination="Depot Bay",
            departure_time="08:45",
            arrival_time="09:15",
            distance_km=6.0,
            allowed_vehicle_types=("BEV",),
            origin_stop_id="stop-b-in",
            destination_stop_id="stop-a",
            route_family_code="r1",
            direction="inbound",
            route_variant_type="main_inbound",
        ),
    ]
    return DispatchContext(
        service_date="2026-04-05",
        trips=trips,
        turnaround_rules={
            "stop-b-out": TurnaroundRule(stop_id="stop-b-out", min_turnaround_min=5),
            "stop-b-in": TurnaroundRule(stop_id="stop-b-in", min_turnaround_min=5),
            "stop-a": TurnaroundRule(stop_id="stop-a", min_turnaround_min=5),
        },
        deadhead_rules={
            ("stop-b-out", "stop-b-in"): DeadheadRule(
                from_stop="stop-b-out",
                to_stop="stop-b-in",
                travel_time_min=8,
            ),
        },
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
            )
        },
    )


def test_dispatch_context_resolves_location_aliases_from_trip_labels() -> None:
    context = _context()

    assert context.get_turnaround_min("Station Bay 1") == 5
    assert context.get_deadhead_min("Station Bay 1", "Station Bay 2") == 8


def test_dispatch_generator_preserves_deadhead_minutes_when_graph_uses_stop_ids() -> None:
    context = _context()
    graph = {"t1": ["t2"], "t2": []}

    duties = DispatchGenerator().generate_greedy_duties_from_graph(context, "BEV", graph)

    assert len(duties) == 1
    assert duties[0].trip_ids == ["t1", "t2"]
    assert duties[0].legs[1].deadhead_from_prev_min == 8
