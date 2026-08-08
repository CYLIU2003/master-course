from dataclasses import replace

from src.dispatch.models import Trip
from src.optimization import OptimizationMode
from src.optimization.common.problem import OptimizationConfig, ProblemTrip
from src.optimization.milp.engine import MILPOptimizer
from src.optimization.milp.solver_adapter import (
    select_bev_frontier_feasibility_witness,
)
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
    assert result.plan.metadata["stage1_bev_frontier_enabled"] is True
    assert result.solver_metadata["stage1_bev_frontier_enabled"] is True
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
    assert all(
        int(row["actual_used_bev"])
        >= int(row["minimum_used_bev_count"])
        for row in rows
    )
    assert all(
        row["frontier_resolution_source"]
        in {
            "direct_target_candidate",
            "nested_higher_used_bev_candidate",
        }
        for row in rows
    )
    target_two = next(
        record
        for record in certificate["target_records"]
        if record["target_used_bev"] == 2
    )
    target_one = next(
        record
        for record in certificate["target_records"]
        if record["target_used_bev"] == 1
    )
    symmetry_groups = result.plan.metadata[
        "stage1_identical_vehicle_groups"
    ]
    bev_group = next(
        group for group in symmetry_groups if group[0].startswith("bev-")
    )
    ice_group = next(
        group for group in symmetry_groups if group[0].startswith("ice-")
    )
    assert target_one[
        "partial_mip_start_symmetry_prefix_normalized"
    ] is True
    target_one_remap = target_one[
        "partial_mip_start_symmetry_prefix_vehicle_id_remap"
    ]
    assert set(target_one_remap).issubset(set(ice_group) | set(bev_group))
    assert set(target_one_remap.values()).issubset(
        set(ice_group) | set(bev_group)
    )
    assert set(target_two["partial_mip_start_source_vehicle_ids"]) == set(
        ice_group
    )
    assert set(target_two["partial_mip_start_target_vehicle_ids"]) == set(
        bev_group
    )
    assert target_two["partial_mip_start_applied"] is True
    assert isinstance(
        target_two["partial_mip_start_symmetry_prefix_normalized"],
        bool,
    )
    assert target_two["partial_mip_start_replacement_count"] == 2
    assert target_two["frontier_resolution_candidate_hash"]
    assert (
        int(target_two["frontier_resolution_actual_used_bev"])
        >= int(target_two["minimum_used_bev_count"])
    )
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


def test_bev_frontier_uses_higher_k_physical_witness_for_nested_target() -> None:
    """A feasible K+2 candidate also resolves lower-bound targets K and K+1."""

    candidates = [
        {
            "candidate_hash": "target-k-physical-failure",
            "used_bev": 26,
            "used_ice": 6,
            "stage2_actual_canonical_cost_jpy": 729_854.0,
            "feasible": False,
        },
        {
            "candidate_hash": "higher-k-physical-witness",
            "used_bev": 28,
            "used_ice": 19,
            "stage2_actual_canonical_cost_jpy": 1_027_758.0,
            "feasible": True,
        },
        {
            "candidate_hash": "higher-k-more-expensive",
            "used_bev": 29,
            "used_ice": 19,
            "stage2_actual_canonical_cost_jpy": 1_048_000.0,
            "feasible": True,
        },
    ]

    witness_k26 = select_bev_frontier_feasibility_witness(26, candidates)
    witness_k27 = select_bev_frontier_feasibility_witness(27, candidates)
    witness_k29 = select_bev_frontier_feasibility_witness(29, candidates)
    no_witness_k30 = select_bev_frontier_feasibility_witness(30, candidates)

    assert witness_k26 is not None
    assert witness_k27 is not None
    assert witness_k29 is not None
    assert witness_k26["candidate_hash"] == "higher-k-physical-witness"
    assert witness_k27["candidate_hash"] == "higher-k-physical-witness"
    assert witness_k29["candidate_hash"] == "higher-k-more-expensive"
    assert no_witness_k30 is None


def test_bev_frontier_witness_forms_lowest_cost_candidate_pool_envelope() -> None:
    """Nested rows select the lowest-cost feasible evaluated higher-K plan."""

    candidates = [
        {
            "candidate_hash": "direct-k15",
            "used_bev": 15,
            "stage2_actual_canonical_cost_jpy": 706_897.0,
            "feasible": True,
        },
        {
            "candidate_hash": "higher-k17-cheaper",
            "used_bev": 17,
            "stage2_actual_canonical_cost_jpy": 706_175.0,
            "feasible": True,
        },
    ]

    witness = select_bev_frontier_feasibility_witness(15, candidates)

    assert witness is not None
    assert witness["candidate_hash"] == "higher-k17-cheaper"
