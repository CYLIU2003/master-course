from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.optimization.milp.solver_adapter as solver_adapter_module
from src.dispatch.models import DispatchContext, DutyLeg, Trip, VehicleDuty
from src.gurobi_runtime import is_gurobi_available
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.milp.solver_adapter import (
    GurobiMILPAdapter,
    MILPSolverOutcome,
    _exchange_duty_suffixes,
    _maximum_bipartite_vehicle_matching,
    _merge_route_band_repartition_plan,
    _remap_plan_vehicle_ids,
    _route_band_repartition_retry_budget,
)


def _trip(trip_id: str, departure: str) -> Trip:
    return Trip(
        trip_id=trip_id,
        route_id="route",
        origin="DEPOT",
        destination="DEPOT",
        departure_time=departure,
        arrival_time=departure,
        distance_km=1.0,
        allowed_vehicle_types=("BEV", "ICE"),
        operator_id="tokyu",
    )


def _seed_plan() -> AssignmentPlan:
    duties = (
        VehicleDuty(
            duty_id="duty-ice",
            vehicle_type="ICE",
            legs=(DutyLeg(_trip("trip-ice", "08:00")),),
        ),
        VehicleDuty(
            duty_id="duty-bev",
            vehicle_type="BEV",
            legs=(DutyLeg(_trip("trip-bev", "09:00")),),
        ),
    )
    return AssignmentPlan(
        duties=duties,
        served_trip_ids=("trip-ice", "trip-bev"),
        metadata={
            "duty_vehicle_map": {
                "duty-ice": "ice-1",
                "duty-bev": "bev-used",
            },
            "stage1_feasible": True,
            "stage2_feasible": True,
            "stage2_has_feasible_incumbent": True,
        },
    )


def _problem() -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="unused-bev-neighborhood",
            timestep_min=60,
        ),
        dispatch_context=SimpleNamespace(),
        trips=(),
        vehicles=(
            ProblemVehicle("ice-1", "ICE", "DEPOT"),
            ProblemVehicle("bev-used", "BEV", "DEPOT"),
            ProblemVehicle("bev-a", "BEV", "DEPOT"),
            ProblemVehicle("bev-b", "BEV", "DEPOT"),
        ),
    )


def test_maximum_bipartite_vehicle_matching_is_maximum_and_deterministic() -> None:
    matching = _maximum_bipartite_vehicle_matching(
        {
            "ice-a": ("bev-1", "bev-2"),
            "ice-b": ("bev-1",),
            "ice-c": ("bev-2", "bev-3"),
        }
    )

    assert matching == {
        "ice-a": "bev-2",
        "ice-b": "bev-1",
        "ice-c": "bev-3",
    }


def test_remap_plan_vehicle_ids_clears_stale_energy_and_preserves_paths() -> None:
    seed = _seed_plan()
    remapped = _remap_plan_vehicle_ids(
        seed,
        replacement_by_source_vehicle={"ice-1": "bev-a"},
        vehicle_type_by_id={
            "ice-1": "ICE",
            "bev-used": "BEV",
            "bev-a": "BEV",
        },
        candidate_source="test",
    )

    assert remapped.vehicle_paths() == {
        "bev-a": ("trip-ice",),
        "bev-used": ("trip-bev",),
    }
    assert all(duty.vehicle_type == "BEV" for duty in remapped.duties)
    assert remapped.charging_slots == ()
    assert remapped.vehicle_soc_kwh_by_vehicle_slot == {}


def test_exchange_duty_suffixes_preserves_coverage_and_rebuilds_cross_arcs() -> None:
    first_trips = (_trip("a-1", "08:00"), _trip("a-2", "10:00"))
    second_trips = (_trip("b-1", "08:30"), _trip("b-2", "10:30"))
    plan = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="duty-ice",
                vehicle_type="ICE",
                legs=tuple(DutyLeg(trip) for trip in first_trips),
            ),
            VehicleDuty(
                duty_id="duty-bev",
                vehicle_type="BEV",
                legs=tuple(DutyLeg(trip) for trip in second_trips),
            ),
        ),
        charging_slots=(),
        served_trip_ids=("a-1", "a-2", "b-1", "b-2"),
        metadata={
            "duty_vehicle_map": {
                "duty-ice": "ice-1",
                "duty-bev": "bev-used",
            }
        },
    )
    context = DispatchContext(
        service_date="2025-08-05",
        trips=[*first_trips, *second_trips],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={},
        default_turnaround_min=10,
    )

    exchanged = _exchange_duty_suffixes(
        plan,
        first_duty_id="duty-ice",
        second_duty_id="duty-bev",
        first_split_index=1,
        second_split_index=1,
        vehicle_type_by_id={"ice-1": "ICE", "bev-used": "BEV"},
        dispatch_context=context,
        candidate_source="test_suffix_exchange",
    )

    assert exchanged is not None
    assert exchanged.vehicle_paths() == {
        "bev-used": ("b-1", "a-2"),
        "ice-1": ("a-1", "b-2"),
    }
    assert sorted(exchanged.served_trip_ids) == ["a-1", "a-2", "b-1", "b-2"]
    assert exchanged.charging_slots == ()
    assert exchanged.vehicle_soc_kwh_by_vehicle_slot == {}
    exchange = exchanged.metadata["phase4_seed_duty_suffix_exchange"]
    assert exchange["first_split_index"] == 1
    assert exchange["second_split_index"] == 1


