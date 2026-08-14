from dataclasses import replace
from types import SimpleNamespace

import pytest

import src.optimization.engine as optimization_engine_module
from src.dispatch.models import (
    DeadheadRule,
    DispatchContext,
    DutyLeg,
    Trip,
    VehicleDuty,
    VehicleProfile,
)
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    DepotEnergyAsset,
    OptimizationObjectiveWeights,
    OptimizationScenario,
    ChargerDefinition,
    OptimizationConfig,
    OptimizationMode,
    EnergyPriceSlot,
    ProblemVehicle,
)
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.seed_fingerprint import (
    phase4_seed_plan_fingerprint,
)
from src.optimization.engine import (
    OptimizationEngine,
    _phase4_seed_composition_search_limits,
    _phase4_seed_inventory_span_truncated,
    _phase4_seed_model_build_overhead_allowance_sec,
    _phase4_seed_stage2_iis_assignment_guidance,
    _phase4_seed_time_limit_with_shared_budget,
    actual_cost_objective_reconciles,
)
from src.gurobi_runtime import ensure_gurobi
from src.optimization.milp.model_builder import MILPModelBuilder
from src.optimization.milp.solver_adapter import (
    _add_assignment_pattern_no_good_cuts,
    _add_identical_vehicle_trip_count_symmetry,
    _apply_assignment_pattern_branch_priorities,
    _composition_target_continuation_priority_key,
    _composition_target_time_limit_sec,
    GurobiMILPAdapter,
    _actual_bess_terminal_soc_deviation_by_depot,
    _identical_vehicle_prefix_remap,
    _integrated_search_controls,
    _ordered_identical_vehicle_groups,
    _stage1_candidate_evaluation_priority_key,
    _verified_start_objective_search_bounds,
)
from test_post_return_soc_target import _dispatch_context


def test_phase4_seed_extracts_only_certified_iis_guidance_patterns() -> None:
    patterns = _phase4_seed_stage2_iis_assignment_guidance(
        [
            {
                "candidate_hash": "local-candidate",
                "stage2_solver_status": "infeasible",
                "iis_hash": "local-iis",
                "stage2_iis_assignment_cut_type": (
                    "vehicle_local_exact_assignment_pattern_no_good_cut"
                ),
                "stage2_iis_assignment_cut_scope": (
                    "vehicle_local_exact_assignment_pattern"
                ),
                "stage2_iis_assignment_cut_vehicle_ids": ["bev-1"],
                "vehicle_trip_assignments": [
                    {"vehicle_id": "bev-1", "trip_id": "trip-1"},
                    {"vehicle_id": "bev-1", "trip_id": "trip-2"},
                    {"vehicle_id": "bev-2", "trip_id": "trip-3"},
                ],
            },
            {
                "candidate_hash": "feasible-candidate",
                "stage2_solver_status": "optimal",
                "stage2_iis_assignment_cut_type": (
                    "full_assignment_no_good_cut"
                ),
                "vehicle_trip_assignments": [
                    {"vehicle_id": "bev-2", "trip_id": "trip-3"},
                ],
            },
        ]
    )

    assert patterns == (
        {
            "assignment_pairs": [
                ["bev-1", "trip-1"],
                ["bev-1", "trip-2"],
            ],
            "exact_pattern_vehicle_ids": ["bev-1"],
            "cut_type": (
                "vehicle_local_exact_assignment_pattern_no_good_cut"
            ),
            "cut_scope": "vehicle_local_exact_assignment_pattern",
            "source_candidate_hash": "local-candidate",
            "stage2_iis_hash": "local-iis",
        },
    )


def test_vehicle_local_iis_cut_forbids_only_the_exact_assignment_pattern() -> None:
    gp, GRB = ensure_gurobi()

    def solve_with_fixed_pattern(
        fixed_values: dict[tuple[str, str], int],
    ) -> tuple[int, dict[str, object]]:
        model = gp.Model("vehicle_local_exact_iis_cut_contract")
        model.Params.OutputFlag = 0
        assignment_vars = {
            ("bev-1", trip_id): model.addVar(
                vtype=GRB.BINARY,
                name=f"y_bev_1_{trip_id}",
            )
            for trip_id in ("trip-1", "trip-2", "trip-3")
        }
        audit = _add_assignment_pattern_no_good_cuts(
            model=model,
            gp=gp,
            assignment_vars=assignment_vars,
            raw_cuts=(
                {
                    "assignment_pairs": (
                        ("bev-1", "trip-1"),
                        ("bev-1", "trip-2"),
                    ),
                    "exact_pattern_vehicle_ids": ("bev-1",),
                    "source_candidate_hash": "candidate-a",
                },
            ),
            name_prefix="test_iis_cut",
        )
        for pair, value in fixed_values.items():
            model.addConstr(assignment_vars[pair] == value)
        model.setObjective(0.0, GRB.MINIMIZE)
        model.optimize()
        return int(model.Status), audit

    exact_status, exact_audit = solve_with_fixed_pattern(
        {
            ("bev-1", "trip-1"): 1,
            ("bev-1", "trip-2"): 1,
            ("bev-1", "trip-3"): 0,
        }
    )
    superset_status, superset_audit = solve_with_fixed_pattern(
        {
            ("bev-1", "trip-1"): 1,
            ("bev-1", "trip-2"): 1,
            ("bev-1", "trip-3"): 1,
        }
    )

    assert exact_status == GRB.INFEASIBLE
    assert superset_status == GRB.OPTIMAL
    assert exact_audit == superset_audit
    assert exact_audit["constraint_count"] == 1
    assert exact_audit["source_candidate_hashes"] == ("candidate-a",)
    assert "integer_feasible_set_unchanged" in exact_audit["semantics"]


def test_phase4_iis_guidance_is_non_directional_and_keeps_pattern_feasible() -> None:
    gp, GRB = ensure_gurobi()
    model = gp.Model("phase4_iis_nondirectional_guidance_contract")
    model.Params.OutputFlag = 0
    assignment_vars = {
        ("bev-1", trip_id): model.addVar(
            vtype=GRB.BINARY,
            name=f"y_bev_1_{trip_id}",
        )
        for trip_id in ("trip-1", "trip-2", "trip-3")
    }
    audit = _apply_assignment_pattern_branch_priorities(
        assignment_vars=assignment_vars,
        raw_patterns=(
            {
                "assignment_pairs": (
                    ("bev-1", "trip-1"),
                    ("bev-1", "trip-2"),
                ),
                "exact_pattern_vehicle_ids": ("bev-1",),
                "source_candidate_hash": "candidate-a",
            },
        ),
    )
    for pair, value in {
        ("bev-1", "trip-1"): 1,
        ("bev-1", "trip-2"): 1,
        ("bev-1", "trip-3"): 0,
    }.items():
        model.addConstr(assignment_vars[pair] == value)
    model.setObjective(0.0, GRB.MINIMIZE)
    model.optimize()

    assert model.Status == GRB.OPTIMAL
    assert assignment_vars[("bev-1", "trip-1")].BranchPriority == 1
    assert assignment_vars[("bev-1", "trip-2")].BranchPriority == 1
    assert assignment_vars[("bev-1", "trip-3")].BranchPriority == 0
    assert audit["pattern_count"] == 1
    assert audit["promoted_assignment_variable_count"] == 2
    assert "non_directional_branch_priority" in audit["semantics"]


def test_phase4_seed_keeps_full_assignment_cut_conservative() -> None:
    patterns = _phase4_seed_stage2_iis_assignment_guidance(
        [
            {
                "candidate_hash": "shared-candidate",
                "stage2_solver_status": "infeasible",
                "iis_hash": "shared-iis",
                "stage2_iis_assignment_cut_type": (
                    "full_assignment_no_good_cut"
                ),
                "stage2_iis_assignment_cut_scope": "full_assignment",
                "stage2_iis_assignment_cut_vehicle_ids": [],
                "vehicle_trip_assignments": [
                    {"vehicle_id": "bev-1", "trip_id": "trip-1"},
                    {"vehicle_id": "ice-1", "trip_id": "trip-2"},
                ],
            }
        ]
    )

    assert patterns[0]["assignment_pairs"] == [
        ["bev-1", "trip-1"],
        ["ice-1", "trip-2"],
    ]
    assert patterns[0]["exact_pattern_vehicle_ids"] == []


def test_verified_integrated_start_uses_bound_certification_profile() -> None:
    assert _integrated_search_controls(
        verified_feasible_start=True
    ) == {
        "profile": "certify_bound_from_verified_feasible_start",
        "mip_focus": 3,
        "heuristics": 0.01,
        "presolve": 1,
        "nodefile_start_gb": 0.5,
        "root_method": 1,
        "node_method": 1,
        "soft_mem_limit_gb": 32.0,
    }
    cold_start_controls = _integrated_search_controls(
        verified_feasible_start=False
    )
    assert cold_start_controls["profile"] == "find_feasible_solution_then_bound"
    assert cold_start_controls["nodefile_start_gb"] == 0.5
    assert cold_start_controls["root_method"] == 1
    assert cold_start_controls["node_method"] == 1
    assert cold_start_controls["soft_mem_limit_gb"] == 32.0


def test_verified_start_bounds_preserve_seed_and_limit_vehicle_days() -> None:
    bounds = _verified_start_objective_search_bounds(
        warm_start_audit={
            "integrated_dispatch_fixed_recourse_feasible": True,
            "dispatch_fixed_recourse_objective_value": 666_164.0,
        },
        analytical_floor_blockers=(),
        vehicle_usage_weight=1.0,
        vehicle_usage_unit_cost=20_000.0,
        feasibility_tolerance=1.0e-9,
    )

    assert bounds["eligible"] is True
    assert bounds["objective_upper_bound_jpy"] > 666_164.0
    assert bounds["vehicle_day_upper_bound"] == 33


def test_verified_start_vehicle_day_cap_blocks_negative_objective_terms() -> None:
    bounds = _verified_start_objective_search_bounds(
        warm_start_audit={
            "integrated_dispatch_fixed_recourse_feasible": True,
            "dispatch_fixed_recourse_objective_value": 666_164.0,
        },
        analytical_floor_blockers=("negative_return_leg_bonus_term",),
        vehicle_usage_weight=1.0,
        vehicle_usage_unit_cost=20_000.0,
        feasibility_tolerance=1.0e-9,
    )

    assert bounds["eligible"] is True
    assert bounds["objective_upper_bound_jpy"] is not None
    assert bounds["vehicle_day_upper_bound"] is None


