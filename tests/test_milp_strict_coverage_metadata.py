from __future__ import annotations

from dataclasses import replace

import pytest

from src.dispatch.models import (
    DeadheadRule,
    DispatchContext,
    Trip,
    TurnaroundRule,
    VehicleProfile,
)
from src.gurobi_runtime import is_gurobi_available
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import (
    OptimizationConfig,
    OptimizationMode,
    ProblemTrip,
)
from src.optimization.milp.engine import MILPOptimizer
from src.optimization.milp.solver_adapter import (
    _best_objective_stop_from_certified_lower_bound,
    _configured_gurobi_feasibility_tol,
    _configured_gurobi_integrality_tol,
    _configured_gurobi_threads,
    _has_exact_mip_optimality_certificate,
    _single_path_flow_implies_temporal_exclusivity,
    _stage1_termination_reason,
)
from src.optimization.engine import OptimizationEngine


def test_exact_mip_optimality_requires_zero_certified_gap() -> None:
    assert _has_exact_mip_optimality_certificate("optimal", 0.0) is True
    assert _has_exact_mip_optimality_certificate("optimal", 1.0e-9) is True
    assert _has_exact_mip_optimality_certificate("optimal", 0.0475) is False
    assert _has_exact_mip_optimality_certificate("objective_limit", 0.0) is False
    assert _has_exact_mip_optimality_certificate("optimal", None) is False


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_milp_strict_coverage_metadata_is_exported() -> None:
    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="DEPOT",
                destination="A",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            )
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={"ICE": VehicleProfile(vehicle_type="ICE")},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="milp-metadata",
        vehicle_counts={"ICE": 1},
        canonical_depot_id="DEPOT",
        service_coverage_mode="strict",
    )

    result = MILPOptimizer().solve(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, time_limit_sec=10),
    )

    assert result.solver_metadata["service_coverage_mode"] == "strict"
    assert result.solver_metadata["allow_partial_service"] is False
    assert result.solver_metadata["strict_coverage_enforced"] is True


def test_certified_lower_bound_converts_to_positive_objective_stop() -> None:
    assert _best_objective_stop_from_certified_lower_bound(
        640_000.0,
        0.1,
    ) == pytest.approx(711_111.1111111111)
    assert _best_objective_stop_from_certified_lower_bound(-1.0, 0.1) is None
    assert _best_objective_stop_from_certified_lower_bound(1.0, 1.0) is None


def test_stage1_termination_reason_keeps_best_obj_stop_distinct_from_time_limit() -> None:
    assert _stage1_termination_reason(
        solver_status="objective_limit",
        best_obj_stop_applied=True,
    ) == "best_obj_stop"
    assert _stage1_termination_reason(
        solver_status="objective_limit",
        best_obj_stop_applied=False,
    ) == "objective_limit"
    assert _stage1_termination_reason(
        solver_status="time_limit",
        best_obj_stop_applied=False,
    ) == "time_limit"


def test_explicit_gurobi_threads_must_be_positive() -> None:
    assert _configured_gurobi_threads(OptimizationConfig(gurobi_threads=1)) == 1
    with pytest.raises(ValueError, match="positive integer"):
        _configured_gurobi_threads(OptimizationConfig(gurobi_threads=0))


def test_gurobi_feasibility_tolerances_are_stage_specific_and_validated() -> None:
    config = OptimizationConfig()
    assert _configured_gurobi_feasibility_tol(
        config, stage=1
    ) == pytest.approx(1.0e-6)
    assert _configured_gurobi_feasibility_tol(
        config, stage=2
    ) == pytest.approx(1.0e-9)

    with pytest.raises(ValueError, match=r"\[1e-9, 1e-2\]"):
        _configured_gurobi_feasibility_tol(
            OptimizationConfig(stage2_gurobi_feasibility_tol=1.0e-10),
            stage=2,
        )


def test_stage2_gurobi_integrality_tolerance_is_strict_and_validated() -> None:
    assert _configured_gurobi_integrality_tol(
        OptimizationConfig(),
        stage=2,
    ) == pytest.approx(1.0e-9)

    with pytest.raises(ValueError, match=r"\[1e-9, 1e-1\]"):
        _configured_gurobi_integrality_tol(
            OptimizationConfig(stage2_gurobi_integrality_tol=1.0e-10),
            stage=2,
        )
    with pytest.raises(ValueError, match="stage must be 2"):
        _configured_gurobi_integrality_tol(
            OptimizationConfig(),
            stage=1,
        )