def test_route_band_repartition_merge_rejects_changed_trip_coverage() -> None:
    seed = _seed_plan()
    invalid_repartition = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="replacement",
                vehicle_type="BEV",
                legs=(DutyLeg(_trip("trip-ice", "08:00")),),
            ),
        ),
        served_trip_ids=("trip-ice",),
        metadata={"duty_vehicle_map": {"replacement": "bev-a"}},
    )

    merged = _merge_route_band_repartition_plan(
        seed,
        repartitioned_plan=invalid_repartition,
        affected_vehicle_ids=("ice-1", "bev-used"),
        vehicle_type_by_id={"bev-a": "BEV"},
        metadata_updates={"source": "test"},
    )

    assert merged is None


def test_route_band_retry_budget_reserves_a_complete_feedback_pass() -> None:
    budget = _route_band_repartition_retry_budget(
        fair_group_budget_sec=90.0,
        minimum_stage2_time_sec=5,
        requested_feedback_max_iterations=1,
    )

    assert budget.total_time_limit_sec == 90
    assert budget.feedback_max_iterations == 1
    assert budget.solve_pass_count == 2
    assert budget.stage1_time_limit_sec > budget.stage2_time_limit_sec >= 5
    assert (
        budget.solve_pass_count
        * (budget.stage1_time_limit_sec + budget.stage2_time_limit_sec)
        + budget.reserved_overhead_sec
        <= budget.total_time_limit_sec
    )


