from __future__ import annotations

from types import SimpleNamespace

from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationMode,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.milp.engine import MILPOptimizer
from src.optimization.milp.solver_adapter import MILPSolverOutcome


class _Breakdown:
    def to_dict(self) -> dict[str, float]:
        return {"objective_value": 0.0}


def test_milp_optimizer_avoids_full_model_build_for_metadata(monkeypatch) -> None:
    optimizer = MILPOptimizer()

    class _FakeBuilder:
        def enumerate_assignment_pairs(self, problem):
            return [("veh-1", "t1")]

        def enumerate_arc_pairs(self, problem, trip_by_id):
            return []

        def build(self, problem):
            raise AssertionError("full MILP model build should not run for metadata only")

    class _FakeAdapter:
        def solve(self, problem, config):
            return (
                MILPSolverOutcome(
                    solver_status="optimal",
                    used_backend="fake",
                    supports_exact_milp=True,
                ),
                AssignmentPlan(served_trip_ids=("t1",)),
            )

    monkeypatch.setattr(optimizer, "_builder", _FakeBuilder())
    monkeypatch.setattr(optimizer, "_adapter", _FakeAdapter())
    monkeypatch.setattr(
        optimizer,
        "_feasibility",
        SimpleNamespace(
            evaluate=lambda problem, plan: SimpleNamespace(
                feasible=True,
                warnings=(),
                errors=(),
            )
        ),
    )
    monkeypatch.setattr(
        optimizer,
        "_evaluator",
        SimpleNamespace(
            evaluate=lambda problem, plan: _Breakdown(),
            build_plan_ledgers=lambda problem, plan, breakdown: ((), ()),
        ),
    )

    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s1", timestep_min=60),
        dispatch_context=SimpleNamespace(),
        trips=(
            ProblemTrip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_min=480,
                arrival_min=510,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=12.0,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                battery_capacity_kwh=300.0,
                reserve_soc=30.0,
            ),
        ),
    )

    result = optimizer.solve(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, time_limit_sec=15),
    )

    assert result.solver_status == "optimal"
    assert result.solver_metadata["model_stats"]["variables"]["assignment"] == 1
    assert result.solver_metadata["solver_objective_matches_accounting_total"] is True
    assert result.solver_metadata["eligible_for_main_benchmark"] is True
    assert result.solver_metadata["candidate_generation_mode"] == (
        "full_network_branch_and_cut"
    )


def test_milp_optimizer_propagates_phase_metadata(monkeypatch) -> None:
    optimizer = MILPOptimizer()

    class _FakeBuilder:
        def enumerate_assignment_pairs(self, problem):
            return []

        def enumerate_arc_pairs(self, problem, trip_by_id):
            return []

        def arc_pruning_summary(self, problem, trip_by_id):
            return {}

    class _FakeAdapter:
        def solve(self, problem, config):
            return (
                MILPSolverOutcome(
                    solver_status="phase2_assignment_feasible",
                    used_backend="fake",
                    supports_exact_milp=False,
                ),
                AssignmentPlan(
                    served_trip_ids=("t1",),
                    metadata={
                        "phase": "phase2_assignment_only",
                        "result_class": "assignment_only_result",
                        "research_kpi_eligible": False,
                        "charging_dispatch_evaluated": False,
                        "soc_constraints_evaluated": False,
                        "supports_assignment_milp": True,
                        "stage1_vehicle_count_lower_bound": 1,
                        "stage1_vehicle_count_lower_bound_constraint_count": 1,
                        "stage1_vehicle_count_lower_bound_semantics": (
                            "relaxed_dispatch_feasible_minimum_path_cover_vehicle_day_lb"
                        ),
                    },
                ),
            )

    monkeypatch.setattr(optimizer, "_builder", _FakeBuilder())
    monkeypatch.setattr(optimizer, "_adapter", _FakeAdapter())
    monkeypatch.setattr(
        optimizer,
        "_feasibility",
        SimpleNamespace(
            evaluate=lambda problem, plan: SimpleNamespace(
                feasible=True,
                warnings=(),
                errors=(),
                metrics={},
            )
        ),
    )
    monkeypatch.setattr(
        optimizer,
        "_evaluator",
        SimpleNamespace(
            evaluate=lambda problem, plan: _Breakdown(),
            build_plan_ledgers=lambda problem, plan, breakdown: ((), ()),
        ),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s1", timestep_min=60),
        dispatch_context=SimpleNamespace(),
        trips=(
            ProblemTrip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_min=480,
                arrival_min=510,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
                energy_kwh=12.0,
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                battery_capacity_kwh=300.0,
                reserve_soc=30.0,
            ),
        ),
        metadata={
            "solver_objective_matches_accounting_total": False,
            "strict_coverage_precheck": {
                "checked": True,
                "relaxed_vehicle_lower_bound": 1,
            },
        },
    )

    result = optimizer.solve(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, phase="phase2_assignment_only"),
    )

    assert result.solver_metadata["phase"] == "phase2_assignment_only"
    assert result.solver_metadata["result_class"] == "assignment_only_result"
    assert result.solver_metadata["research_kpi_eligible"] is False
    assert result.solver_metadata["charging_dispatch_evaluated"] is False
    assert result.solver_metadata["soc_constraints_evaluated"] is False
    assert result.solver_metadata["solver_objective_matches_accounting_total"] is False
    assert result.solver_metadata["stage1_vehicle_count_lower_bound"] == 1
    assert result.solver_metadata["stage1_vehicle_count_lower_bound_constraint_count"] == 1
    assert result.solver_metadata["strict_coverage_precheck"][
        "relaxed_vehicle_lower_bound"
    ] == 1
    assert result.solver_metadata["eligible_for_main_benchmark"] is False
    assert result.solver_metadata["eligible_for_appendix_benchmark"] is True
    assert result.solver_metadata["candidate_generation_mode"] == (
        "successor_pruned_branch_and_cut"
    )
    assert "Successor-pruned" in result.solver_metadata["comparison_note"]


