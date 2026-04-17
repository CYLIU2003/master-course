from __future__ import annotations

from src.dispatch.models import DeadheadRule, DispatchContext, Trip, VehicleProfile
from src.optimization.common.builder import ProblemBuilder


def _scenario() -> dict:
    return {
        "meta": {"id": "builder-wiring"},
        "simulation_config": {
            "allow_same_day_depot_cycles": True,
            "max_depot_cycles_per_vehicle_per_day": 3,
            "service_coverage_mode": "strict",
        },
        "scenario_overlay": {
            "solver_config": {},
            "charging_constraints": {},
            "cost_coefficients": {},
        },
        "depots": [{"id": "dep-1", "name": "Depot 1"}],
        "routes": [{"id": "r1", "route_id": "r1"}],
        "vehicles": [
            {
                "id": "veh-1",
                "depotId": "dep-1",
                "type": "ICE",
            }
        ],
        "timetable_rows": [
            {
                "trip_id": "t1",
                "route_id": "r1",
                "origin": "A",
                "destination": "B",
                "departure": "08:00",
                "arrival": "08:30",
                "distance_km": 10.0,
                "service_id": "WEEKDAY",
                "allowed_vehicle_types": ["ICE"],
            }
        ],
        "deadhead_rules": [],
        "turnaround_rules": [],
    }


def test_builder_wires_same_day_coverage_and_band_defaults() -> None:
    problem = ProblemBuilder().build_from_scenario(
        _scenario(),
        depot_id="dep-1",
        service_id="WEEKDAY",
        planning_days=1,
    )

    assert problem.metadata["daily_fragment_limit"] >= 2
    assert problem.metadata["service_coverage_mode"] == "strict"
    assert problem.metadata["allow_partial_service"] is False
    assert problem.metadata["fixed_route_band_mode"] is False


def test_builder_prefers_explicit_service_coverage_mode_over_allow_partial_service() -> None:
    scenario = _scenario()
    scenario["simulation_config"] = {
        **scenario["simulation_config"],
        "service_coverage_mode": "strict",
        "allow_partial_service": True,
    }

    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id="dep-1",
        service_id="WEEKDAY",
        planning_days=1,
    )

    assert problem.metadata["service_coverage_mode"] == "strict"
    assert problem.metadata["allow_partial_service"] is False


def test_builder_falls_back_to_allow_partial_service_when_coverage_mode_is_missing() -> None:
    scenario = _scenario()
    scenario["simulation_config"] = {
        key: value
        for key, value in scenario["simulation_config"].items()
        if key != "service_coverage_mode"
    }
    scenario["simulation_config"]["allow_partial_service"] = True

    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id="dep-1",
        service_id="WEEKDAY",
        planning_days=1,
    )

    assert problem.metadata["service_coverage_mode"] == "penalized"
    assert problem.metadata["allow_partial_service"] is True


def test_builder_forces_fixed_route_band_when_intra_depot_swap_is_disabled() -> None:
    scenario = _scenario()
    scenario["dispatch_scope"] = {"allowIntraDepotRouteSwap": False}
    scenario["simulation_config"] = {
        **scenario["simulation_config"],
        "fixed_route_band_mode": False,
    }

    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id="dep-1",
        service_id="WEEKDAY",
        planning_days=1,
    )

    assert problem.metadata["fixed_route_band_mode"] is True
    assert problem.metadata["fixed_route_band_mode_requested"] is False
    assert problem.metadata["fixed_route_band_mode_forced_by_scope_swap_lock"] is True


def test_weighted_path_cover_prefers_lower_deadhead_matching() -> None:
    context = DispatchContext(
        service_date="WEEKDAY",
        trips=[
            Trip("a", "r", "A", "B", "08:00", "08:20", 1.0, ("BEV",)),
            Trip("b", "r", "C", "D", "08:30", "09:00", 1.0, ("BEV",)),
            Trip("c", "r", "E", "F", "08:35", "09:05", 1.0, ("BEV",)),
        ],
        turnaround_rules={},
        deadhead_rules={
            ("B", "C"): DeadheadRule("B", "C", 9),
            ("B", "E"): DeadheadRule("B", "E", 1),
        },
        vehicle_profiles={"BEV": VehicleProfile("BEV")},
    )
    trip_map = context.trips_by_id()

    pair_left, _pair_right, _cost = ProblemBuilder()._minimum_cost_maximum_matching(
        {"a": ("b", "c"), "b": (), "c": ()},
        trip_map=trip_map,
        context=context,
    )

    assert pair_left["a"] == "c"


def test_builder_aliases_same_named_stop_ids_for_direct_waits() -> None:
    scenario = _scenario()
    scenario["routes"] = [
        {"id": "r-out", "route_id": "r-out", "routeFamilyCode": "FAM1"},
        {"id": "r-in", "route_id": "r-in", "routeFamilyCode": "FAM1"},
    ]
    scenario["timetable_rows"] = [
        {
            "trip_id": "t1",
            "route_id": "r-out",
            "origin": "Depot",
            "destination": "Terminal",
            "origin_stop_id": "stop-depot",
            "destination_stop_id": "stop-term-out",
            "departure": "08:00",
            "arrival": "08:30",
            "distance_km": 10.0,
            "service_id": "WEEKDAY",
            "allowed_vehicle_types": ["ICE"],
            "routeFamilyCode": "FAM1",
            "direction": "outbound",
            "routeVariantType": "main_outbound",
        },
        {
            "trip_id": "t2",
            "route_id": "r-in",
            "origin": "Terminal",
            "destination": "Depot",
            "origin_stop_id": "stop-term-in",
            "destination_stop_id": "stop-depot",
            "departure": "08:40",
            "arrival": "09:10",
            "distance_km": 10.0,
            "service_id": "WEEKDAY",
            "allowed_vehicle_types": ["ICE"],
            "routeFamilyCode": "FAM1",
            "direction": "inbound",
            "routeVariantType": "main_inbound",
        },
    ]
    scenario["stops"] = [
        {"id": "stop-depot", "name": "Depot"},
        {"id": "stop-term-out", "name": "Terminal"},
        {"id": "stop-term-in", "name": "Terminal"},
    ]
    scenario["turnaround_rules"] = [
        {"stop_id": "stop-term-out", "min_turnaround_min": 5},
        {"stop_id": "stop-term-in", "min_turnaround_min": 5},
        {"stop_id": "stop-depot", "min_turnaround_min": 5},
    ]

    problem = ProblemBuilder().build_from_scenario(
        scenario,
        depot_id="dep-1",
        service_id="WEEKDAY",
        planning_days=1,
    )

    assert problem.dispatch_context.locations_equivalent("stop-term-out", "stop-term-in") is True
    assert problem.dispatch_context.get_deadhead_min("stop-term-out", "stop-term-in") == 0
