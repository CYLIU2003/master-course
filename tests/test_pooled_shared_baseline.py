from __future__ import annotations

import pytest

from src.dispatch.models import DispatchContext, Trip, TurnaroundRule, VehicleProfile
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import ProblemVehicle


def _shared_context() -> DispatchContext:
    return DispatchContext(
        service_date="2026-04-05",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="Depot",
                destination="A",
                departure_time="08:00",
                arrival_time="08:20",
                distance_km=5.0,
                allowed_vehicle_types=("BEV", "ICE"),
                origin_stop_id="dep",
                destination_stop_id="a",
            ),
            Trip(
                trip_id="t2",
                route_id="r1",
                origin="Depot",
                destination="B",
                departure_time="08:00",
                arrival_time="08:20",
                distance_km=5.0,
                allowed_vehicle_types=("BEV", "ICE"),
                origin_stop_id="dep",
                destination_stop_id="b",
            ),
            Trip(
                trip_id="t3",
                route_id="r1",
                origin="A",
                destination="Depot",
                departure_time="08:40",
                arrival_time="09:00",
                distance_km=5.0,
                allowed_vehicle_types=("BEV", "ICE"),
                origin_stop_id="a",
                destination_stop_id="dep",
            ),
            Trip(
                trip_id="t4",
                route_id="r1",
                origin="B",
                destination="Depot",
                departure_time="08:40",
                arrival_time="09:00",
                distance_km=5.0,
                allowed_vehicle_types=("BEV", "ICE"),
                origin_stop_id="b",
                destination_stop_id="dep",
            ),
        ],
        turnaround_rules={
            "dep": TurnaroundRule(stop_id="dep", min_turnaround_min=5),
            "a": TurnaroundRule(stop_id="a", min_turnaround_min=5),
            "b": TurnaroundRule(stop_id="b", min_turnaround_min=5),
        },
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(vehicle_type="BEV", battery_capacity_kwh=300.0, energy_consumption_kwh_per_km=1.0),
            "ICE": VehicleProfile(vehicle_type="ICE", fuel_tank_capacity_l=200.0, fuel_consumption_l_per_km=0.4),
        },
        location_aliases={"dep-1": ("dep",), "dep-2": ("dep",)},
    )


def test_build_baseline_plan_uses_pooled_shared_path_cover_when_scope_is_fully_shared(monkeypatch: pytest.MonkeyPatch) -> None:
    context = _shared_context()
    vehicles = (
        ProblemVehicle(vehicle_id="ice-1", vehicle_type="ICE", home_depot_id="dep-1"),
        ProblemVehicle(vehicle_id="bev-1", vehicle_type="BEV", home_depot_id="dep-2"),
    )
    feasible_connections = {
        "t1": ("t3",),
        "t2": ("t4",),
        "t3": (),
        "t4": (),
    }

    def _unexpected_dispatch_call(*args, **kwargs):
        raise AssertionError("per-type dispatch fallback should not be used for fully shared pooled baseline")

    monkeypatch.setattr(
        "src.optimization.common.builder.DispatchGenerator.generate_greedy_duties",
        _unexpected_dispatch_call,
    )

    plan = ProblemBuilder()._build_baseline_plan(
        context,
        vehicles=vehicles,
        max_fragments_per_vehicle=1,
        all_trip_ids={"t1", "t2", "t3", "t4"},
        feasible_connections=feasible_connections,
    )

    assert plan.metadata["source"] == "dispatch_pooled_shared_path_cover_baseline"
    assert plan.unserved_trip_ids == ()
    assert set(plan.served_trip_ids) == {"t1", "t2", "t3", "t4"}
    assert {duty.duty_id for duty in plan.duties} == {"ice-1", "bev-1"}