def test_verified_start_vehicle_day_cap_requires_enabled_cost_component() -> None:
    bounds = _verified_start_objective_search_bounds(
        warm_start_audit={
            "integrated_dispatch_fixed_recourse_feasible": True,
            "dispatch_fixed_recourse_objective_value": 666_164.0,
        },
        analytical_floor_blockers=(),
        vehicle_usage_weight=1.0,
        vehicle_usage_unit_cost=20_000.0,
        vehicle_usage_cost_enabled=False,
        feasibility_tolerance=1.0e-9,
    )

    assert bounds["eligible"] is True
    assert bounds["objective_upper_bound_jpy"] is not None
    assert bounds["vehicle_day_upper_bound"] is None
    assert bounds["blocking_reasons"] == [
        "positive_vehicle_day_cost_unavailable"
    ]


def test_verified_start_cap_does_not_change_ev_utilization_objective() -> None:
    bounds = _verified_start_objective_search_bounds(
        warm_start_audit={
            "integrated_dispatch_fixed_recourse_feasible": True,
            "dispatch_fixed_recourse_objective_value": 666_164.0,
        },
        analytical_floor_blockers=(),
        vehicle_usage_weight=1.0,
        vehicle_usage_unit_cost=20_000.0,
        feasibility_tolerance=1.0e-9,
        canonical_cost_is_primary_objective=False,
    )

    assert bounds["eligible"] is False
    assert bounds["objective_upper_bound_jpy"] is None
    assert bounds["vehicle_day_upper_bound"] is None
    assert bounds["blocking_reasons"] == [
        "canonical_cost_is_not_primary_objective"
    ]


def test_verified_start_bounds_can_use_certified_canonical_cost_field() -> None:
    bounds = _verified_start_objective_search_bounds(
        warm_start_audit={
            "integrated_dispatch_fixed_recourse_feasible": True,
            "dispatch_fixed_recourse_objective_value": 32.0,
            "dispatch_fixed_recourse_canonical_cost_jpy": 650_234.0,
        },
        analytical_floor_blockers=(),
        vehicle_usage_weight=1.0,
        vehicle_usage_unit_cost=20_000.0,
        feasibility_tolerance=1.0e-9,
        incumbent_objective_field=(
            "dispatch_fixed_recourse_canonical_cost_jpy"
        ),
    )

    assert bounds["eligible"] is True
    assert bounds["objective_upper_bound_jpy"] > 650_234.0
    assert bounds["vehicle_day_upper_bound"] == 32
    assert bounds["incumbent_objective_field"] == (
        "dispatch_fixed_recourse_canonical_cost_jpy"
    )


def test_exact_composition_targets_continue_outward_despite_cost_score() -> None:
    records = [
        {
            "target_within_selected_inventory": True,
            "target_used_bev": 32,
            "delta_used_bev_from_primary": 19,
            "requested_order_index": 5,
            "search_priority_lower_bound_jpy": 600_000.0,
            "search_priority_lower_bound_certified": True,
        },
        {
            "target_within_selected_inventory": True,
            "target_used_bev": 14,
            "delta_used_bev_from_primary": 1,
            "requested_order_index": 1,
            "search_priority_lower_bound_jpy": 710_000.0,
            "search_priority_lower_bound_certified": True,
        },
        {
            "target_within_selected_inventory": True,
            "target_used_bev": 12,
            "delta_used_bev_from_primary": -1,
            "requested_order_index": 2,
            "search_priority_lower_bound_jpy": 700_000.0,
            "search_priority_lower_bound_certified": True,
        },
        {
            "target_within_selected_inventory": True,
            "target_used_bev": 15,
            "delta_used_bev_from_primary": 2,
            "requested_order_index": 3,
            "search_priority_lower_bound_jpy": 690_000.0,
            "search_priority_lower_bound_certified": True,
        },
    ]

    continuation_ordered = sorted(
        records,
        key=_composition_target_continuation_priority_key,
    )

    assert [record["target_used_bev"] for record in continuation_ordered] == [
        14,
        12,
        15,
        32,
    ]


def test_adjacent_continuation_budget_is_shared_equally() -> None:
    continuation_seconds = _composition_target_time_limit_sec(
        remaining_budget_sec=300.0,
        remaining_target_count=25,
        target_time_limit_cap_sec=60.0,
    )

    assert continuation_seconds == pytest.approx(12.0)
    assert continuation_seconds * 25 == pytest.approx(300.0)


def test_phase4_seed_wall_allowance_preserves_stage2_solver_budget() -> None:
    assert _phase4_seed_model_build_overhead_allowance_sec(
        available_vehicle_count=60,
        candidate_limit=61,
    ) == 600
    assert _phase4_seed_model_build_overhead_allowance_sec(
        available_vehicle_count=2,
        candidate_limit=21,
    ) == 20
    assert _phase4_seed_model_build_overhead_allowance_sec(
        available_vehicle_count=60,
        candidate_limit=1,
    ) == 0


def test_phase4_seed_reserves_half_of_shared_budget_for_integrated_search() -> None:
    assert _phase4_seed_time_limit_with_shared_budget(
        requested_seed_time_limit_sec=600,
        total_time_limit_sec=600.0,
    ) == 300
    assert _phase4_seed_time_limit_with_shared_budget(
        requested_seed_time_limit_sec=100,
        total_time_limit_sec=600.0,
    ) == 100
    assert _phase4_seed_time_limit_with_shared_budget(
        requested_seed_time_limit_sec=60,
        total_time_limit_sec=30.0,
    ) == 15


def test_stage2_candidates_prioritize_weather_aware_relaxed_cost() -> None:
    candidates = [
        (1, 705_000.0, "primary", "primary_pool", AssignmentPlan()),
        (2, 666_000.0, "sunny-high-bev", "composition", AssignmentPlan()),
        (3, float("nan"), "invalid", "composition", AssignmentPlan()),
        (4, 666_000.0, "sunny-high-bev-b", "composition", AssignmentPlan()),
    ]

    ordered = sorted(
        candidates,
        key=_stage1_candidate_evaluation_priority_key,
    )

    assert [candidate[2] for candidate in ordered] == [
        "sunny-high-bev",
        "sunny-high-bev-b",
        "primary",
        "invalid",
    ]


def test_identical_vehicle_prefix_remap_preserves_duty_choice() -> None:
    remap = _identical_vehicle_prefix_remap(
        {"ice-b", "ice-c", "bev-a"},
        (("ice-a", "ice-b", "ice-c"), ("bev-a", "bev-b")),
    )

    assert remap == {"ice-c": "ice-a"}


def test_identical_vehicle_prefix_remap_orders_partial_start_by_trip_count() -> None:
    remap = _identical_vehicle_prefix_remap(
        {"ice-a", "ice-c"},
        (("ice-a", "ice-b", "ice-c"),),
        {
            ("ice-a", "trip-1"),
            ("ice-c", "trip-2"),
            ("ice-c", "trip-3"),
        },
    )

    assert remap == {"ice-c": "ice-a", "ice-a": "ice-b"}


def test_identical_vehicle_group_keeps_baseline_active_identifier_first() -> None:
    base = _phase4_seed_problem("identical-vehicle-symmetry")
    identical_a = ProblemVehicle(
        vehicle_id="ice-a",
        vehicle_type="ICE",
        home_depot_id="DEPOT",
        initial_fuel_l=100.0,
        fuel_tank_capacity_l=120.0,
        fuel_reserve_l=12.0,
        fuel_consumption_l_per_km=0.2,
    )
    identical_b = replace(identical_a, vehicle_id="ice-b")
    nonidentical = replace(
        identical_a,
        vehicle_id="ice-c",
        initial_fuel_l=90.0,
    )
    baseline = AssignmentPlan(
        duties=(VehicleDuty("duty-b", "ICE", ()),),
        metadata={"duty_vehicle_map": {"duty-b": "ice-b"}},
    )
    problem = replace(
        base,
        vehicles=(identical_a, identical_b, nonidentical),
        baseline_plan=baseline,
    )

    assert _ordered_identical_vehicle_groups(problem) == (
        ("ice-b", "ice-a"),
    )


def test_vehicle_group_does_not_ignore_distinct_initial_soc() -> None:
    base = _phase4_seed_problem("vehicle-symmetry-initial-soc")
    bev_a = replace(base.vehicles[0], vehicle_id="bev-a", initial_soc=0.4)
    bev_b = replace(base.vehicles[0], vehicle_id="bev-b", initial_soc=0.8)
    problem = replace(
        base,
        vehicles=(bev_a, bev_b),
        baseline_plan=None,
    )

    assert _ordered_identical_vehicle_groups(problem) == ()


def test_identical_vehicle_group_orders_active_warm_start_by_first_fragment() -> None:
    base = _phase4_seed_problem("identical-vehicle-start-order")
    early_dispatch_trip = replace(
        base.dispatch_context.trips[0],
        trip_id="trip-early",
        departure_time="08:00",
        arrival_time="09:00",
    )
    late_dispatch_trip = replace(
        base.dispatch_context.trips[0],
        trip_id="trip-late",
        departure_time="10:00",
        arrival_time="11:00",
    )
    early_trip = replace(
        base.trips[0],
        trip_id="trip-early",
        departure_min=8 * 60,
        arrival_min=9 * 60,
    )
    late_trip = replace(
        base.trips[0],
        trip_id="trip-late",
        departure_min=10 * 60,
        arrival_min=11 * 60,
    )
    identical_a = ProblemVehicle(
        vehicle_id="ice-a",
        vehicle_type="ICE",
        home_depot_id="DEPOT",
        initial_fuel_l=100.0,
        fuel_tank_capacity_l=120.0,
        fuel_reserve_l=12.0,
        fuel_consumption_l_per_km=0.2,
    )
    identical_b = replace(identical_a, vehicle_id="ice-b")
    baseline = AssignmentPlan(
        duties=(
            VehicleDuty("duty-a", "ICE", (DutyLeg(late_dispatch_trip),)),
            VehicleDuty("duty-b", "ICE", (DutyLeg(early_dispatch_trip),)),
        ),
        metadata={
            "duty_vehicle_map": {
                "duty-a": "ice-a",
                "duty-b": "ice-b",
            }
        },
    )
    problem = replace(
        base,
        trips=(late_trip, early_trip),
        vehicles=(identical_a, identical_b),
        baseline_plan=baseline,
    )

    assert _ordered_identical_vehicle_groups(problem) == (
        ("ice-b", "ice-a"),
    )


