from dataclasses import replace

from src.dispatch.models import Trip
from src.optimization import OptimizationMode
from src.optimization.common.problem import OptimizationConfig, ProblemTrip
from src.optimization.milp.engine import MILPOptimizer
from test_weather_coupled_assignment import (
    _full_phase3_composition_counterexample,
)


def test_bev_frontier_uses_only_minimum_bev_constraint() -> None:
    result = MILPOptimizer().solve(
        _full_phase3_composition_counterexample(),
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase3_two_stage",
            research_run=True,
            time_limit_sec=60,
            stage1_time_limit_sec=40,
            stage2_time_limit_sec=20,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            stage1_best_obj_stop_enabled=False,
            stage1_stage2_candidate_limit=3,
            stage1_bev_frontier_enabled=True,
            stage1_bev_frontier_min_count=1,
            stage1_bev_frontier_max_count=2,
            stage1_bev_frontier_target_time_limit_sec=5.0,
            gurobi_threads=1,
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    frontier = dict(result.plan.metadata["bev_cost_frontier"])
    rows = list(frontier["rows"])
    certificate = dict(
        result.plan.metadata[
            "stage1_used_powertrain_composition_search"
        ]
    )

    assert frontier["constraint_semantics"].startswith(
        "sum(used_electric_vehicle) >= K"
    )
    assert frontier["frontier_total_used_vehicle_count_fixed"] is False
    assert certificate["frontier_total_used_vehicle_count_fixed"] is False
    assert all(
        record["target_used_ice"] is None
        for record in certificate["target_records"]
    )
    assert all(
        record["target_total_used_vehicle_count"] is None
        for record in certificate["target_records"]
    )
    assert [row["minimum_used_bev_count"] for row in rows] == [1, 2]
    target_two = next(
        record
        for record in certificate["target_records"]
        if record["target_used_bev"] == 2
    )
    assert target_two["partial_mip_start_applied"] is True
    assert target_two["partial_mip_start_replacement_count"] == 2
    assert len(target_two["partial_mip_start_source_vehicle_ids"]) == 2
    assert len(target_two["partial_mip_start_target_vehicle_ids"]) == 2
    assert (
        target_two["partial_mip_start_semantics"]
        == "one_or_more_unused_opposite_powertrain_activations_and_"
        "source_vehicle_retirements"
    )


def test_bev_frontier_can_increase_total_fleet_with_duty_splits() -> None:
    """High K receives a feasible start even when whole-duty swaps are invalid."""

    base = _full_phase3_composition_counterexample()
    trip_specs = (
        ("ice-a", "06:00", "07:00", 360, 420, ("ICE",)),
        ("ice-b", "06:30", "07:30", 390, 450, ("ICE",)),
        ("flex-a", "08:00", "09:00", 480, 540, ("BEV", "ICE")),
        ("flex-b", "08:30", "09:30", 510, 570, ("BEV", "ICE")),
    )
    dispatch_trips = [
        Trip(
            trip_id=trip_id,
            route_id="split-activation-route",
            origin="DEPOT",
            destination="DEPOT",
            departure_time=departure,
            arrival_time=arrival,
            distance_km=5.0,
            allowed_vehicle_types=allowed_vehicle_types,
            origin_stop_id="DEPOT",
            destination_stop_id="DEPOT",
        )
        for (
            trip_id,
            departure,
            arrival,
            _departure_min,
            _arrival_min,
            allowed_vehicle_types,
        ) in trip_specs
    ]
    problem_trips = tuple(
        ProblemTrip(
            trip_id=trip_id,
            route_id="split-activation-route",
            origin="DEPOT",
            destination="DEPOT",
            departure_min=departure_min,
            arrival_min=arrival_min,
            distance_km=5.0,
            energy_kwh=5.0,
            allowed_vehicle_types=allowed_vehicle_types,
        )
        for (
            trip_id,
            _departure,
            _arrival,
            departure_min,
            arrival_min,
            allowed_vehicle_types,
        ) in trip_specs
    )
    problem = replace(
        base,
        dispatch_context=replace(
            base.dispatch_context,
            trips=dispatch_trips,
        ),
        trips=problem_trips,
        feasible_connections={
            "ice-a": ("flex-a", "flex-b"),
            "ice-b": ("flex-a", "flex-b"),
            "flex-a": (),
            "flex-b": (),
        },
        metadata={
            **dict(base.metadata),
            "fixed_route_band_mode": False,
            "vehicle_usage_cost_jpy_per_used_bus": 1_000.0,
            "vehicle_usage_cost_semantics": "provisional_sensitivity",
        },
    )

    result = MILPOptimizer().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase3_two_stage",
            research_run=True,
            time_limit_sec=60,
            stage1_time_limit_sec=40,
            stage2_time_limit_sec=20,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            stage1_best_obj_stop_enabled=False,
            stage1_stage2_candidate_limit=3,
            stage1_bev_frontier_enabled=True,
            stage1_bev_frontier_min_count=2,
            stage1_bev_frontier_max_count=2,
            stage1_bev_frontier_target_time_limit_sec=10.0,
            gurobi_threads=1,
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    certificate = dict(
        result.plan.metadata["stage1_used_powertrain_composition_search"]
    )
    target = certificate["target_records"][0]
    primary = certificate["primary_used_powertrain_composition"]
    assert primary == {"used_bev": 1, "used_ice": 2}
    assert target["solution_count"] >= 1
    assert target["actual_used_bev"] == 2
    assert target["actual_used_ice"] == 2
    assert target["partial_mip_start_applied"] is True, {
        "primary": certificate["primary_used_powertrain_composition"],
        "start_counts": result.plan.metadata[
            "stage1_composition_activation_mip_start_counts"
        ],
        "target": target,
    }
    assert (
        target["partial_mip_start_mode"]
        == "unused_bev_duty_suffix_split_activation"
    )
    assert target["partial_mip_start_replacement_count"] == 0
    assert target["partial_mip_start_split_activation_count"] == 1
    assert target["partial_mip_start_activation_count"] == 1
    assert len(target["partial_mip_start_split_trip_ids"]) == 1