def test_research_phase3_does_not_publish_stage1_candidate_when_stage2_is_infeasible(monkeypatch) -> None:
    optimizer = MILPOptimizer()

    class _FakeBuilder:
        def enumerate_assignment_pairs(self, problem):
            return [("veh-1", "t1")]

        def enumerate_arc_pairs(self, problem, trip_by_id):
            return []

        def arc_pruning_summary(self, problem, trip_by_id):
            return {}

    class _FakeAdapter:
        def solve(self, problem, config):
            return (
                MILPSolverOutcome(
                    solver_status="infeasible",
                    used_backend="fake_two_stage",
                    supports_exact_milp=True,
                    has_feasible_incumbent=False,
                ),
                AssignmentPlan(
                    served_trip_ids=("t1",),
                    metadata={
                        "phase": "phase3_two_stage",
                        "stage1_feasible": True,
                        "stage2_feasible": False,
                        "stage1_has_feasible_incumbent": True,
                        "stage2_has_feasible_incumbent": False,
                        "supports_two_stage_milp": False,
                        "supports_integrated_exact_milp": False,
                    },
                ),
            )

    monkeypatch.setattr(optimizer, "_builder", _FakeBuilder())
    monkeypatch.setattr(optimizer, "_adapter", _FakeAdapter())
    monkeypatch.setattr(
        optimizer,
        "_feasibility",
        SimpleNamespace(
            evaluate=lambda problem, plan: SimpleNamespace(
                feasible=not bool(plan.unserved_trip_ids),
                warnings=(),
                errors=("stage2 candidate was not published",) if plan.unserved_trip_ids else (),
                metrics={},
            )
        ),
    )
    monkeypatch.setattr(
        optimizer,
        "_evaluator",
        SimpleNamespace(
            evaluate=lambda problem, plan: _Breakdown(),
            build_plan_ledgers=lambda problem, plan, breakdown: ((), ()),
        ),
    )
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s-stage2-infeasible", timestep_min=60),
        dispatch_context=SimpleNamespace(),
        trips=(
            ProblemTrip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_min=480,
                arrival_min=510,
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
            ),
        ),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
            ),
        ),
    )

    result = optimizer.solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase3_two_stage",
            research_run=True,
        ),
    )

    assert result.plan.served_trip_ids == ()
    assert result.plan.unserved_trip_ids == ("t1",)
    assert result.plan.metadata["research_candidate_only"] is True
    assert result.plan.metadata["assignment_candidate_available"] is True
    assert result.solver_metadata["stage1_feasible"] is True
    assert result.solver_metadata["stage2_feasible"] is False

    ordinary_result = optimizer.solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            phase="phase3_two_stage",
            research_run=False,
        ),
    )
    assert ordinary_result.plan.served_trip_ids == ()
    assert ordinary_result.plan.unserved_trip_ids == ("t1",)
    assert ordinary_result.plan.metadata["stage2_candidate_only"] is True