def test_identical_vehicle_group_prioritizes_warm_start_trip_count() -> None:
    base = _phase4_seed_problem("identical-vehicle-trip-count-order")
    dispatch_trips = tuple(
        replace(
            base.dispatch_context.trips[0],
            trip_id=f"trip-{index}",
            departure_time=f"{7 + index:02d}:00",
            arrival_time=f"{8 + index:02d}:00",
        )
        for index in range(1, 4)
    )
    problem_trips = tuple(
        replace(
            base.trips[0],
            trip_id=trip.trip_id,
            departure_min=(7 + index) * 60,
            arrival_min=(8 + index) * 60,
        )
        for index, trip in enumerate(dispatch_trips, start=1)
    )
    identical_a = ProblemVehicle(
        vehicle_id="ice-a",
        vehicle_type="ICE",
        home_depot_id="DEPOT",
        initial_fuel_l=100.0,
        fuel_tank_capacity_l=120.0,
        fuel_reserve_l=12.0,
        fuel_consumption_l_per_km=0.2,
    )
    identical_b = replace(identical_a, vehicle_id="ice-b")
    baseline = AssignmentPlan(
        duties=(
            VehicleDuty("duty-a", "ICE", (DutyLeg(dispatch_trips[0]),)),
            VehicleDuty(
                "duty-b",
                "ICE",
                (DutyLeg(dispatch_trips[1]), DutyLeg(dispatch_trips[2])),
            ),
        ),
        metadata={
            "duty_vehicle_map": {
                "duty-a": "ice-a",
                "duty-b": "ice-b",
            }
        },
    )
    problem = replace(
        base,
        trips=problem_trips,
        vehicles=(identical_a, identical_b),
        baseline_plan=baseline,
    )

    assert _ordered_identical_vehicle_groups(problem) == (("ice-b", "ice-a"),)


def test_trip_count_symmetry_keeps_one_exact_clone_orbit_representative() -> None:
    gp, GRB = ensure_gurobi()

    def solve(
        selected_starts: set[tuple[str, str]],
    ) -> tuple[int, dict[str, object]]:
        model = gp.Model("trip_count_symmetry")
        model.Params.OutputFlag = 0
        start_arc = {
            (vehicle_id, trip_id): model.addVar(
                vtype=GRB.BINARY,
                name=f"start_{vehicle_id}_{trip_id}",
            )
            for vehicle_id in ("vehicle-a", "vehicle-b")
            for trip_id in ("trip-1", "trip-2", "trip-3", "trip-4")
        }
        audit = _add_identical_vehicle_trip_count_symmetry(
            model=model,
            assignment_arc=start_arc,
            identical_vehicle_groups=(("vehicle-a", "vehicle-b"),),
            name_prefix="test_trip_count",
        )
        for key, variable in start_arc.items():
            model.addConstr(variable == (1 if key in selected_starts else 0))
        model.setObjective(0.0, GRB.MINIMIZE)
        model.optimize()
        return int(model.Status), audit

    canonical_status, audit = solve(
        {
            ("vehicle-a", "trip-1"),
            ("vehicle-a", "trip-2"),
            ("vehicle-a", "trip-4"),
            ("vehicle-b", "trip-3"),
        }
    )
    swapped_status, _ = solve(
        {
            ("vehicle-a", "trip-3"),
            ("vehicle-b", "trip-1"),
            ("vehicle-b", "trip-2"),
            ("vehicle-b", "trip-4"),
        }
    )

    assert canonical_status == GRB.OPTIMAL
    assert swapped_status == GRB.INFEASIBLE
    assert audit["integer_feasible_orbit_preserved"] is True
    assert audit["eligible_group_count"] == 1
    assert audit["transition_domain_check_mode"] == "not_present"
    assert audit["additional_variable_count"] == 0
    assert audit["ordering_constraint_count"] == 1
    assert "nonincreasing_total_assigned_trip_count" in audit["semantics"]


def test_trip_count_symmetry_skips_nonidentical_assignment_domains() -> None:
    gp, GRB = ensure_gurobi()
    model = gp.Model("trip_count_symmetry_domain_guard")
    model.Params.OutputFlag = 0
    start_arc = {
        ("vehicle-a", "trip-1"): model.addVar(vtype=GRB.BINARY),
        ("vehicle-a", "trip-2"): model.addVar(vtype=GRB.BINARY),
        ("vehicle-b", "trip-1"): model.addVar(vtype=GRB.BINARY),
    }

    audit = _add_identical_vehicle_trip_count_symmetry(
        model=model,
        assignment_arc=start_arc,
        identical_vehicle_groups=(("vehicle-a", "vehicle-b"),),
        name_prefix="test_domain_guard",
    )

    assert audit["enabled"] is False
    assert audit["eligible_group_count"] == 0
    assert audit["skipped_group_count"] == 1
    assert audit["groups"][0]["reason"] == "assignment_domain_mismatch"
    assert audit["additional_variable_count"] == 0
    assert audit["ordering_constraint_count"] == 0


def test_trip_count_symmetry_skips_nonidentical_transition_domains() -> None:
    gp, GRB = ensure_gurobi()
    model = gp.Model("trip_count_symmetry_transition_domain_guard")
    model.Params.OutputFlag = 0
    assignment_arc = {
        (vehicle_id, trip_id): model.addVar(vtype=GRB.BINARY)
        for vehicle_id in ("vehicle-a", "vehicle-b")
        for trip_id in ("trip-1", "trip-2")
    }
    transition_arc = {
        ("vehicle-a", "trip-1", "trip-2"): model.addVar(vtype=GRB.BINARY),
    }

    audit = _add_identical_vehicle_trip_count_symmetry(
        model=model,
        assignment_arc=assignment_arc,
        transition_arc=transition_arc,
        identical_vehicle_groups=(("vehicle-a", "vehicle-b"),),
        name_prefix="test_transition_domain_guard",
    )

    assert audit["enabled"] is False
    assert audit["skipped_group_count"] == 1
    assert audit["groups"][0]["reason"] == "transition_domain_mismatch"
    assert audit["groups"][0]["transition_domain_sizes"] == {
        "vehicle-a": 1,
        "vehicle-b": 0,
    }
    assert audit["ordering_constraint_count"] == 0


def test_trip_count_symmetry_full_scope_adds_only_adjacent_group_rows() -> None:
    gp, GRB = ensure_gurobi()
    model = gp.Model("trip_count_symmetry_full_scope_size")
    model.Params.OutputFlag = 0
    bev_ids = tuple(f"bev-{index:02d}" for index in range(35))
    ice_ids = tuple(f"ice-{index:02d}" for index in range(25))
    trip_ids = tuple(f"trip-{index:03d}" for index in range(264))
    assignment_arc = {
        (vehicle_id, trip_id): model.addVar(vtype=GRB.BINARY)
        for vehicle_id in bev_ids + ice_ids
        for trip_id in trip_ids
    }
    model.update()
    variable_count_before = int(model.NumVars)

    audit = _add_identical_vehicle_trip_count_symmetry(
        model=model,
        assignment_arc=assignment_arc,
        identical_vehicle_groups=(bev_ids, ice_ids),
        name_prefix="test_full_scope_trip_count",
    )
    model.update()

    assert audit["eligible_group_count"] == 2
    assert audit["ordering_constraint_count"] == 58
    assert audit["additional_variable_count"] == 0
    assert int(model.NumVars) == variable_count_before
    assert int(model.NumConstrs) == 58


def test_phase4_trip_count_symmetry_preserves_exact_objective() -> None:
    base = _phase4_seed_problem("phase4-trip-count-symmetry")
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        phase="phase4_integrated",
        integrated_actual_cost_objective=True,
        time_limit_sec=30,
        mip_gap=0.0,
        random_seed=42,
        warm_start=False,
        allow_postsolve_repair=False,
        research_run=True,
    )
    base_outcome, base_plan = GurobiMILPAdapter().solve(base, config)
    clone = replace(base.vehicles[0], vehicle_id="BEV_002")
    symmetric_problem = replace(
        base,
        vehicles=(base.vehicles[0], clone),
        baseline_plan=None,
    )

    symmetric_outcome, symmetric_plan = GurobiMILPAdapter().solve(
        symmetric_problem,
        config,
    )

    assert base_outcome.has_feasible_incumbent, base_outcome.solver_status
    assert symmetric_outcome.has_feasible_incumbent, symmetric_outcome.solver_status
    assert symmetric_plan.metadata["objective_value"] == pytest.approx(
        base_plan.metadata["objective_value"]
    )
    audit = symmetric_plan.metadata[
        "integrated_identical_vehicle_trip_count_symmetry"
    ]
    assert audit["enabled"] is True
    assert audit["integer_feasible_orbit_preserved"] is True
    assert audit["eligible_group_count"] == 1
    assert audit["transition_domain_check_mode"] == (
        "complete_successor_network_proof"
    )
    assert audit["additional_variable_count"] == 0
    assert audit["ordering_constraint_count"] == 1
    assert symmetric_plan.metadata[
        "integrated_identical_vehicle_trip_count_ordering_constraint_count"
    ] == 1


def _exact_ice_clone_audit(
    problem: CanonicalOptimizationProblem,
    *,
    assignment_pairs=None,
    arc_pairs=None,
):
    adapter = GurobiMILPAdapter()
    builder = MILPModelBuilder()
    effective_assignment_pairs = (
        builder.enumerate_assignment_pairs(problem)
        if assignment_pairs is None
        else assignment_pairs
    )
    effective_arc_pairs = (
        builder.enumerate_arc_pairs(problem, problem.trip_by_id())
        if arc_pairs is None
        else arc_pairs
    )
    dispatch_trip_by_id = problem.dispatch_context.trips_by_id()
    startup_prechecks = {
        (vehicle_id, trip_id): adapter._startup_energy_precheck(
            problem,
            next(
                vehicle
                for vehicle in problem.vehicles
                if vehicle.vehicle_id == vehicle_id
            ),
            problem.trip_by_id()[trip_id],
            dispatch_trip_by_id=dispatch_trip_by_id,
        )
        for vehicle_id, trip_id in effective_assignment_pairs
    }
    return adapter._exact_combustion_clone_flow_aggregation_audit(
        problem=problem,
        identical_vehicle_groups=_ordered_identical_vehicle_groups(problem),
        assignment_pairs=effective_assignment_pairs,
        arc_pairs=effective_arc_pairs,
        startup_energy_precheck_by_assignment=startup_prechecks,
        planning_days=1,
        daily_fragment_limit=1,
        max_start_fragments_per_vehicle=1,
        max_end_fragments_per_vehicle=1,
    )


def _exact_ice_clone_problem() -> CanonicalOptimizationProblem:
    base = _phase4_seed_problem("exact-ice-clone-flow-audit")
    ice_a = ProblemVehicle(
        vehicle_id="ICE_001",
        vehicle_type="ICE",
        home_depot_id="DEPOT",
        initial_fuel_l=100.0,
        fuel_tank_capacity_l=100.0,
        fuel_reserve_l=10.0,
        fuel_consumption_l_per_km=0.25,
    )
    ice_b = replace(ice_a, vehicle_id="ICE_002")
    return replace(
        base,
        dispatch_context=replace(
            base.dispatch_context,
            trips=tuple(
                replace(trip, allowed_vehicle_types=("ICE",))
                for trip in base.dispatch_context.trips
            ),
        ),
        trips=tuple(
            replace(trip, allowed_vehicle_types=("ICE",))
            for trip in base.trips
        ),
        vehicles=(ice_a, ice_b),
        baseline_plan=None,
    )


