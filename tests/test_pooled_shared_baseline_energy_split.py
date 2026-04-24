from __future__ import annotations

from src.dispatch.models import DeadheadRule, DispatchContext, Trip, TurnaroundRule, VehicleProfile
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import ChargerDefinition, ProblemVehicle


def _linear_bev_context() -> DispatchContext:
    return DispatchContext(
        service_date="2026-04-21",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="Depot",
                destination="A",
                departure_time="08:00",
                arrival_time="08:20",
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                origin_stop_id="dep",
                destination_stop_id="a",
            ),
            Trip(
                trip_id="t2",
                route_id="r1",
                origin="A",
                destination="B",
                departure_time="08:30",
                arrival_time="08:50",
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                origin_stop_id="a",
                destination_stop_id="b",
            ),
            Trip(
                trip_id="t3",
                route_id="r1",
                origin="B",
                destination="C",
                departure_time="09:00",
                arrival_time="09:20",
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                origin_stop_id="b",
                destination_stop_id="c",
            ),
            Trip(
                trip_id="t4",
                route_id="r1",
                origin="C",
                destination="Depot",
                departure_time="09:30",
                arrival_time="09:50",
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                origin_stop_id="c",
                destination_stop_id="dep",
            ),
        ],
        turnaround_rules={
            "dep": TurnaroundRule(stop_id="dep", min_turnaround_min=5),
            "a": TurnaroundRule(stop_id="a", min_turnaround_min=5),
            "b": TurnaroundRule(stop_id="b", min_turnaround_min=5),
            "c": TurnaroundRule(stop_id="c", min_turnaround_min=5),
        },
        deadhead_rules={
            ("bev-1", "dep"): DeadheadRule(from_stop="bev-1", to_stop="dep", travel_time_min=0),
            ("bev-2", "dep"): DeadheadRule(from_stop="bev-2", to_stop="dep", travel_time_min=0),
            ("bev-1", "b"): DeadheadRule(from_stop="bev-1", to_stop="b", travel_time_min=10),
            ("bev-2", "b"): DeadheadRule(from_stop="bev-2", to_stop="b", travel_time_min=10),
        },
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=30.0,
                energy_consumption_kwh_per_km=1.0,
            ),
        },
        location_aliases={"bev-1": ("dep",), "bev-2": ("dep",)},
    )


def test_pooled_shared_baseline_splits_chain_when_vehicle_energy_is_insufficient() -> None:
    context = _linear_bev_context()
    vehicles = (
        ProblemVehicle(
            vehicle_id="bev-1",
            vehicle_type="BEV",
            home_depot_id="bev-1",
            initial_soc=25.0,
            reserve_soc=5.0,
            battery_capacity_kwh=30.0,
            energy_consumption_kwh_per_km=1.0,
        ),
        ProblemVehicle(
            vehicle_id="bev-2",
            vehicle_type="BEV",
            home_depot_id="bev-2",
            initial_soc=25.0,
            reserve_soc=5.0,
            battery_capacity_kwh=30.0,
            energy_consumption_kwh_per_km=1.0,
        ),
    )
    feasible_connections = {
        "t1": ("t2",),
        "t2": ("t3",),
        "t3": ("t4",),
        "t4": (),
    }

    plan = ProblemBuilder()._build_pooled_shared_baseline(
        context,
        vehicles=vehicles,
        all_trip_ids={"t1", "t2", "t3", "t4"},
        feasible_connections=feasible_connections,
    )

    assert plan.metadata["source"] == "dispatch_pooled_shared_path_cover_baseline"
    assert plan.unserved_trip_ids == ()
    assert len(plan.duties) == 2
    assert [duty.trip_ids for duty in plan.duties] == [["t1", "t2"], ["t3", "t4"]]
    assert plan.metadata["path_cover_chain_count"] == 1
    assert plan.metadata["path_cover_segment_count"] == 2


def test_pooled_shared_baseline_splits_chain_for_post_return_target_feasibility() -> None:
    context = _linear_bev_context()
    context.deadhead_rules[("b", "bev-1")] = DeadheadRule(from_stop="b", to_stop="bev-1", travel_time_min=10)
    context.deadhead_rules[("b", "bev-2")] = DeadheadRule(from_stop="b", to_stop="bev-2", travel_time_min=10)
    context.__post_init__()
    vehicles = (
        ProblemVehicle(
            vehicle_id="bev-1",
            vehicle_type="BEV",
            home_depot_id="bev-1",
            initial_soc=35.0,
            reserve_soc=5.0,
            battery_capacity_kwh=50.0,
            energy_consumption_kwh_per_km=1.0,
        ),
        ProblemVehicle(
            vehicle_id="bev-2",
            vehicle_type="BEV",
            home_depot_id="bev-2",
            initial_soc=35.0,
            reserve_soc=5.0,
            battery_capacity_kwh=50.0,
            energy_consumption_kwh_per_km=1.0,
        ),
    )
    feasible_connections = {
        "t1": ("t2",),
        "t2": ("t3",),
        "t3": ("t4",),
        "t4": (),
    }

    plan = ProblemBuilder()._build_pooled_shared_baseline(
        context,
        vehicles=vehicles,
        all_trip_ids={"t1", "t2", "t3", "t4"},
        feasible_connections=feasible_connections,
        chargers=(ChargerDefinition("chg-1", "bev-1", 20.0), ChargerDefinition("chg-2", "bev-2", 20.0)),
        timestep_min=60,
        final_soc_floor_percent=10.0,
        final_soc_target_percent=60.0,
        final_soc_target_tolerance_percent=0.0,
    )

    assert plan.unserved_trip_ids == ()
    assert len(plan.duties) == 2
    assert [duty.trip_ids for duty in plan.duties] == [["t1", "t2"], ["t3", "t4"]]