def test_route_band_retry_budget_disables_unfunded_feedback() -> None:
    budget = _route_band_repartition_retry_budget(
        fair_group_budget_sec=4.0,
        minimum_stage2_time_sec=1,
        requested_feedback_max_iterations=1,
    )

    assert budget.feedback_max_iterations == 0
    assert budget.solve_pass_count == 1
    assert budget.stage1_time_limit_sec == 2
    assert budget.stage2_time_limit_sec == 1
    assert budget.reserved_overhead_sec == 1


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
@pytest.mark.parametrize(
    ("reduced_stage2_feasible", "feedback_applied"),
    ((True, False), (False, False), (True, True)),
)
def test_route_band_repartition_is_full_stage2_validated_before_selection(
    monkeypatch,
    reduced_stage2_feasible,
    feedback_applied,
) -> None:
    class _FakeFeasibilityChecker:
        def evaluate(self, _problem, _plan):
            return SimpleNamespace(feasible=True, errors=())

    class _FakeCostEvaluator:
        def evaluate(self, _problem, plan):
            has_ice = any(
                duty.vehicle_type == "ICE" for duty in plan.duties
            )
            return SimpleNamespace(
                total_cost=100.0 if has_ice else 80.0,
                evaluation_feasible=True,
            )

    trips = (
        _trip("a-1", "08:00"),
        _trip("a-2", "10:00"),
        _trip("b-1", "08:30"),
        _trip("b-2", "10:30"),
    )
    context = DispatchContext(
        service_date="2025-08-05",
        trips=list(trips),
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={},
        default_turnaround_min=10,
    )
    seed = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="duty-ice",
                vehicle_type="ICE",
                legs=(DutyLeg(trips[0]), DutyLeg(trips[1])),
            ),
            VehicleDuty(
                duty_id="duty-bev",
                vehicle_type="BEV",
                legs=(DutyLeg(trips[2]), DutyLeg(trips[3])),
            ),
        ),
        served_trip_ids=tuple(trip.trip_id for trip in trips),
        metadata={
            "duty_vehicle_map": {
                "duty-ice": "ice-1",
                "duty-bev": "bev-used",
            },
            "stage1_feasible": True,
            "stage2_feasible": True,
            "stage2_has_feasible_incumbent": True,
        },
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="route-band-repartition",
            timestep_min=60,
        ),
        dispatch_context=context,
        trips=tuple(
            ProblemTrip(
                trip_id=trip.trip_id,
                route_id=trip.route_id,
                origin=trip.origin,
                destination=trip.destination,
                departure_min=trip.departure_min,
                arrival_min=trip.arrival_min,
                distance_km=trip.distance_km,
                allowed_vehicle_types=trip.allowed_vehicle_types,
            )
            for trip in trips
        ),
        vehicles=(
            ProblemVehicle("ice-1", "ICE", "DEPOT"),
            ProblemVehicle("bev-used", "BEV", "DEPOT"),
            ProblemVehicle("bev-unused", "BEV", "DEPOT"),
        ),
        feasible_connections={
            "a-1": ("a-2", "b-2"),
            "b-1": ("a-2", "b-2"),
        },
        metadata={"fixed_route_band_mode": True},
    )
    monkeypatch.setattr(
        solver_adapter_module,
        "FeasibilityChecker",
        _FakeFeasibilityChecker,
    )
    monkeypatch.setattr(
        solver_adapter_module,
        "CostEvaluator",
        _FakeCostEvaluator,
    )
    adapter = GurobiMILPAdapter()
    reduced_stage1_calls = []
    full_stage2_calls = []
    full_stage2_sources = []

    def _fake_reduced_stage1(
        reduced_problem,
        _config,
        *,
        stage2_enabled,
        diagnostic_mode=False,
    ):
        assert stage2_enabled is True
        assert diagnostic_mode is False
        assert full_stage2_sources
        assert _config.time_limit_sec >= (
            _config.stage1_time_limit_sec + _config.stage2_time_limit_sec
        )
        assert reduced_problem.metadata["stage2_feedback_max_iterations"] == 1
        assert {vehicle.vehicle_type for vehicle in reduced_problem.vehicles} == {
            "BEV"
        }
        assert reduced_problem.metadata["minimum_used_bev_count"] == 2
        assert reduced_problem.metadata[
            "phase4_seed_route_band_repartition_maximum_used_vehicle_count"
        ] == 2
        assert len(reduced_problem.trips) == 4
        reduced_stage1_calls.append(reduced_problem)
        trip_by_id = reduced_problem.trip_by_id()
        repartitioned = AssignmentPlan(
            duties=(
                VehicleDuty(
                    duty_id="repartition-a",
                    vehicle_type="BEV",
                    legs=(
                        DutyLeg(trip_by_id["a-1"]),
                        DutyLeg(trip_by_id["b-2"]),
                    ),
                ),
                VehicleDuty(
                    duty_id="repartition-b",
                    vehicle_type="BEV",
                    legs=(
                        DutyLeg(trip_by_id["b-1"]),
                        DutyLeg(trip_by_id["a-2"]),
                    ),
                ),
            ),
            served_trip_ids=tuple(sorted(trip_by_id)),
            metadata={
                "duty_vehicle_map": {
                    "repartition-a": "bev-used",
                    "repartition-b": "bev-unused",
                },
                "stage1_feasible": True,
                "stage2_feasible": reduced_stage2_feasible,
                "stage2_has_feasible_incumbent": reduced_stage2_feasible,
                "stage2_solver_status": (
                    "optimal" if reduced_stage2_feasible else "time_limit"
                ),
                "stage2_feedback_iteration": int(feedback_applied),
                "stage2_feedback_history": (
                    [{"iteration": 0, "candidate_hash": "retry-hash"}]
                    if feedback_applied
                    else []
                ),
                "stage1_feasibility_no_good_cuts": (
                    [{"candidate_hash": "retry-hash"}]
                    if feedback_applied
                    else []
                ),
            },
        )
        return (
            MILPSolverOutcome(
                solver_status="optimal",
                used_backend="test-reduced-stage1-stage2",
                supports_exact_milp=True,
                has_feasible_incumbent=True,
                incumbent_count=1,
            ),
            repartitioned,
        )

    def _fake_full_stage2(full_problem, _config, plan, **_kwargs):
        assert full_problem.trips == problem.trips
        assert full_problem.vehicles == problem.vehicles
        assert full_problem.dispatch_context is problem.dispatch_context
        full_stage2_sources.append((plan.metadata or {}).get("source"))
        if (plan.metadata or {}).get("source") != (
            "phase4_seed_route_band_repartition_activation"
        ):
            return (
                MILPSolverOutcome(
                    solver_status="infeasible",
                    used_backend="test-full-stage2",
                    supports_exact_milp=True,
                    has_feasible_incumbent=False,
                ),
                plan,
            )
        assert set(plan.duties_by_vehicle()) == {"bev-used", "bev-unused"}
        assert sorted(plan.served_trip_ids) == sorted(
            trip.trip_id for trip in trips
        )
        full_stage2_calls.append(plan)
        solved = AssignmentPlan(
            **{
                **plan.__dict__,
                "metadata": {
                    **dict(plan.metadata or {}),
                    "stage2_feasible": True,
                    "stage2_has_feasible_incumbent": True,
                },
            }
        )
        return (
            MILPSolverOutcome(
                solver_status="optimal",
                used_backend="test-full-stage2",
                supports_exact_milp=True,
                has_feasible_incumbent=True,
                incumbent_count=1,
            ),
            solved,
        )

    monkeypatch.setattr(adapter, "_solve_thesis_two_stage", _fake_reduced_stage1)
    monkeypatch.setattr(
        adapter,
        "_solve_thesis_stage2_charging_dispatch",
        _fake_full_stage2,
    )

    selected, audit = (
        adapter.improve_phase4_seed_with_unused_bev_neighborhood(
            problem,
            OptimizationConfig(
                phase4_phase3_seed_unused_bev_neighborhood_enabled=True,
                phase4_phase3_seed_unused_bev_neighborhood_time_limit_sec=30,
                phase4_phase3_seed_route_band_repartition_time_limit_sec=30,
                phase4_phase3_seed_unused_bev_neighborhood_per_solve_sec=1,
                phase4_phase3_seed_unused_bev_neighborhood_max_evaluations=10,
                phase4_phase3_seed_powertrain_duty_swap_rounds=1,
                phase4_phase3_seed_unused_bev_identity_exchange_rounds=0,
            ),
            seed,
        )
    )

    assert len(reduced_stage1_calls) == 1
    assert full_stage2_sources[0] == (
        "phase4_seed_unused_bev_single_activation"
    )
    if reduced_stage2_feasible:
        assert len(full_stage2_calls) == 1
        assert full_stage2_sources[-1] == (
            "phase4_seed_route_band_repartition_activation"
        )
        assert set(selected.duties_by_vehicle()) == {
            "bev-used",
            "bev-unused",
        }
        assert audit["selected"] is True
        assert audit["selected_candidate_kind"] == (
            "route_band_repartition_activation"
        )
        assert audit["route_band_repartition_candidate_count"] == 1
        assert audit["route_band_repartition_full_feasible_count"] == 1
    else:
        assert full_stage2_calls == []
        assert set(selected.duties_by_vehicle()) == {"ice-1", "bev-used"}
        assert audit["selected"] is False
        assert audit["route_band_repartition_candidate_count"] == 0
        assert audit["route_band_repartition_full_feasible_count"] == 0
        assert audit["route_band_repartition_attempts"][0]["status"] == (
            "reduced_stage1_stage2_no_exact_all_bev_incumbent"
        )
    assert audit["weather_strategy_bias_applied"] is False
    assert audit["route_band_repartition_feedback_max_iterations"] == 1
    attempt = audit["route_band_repartition_attempts"][0]
    assert attempt["stage2_feedback_max_iterations"] == 1
    assert attempt["stage2_feedback_solve_pass_count"] == 2
    assert attempt["stage2_feedback_applied"] is feedback_applied
    assert len(attempt["stage2_feedback_history"]) == int(feedback_applied)
    assert attempt["stage2_feedback_iteration"] == int(feedback_applied)
    assert attempt["stage1_feasibility_no_good_cut_count"] == int(
        feedback_applied
    )
    assert attempt["reduced_stage2_solver_status"] == (
        "optimal" if reduced_stage2_feasible else "time_limit"
    )
    assert attempt["reduced_total_time_limit_sec"] >= (
        attempt["stage2_feedback_solve_pass_count"]
        * (
            attempt["reduced_stage1_time_limit_sec"]
            + attempt["reduced_stage2_time_limit_sec"]
        )
        + attempt["feedback_reserved_overhead_sec"]
    )