def test_exact_ice_clone_flow_audit_certifies_redundant_fuel_state() -> None:
    audit = _exact_ice_clone_audit(_exact_ice_clone_problem())

    assert audit["applied"] is False
    assert audit["integer_feasible_set_changed"] is False
    assert audit["certified_candidate_group_count"] == 1
    assert audit["potential_binary_variable_reduction"] == 3
    group = audit["groups"][0]
    assert group["certified_candidate"] is True
    assert group["finite_fuel_constraints_proved_redundant"] is True
    assert group["fuel_redundancy_margin_l"] >= 0.0
    assert group["longest_possible_duty_trip_ids"] == ("t1",)


def test_exact_ice_clone_flow_audit_rejects_assignment_domain_mismatch() -> None:
    problem = _exact_ice_clone_problem()
    assignment_pairs = MILPModelBuilder().enumerate_assignment_pairs(problem)

    audit = _exact_ice_clone_audit(
        problem,
        assignment_pairs=assignment_pairs[:-1],
    )

    assert audit["certified_candidate_group_count"] == 0
    assert "assignment_domain_mismatch" in audit["groups"][0]["blockers"]


def test_exact_ice_clone_flow_audit_rejects_insufficient_initial_fuel() -> None:
    base = _exact_ice_clone_problem()
    problem = replace(
        base,
        trips=tuple(
            replace(trip, distance_km=500.0)
            for trip in base.trips
        ),
    )

    audit = _exact_ice_clone_audit(problem)

    assert audit["certified_candidate_group_count"] == 0
    assert (
        "longest_possible_duty_exceeds_usable_initial_fuel"
        in audit["groups"][0]["blockers"]
    )


def test_exact_ice_clone_flow_audit_rejects_multiday_structure() -> None:
    problem = _exact_ice_clone_problem()
    adapter = GurobiMILPAdapter()
    builder = MILPModelBuilder()
    assignment_pairs = builder.enumerate_assignment_pairs(problem)
    startup_prechecks = {
        (vehicle_id, trip_id): adapter._startup_energy_precheck(
            problem,
            next(
                vehicle
                for vehicle in problem.vehicles
                if vehicle.vehicle_id == vehicle_id
            ),
            problem.trip_by_id()[trip_id],
        )
        for vehicle_id, trip_id in assignment_pairs
    }

    audit = adapter._exact_combustion_clone_flow_aggregation_audit(
        problem=problem,
        identical_vehicle_groups=_ordered_identical_vehicle_groups(problem),
        assignment_pairs=assignment_pairs,
        arc_pairs=builder.enumerate_arc_pairs(problem, problem.trip_by_id()),
        startup_energy_precheck_by_assignment=startup_prechecks,
        planning_days=2,
        daily_fragment_limit=1,
        max_start_fragments_per_vehicle=1,
        max_end_fragments_per_vehicle=1,
    )

    assert audit["certified_candidate_group_count"] == 0
    assert "planning_horizon_is_not_one_day" in audit["groups"][0]["blockers"]


def test_phase4_exact_ice_clone_convexification_preserves_objective() -> None:
    base = _exact_ice_clone_problem()
    common_metadata = {
        **dict(base.metadata or {}),
        "cost_component_flags": {
            **dict(
                (base.metadata or {}).get("cost_component_flags") or {}
            ),
            "driver_cost": False,
        },
        "vehicle_usage_cost_jpy_per_used_bus": 20_000.0,
    }
    aggregated_problem = replace(
        base,
        metadata={
            **common_metadata,
            "exact_combustion_clone_flow_aggregation_enabled": True,
        },
    )
    discrete_problem = replace(
        base,
        metadata={
            **common_metadata,
            "exact_combustion_clone_flow_aggregation_enabled": False,
        },
    )
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        phase="phase4_integrated",
        integrated_actual_cost_objective=True,
        time_limit_sec=30,
        mip_gap=0.0,
        random_seed=42,
        warm_start=False,
        allow_postsolve_repair=False,
        research_run=True,
    )

    aggregated_outcome, aggregated_plan = GurobiMILPAdapter().solve(
        aggregated_problem,
        config,
    )
    discrete_outcome, discrete_plan = GurobiMILPAdapter().solve(
        discrete_problem,
        config,
    )

    assert aggregated_outcome.has_feasible_incumbent
    assert discrete_outcome.has_feasible_incumbent
    assert aggregated_plan.metadata["objective_value"] == pytest.approx(
        discrete_plan.metadata["objective_value"]
    )
    assert aggregated_plan.served_trip_ids == discrete_plan.served_trip_ids
    assert len(aggregated_plan.duties) == len(discrete_plan.duties) == 1
    assert aggregated_plan.metadata[
        "integrated_exact_combustion_clone_flow_aggregation_audit"
    ]["applied"] is True
    aggregation_audit = aggregated_plan.metadata[
        "integrated_exact_combustion_clone_flow_aggregation_audit"
    ]
    assert aggregation_audit["net_binary_variable_reduction"] > 0
    assert aggregation_audit["recovered_path_count"] == 1
    assert aggregation_audit["recovered_vehicle_ids"] == ("ICE_001",)
    discrete_audit = discrete_plan.metadata[
        "integrated_exact_combustion_clone_flow_aggregation_audit"
    ]
    assert discrete_audit["applied"] is False
    assert "disabled_by_scenario" in discrete_audit[
        "application_blockers"
    ]

def test_phase4_exact_ice_clone_convexification_preserves_path_count() -> None:
    base = _exact_ice_clone_problem()
    dispatch_trip_1 = replace(
        base.dispatch_context.trips[0],
        trip_id="parallel-1",
    )
    dispatch_trip_2 = replace(
        base.dispatch_context.trips[0],
        trip_id="parallel-2",
    )
    problem_trip_1 = replace(base.trips[0], trip_id="parallel-1")
    problem_trip_2 = replace(base.trips[0], trip_id="parallel-2")
    problem = replace(
        base,
        dispatch_context=replace(
            base.dispatch_context,
            trips=(dispatch_trip_1, dispatch_trip_2),
        ),
        trips=(problem_trip_1, problem_trip_2),
        feasible_connections={"parallel-1": (), "parallel-2": ()},
        metadata={
            **dict(base.metadata or {}),
            "cost_component_flags": {"driver_cost": False},
            "vehicle_usage_cost_jpy_per_used_bus": 20_000.0,
            "exact_combustion_clone_flow_aggregation_enabled": True,
        },
    )
    outcome, plan = GurobiMILPAdapter().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            allow_postsolve_repair=False,
            research_run=True,
        ),
    )

    assert outcome.has_feasible_incumbent
    assert plan.served_trip_ids == ("parallel-1", "parallel-2")
    assert len(plan.duties) == 2
    audit = plan.metadata[
        "integrated_exact_combustion_clone_flow_aggregation_audit"
    ]
    assert audit["applied"] is True
    assert audit["recovered_path_count"] == 2
    assert audit["recovered_vehicle_ids"] == ("ICE_001", "ICE_002")


def test_phase4_exact_ice_clone_convexification_accepts_verified_seed() -> None:
    base = _exact_ice_clone_problem()
    problem = replace(
        base,
        depot_energy_assets={},
        metadata={
            **dict(base.metadata or {}),
            "cost_component_flags": {"driver_cost": False},
            "exact_combustion_clone_flow_aggregation_enabled": True,
        },
    )
    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            phase4_phase3_seed_enabled=True,
            phase4_phase3_seed_time_limit_sec=30,
            stage1_stage2_candidate_limit=1,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=True,
            allow_postsolve_repair=False,
            research_run=True,
            requested_phase_token="phase4_integrated",
            requested_phase="phase4_integrated",
            resolved_phase="phase4_integrated",
            executed_phase="phase4_integrated",
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    aggregation_audit = result.plan.metadata[
        "integrated_exact_combustion_clone_flow_aggregation_audit"
    ]
    assert aggregation_audit["applied"] is True
    assert aggregation_audit["aggregate_mip_start_complete"] is True, (
        result.plan.metadata["integrated_warm_start_audit"].get("reason")
    )
    assert result.plan.metadata["integrated_warm_start_audit"][
        "applied"
    ] is True


def test_phase3_records_trip_count_symmetry_audit() -> None:
    base = _phase4_seed_problem("phase3-trip-count-symmetry")
    clone = replace(base.vehicles[0], vehicle_id="BEV_002")
    problem = replace(
        base,
        vehicles=(base.vehicles[0], clone),
        baseline_plan=None,
    )

    outcome, plan = GurobiMILPAdapter().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase3_two_stage",
            time_limit_sec=30,
            stage1_time_limit_sec=30,
            stage2_time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            allow_postsolve_repair=False,
            research_run=True,
        ),
    )

    assert outcome.has_feasible_incumbent, outcome.solver_status
    audit = plan.metadata["stage1_identical_vehicle_trip_count_symmetry"]
    assert audit["enabled"] is True
    assert audit["eligible_group_count"] == 1
    assert audit["transition_domain_check_mode"] == (
        "complete_successor_network_proof"
    )
    assert audit["ordering_constraint_count"] == 1
    assert plan.metadata[
        "stage1_identical_vehicle_trip_count_ordering_constraint_count"
    ] == 1


def test_phase4_seed_composition_search_scales_with_selected_fleet() -> None:
    candidate_limit, radius = _phase4_seed_composition_search_limits(
        available_vehicle_count=60,
        requested_candidate_limit=1,
        requested_radius=0,
    )

    assert candidate_limit == 61
    assert radius == 60


def test_phase4_seed_composition_search_preserves_small_scope_floor() -> None:
    candidate_limit, radius = _phase4_seed_composition_search_limits(
        available_vehicle_count=2,
        requested_candidate_limit=1,
        requested_radius=0,
    )

    assert candidate_limit == 21
    assert radius == 10


def test_phase4_seed_composition_search_caps_oversized_scope() -> None:
    candidate_limit, radius = _phase4_seed_composition_search_limits(
        available_vehicle_count=100,
        requested_candidate_limit=500,
        requested_radius=500,
    )

    assert candidate_limit == 100
    assert radius == 100
    assert _phase4_seed_inventory_span_truncated(99) is False
    assert _phase4_seed_inventory_span_truncated(100) is True


