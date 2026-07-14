from __future__ import annotations

import pytest

from src.dispatch.models import DeadheadRule, DispatchContext, Trip, VehicleProfile
from src.gurobi_runtime import is_gurobi_available
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import OptimizationConfig, OptimizationMode
from src.optimization.milp.engine import MILPOptimizer
from src.optimization.milp.solver_adapter import GurobiMILPAdapter


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_milp_fragment_pairwise_reset_cut_blocks_impossible_two_fragment_reuse() -> None:
    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
            Trip(
                trip_id="t2",
                route_id="r1",
                origin="C",
                destination="D",
                departure_time="08:30",
                arrival_time="08:40",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
        ],
        turnaround_rules={},
        deadhead_rules={
            ("DEPOT", "A"): DeadheadRule("DEPOT", "A", 5),
            ("DEPOT", "C"): DeadheadRule("DEPOT", "C", 5),
        },
        vehicle_profiles={"ICE": VehicleProfile(vehicle_type="ICE")},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="milp-reset-cut",
        vehicle_counts={"ICE": 1},
        canonical_depot_id="DEPOT",
        allow_same_day_depot_cycles=True,
        max_depot_cycles_per_vehicle_per_day=2,
        max_fragments_per_vehicle_per_day=2,
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=2,
        service_coverage_mode="strict",
    )

    result = MILPOptimizer().solve(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, time_limit_sec=10),
    )

    assert result.feasible is False
    assert result.plan.unserved_trip_ids == ("t1", "t2")


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_milp_blocks_nested_fragments_inside_selected_connection_span() -> None:
    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                route_family_code="band-1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
            Trip(
                trip_id="t2",
                route_id="r2",
                route_family_code="band-2",
                origin="C",
                destination="D",
                departure_time="08:30",
                arrival_time="08:40",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
            Trip(
                trip_id="t3",
                route_id="r1",
                route_family_code="band-1",
                origin="E",
                destination="F",
                departure_time="09:00",
                arrival_time="09:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
        ],
        turnaround_rules={},
        deadhead_rules={
            ("DEPOT", "A"): DeadheadRule("DEPOT", "A", 5),
            ("DEPOT", "C"): DeadheadRule("DEPOT", "C", 5),
            ("DEPOT", "E"): DeadheadRule("DEPOT", "E", 5),
            ("B", "E"): DeadheadRule("B", "E", 5),
            ("B", "DEPOT"): DeadheadRule("B", "DEPOT", 5),
            ("D", "DEPOT"): DeadheadRule("D", "DEPOT", 5),
            ("F", "DEPOT"): DeadheadRule("F", "DEPOT", 5),
        },
        vehicle_profiles={"ICE": VehicleProfile(vehicle_type="ICE")},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="nested-fragment-cut",
        vehicle_counts={"ICE": 1},
        canonical_depot_id="DEPOT",
        allow_same_day_depot_cycles=True,
        max_depot_cycles_per_vehicle_per_day=2,
        max_fragments_per_vehicle_per_day=2,
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=2,
        fixed_route_band_mode=True,
        service_coverage_mode="strict",
    )

    result = MILPOptimizer().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            time_limit_sec=10,
            mip_gap=0.0,
            phase="phase3_two_stage",
        ),
    )

    assert result.feasible is False
    assert result.plan.unserved_trip_ids == ("t1", "t2", "t3")


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_fragment_reset_cuts_cache_diagnostic_but_keep_per_vehicle_cuts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache only the repeated diagnosis, never the vehicle-specific cut."""
    import gurobipy as gp
    from src.optimization.milp import solver_adapter as adapter_module

    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
            Trip(
                trip_id="t2",
                route_id="r1",
                origin="C",
                destination="D",
                departure_time="08:30",
                arrival_time="08:40",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
        ],
        turnaround_rules={},
        deadhead_rules={
            ("DEPOT", "A"): DeadheadRule("DEPOT", "A", 5),
            ("DEPOT", "C"): DeadheadRule("DEPOT", "C", 5),
        },
        vehicle_profiles={"ICE": VehicleProfile(vehicle_type="ICE")},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="cached-reset-cut",
        vehicle_counts={"ICE": 2},
        canonical_depot_id="DEPOT",
        service_coverage_mode="strict",
    )
    model = gp.Model("cached_reset_cut")
    model.Params.OutputFlag = 0
    vehicle_ids = tuple(vehicle.vehicle_id for vehicle in problem.vehicles)
    end_arc = {
        (vehicle_id, trip.trip_id): model.addVar(vtype=gp.GRB.BINARY)
        for vehicle_id in vehicle_ids
        for trip in problem.trips
    }
    start_arc = {
        (vehicle_id, trip.trip_id): model.addVar(vtype=gp.GRB.BINARY)
        for vehicle_id in vehicle_ids
        for trip in problem.trips
    }
    calls = 0
    original = adapter_module.fragment_transition_diagnostic

    def counted_diagnostic(*args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(adapter_module, "fragment_transition_diagnostic", counted_diagnostic)
    cut_count = GurobiMILPAdapter()._add_fragment_pairwise_depot_reset_cuts(
        model,
        trip_by_id=problem.trip_by_id(),
        vehicles=problem.vehicles,
        assignment_trip_ids_by_vehicle={
            vehicle_id: ["t1", "t2"] for vehicle_id in vehicle_ids
        },
        start_arc=start_arc,
        end_arc=end_arc,
        trip_day_index_by_trip_id={"t1": 0, "t2": 0},
        problem=problem,
        allow_same_day_depot_cycles=True,
        fixed_route_band_mode=False,
    )

    assert calls == 1
    assert cut_count == 2