def test_suffix_exchange_can_activate_bev_when_whole_duty_replacement_cannot(
    monkeypatch,
) -> None:
    class _FakeFeasibilityChecker:
        def evaluate(self, _problem, _plan):
            return SimpleNamespace(feasible=True, errors=())

    class _FakeCostEvaluator:
        def evaluate(self, _problem, plan):
            has_ice = any(
                duty.vehicle_type == "ICE" for duty in plan.duties
            )
            return SimpleNamespace(
                total_cost=100.0 if has_ice else 80.0,
                evaluation_feasible=True,
            )

    trips = (
        _trip("a-1", "08:00"),
        _trip("a-2", "10:00"),
        _trip("b-1", "08:30"),
        _trip("b-2", "10:30"),
    )
    context = DispatchContext(
        service_date="2025-08-05",
        trips=list(trips),
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={},
        default_turnaround_min=10,
    )
    seed = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="duty-ice",
                vehicle_type="ICE",
                legs=(DutyLeg(trips[0]), DutyLeg(trips[1])),
            ),
            VehicleDuty(
                duty_id="duty-bev",
                vehicle_type="BEV",
                legs=(DutyLeg(trips[2]), DutyLeg(trips[3])),
            ),
        ),
        served_trip_ids=tuple(trip.trip_id for trip in trips),
        metadata={
            "duty_vehicle_map": {
                "duty-ice": "ice-1",
                "duty-bev": "bev-used",
            },
            "stage1_feasible": True,
            "stage2_feasible": True,
            "stage2_has_feasible_incumbent": True,
        },
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="suffix-activation",
            timestep_min=60,
        ),
        dispatch_context=context,
        trips=(),
        vehicles=(
            ProblemVehicle("ice-1", "ICE", "DEPOT"),
            ProblemVehicle("bev-used", "BEV", "DEPOT"),
            ProblemVehicle("bev-unused", "BEV", "DEPOT"),
        ),
    )
    monkeypatch.setattr(
        solver_adapter_module,
        "FeasibilityChecker",
        _FakeFeasibilityChecker,
    )
    monkeypatch.setattr(
        solver_adapter_module,
        "CostEvaluator",
        _FakeCostEvaluator,
    )
    adapter = GurobiMILPAdapter()

    def _fake_stage2(_problem, _config, plan, **_kwargs):
        paths = plan.vehicle_paths()
        suffix_reconstructed = set(paths.values()) == {
            ("a-1", "b-2"),
            ("b-1", "a-2"),
        }
        solved = AssignmentPlan(
            **{
                **plan.__dict__,
                "metadata": {
                    **dict(plan.metadata or {}),
                    "stage2_feasible": suffix_reconstructed,
                    "stage2_has_feasible_incumbent": suffix_reconstructed,
                },
            }
        )
        return (
            MILPSolverOutcome(
                solver_status=(
                    "optimal" if suffix_reconstructed else "infeasible"
                ),
                used_backend="test",
                supports_exact_milp=True,
                has_feasible_incumbent=suffix_reconstructed,
                incumbent_count=1 if suffix_reconstructed else 0,
            ),
            solved,
        )

    monkeypatch.setattr(
        adapter,
        "_solve_thesis_stage2_charging_dispatch",
        _fake_stage2,
    )

    selected, audit = (
        adapter.improve_phase4_seed_with_unused_bev_neighborhood(
            problem,
            OptimizationConfig(
                phase4_phase3_seed_unused_bev_neighborhood_enabled=True,
                phase4_phase3_seed_unused_bev_neighborhood_time_limit_sec=30,
                phase4_phase3_seed_unused_bev_neighborhood_per_solve_sec=1,
                phase4_phase3_seed_unused_bev_neighborhood_max_evaluations=20,
                phase4_phase3_seed_powertrain_duty_swap_rounds=1,
                phase4_phase3_seed_unused_bev_identity_exchange_rounds=0,
            ),
            seed,
        )
    )

    assert set(selected.duties_by_vehicle()) == {"bev-used", "bev-unused"}
    assert audit["selected"] is True
    assert audit["selected_candidate_kind"] == (
        "duty_suffix_exchange_activation_round_1"
    )
    assert audit["trip_paths_modified"] is True
    assert audit["selected_used_bev"] == 2
    assert audit["selected_used_ice"] == 0
    assert audit["duty_suffix_exchange_candidates_dispatch_feasible"] == 1