def test_single_path_redundancy_requires_strictly_forward_arcs() -> None:
    trip_by_id = {
        "t1": ProblemTrip(
            trip_id="t1",
            route_id="r",
            origin="A",
            destination="B",
            departure_min=480,
            arrival_min=490,
            distance_km=1.0,
            allowed_vehicle_types=("ICE",),
        ),
        "t2": ProblemTrip(
            trip_id="t2",
            route_id="r",
            origin="B",
            destination="C",
            departure_min=500,
            arrival_min=510,
            distance_km=1.0,
            allowed_vehicle_types=("ICE",),
        ),
        "same": ProblemTrip(
            trip_id="same",
            route_id="r",
            origin="B",
            destination="C",
            departure_min=480,
            arrival_min=490,
            distance_km=1.0,
            allowed_vehicle_types=("ICE",),
        ),
    }
    assert _single_path_flow_implies_temporal_exclusivity(
        max_start_fragments_per_vehicle=1,
        max_end_fragments_per_vehicle=1,
        arc_pairs=(("v", "t1", "t2"),),
        trip_by_id=trip_by_id,
    ) is True
    assert _single_path_flow_implies_temporal_exclusivity(
        max_start_fragments_per_vehicle=2,
        max_end_fragments_per_vehicle=1,
        arc_pairs=(("v", "t1", "t2"),),
        trip_by_id=trip_by_id,
    ) is False
    assert _single_path_flow_implies_temporal_exclusivity(
        max_start_fragments_per_vehicle=1,
        max_end_fragments_per_vehicle=1,
        arc_pairs=(("v", "t1", "same"),),
        trip_by_id=trip_by_id,
    ) is False


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_stage1_path_cover_lower_bound_reaches_vehicle_day_cost_bound() -> None:
    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id=trip_id,
                route_id="r1",
                origin="DEPOT",
                destination=destination,
                departure_time="08:00",
                arrival_time="08:30",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            )
            for trip_id, destination in (("t1", "A"), ("t2", "B"))
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={"ICE": VehicleProfile(vehicle_type="ICE")},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="stage1-lower-bound",
        vehicle_counts={"ICE": 2},
        canonical_depot_id="DEPOT",
        service_coverage_mode="strict",
    )
    problem = replace(
        problem,
        metadata={
            **dict(problem.metadata or {}),
            "vehicle_usage_cost_jpy_per_used_bus": 20_000.0,
            "cost_component_flags": {
                "vehicle_usage_cost": True,
                # Isolate the path-cover vehicle-day certificate. Phase 3 now
                # includes enabled driver cost in the Stage 1 objective.
                "driver_cost": False,
            },
        },
    )

    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase2_assignment_only",
            time_limit_sec=10,
            mip_gap=0.0,
        ),
    )

    assert result.solver_metadata["stage1_vehicle_count_lower_bound"] == 2
    assert result.solver_metadata[
        "stage1_vehicle_count_lower_bound_constraint_count"
    ] == 1
    assert result.solver_metadata["stage1_best_bound"] == pytest.approx(40_000.0)
    assert result.solver_metadata[
        "stage1_analytical_objective_lower_bound"
    ] == pytest.approx(40_000.0)
    assert result.solver_metadata[
        "stage1_analytical_objective_lower_bound_semantics"
    ] == (
        "sum_of_strict_path_cover_vehicle_usage_cost_floor_"
        "and_optimistic_weather_energy_fuel_cost_floor"
    )
    assert result.solver_metadata[
        "stage1_vehicle_usage_analytical_lower_bound"
    ] == pytest.approx(40_000.0)
    assert result.solver_metadata[
        "stage1_analytical_weather_energy_fuel_lower_bound"
    ] == pytest.approx(0.0)
    assert (
        result.solver_metadata[
            "stage1_analytical_total_objective_certificate_eligible"
        ]
        is True
    )


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_stage1_exact_bev_activation_count_policy_is_enforced() -> None:
    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id=trip_id,
                route_id="r1",
                origin="DEPOT",
                destination=destination,
                departure_time="08:00",
                arrival_time="08:30",
                distance_km=1.0,
                allowed_vehicle_types=("BEV",),
            )
            for trip_id, destination in (("t1", "A"), ("t2", "B"))
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.0,
            )
        },
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="stage1-exact-bev-activation-count",
        vehicle_counts={"BEV": 3},
        canonical_depot_id="DEPOT",
        service_coverage_mode="strict",
    )
    unmarked_problem = replace(
        problem,
        metadata={
            **dict(problem.metadata or {}),
            "minimum_used_bev_count": 2,
            "phase4_seed_route_band_repartition_"
            "maximum_used_vehicle_count": 2,
        },
    )
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        phase="phase2_assignment_only",
        time_limit_sec=10,
        mip_gap=0.0,
    )
    with pytest.raises(
        ValueError,
        match="only for an explicit Phase-4 seed candidate",
    ):
        OptimizationEngine().solve(unmarked_problem, config)

    problem = replace(
        unmarked_problem,
        metadata={
            **dict(unmarked_problem.metadata or {}),
            "phase4_seed_route_band_repartition_candidate": True,
        },
    )

    result = OptimizationEngine().solve(
        problem,
        config,
    )

    assert result.feasible is True
    assert len(result.plan.duties_by_vehicle()) == 2
    assert result.plan.metadata["minimum_used_bev_count"] == 2
    assert result.plan.metadata[
        "phase4_seed_route_band_repartition_maximum_used_vehicle_count"
    ] == 2
    assert result.plan.metadata[
        "phase4_seed_route_band_repartition_"
        "maximum_used_vehicle_count_policy_enabled"
    ] is True


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_stage1_omits_arc_links_implied_by_node_flow_equalities() -> None:
    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="DEPOT",
                destination="A",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
            Trip(
                trip_id="t2",
                route_id="r1",
                origin="A",
                destination="DEPOT",
                departure_time="08:20",
                arrival_time="08:30",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
        ],
        turnaround_rules={"A": TurnaroundRule(stop_id="A", min_turnaround_min=0)},
        deadhead_rules={},
        vehicle_profiles={"ICE": VehicleProfile(vehicle_type="ICE")},
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="stage1-redundant-arc-links",
        vehicle_counts={"ICE": 1},
        canonical_depot_id="DEPOT",
        service_coverage_mode="strict",
    )

    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase2_assignment_only",
            time_limit_sec=10,
            mip_gap=0.0,
        ),
    )

    assert result.feasible is True
    assert set(result.plan.served_trip_ids) == {"t1", "t2"}
    assert result.solver_metadata[
        "stage1_redundant_arc_link_constraints_omitted"
    ] == 2
    assert result.solver_metadata["stage1_model_variable_count"] > 0
    assert result.solver_metadata["stage1_model_constraint_count"] > 0
    assert result.solver_metadata["stage1_model_binary_variable_count"] >= 0
    assert result.solver_metadata["stage1_model_integer_variable_count"] >= 0
    assert result.solver_metadata["stage1_model_continuous_variable_count"] >= 0
    assert result.solver_metadata["stage1_model_nonzero_coefficient_count"] > 0
    assert result.solver_metadata["stage1_pre_optimize_seconds"] >= 0.0
    assert result.solver_metadata[
        "stage1_single_path_redundancy_elimination_applied"
    ] is True
    assert result.solver_metadata["assignment_solution_method"] == (
        "full_candidate_network_stage1_milp"
    )
    assert result.solver_metadata["assignment_global_optimality"] is (
        result.solver_metadata["stage1_solver_status"] == "optimal"
        and result.solver_metadata["stage1_mip_gap_ratio"] <= 1.0e-8
    )
    assert result.solver_metadata["assignment_global_optimality_scope"] == (
        "full_candidate_network_stage1_assignment_objective"
    )


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_integrated_omits_arc_links_implied_by_node_flow_equalities() -> None:
    context = DispatchContext(
        service_date="2026-04-10",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="DEPOT",
                destination="A",
                departure_time="08:00",
                arrival_time="08:10",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
            Trip(
                trip_id="t2",
                route_id="r1",
                origin="B",
                destination="DEPOT",
                departure_time="08:20",
                arrival_time="08:30",
                distance_km=1.0,
                allowed_vehicle_types=("ICE",),
            ),
        ],
        turnaround_rules={"A": TurnaroundRule(stop_id="A", min_turnaround_min=0)},
        deadhead_rules={
            ("A", "B"): DeadheadRule(
                from_stop="A",
                to_stop="B",
                travel_time_min=5,
            )
        },
        vehicle_profiles={
            "ICE": VehicleProfile(
                vehicle_type="ICE",
                fuel_tank_capacity_l=300.0,
                fuel_consumption_l_per_km=0.2,
            )
        },
    )
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="integrated-redundant-arc-links",
        vehicle_counts={"ICE": 1},
        canonical_depot_id="DEPOT",
        service_coverage_mode="strict",
    )

    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            time_limit_sec=10,
            mip_gap=0.0,
            warm_start=False,
        ),
    )

    assert result.feasible is True
    assert set(result.plan.served_trip_ids) == {"t1", "t2"}
    assert result.solver_metadata[
        "integrated_redundant_arc_link_constraints_omitted"
    ] == 2
    assert result.solver_metadata[
        "integrated_activity_blocking_formulation"
    ] == "pairwise_strong_lp"
    assert result.solver_metadata[
        "integrated_activity_blocking_constraint_count"
    ] > 0
    assert result.solver_metadata[
        "integrated_redundant_endpoint_away_blocking_terms_omitted"
    ] == 1
    assert result.solver_metadata[
        "integrated_redundant_endpoint_away_blocking_semantics"
    ].startswith("lp_dominance_only")
