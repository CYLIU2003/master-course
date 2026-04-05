from __future__ import annotations

from src.dispatch.models import DeadheadRule, DispatchContext, DutyLeg, Trip, VehicleDuty, VehicleProfile
from src.optimization.common.problem import ProblemVehicle
from src.optimization.common.vehicle_assignment import assign_duty_fragments_to_vehicles


def test_assign_duty_fragments_adds_startup_deadhead_from_home_depot() -> None:
    trip = Trip(
        trip_id="t1",
        route_id="r1",
        origin="Route Stop",
        destination="Terminal",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-route",
        destination_stop_id="stop-terminal",
    )
    context = DispatchContext(
        service_date="2026-04-05",
        trips=[trip],
        turnaround_rules={},
        deadhead_rules={
            ("stop-depot", "stop-route"): DeadheadRule(
                from_stop="stop-depot",
                to_stop="stop-route",
                travel_time_min=12,
            ),
        },
        vehicle_profiles={"BEV": VehicleProfile(vehicle_type="BEV")},
        location_aliases={"dep1": ("stop-depot",)},
    )
    duty = VehicleDuty(
        duty_id="duty-1",
        vehicle_type="BEV",
        legs=(DutyLeg(trip=trip, deadhead_from_prev_min=0),),
    )
    vehicle = ProblemVehicle(
        vehicle_id="veh-1",
        vehicle_type="BEV",
        home_depot_id="dep1",
    )

    duties, duty_vehicle_map, skipped = assign_duty_fragments_to_vehicles(
        (duty,),
        vehicles=(vehicle,),
        max_fragments_per_vehicle=1,
        dispatch_context=context,
    )

    assert skipped == ()
    assert duty_vehicle_map == {"veh-1": "veh-1"}
    assert duties[0].legs[0].deadhead_from_prev_min == 12