def test_unused_bev_neighborhood_selects_only_exact_lower_cost_candidate(
    monkeypatch,
) -> None:
    class _FakeFeasibilityChecker:
        def evaluate(self, _problem, _plan):
            return SimpleNamespace(feasible=True, errors=())

    class _FakeCostEvaluator:
        def evaluate(self, _problem, plan):
            used_ids = set(plan.duties_by_vehicle())
            if "ice-1" in used_ids:
                cost = 100.0
            elif used_ids == {"bev-a", "bev-b"}:
                cost = 70.0
            elif used_ids == {"bev-used", "bev-b"}:
                cost = 75.0
            else:
                cost = 80.0
            return SimpleNamespace(
                total_cost=cost,
                evaluation_feasible=True,
            )

    monkeypatch.setattr(
        solver_adapter_module,
        "FeasibilityChecker",
        _FakeFeasibilityChecker,
    )
    monkeypatch.setattr(
        solver_adapter_module,
        "CostEvaluator",
        _FakeCostEvaluator,
    )
    adapter = GurobiMILPAdapter()

    def _fake_stage2(_problem, _config, plan, **_kwargs):
        solved = AssignmentPlan(
            **{
                **plan.__dict__,
                "metadata": {
                    **dict(plan.metadata or {}),
                    "stage2_feasible": True,
                    "stage2_has_feasible_incumbent": True,
                },
            }
        )
        return (
            MILPSolverOutcome(
                solver_status="optimal",
                used_backend="test",
                supports_exact_milp=True,
                has_feasible_incumbent=True,
                incumbent_count=1,
            ),
            solved,
        )

    monkeypatch.setattr(
        adapter,
        "_solve_thesis_stage2_charging_dispatch",
        _fake_stage2,
    )

    selected, audit = (
        adapter.improve_phase4_seed_with_unused_bev_neighborhood(
            _problem(),
            OptimizationConfig(
                phase4_phase3_seed_unused_bev_neighborhood_enabled=True,
                phase4_phase3_seed_unused_bev_neighborhood_time_limit_sec=30,
                phase4_phase3_seed_unused_bev_neighborhood_per_solve_sec=1,
                phase4_phase3_seed_unused_bev_neighborhood_max_evaluations=20,
                phase4_phase3_seed_unused_bev_identity_exchange_rounds=2,
            ),
            _seed_plan(),
        )
    )

    assert set(selected.duties_by_vehicle()) == {"bev-a", "bev-b"}
    assert audit["selected"] is True
    assert audit["selected_canonical_cost_jpy"] == 70.0
    assert audit["selected_cost_improvement_jpy"] == 30.0
    assert audit["selected_used_bev"] == 2
    assert audit["selected_used_ice"] == 0
    assert audit["maximum_observed_used_bev"] == 2
    assert audit["weather_strategy_bias_applied"] is False
    assert audit["global_optimality_claimed"] is False
    assert audit["unused_bev_exact_clone_equivalence_classes"] == [
        ["bev-a", "bev-b"]
    ]
    assert audit["pairwise_representative_evaluation_count"] == 1
    assert audit["inferred_equivalent_adjacency_count"] == 1

    class _ExpensiveBevCostEvaluator:
        def evaluate(self, _problem, plan):
            used_ids = set(plan.duties_by_vehicle())
            cost = 100.0 if "ice-1" in used_ids else 120.0
            return SimpleNamespace(
                total_cost=cost,
                evaluation_feasible=True,
            )

    monkeypatch.setattr(
        solver_adapter_module,
        "CostEvaluator",
        _ExpensiveBevCostEvaluator,
    )
    expensive_bev_adapter = GurobiMILPAdapter()
    monkeypatch.setattr(
        expensive_bev_adapter,
        "_solve_thesis_stage2_charging_dispatch",
        _fake_stage2,
    )
    retained, expensive_audit = (
        expensive_bev_adapter.improve_phase4_seed_with_unused_bev_neighborhood(
            _problem(),
            OptimizationConfig(
                phase4_phase3_seed_unused_bev_neighborhood_enabled=True,
                phase4_phase3_seed_unused_bev_neighborhood_time_limit_sec=30,
                phase4_phase3_seed_unused_bev_neighborhood_per_solve_sec=1,
                phase4_phase3_seed_unused_bev_neighborhood_max_evaluations=20,
                phase4_phase3_seed_unused_bev_identity_exchange_rounds=2,
            ),
            _seed_plan(),
        )
    )

    assert set(retained.duties_by_vehicle()) == {"ice-1", "bev-used"}
    assert expensive_audit["selected"] is False
    assert expensive_audit["selected_canonical_cost_jpy"] == 100.0
    assert expensive_audit["maximum_observed_used_bev"] == 2
    assert expensive_audit["maximum_bev_candidate_canonical_cost_jpy"] == 120.0


