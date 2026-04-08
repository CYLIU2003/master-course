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


def test_assign_duty_fragments_skips_vehicle_without_startup_deadhead_path() -> None:
    trip = Trip(
        trip_id="t1",
        route_id="r1",
        origin="Route Stop",
        destination="Terminal",
        departure_time="05:00",
        arrival_time="05:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-route",
        destination_stop_id="stop-terminal",
    )
    context = DispatchContext(
        service_date="2026-04-05",
        trips=[trip],
        turnaround_rules={},
        deadhead_rules={},
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

    assert duties == ()
    assert duty_vehicle_map == {}
    assert skipped == ("t1",)


def test_assign_duty_fragments_allows_cross_band_fragments_via_depot_reset() -> None:
    trip_a = Trip(
        trip_id="t_a",
        route_id="route-a",
        origin="Stop A",
        destination="Stop B",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-a",
        destination_stop_id="stop-b",
        route_family_code="黒07(入出庫便)",
    )
    trip_b = Trip(
        trip_id="t_b",
        route_id="route-b",
        origin="Stop C",
        destination="Stop D",
        departure_time="09:00",
        arrival_time="10:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-c",
        destination_stop_id="stop-d",
        route_family_code="渋24",
    )
    context = DispatchContext(
        service_date="2026-04-05",
        trips=[trip_a, trip_b],
        turnaround_rules={},
        deadhead_rules={
            ("stop-b", "stop-depot"): DeadheadRule(
                from_stop="stop-b",
                to_stop="stop-depot",
                travel_time_min=10,
            ),
            ("stop-depot", "stop-c"): DeadheadRule(
                from_stop="stop-depot",
                to_stop="stop-c",
                travel_time_min=10,
            ),
            ("stop-depot", "stop-a"): DeadheadRule(
                from_stop="stop-depot",
                to_stop="stop-a",
                travel_time_min=5,
            ),
        },
        vehicle_profiles={"BEV": VehicleProfile(vehicle_type="BEV")},
        fixed_route_band_mode=True,
        location_aliases={"dep1": ("stop-depot",)},
    )
    vehicle = ProblemVehicle(
        vehicle_id="veh-1",
        vehicle_type="BEV",
        home_depot_id="dep1",
    )
    duty_a = VehicleDuty(
        duty_id="duty-a",
        vehicle_type="BEV",
        legs=(DutyLeg(trip=trip_a, deadhead_from_prev_min=0),),
    )
    duty_b = VehicleDuty(
        duty_id="duty-b",
        vehicle_type="BEV",
        legs=(DutyLeg(trip=trip_b, deadhead_from_prev_min=0),),
    )

    duties, duty_vehicle_map, skipped = assign_duty_fragments_to_vehicles(
        (duty_a, duty_b),
        vehicles=(vehicle,),
        max_fragments_per_vehicle=2,
        dispatch_context=context,
        fixed_route_band_mode=True,
    )

    assert len(duties) == 2
    assert duty_vehicle_map == {"veh-1": "veh-1", "veh-1__frag2": "veh-1"}
    assert skipped == ()


def test_assign_duty_fragments_skips_cross_band_fragment_without_depot_reset_gap() -> None:
    trip_a = Trip(
        trip_id="t_a",
        route_id="route-a",
        origin="Stop A",
        destination="Stop B",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-a",
        destination_stop_id="stop-b",
        route_family_code="黒07(入出庫便)",
    )
    trip_b = Trip(
        trip_id="t_b",
        route_id="route-b",
        origin="Stop C",
        destination="Stop D",
        departure_time="08:45",
        arrival_time="09:15",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-c",
        destination_stop_id="stop-d",
        route_family_code="渋24",
    )
    context = DispatchContext(
        service_date="2026-04-05",
        trips=[trip_a, trip_b],
        turnaround_rules={},
        deadhead_rules={
            ("stop-b", "stop-depot"): DeadheadRule(
                from_stop="stop-b",
                to_stop="stop-depot",
                travel_time_min=10,
            ),
            ("stop-depot", "stop-c"): DeadheadRule(
                from_stop="stop-depot",
                to_stop="stop-c",
                travel_time_min=10,
            ),
            ("stop-depot", "stop-a"): DeadheadRule(
                from_stop="stop-depot",
                to_stop="stop-a",
                travel_time_min=5,
            ),
        },
        vehicle_profiles={"BEV": VehicleProfile(vehicle_type="BEV")},
        fixed_route_band_mode=True,
        location_aliases={"dep1": ("stop-depot",)},
    )
    vehicle = ProblemVehicle(
        vehicle_id="veh-1",
        vehicle_type="BEV",
        home_depot_id="dep1",
    )
    duty_a = VehicleDuty(
        duty_id="duty-a",
        vehicle_type="BEV",
        legs=(DutyLeg(trip=trip_a, deadhead_from_prev_min=0),),
    )
    duty_b = VehicleDuty(
        duty_id="duty-b",
        vehicle_type="BEV",
        legs=(DutyLeg(trip=trip_b, deadhead_from_prev_min=0),),
    )

    duties, duty_vehicle_map, skipped = assign_duty_fragments_to_vehicles(
        (duty_a, duty_b),
        vehicles=(vehicle,),
        max_fragments_per_vehicle=2,
        dispatch_context=context,
        fixed_route_band_mode=True,
    )

    assert len(duties) == 1
    assert duty_vehicle_map == {"veh-1": "veh-1"}
    assert skipped == ("t_b",)


def test_assign_duty_fragments_skips_same_band_fragment_without_depot_reset_gap() -> None:
    trip_a = Trip(
        trip_id="t_a",
        route_id="route-a",
        origin="Stop A",
        destination="Stop B",
        departure_time="08:00",
        arrival_time="08:30",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-a",
        destination_stop_id="stop-b",
        route_family_code="渋24",
    )
    trip_b = Trip(
        trip_id="t_b",
        route_id="route-b",
        origin="Stop C",
        destination="Stop D",
        departure_time="08:45",
        arrival_time="09:15",
        distance_km=5.0,
        allowed_vehicle_types=("BEV",),
        origin_stop_id="stop-c",
        destination_stop_id="stop-d",
        route_family_code="渋24",
    )
    context = DispatchContext(
        service_date="2026-04-05",
        trips=[trip_a, trip_b],
        turnaround_rules={},
        deadhead_rules={
            ("stop-b", "stop-depot"): DeadheadRule(
                from_stop="stop-b",
                to_stop="stop-depot",
                travel_time_min=10,
            ),
            ("stop-depot", "stop-c"): DeadheadRule(
                from_stop="stop-depot",
                to_stop="stop-c",
                travel_time_min=10,
            ),
            ("stop-depot", "stop-a"): DeadheadRule(
                from_stop="stop-depot",
                to_stop="stop-a",
                travel_time_min=5,
            ),
        },
        vehicle_profiles={"BEV": VehicleProfile(vehicle_type="BEV")},
        fixed_route_band_mode=True,
        location_aliases={"dep1": ("stop-depot",)},
    )
    vehicle = ProblemVehicle(
        vehicle_id="veh-1",
        vehicle_type="BEV",
        home_depot_id="dep1",
    )
    duty_a = VehicleDuty(
        duty_id="duty-a",
        vehicle_type="BEV",
        legs=(DutyLeg(trip=trip_a, deadhead_from_prev_min=0),),
    )
    duty_b = VehicleDuty(
        duty_id="duty-b",
        vehicle_type="BEV",
        legs=(DutyLeg(trip=trip_b, deadhead_from_prev_min=0),),
    )

    duties, duty_vehicle_map, skipped = assign_duty_fragments_to_vehicles(
        (duty_a, duty_b),
        vehicles=(vehicle,),
        max_fragments_per_vehicle=2,
        dispatch_context=context,
        fixed_route_band_mode=True,
    )

    assert len(duties) == 1
    assert duty_vehicle_map == {"veh-1": "veh-1"}
    assert skipped == ("t_b",)