def _same_slot_back_to_back_problem(
    vehicle_type: str,
) -> CanonicalOptimizationProblem:
    """Build two feasible trips that share one coarse energy slot.

    The first trip plus the canonical ten-minute turnaround ends exactly when
    the second trip departs.  Both trips intersect the 07:00--08:00 energy
    slot, but they never overlap in physical time.
    """
    dispatch_context = DispatchContext(
        service_date="2025-08-05",
        trips=[
            Trip(
                trip_id="trip-0703",
                route_id="route-a-b",
                origin="DEPOT",
                destination="B",
                departure_time="07:03",
                arrival_time="07:47",
                distance_km=5.0,
                allowed_vehicle_types=(vehicle_type,),
                origin_stop_id="DEPOT",
                destination_stop_id="B",
                operator_id="tokyu",
            ),
            Trip(
                trip_id="trip-0757",
                route_id="route-b-depot",
                origin="B",
                destination="DEPOT",
                departure_time="07:57",
                arrival_time="08:48",
                distance_km=5.0,
                allowed_vehicle_types=(vehicle_type,),
                origin_stop_id="B",
                destination_stop_id="DEPOT",
                operator_id="tokyu",
            ),
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            vehicle_type: VehicleProfile(
                vehicle_type=vehicle_type,
                battery_capacity_kwh=(
                    100.0 if vehicle_type == "BEV" else None
                ),
                energy_consumption_kwh_per_km=(
                    1.0 if vehicle_type == "BEV" else None
                ),
                fuel_tank_capacity_l=(
                    100.0 if vehicle_type == "ICE" else None
                ),
                fuel_consumption_l_per_km=(
                    0.1 if vehicle_type == "ICE" else None
                ),
            )
        },
        default_turnaround_min=10,
    )
    return ProblemBuilder().build_from_dispatch(
        dispatch_context,
        scenario_id="same-slot-back-to-back",
        vehicle_counts={vehicle_type: 1},
        chargers=(
            (ChargerDefinition("chg-1", "DEPOT", 60.0),)
            if vehicle_type == "BEV"
            else ()
        ),
        canonical_depot_id="DEPOT",
        timestep_min=60,
        operation_start_time="05:00",
        operation_end_time="23:00",
        final_soc_floor_percent=20.0,
        price_slots=tuple(
            EnergyPriceSlot(
                slot_index=slot_index,
                grid_buy_yen_per_kwh=30.0,
            )
            for slot_index in range(24)
        ),
        vehicle_usage_cost_jpy_per_used_bus=0.0,
    )


def _late_final_slot_problem() -> CanonicalOptimizationProblem:
    """Build one BEV trip spanning the final two hourly SOC slots."""

    dispatch_context = DispatchContext(
        service_date="2025-08-05",
        trips=[
            Trip(
                trip_id="late-final-trip",
                route_id="late-route",
                origin="Depot",
                destination="Terminal",
                departure_time="22:50",
                arrival_time="23:14",
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                origin_stop_id="DEPOT",
                destination_stop_id="B",
                operator_id="tokyu",
            )
        ],
        turnaround_rules={},
        deadhead_rules={
            ("DEPOT", "Depot"): DeadheadRule("DEPOT", "Depot", 0),
            ("B", "DEPOT"): DeadheadRule("B", "DEPOT", 4),
        },
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=100.0,
                energy_consumption_kwh_per_km=1.0,
            )
        },
        location_aliases={"Depot": ("DEPOT",)},
    )
    problem = ProblemBuilder().build_from_dispatch(
        dispatch_context,
        scenario_id="late-final-slot-integrated",
        vehicle_counts={"BEV": 1},
        chargers=(ChargerDefinition("chg-1", "DEPOT", 60.0),),
        canonical_depot_id="DEPOT",
        timestep_min=60,
        operation_start_time="00:00",
        operation_end_time="23:59",
        final_soc_floor_percent=20.0,
        final_soc_target_percent=80.0,
        final_soc_target_tolerance_percent=0.0,
        price_slots=tuple(
            EnergyPriceSlot(
                slot_index=slot_index,
                # Make the active final slot uniquely cheapest.  A missing
                # C12 row would deterministically attract illegal charging.
                grid_buy_yen_per_kwh=(0.0 if slot_index == 23 else 10.0),
            )
            for slot_index in range(24)
        ),
        vehicle_usage_cost_jpy_per_used_bus=0.0,
    )
    # Keep enough headroom to charge the late trip's energy before departure;
    # the actual-cost contract changes the terminal policy to return-to-initial.
    return replace(
        problem,
        vehicles=tuple(
            replace(vehicle, initial_soc=80.0)
            for vehicle in problem.vehicles
        ),
    )


def _problem() -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="actual-cost-contract",
            objective_mode="total_cost",
            service_coverage_mode="strict",
        ),
        dispatch_context=SimpleNamespace(),
        trips=(),
        vehicles=(),
        objective_weights=OptimizationObjectiveWeights(
            energy=2.0,
            fuel=3.0,
            demand=4.0,
            switch=5.0,
            degradation=6.0,
            return_leg_bonus=7.0,
        ),
        depot_energy_assets={
            "depot": DepotEnergyAsset(
                depot_id="depot",
                bess_enabled=True,
                bess_energy_kwh=6000.0,
                bess_power_kw=900.0,
                bess_initial_soc_kwh=3000.0,
                bess_soc_min_kwh=1200.0,
                bess_soc_max_kwh=4800.0,
                bess_terminal_soc_min_kwh=1200.0,
            )
        },
        metadata={
            "vehicle_usage_cost_jpy_per_used_bus": 20_000.0,
            "vehicle_usage_cost_semantics": "unclassified",
            "cost_component_flags": {},
        },
    )


def test_integrated_actual_cost_contract_removes_nonaccounting_terms() -> None:
    aligned = OptimizationEngine._apply_integrated_actual_cost_contract(
        _problem()
    )
    flags = aligned.metadata["cost_component_flags"]

    assert aligned.objective_weights.energy == 1.0
    assert aligned.objective_weights.fuel == 1.0
    assert aligned.objective_weights.demand == 1.0
    assert aligned.objective_weights.switch == 0.0
    assert aligned.objective_weights.degradation == 1.0
    assert aligned.objective_weights.return_leg_bonus == 0.0
    assert flags["grid_to_bus_priority_penalty"] is False
    assert flags["opportunistic_topup_deficit_penalty"] is False
    assert flags["battery_degradation_cost"] is True
    assert aligned.metadata["pv_curtail_penalty_yen_per_kwh"] == 0.0
    assert aligned.depot_energy_assets["depot"].bess_terminal_soc_target_kwh == 3000.0
    assert aligned.depot_energy_assets["depot"].bess_terminal_soc_policy == (
        "return_to_initial"
    )
    assert aligned.metadata[
        "research_economic_claim_blocked_by_vehicle_usage_cost_semantics"
    ] is True


def test_actual_cost_objective_reconciliation_fails_closed() -> None:
    assert actual_cost_objective_reconciles(
        raw_objective_jpy=100.0,
        accounting_total_jpy=100.0,
        structural_contract_passed=True,
        feasible=True,
        solution_unmodified=True,
    )


def test_provisional_vehicle_day_cost_remains_research_blocked() -> None:
    problem = _problem()
    problem = replace(
        problem,
        metadata={
            **dict(problem.metadata),
            "vehicle_usage_cost_semantics": "provisional_sensitivity",
        },
    )
    aligned = OptimizationEngine._apply_integrated_actual_cost_contract(
        problem
    )

    assert aligned.metadata["vehicle_usage_cost_semantics_classified"] is True
    assert aligned.metadata[
        "vehicle_usage_cost_semantics_research_eligible"
    ] is False
    assert aligned.metadata[
        "research_economic_claim_blocked_by_vehicle_usage_cost_semantics"
    ] is True
    assert not actual_cost_objective_reconciles(
        raw_objective_jpy=100.01,
        accounting_total_jpy=100.0,
        structural_contract_passed=True,
        feasible=True,
        solution_unmodified=True,
    )


def test_integrated_ev_utilization_keeps_cost_contract_without_cost_claim() -> None:
    aligned = OptimizationEngine._apply_integrated_actual_cost_contract(
        _problem(),
        objective_kind="minimum_ice_fuel_lexicographic",
    )

    assert aligned.metadata["integrated_actual_cost_contract_applied"] is True
    assert aligned.metadata["integrated_actual_cost_objective_requested"] is False
    assert aligned.metadata["integrated_primary_objective_kind"] == (
        "minimum_ice_fuel_lexicographic"
    )
    assert aligned.metadata["actual_cost_objective_structural_contract_passed"] is True


def test_research_lexicographic_contract_reports_vehicle_days_as_primary() -> None:
    base_problem = _problem()
    problem = replace(
        base_problem,
        metadata={
            **dict(base_problem.metadata),
            "objective_preset": "research_lexicographic_v1",
        },
    )

    aligned, _ = OptimizationEngine._apply_phase_contract(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            research_run=True,
            integrated_actual_cost_objective=True,
        ),
    )

    assert aligned.metadata["integrated_primary_objective_kind"] == (
        "minimum_used_vehicle_days_lexicographic"
    )
    assert aligned.metadata["integrated_actual_cost_objective_requested"] is False
    assert aligned.metadata["objective_actual_cost_mode"] is False
    assert aligned.metadata["objective_semantics"] == (
        "lexicographic_vehicle_days_then_canonical_cost_then_deadhead_and_"
        "charge_sessions"
    )

    policy_config = replace(
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            research_run=True,
            integrated_actual_cost_objective=True,
        ),
        integrated_ev_utilization_mode="minimum_ice_fuel_lexicographic",
    )
    policy_aligned, _ = OptimizationEngine._apply_phase_contract(
        problem,
        policy_config,
    )
    assert policy_aligned.metadata["integrated_primary_objective_kind"] == (
        "minimum_used_vehicle_days_lexicographic"
    )


def test_phase4_solver_reconciles_integrated_actual_cost_on_full_day() -> None:
    problem = ProblemBuilder().build_from_dispatch(
        _dispatch_context(),
        scenario_id="actual-cost-solver",
        vehicle_counts={"BEV": 1},
        chargers=(ChargerDefinition("chg-1", "DEPOT", 60.0),),
        canonical_depot_id="DEPOT",
        timestep_min=60,
        operation_start_time="05:00",
        operation_end_time="23:00",
        final_soc_floor_percent=20.0,
        final_soc_target_percent=80.0,
        final_soc_target_tolerance_percent=0.0,
        price_slots=tuple(
            EnergyPriceSlot(
                slot_index=slot_index,
                grid_buy_yen_per_kwh=10.0,
            )
            for slot_index in range(24)
        ),
        vehicle_usage_cost_jpy_per_used_bus=0.0,
    )
    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            allow_postsolve_repair=False,
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.solver_metadata[
        "actual_cost_objective_numeric_reconciliation_passed"
    ] is True
    assert result.solver_metadata[
        "solver_objective_matches_accounting_total"
    ] is True
    assert result.cost_breakdown["objective_is_actual_cost"] is True
    assert result.solver_metadata["assignment_energy_coupling_mode"] == (
        "phase4_integrated_slot_energy_recourse"
    )
    assert result.solver_metadata["solve_time_sec"] is not None
    terminal_targets = result.solver_metadata[
        "vehicle_terminal_soc_target_kwh_by_vehicle"
    ]
    terminal_values = result.solver_metadata[
        "vehicle_terminal_soc_kwh_by_vehicle"
    ]
    terminal_contract = result.plan.metadata[
        "bev_terminal_soc_numeric_acceptance_contract"
    ]
    accepted_deviation_kwh = (
        terminal_contract["scientific_tolerance_kwh"]
        + terminal_contract["numeric_comparison_margin_kwh"]
    )

    assert result.solver_metadata["bev_terminal_soc_balance_satisfied"] is True
    assert terminal_targets
    assert terminal_values.keys() == terminal_targets.keys()
    assert result.plan.metadata["bev_terminal_soc_balance_satisfied"] is True
    for vehicle_id, target_kwh in terminal_targets.items():
        assert terminal_values[vehicle_id] == pytest.approx(
            target_kwh,
            abs=accepted_deviation_kwh,
        )