def test_unused_bev_neighborhood_tries_full_ice_retirement_first(
    monkeypatch,
) -> None:
    class _FakeFeasibilityChecker:
        def evaluate(self, _problem, _plan):
            return SimpleNamespace(feasible=True, errors=())

    class _FakeCostEvaluator:
        def evaluate(self, _problem, plan):
            has_ice = any(
                duty.vehicle_type == "ICE" for duty in plan.duties
            )
            return SimpleNamespace(
                total_cost=100.0 if has_ice else 70.0,
                evaluation_feasible=True,
            )

    monkeypatch.setattr(
        solver_adapter_module,
        "FeasibilityChecker",
        _FakeFeasibilityChecker,
    )
    monkeypatch.setattr(
        solver_adapter_module,
        "CostEvaluator",
        _FakeCostEvaluator,
    )
    adapter = GurobiMILPAdapter()
    stage2_sources: list[str] = []

    def _fake_stage2(_problem, _config, plan, **_kwargs):
        stage2_sources.append(str((plan.metadata or {}).get("source") or ""))
        solved = AssignmentPlan(
            **{
                **plan.__dict__,
                "metadata": {
                    **dict(plan.metadata or {}),
                    "stage2_feasible": True,
                    "stage2_has_feasible_incumbent": True,
                },
            }
        )
        return (
            MILPSolverOutcome(
                solver_status="optimal",
                used_backend="test",
                supports_exact_milp=True,
                has_feasible_incumbent=True,
                incumbent_count=1,
            ),
            solved,
        )

    monkeypatch.setattr(
        adapter,
        "_solve_thesis_stage2_charging_dispatch",
        _fake_stage2,
    )
    trips = (
        _trip("ice-a-trip", "08:00"),
        _trip("ice-b-trip", "09:00"),
        _trip("bev-trip", "10:00"),
    )
    seed = AssignmentPlan(
        duties=(
            VehicleDuty(
                duty_id="ice-a-duty",
                vehicle_type="ICE",
                legs=(DutyLeg(trips[0]),),
            ),
            VehicleDuty(
                duty_id="ice-b-duty",
                vehicle_type="ICE",
                legs=(DutyLeg(trips[1]),),
            ),
            VehicleDuty(
                duty_id="bev-duty",
                vehicle_type="BEV",
                legs=(DutyLeg(trips[2]),),
            ),
        ),
        served_trip_ids=tuple(trip.trip_id for trip in trips),
        metadata={
            "duty_vehicle_map": {
                "ice-a-duty": "ice-a",
                "ice-b-duty": "ice-b",
                "bev-duty": "bev-used",
            },
            "stage1_feasible": True,
            "stage2_feasible": True,
            "stage2_has_feasible_incumbent": True,
        },
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="direct-full-retirement",
            timestep_min=60,
        ),
        dispatch_context=SimpleNamespace(),
        trips=(),
        vehicles=(
            ProblemVehicle("ice-a", "ICE", "DEPOT"),
            ProblemVehicle("ice-b", "ICE", "DEPOT"),
            ProblemVehicle("bev-used", "BEV", "DEPOT"),
            ProblemVehicle("bev-a", "BEV", "DEPOT"),
            ProblemVehicle("bev-b", "BEV", "DEPOT"),
        ),
    )

    selected, audit = (
        adapter.improve_phase4_seed_with_unused_bev_neighborhood(
            problem,
            OptimizationConfig(
                phase4_phase3_seed_unused_bev_neighborhood_enabled=True,
                phase4_phase3_seed_unused_bev_neighborhood_time_limit_sec=30,
                phase4_phase3_seed_unused_bev_neighborhood_per_solve_sec=1,
                phase4_phase3_seed_unused_bev_neighborhood_max_evaluations=10,
                phase4_phase3_seed_powertrain_duty_swap_rounds=2,
                phase4_phase3_seed_unused_bev_identity_exchange_rounds=2,
            ),
            seed,
        )
    )

    assert stage2_sources == ["phase4_seed_direct_full_ice_retirement"]
    assert set(selected.duties_by_vehicle()) == {
        "bev-a",
        "bev-b",
        "bev-used",
    }
    assert audit["selected_candidate_kind"] == "direct_full_ice_retirement"
    assert audit["selected_used_bev"] == 3
    assert audit["selected_used_ice"] == 0
    assert audit["candidate_evaluation_count"] == 1
    assert audit["direct_full_ice_retirement_short_circuit_applied"] is True
    assert audit["termination_reason"] == (
        "direct_full_ice_retirement_strict_cost_improvement"
    )


def test_pairwise_search_reserves_and_validates_cumulative_matching(
    monkeypatch,
) -> None:
    class _FakeFeasibilityChecker:
        def evaluate(self, _problem, _plan):
            return SimpleNamespace(feasible=True, errors=())

    class _FakeCostEvaluator:
        def evaluate(self, _problem, plan):
            used_bev = sum(
                duty.vehicle_type == "BEV" for duty in plan.duties
            )
            return SimpleNamespace(
                total_cost=100.0 - 10.0 * used_bev,
                evaluation_feasible=True,
            )

    monkeypatch.setattr(
        solver_adapter_module,
        "FeasibilityChecker",
        _FakeFeasibilityChecker,
    )
    monkeypatch.setattr(
        solver_adapter_module,
        "CostEvaluator",
        _FakeCostEvaluator,
    )
    adapter = GurobiMILPAdapter()

    def _fake_stage2(_problem, _config, plan, **_kwargs):
        used_bev = sum(duty.vehicle_type == "BEV" for duty in plan.duties)
        feasible = used_bev <= 2
        solved = AssignmentPlan(
            **{
                **plan.__dict__,
                "metadata": {
                    **dict(plan.metadata or {}),
                    "stage2_feasible": feasible,
                    "stage2_has_feasible_incumbent": feasible,
                },
            }
        )
        return (
            MILPSolverOutcome(
                solver_status="optimal" if feasible else "infeasible",
                used_backend="test",
                supports_exact_milp=True,
                has_feasible_incumbent=feasible,
                incumbent_count=1 if feasible else 0,
            ),
            solved,
        )

    monkeypatch.setattr(
        adapter,
        "_solve_thesis_stage2_charging_dispatch",
        _fake_stage2,
    )
    trips = tuple(
        _trip(f"trip-{index}", f"{8 + index:02d}:00")
        for index in range(4)
    )
    seed = AssignmentPlan(
        duties=tuple(
            VehicleDuty(
                duty_id=f"duty-{index}",
                vehicle_type="ICE",
                legs=(DutyLeg(trip),),
            )
            for index, trip in enumerate(trips)
        ),
        served_trip_ids=tuple(trip.trip_id for trip in trips),
        metadata={
            "duty_vehicle_map": {
                f"duty-{index}": f"ice-{index}"
                for index in range(4)
            },
            "stage1_feasible": True,
            "stage2_feasible": True,
            "stage2_has_feasible_incumbent": True,
        },
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="round-robin-reserved-matching",
            timestep_min=60,
        ),
        dispatch_context=SimpleNamespace(),
        trips=(),
        vehicles=tuple(
            [
                ProblemVehicle(f"ice-{index}", "ICE", "DEPOT")
                for index in range(4)
            ]
            + [
                ProblemVehicle(
                    f"bev-{index}",
                    "BEV",
                    "DEPOT",
                    initial_soc=0.5 + index * 0.1,
                )
                for index in range(3)
            ]
        ),
    )

    selected, audit = (
        adapter.improve_phase4_seed_with_unused_bev_neighborhood(
            problem,
            OptimizationConfig(
                phase4_phase3_seed_unused_bev_neighborhood_enabled=True,
                phase4_phase3_seed_unused_bev_neighborhood_time_limit_sec=30,
                phase4_phase3_seed_unused_bev_neighborhood_per_solve_sec=1,
                phase4_phase3_seed_unused_bev_neighborhood_max_evaluations=9,
                phase4_phase3_seed_powertrain_duty_swap_rounds=0,
                phase4_phase3_seed_unused_bev_identity_exchange_rounds=0,
            ),
            seed,
        )
    )

    assert audit["direct_full_ice_retirement_status"] == (
        "skipped_insufficient_unused_bev"
    )
    assert audit["pairwise_candidate_order"] == (
        "round_robin_ice_duties_with_rotated_target_classes"
    )
    assert audit["matching_validation_evaluation_reserve"] == 5
    assert audit["pairwise_evaluation_limit"] == 4
    assert audit["pairwise_representative_evaluation_count"] == 4
    assert all(
        audit["single_activation_feasibility_graph"][f"ice-{index}"]
        for index in range(4)
    )
    assert audit["maximum_cardinality_pairwise_matching_size"] == 3
    assert audit["cumulative_mapping_seeded_from_pairwise_edge"] is True
    assert audit["selected_candidate_kind"] == (
        "cumulative_matching_activation"
    )
    assert audit["selected_used_bev"] == 2
    assert audit["selected_used_ice"] == 2
    assert set(selected.duties_by_vehicle()).issuperset(
        {"ice-2", "ice-3"}
    )