def test_phase4_degradation_uses_canonical_throughput_price() -> None:
    problem = ProblemBuilder().build_from_dispatch(
        _dispatch_context(),
        scenario_id="actual-cost-degradation-throughput",
        vehicle_counts={"BEV": 1},
        chargers=(ChargerDefinition("chg-1", "DEPOT", 60.0),),
        canonical_depot_id="DEPOT",
        timestep_min=60,
        operation_start_time="05:00",
        operation_end_time="23:00",
        final_soc_floor_percent=20.0,
        final_soc_target_percent=80.0,
        final_soc_target_tolerance_percent=0.0,
        price_slots=tuple(
            EnergyPriceSlot(
                slot_index=slot_index,
                grid_buy_yen_per_kwh=10.0,
            )
            for slot_index in range(24)
        ),
        battery_degradation_price_jpy_per_kwh=2.5,
        vehicle_usage_cost_jpy_per_used_bus=0.0,
    )

    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            allow_postsolve_repair=False,
        ),
    )
    charged_kwh = sum(
        slot.charge_kw * problem.scenario.timestep_min / 60.0
        for slot in result.plan.charging_slots
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.cost_breakdown["degradation_cost"] == pytest.approx(
        charged_kwh * 2.5
    )
    assert result.solver_metadata[
        "solver_objective_matches_accounting_total"
    ] is True


def test_phase4_final_slot_trip_has_one_energy_debit_and_no_trip_charge() -> None:
    problem = _late_final_slot_problem()

    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            allow_postsolve_repair=False,
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.solver_metadata["bev_terminal_soc_balance_satisfied"] is True
    assert all(
        slot.slot_index != 23
        for slot in result.plan.charging_slots
    )
    assert not any(
        "charging occurs during active trip slot 23" in reason
        or "exceeds return-to-initial" in reason
        for reason in result.infeasibility_reasons
    )
    terminal_values = result.solver_metadata[
        "vehicle_terminal_soc_kwh_by_vehicle"
    ]
    terminal_targets = result.solver_metadata[
        "vehicle_terminal_soc_target_kwh_by_vehicle"
    ]
    assert terminal_values.keys() == terminal_targets.keys()
    for vehicle_id, target_kwh in terminal_targets.items():
        assert terminal_values[vehicle_id] == pytest.approx(
            target_kwh,
            abs=1.0e-6,
        )


def test_bess_terminal_deviation_uses_physical_soc_trace() -> None:
    deviations = _actual_bess_terminal_soc_deviation_by_depot(
        bess_soc_end_kwh_by_depot_slot={
            "DEPOT": {0: 49.0, 23: 50.0},
        },
        bess_terminal_soc_target_kwh_by_depot={"DEPOT": 50.0},
    )

    assert deviations == {"DEPOT": 0.0}


def test_bess_terminal_deviation_fails_without_physical_soc_trace() -> None:
    with pytest.raises(
        RuntimeError,
        match="BESS terminal target has no solved end-of-slot SOC trace",
    ):
        _actual_bess_terminal_soc_deviation_by_depot(
            bess_soc_end_kwh_by_depot_slot={},
            bess_terminal_soc_target_kwh_by_depot={"DEPOT": 50.0},
        )


@pytest.mark.parametrize("vehicle_type", ["BEV", "ICE"])
def test_phase4_allows_back_to_back_trips_inside_one_energy_slot(
    vehicle_type: str,
) -> None:
    problem = _same_slot_back_to_back_problem(vehicle_type)
    first_trip, second_trip = problem.trips

    assert first_trip.arrival_min + problem.dispatch_context.default_turnaround_min == (
        second_trip.departure_min
    )
    assert GurobiMILPAdapter()._slot_index(
        problem, first_trip.departure_min
    ) == GurobiMILPAdapter()._slot_index(
        problem, second_trip.departure_min
    )

    outcome, plan = GurobiMILPAdapter().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            allow_postsolve_repair=False,
            research_run=True,
        ),
    )

    assert outcome.has_feasible_incumbent, outcome.solver_status
    assert set(plan.served_trip_ids) == {"trip-0703", "trip-0757"}
    assert plan.unserved_trip_ids == ()


def test_phase4_objective_floor_is_disabled_for_negative_bonus_term() -> None:
    problem = _same_slot_back_to_back_problem("ICE")
    problem = replace(
        problem,
        objective_weights=replace(
            problem.objective_weights,
            return_leg_bonus=1.0,
        ),
    )

    outcome, plan = GurobiMILPAdapter().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            allow_postsolve_repair=False,
            research_run=True,
        ),
    )

    assert outcome.has_feasible_incumbent, outcome.solver_status
    assert plan.metadata[
        "integrated_analytical_objective_floor_constraint_count"
    ] == 0
    assert plan.metadata[
        "integrated_analytical_objective_floor_certificate_eligible"
    ] is False
    assert "negative_return_leg_bonus_term" in plan.metadata[
        "integrated_analytical_objective_floor_blockers"
    ]


def _phase4_seed_problem(
    scenario_id: str = "actual-cost-verified-phase3-seed",
) -> CanonicalOptimizationProblem:
    dispatch_context = _dispatch_context()
    dispatch_context = replace(
        dispatch_context,
        trips=tuple(
            replace(trip, operator_id="tokyu")
            for trip in dispatch_context.trips
        ),
    )
    problem = ProblemBuilder().build_from_dispatch(
        dispatch_context,
        scenario_id=scenario_id,
        vehicle_counts={"BEV": 1},
        chargers=(ChargerDefinition("chg-1", "DEPOT", 60.0),),
        canonical_depot_id="DEPOT",
        timestep_min=60,
        operation_start_time="05:00",
        operation_end_time="23:00",
        final_soc_floor_percent=20.0,
        final_soc_target_percent=80.0,
        final_soc_target_tolerance_percent=0.0,
        price_slots=tuple(
            EnergyPriceSlot(
                slot_index=slot_index,
                grid_buy_yen_per_kwh=10.0,
            )
            for slot_index in range(24)
        ),
        vehicle_usage_cost_jpy_per_used_bus=0.0,
    )
    return replace(
        problem,
        depot_energy_assets={
            "DEPOT": DepotEnergyAsset(
                depot_id="DEPOT",
                bess_enabled=True,
                bess_energy_kwh=200.0,
                bess_power_kw=60.0,
                bess_initial_soc_kwh=100.0,
                bess_soc_min_kwh=20.0,
                bess_soc_max_kwh=180.0,
                bess_terminal_soc_min_kwh=20.0,
            )
        },
        metadata={
            **dict(problem.metadata or {}),
            "research_fleet_validation": {"status": "OK"},
            "service_calendar_validation": {"status": "OK"},
        },
    )


def test_integrated_phase4_applies_iis_branch_guidance_without_cutting_plan() -> None:
    base_problem = _phase4_seed_problem("phase4-iis-branch-guidance")
    problem = replace(
        base_problem,
        metadata={
            **dict(base_problem.metadata or {}),
            "phase4_seed_stage2_iis_assignment_guidance": (
                {
                    "assignment_pairs": (("BEV_001", "t1"),),
                    "exact_pattern_vehicle_ids": ("BEV_001",),
                    "source_candidate_hash": "candidate-a",
                },
            ),
        },
    )

    outcome, plan = GurobiMILPAdapter().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            allow_postsolve_repair=False,
            research_run=True,
        ),
    )

    assert outcome.has_feasible_incumbent, outcome.solver_status
    assert plan.served_trip_ids == ("t1",)
    assert plan.metadata[
        "integrated_phase3_iis_assignment_guidance_pattern_count"
    ] == 1
    assert plan.metadata[
        "integrated_phase3_iis_assignment_guidance_variable_count"
    ] == 1
    assert plan.metadata[
        "integrated_phase3_iis_assignment_guidance_branch_priority"
    ] == 1


def test_phase4_uses_verified_same_problem_phase3_plan_as_complete_mip_start() -> None:
    base_problem = _phase4_seed_problem()
    problem = replace(
        base_problem,
        metadata={
            **dict(base_problem.metadata or {}),
            "vehicle_usage_cost_jpy_per_used_bus": 20_000.0,
        },
    )
    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            phase4_phase3_seed_enabled=True,
            phase4_phase3_seed_time_limit_sec=60,
            stage1_stage2_candidate_limit=1,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=True,
            allow_postsolve_repair=False,
            research_run=True,
            requested_phase_token="phase4_integrated",
            requested_phase="phase4_integrated",
            resolved_phase="phase4_integrated",
            executed_phase="phase4_integrated",
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.solver_metadata["warm_start_applied"] is True
    assert result.solver_metadata["warm_start_source"] == (
        "verified_phase3_two_stage_phase4_mip_start"
    )
    assert result.solver_metadata["phase4_phase3_seed_audit"][
        "accepted"
    ] is True
    seed_audit = result.solver_metadata["phase4_phase3_seed_audit"]
    assert seed_audit["seed_stage1_stage2_candidate_evaluation"]
    assert seed_audit["seed_wall_runtime_sec"] > 0.0
    assert seed_audit[
        "seed_stage1_stage2_candidate_evaluation_order"
    ] == "candidate_priority_cost_ascending_then_candidate_hash"
    assert (
        seed_audit[
            "seed_stage1_stage2_candidate_evaluation_initial_budget_sec"
        ]
        > 0.0
    )
    assert seed_audit["seed_stage1_stage2_selected_candidate_hash"]
    assert seed_audit[
        "seed_selected_plan_used_powertrain_composition"
    ]["semantics"] == (
        "selected_phase3_stage2_feasible_mip_start_not_phase4_result"
    )
    assert seed_audit[
        "seed_stage1_primary_candidate_used_powertrain_composition"
    ] == {"used_bev": 1, "used_ice": 0}
    assert seed_audit[
        "seed_stage1_time_indexed_energy_recourse_configuration"
    ]["arbitrary_weather_assignment_bias_used"] is False
    assert result.solver_metadata["phase4_phase3_seed_audit"][
        "seed_stage1_stage2_candidate_limit"
    ] == 21
    assert result.solver_metadata["phase4_phase3_seed_audit"][
        "seed_stage1_composition_search_radius"
    ] == 10
    composition_certificate = result.solver_metadata[
        "stage1_used_powertrain_composition_search"
    ]
    assert composition_certificate["enabled"] is True
    assert composition_certificate["radius_requested"] == 10
    assert result.solver_metadata[
        "stage1_used_powertrain_composition_search_accepted"
    ] is True
    assert len(
        result.solver_metadata["phase4_phase3_seed_audit"][
            "seed_plan_fingerprint"
        ]
    ) == 64
    audit = result.plan.metadata["integrated_warm_start_audit"]
    assert audit["applied"] is True
    assert audit["same_canonical_problem"] is True
    assert audit["complete_assignment_binary_start"] is True
    assert audit["complete_charger_binary_start"] is True
    assert audit["complete_vehicle_soc_start"] is True
    assert audit["complete_bess_soc_start"] is True
    assert audit["complete_bess_mode_binary_start"] is True
    assert audit["bess_mode_binary_start_count"] > 0
    assert audit["physical_energy_trace_start"] is True
    assert audit["dispatch_fixed_recourse_requested"] is True
    assert audit["integrated_dispatch_fixed_recourse_feasible"] is True
    assert audit["integrated_feasible_start_applied"] is True
    assert audit["complete_integrated_solution_start"] is True
    assert audit["integrated_solution_start_count"] > 0
    assert len(audit["integrated_solution_start_fingerprint"]) == 64
    assert audit["dispatch_fixed_recourse_runtime_sec"] >= 0.0
    assert result.solver_metadata["first_feasible_sec"] == 0.0
    assert result.solver_metadata["integrated_mip_focus"] == 3
    assert result.solver_metadata["integrated_heuristics"] == pytest.approx(
        0.01
    )
    assert result.solver_metadata["integrated_symmetry"] == -1
    assert result.solver_metadata["integrated_root_method"] == 1
    assert result.solver_metadata["integrated_node_method"] == 1
    assert result.solver_metadata[
        "integrated_soft_mem_limit_gb"
    ] == pytest.approx(32.0)
    assert result.solver_metadata["integrated_nodefile_start_gb"] == pytest.approx(
        0.5
    )
    assert audit["dispatch_fixed_recourse_root_method"] == 1
    assert audit["dispatch_fixed_recourse_node_method"] == 1
    assert audit[
        "dispatch_fixed_recourse_soft_mem_limit_gb"
    ] == pytest.approx(32.0)
    assert result.solver_metadata["integrated_search_profile"][
        "phase_count_executed"
    ] == 1
    assert result.solver_metadata["integrated_search_profile"]["phases"][0][
        "phase"
    ] == "certify_bound_from_verified_feasible_start"
    assert result.solver_metadata["integrated_search_profile"][
        "schema_version"
    ] == "phase4_integrated_search_profile_v2"
    assert result.solver_metadata[
        "integrated_analytical_objective_floor_constraint_count"
    ] == 1
    assert result.solver_metadata[
        "integrated_verified_start_objective_cap_constraint_count"
    ] == 1
    assert result.solver_metadata[
        "integrated_verified_start_vehicle_day_cap_constraint_count"
    ] == 1
    assert result.solver_metadata[
        "integrated_verified_start_search_bounds"
    ]["eligible"] is True
    assert result.solver_metadata[
        "integrated_analytical_objective_lower_bound"
    ] >= 20_000.0
    assert result.solver_metadata[
        "integrated_analytical_objective_floor_certificate_eligible"
    ] is True
    assert result.solver_metadata["raw_best_bound"] is not None
    assert result.solver_metadata["raw_mip_gap_ratio"] is not None
    assert result.solver_metadata["certified_best_bound"] is not None
    assert result.solver_metadata["certified_mip_gap_ratio"] is not None
    assert (
        result.solver_metadata["certified_best_bound"]
        >= result.solver_metadata["raw_best_bound"]
    )
    assert (
        result.solver_metadata["certified_mip_gap_ratio"]
        <= result.solver_metadata["raw_mip_gap_ratio"]
    )
    assert result.solver_metadata["phase4_phase3_seed_audit"][
        "seed_runtime_sec"
    ] > 0.0
    assert result.solver_metadata[
        "actual_cost_objective_numeric_reconciliation_passed"
    ] is True
    assert result.solver_metadata["research_run_accepted"] is True
    assert result.solver_metadata["research_acceptance_checks"][
        "phase4_declared_seed_handoff_satisfied"
    ] is True
    assert result.solver_metadata["research_acceptance_checks"][
        "phase4_no_hidden_bev_directed_seed"
    ] is True


def test_phase4_primary_seed_and_integrated_search_share_one_wall_budget() -> None:
    base_problem = _phase4_seed_problem("shared-phase4-wall-budget")
    problem = replace(
        base_problem,
        metadata={
            **dict(base_problem.metadata or {}),
            "vehicle_usage_cost_jpy_per_used_bus": 20_000.0,
        },
    )

    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            phase4_phase3_seed_enabled=True,
            phase4_phase3_seed_time_limit_sec=10,
            phase4_phase3_seed_composition_search_enabled=False,
            phase4_phase3_seed_unused_bev_neighborhood_enabled=False,
            stage1_stage2_candidate_limit=10,
            stage1_composition_search_radius=2,
            time_limit_sec=20,
            mip_gap=0.0,
            random_seed=42,
            warm_start=True,
            allow_postsolve_repair=False,
            research_run=True,
            requested_phase_token="phase4_integrated",
            requested_phase="phase4_integrated",
            resolved_phase="phase4_integrated",
            executed_phase="phase4_integrated",
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    seed_audit = result.solver_metadata["phase4_phase3_seed_audit"]
    assert seed_audit["seed_composition_search_enabled"] is False
    assert seed_audit["seed_stage1_stage2_candidate_limit"] == 1
    assert seed_audit["seed_stage1_composition_search_radius"] == 0
    assert seed_audit["seed_model_build_overhead_allowance_sec"] == 0
    assert seed_audit["unused_bev_activation_neighborhood_enabled"] is False
    budget = result.solver_metadata[
        "phase4_shared_wall_clock_budget_audit"
    ]
    assert budget["requested_total_wall_clock_budget_sec"] == pytest.approx(
        20.0
    )
    assert budget["integrated_wall_clock_budget_sec"] < 20.0
    assert budget["precheck_and_seed_wall_runtime_sec"] > 0.0
    assert budget["total_wall_runtime_sec"] <= 21.0


def test_research_lexicographic_seed_certifies_vehicle_days_before_cost() -> None:
    base_problem = _phase4_seed_problem(
        "research-lexicographic-sequential-certification"
    )
    problem = replace(
        base_problem,
        metadata={
            **dict(base_problem.metadata or {}),
            "vehicle_usage_cost_jpy_per_used_bus": 20_000.0,
            "objective_preset": "research_lexicographic_v1",
        },
    )

    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            phase4_phase3_seed_enabled=True,
            phase4_phase3_seed_time_limit_sec=60,
            stage1_stage2_candidate_limit=1,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=True,
            allow_postsolve_repair=False,
            research_run=True,
            requested_phase_token="phase4_integrated",
            requested_phase="phase4_integrated",
            resolved_phase="phase4_integrated",
            executed_phase="phase4_integrated",
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.solver_metadata["integrated_lexicographic_solve_mode"] == (
        "sequential_scalar_certification_v1"
    )
    assert result.solver_metadata[
        "integrated_lexicographic_primary_certified"
    ] is True
    assert result.solver_metadata[
        "integrated_lexicographic_primary_certificate"
    ] == (
        "verified_integrated_recourse_incumbent_matches_"
        "strict_path_cover_integer_lower_bound"
    )
    warm_start_audit = result.solver_metadata["integrated_warm_start_audit"]
    assert warm_start_audit[
        "dispatch_fixed_recourse_used_vehicle_days"
    ] == pytest.approx(1.0)
    assert warm_start_audit[
        "dispatch_fixed_recourse_canonical_cost_jpy"
    ] is not None
    assert result.solver_metadata[
        "integrated_verified_start_search_bounds"
    ]["eligible"] is True
    assert result.solver_metadata[
        "integrated_verified_start_search_bounds"
    ]["incumbent_objective_field"] == (
        "dispatch_fixed_recourse_canonical_cost_jpy"
    )
    assert result.solver_metadata[
        "integrated_verified_start_objective_cap_constraint_count"
    ] == 1
    phases = result.solver_metadata["integrated_search_profile"]["phases"]
    assert phases[0]["phase"] == "lexicographic_used_vehicle_days"
    assert phases[0]["search_profile"] == "certificate_without_resolve"
    assert any(
        phase["phase"] == "lexicographic_canonical_operating_cost"
        for phase in phases
    )
    assert result.solver_metadata[
        "integrated_lexicographic_cost_raw_mip_gap_ratio"
    ] == pytest.approx(0.0)


def test_phase4_stops_after_verified_start_already_certifies_requested_gap() -> None:
    base_problem = _phase4_seed_problem(
        "actual-cost-certified-start-stop"
    )
    problem = replace(
        base_problem,
        metadata={
            **dict(base_problem.metadata or {}),
            "vehicle_usage_cost_jpy_per_used_bus": 20_000.0,
        },
    )

    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            phase4_phase3_seed_enabled=True,
            phase4_phase3_seed_time_limit_sec=60,
            stage1_stage2_candidate_limit=1,
            time_limit_sec=30,
            mip_gap=0.5,
            random_seed=42,
            warm_start=True,
            allow_postsolve_repair=False,
            research_run=True,
            requested_phase_token="phase4_integrated",
            requested_phase="phase4_integrated",
            resolved_phase="phase4_integrated",
            executed_phase="phase4_integrated",
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.solver_metadata[
        "integrated_certified_gap_stop_applied"
    ] is True
    assert result.solver_metadata[
        "integrated_certified_gap_at_verified_start"
    ] <= 0.5
    assert result.solver_metadata[
        "certified_mip_gap_ratio"
    ] <= 0.5
    assert result.solver_status in {"objective_limit", "optimal"}


def test_phase4_formal_gate_rejects_failed_declared_seed(monkeypatch) -> None:
    problem = _phase4_seed_problem("actual-cost-rejected-formal-seed")
    monkeypatch.setattr(
        optimization_engine_module,
        "phase4_seed_plan_fingerprint",
        lambda _plan: "",
    )

    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            phase4_phase3_seed_enabled=True,
            phase4_phase3_seed_time_limit_sec=60,
            stage1_stage2_candidate_limit=1,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=True,
            allow_postsolve_repair=False,
            research_run=True,
            requested_phase_token="phase4_integrated",
            requested_phase="phase4_integrated",
            resolved_phase="phase4_integrated",
            executed_phase="phase4_integrated",
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.solver_metadata["phase4_phase3_seed_audit"][
        "accepted"
    ] is False
    assert result.solver_metadata["research_acceptance_checks"][
        "phase4_declared_seed_handoff_satisfied"
    ] is False
    assert result.solver_metadata["research_run_accepted"] is False


def test_integrated_seed_recourse_preflight_restores_bounds_and_exports_iis() -> None:
    gp, GRB = ensure_gurobi()
    model = gp.Model("phase4_seed_recourse_negative_contract")
    model.Params.OutputFlag = 0
    dispatch = model.addVar(vtype=GRB.BINARY, name="dispatch_seed")
    model.addConstr(dispatch == 0.0, name="integrated_only_conflict")
    model.setObjective(0.0, GRB.MINIMIZE)
    model.update()
    dispatch.Start = 1.0

    audit = GurobiMILPAdapter._certify_integrated_dispatch_fixed_recourse(
        model,
        config=OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            phase4_integrated_seed_recourse_preflight_enabled=True,
            phase4_integrated_seed_recourse_time_limit_sec=10,
        ),
        GRB=GRB,
        integrated_warm_start_audit={"applied": True},
        dispatch_variable_maps=(("assignment", {"vehicle-a|trip-a": dispatch}),),
    )

    assert audit["dispatch_fixed_recourse_status"] == "infeasible"
    assert audit["integrated_dispatch_fixed_recourse_feasible"] is False
    assert audit["dispatch_fixed_recourse_iis_generated"] is True
    assert audit["dispatch_fixed_recourse_model_variable_count"] == 1
    assert audit["dispatch_fixed_recourse_model_constraint_count"] == 1
    assert audit["dispatch_fixed_recourse_iis_constraint_count"] >= 1
    assert audit["dispatch_fixed_recourse_iis_variable_bound_count"] >= 1
    assert len(audit["dispatch_fixed_recourse_iis_fingerprint"]) == 64
    assert audit[
        "dispatch_fixed_recourse_iis_variable_bound_semantic_sample"
    ] == ["LB:assignment[vehicle-a|trip-a]"]
    semantic_constraints = audit[
        "dispatch_fixed_recourse_iis_constraint_semantic_sample"
    ]
    assert len(semantic_constraints) == 1
    assert semantic_constraints[0]["constraint_name"] == (
        "integrated_only_conflict"
    )
    assert semantic_constraints[0]["terms"] == [
        {
            "coefficient": 1.0,
            "variable": "assignment[vehicle-a|trip-a]",
            "raw_variable_name": "dispatch_seed",
        }
    ]
    assert dispatch.LB == 0.0
    assert dispatch.UB == 1.0


def test_phase4_rejects_incomplete_bess_soc_seed_trace() -> None:
    engine = OptimizationEngine()
    problem = _phase4_seed_problem("actual-cost-incomplete-bess-seed")
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        phase="phase4_integrated",
        integrated_actual_cost_objective=True,
        phase4_phase3_seed_enabled=True,
        phase4_phase3_seed_time_limit_sec=60,
        stage1_stage2_candidate_limit=1,
        time_limit_sec=30,
        mip_gap=0.0,
        random_seed=42,
        warm_start=True,
        allow_postsolve_repair=False,
    )
    seeded_problem = engine._with_verified_phase4_phase3_seed(
        problem,
        config,
    )
    assert seeded_problem.baseline_plan is not None
    baseline_metadata = dict(seeded_problem.baseline_plan.metadata or {})
    baseline_metadata.pop("bess_soc_start_kwh_by_depot_slot", None)
    incomplete_plan_without_updated_hash = replace(
        seeded_problem.baseline_plan,
        metadata=baseline_metadata,
    )
    incomplete_fingerprint = phase4_seed_plan_fingerprint(
        incomplete_plan_without_updated_hash
    )
    seed_audit = dict(
        baseline_metadata.get("phase4_phase3_seed_audit") or {}
    )
    seed_audit["seed_plan_fingerprint"] = incomplete_fingerprint
    baseline_metadata["phase4_phase3_seed_audit"] = seed_audit
    baseline_metadata[
        "phase4_seed_plan_fingerprint"
    ] = incomplete_fingerprint
    incomplete_plan = replace(
        incomplete_plan_without_updated_hash,
        metadata=baseline_metadata,
    )
    incomplete_problem = replace(
        seeded_problem,
        baseline_plan=incomplete_plan,
    )

    result = engine.solve(
        incomplete_problem,
        replace(config, phase4_phase3_seed_enabled=False),
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.solver_metadata["warm_start_applied"] is False
    assert result.solver_metadata["integrated_warm_start_audit"][
        "reason"
    ] == "seed_bess_start_soc_trace_missing"


def test_phase4_rejects_seed_plan_changed_after_fingerprinting() -> None:
    engine = OptimizationEngine()
    problem = _phase4_seed_problem("actual-cost-tampered-seed")
    config = OptimizationConfig(
        mode=OptimizationMode.MILP,
        phase="phase4_integrated",
        integrated_actual_cost_objective=True,
        phase4_phase3_seed_enabled=True,
        phase4_phase3_seed_time_limit_sec=60,
        stage1_stage2_candidate_limit=1,
        time_limit_sec=30,
        mip_gap=0.0,
        random_seed=42,
        warm_start=True,
        allow_postsolve_repair=False,
    )
    seeded_problem = engine._with_verified_phase4_phase3_seed(
        problem,
        config,
    )
    assert seeded_problem.baseline_plan is not None
    tampered_plan = replace(
        seeded_problem.baseline_plan,
        vehicle_soc_kwh_by_vehicle_slot={},
    )

    result = engine.solve(
        replace(seeded_problem, baseline_plan=tampered_plan),
        replace(config, phase4_phase3_seed_enabled=False),
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.solver_metadata["warm_start_applied"] is False
    assert result.solver_metadata["integrated_warm_start_audit"][
        "reason"
    ] == "seed_plan_fingerprint_mismatch"


def test_phase4_rejects_unverified_dispatch_baseline_as_integrated_mip_start() -> None:
    problem = ProblemBuilder().build_from_dispatch(
        _dispatch_context(),
        scenario_id="actual-cost-reject-unverified-seed",
        vehicle_counts={"BEV": 1},
        chargers=(ChargerDefinition("chg-1", "DEPOT", 60.0),),
        canonical_depot_id="DEPOT",
        timestep_min=60,
        operation_start_time="05:00",
        operation_end_time="23:00",
        final_soc_floor_percent=20.0,
        final_soc_target_percent=80.0,
        final_soc_target_tolerance_percent=0.0,
        price_slots=tuple(
            EnergyPriceSlot(
                slot_index=slot_index,
                grid_buy_yen_per_kwh=10.0,
            )
            for slot_index in range(24)
        ),
        vehicle_usage_cost_jpy_per_used_bus=0.0,
    )
    assert problem.baseline_plan is not None

    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            phase4_phase3_seed_enabled=False,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=True,
            allow_postsolve_repair=False,
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.solver_metadata["warm_start_applied"] is False
    assert result.solver_metadata["integrated_warm_start_audit"][
        "reason"
    ] == "baseline_is_not_verified_phase3_seed"


def test_phase4_ev_utilization_enforces_canonical_cost_cap() -> None:
    problem = ProblemBuilder().build_from_dispatch(
        _dispatch_context(),
        scenario_id="ev-utilization-cost-cap",
        vehicle_counts={"BEV": 1},
        chargers=(ChargerDefinition("chg-1", "DEPOT", 60.0),),
        canonical_depot_id="DEPOT",
        timestep_min=60,
        operation_start_time="05:00",
        operation_end_time="23:00",
        final_soc_floor_percent=20.0,
        final_soc_target_percent=80.0,
        final_soc_target_tolerance_percent=0.0,
        price_slots=tuple(
            EnergyPriceSlot(
                slot_index=slot_index,
                grid_buy_yen_per_kwh=10.0,
            )
            for slot_index in range(24)
        ),
        vehicle_usage_cost_jpy_per_used_bus=0.0,
    )
    baseline = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_actual_cost_objective=True,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            allow_postsolve_repair=False,
        ),
    )
    cost_cap = float(baseline.cost_breakdown["total_cost"]) * 1.01

    result = OptimizationEngine().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase4_integrated",
            integrated_ev_utilization_mode=(
                "minimum_ice_fuel_lexicographic"
            ),
            integrated_actual_cost_upper_bound_jpy=cost_cap,
            integrated_actual_cost_upper_bound_delta_ratio=0.01,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
            allow_postsolve_repair=False,
        ),
    )

    assert result.feasible, result.infeasibility_reasons
    assert result.cost_breakdown["total_cost"] <= cost_cap + 1.0e-6
    assert result.cost_breakdown["objective_is_actual_cost"] is False
    assert result.solver_metadata["integrated_ev_utilization_mode"] == (
        "minimum_ice_fuel_lexicographic"
    )
    assert result.solver_metadata[
        "integrated_actual_cost_contract_applied"
    ] is True
    assert result.solver_metadata["integrated_primary_objective_kind"] == (
        "minimum_ice_fuel_lexicographic"
    )
    assert result.solver_metadata[
        "integrated_actual_cost_upper_bound_verified"
    ] is True
    assert result.solver_metadata["integrated_primary_ice_fuel_l"] >= 0.0
    assert result.solver_metadata["integrated_lexicographic_solve_mode"] == (
        "sequential_scalar_certification_v1"
    )
    assert result.solver_metadata[
        "integrated_lexicographic_primary_value"
    ] == pytest.approx(
        result.solver_metadata["integrated_primary_ice_fuel_l"]
    )
    assert result.solver_metadata[
        "integrated_lexicographic_primary_best_bound"
    ] is not None
    assert result.solver_metadata[
        "integrated_lexicographic_primary_certified"
    ] is True
    assert "minimum_ice_fuel_l" in result.solver_metadata[
        "integrated_lexicographic_completed_objectives"
    ]
    assert result.solver_metadata[
        "integrated_lexicographic_primary_certificate"
    ] == "gurobi_continuous_objective_bound_certificate"
    policy_primary_stage = next(
        stage
        for stage in result.solver_metadata["integrated_search_profile"][
            "phases"
        ]
        if stage["phase"] == "policy_minimum_ice_fuel_l"
    )
    assert policy_primary_stage["best_bound"] is not None
    assert policy_primary_stage["certificate"] == (
        "gurobi_continuous_objective_bound_certificate"
    )
    assert result.solver_metadata[
        "integrated_lexicographic_cost_status"
    ] == "optimal"
    assert result.solver_metadata[
        "integrated_lexicographic_cost_objective_jpy"
    ] is not None
    assert "canonical_operating_cost" in result.solver_metadata[
        "integrated_lexicographic_completed_objectives"
    ]
    assert any(
        stage["phase"] == "policy_secondary_canonical_operating_cost"
        for stage in result.solver_metadata["integrated_search_profile"][
            "phases"
        ]
    )
