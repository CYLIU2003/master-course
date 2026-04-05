from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.milp.engine import MILPOptimizer
from src.optimization.milp.solver_adapter import GurobiMILPAdapter


def _problem_with_baseline() -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
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
        baseline_plan=AssignmentPlan(
            served_trip_ids=("t1",),
            unserved_trip_ids=(),
            metadata={"source": "dispatch_baseline"},
        ),
    )


def test_baseline_fallback_marks_non_exact_time_limit_baseline() -> None:
    adapter = GurobiMILPAdapter()
    problem = _problem_with_baseline()

    fallback = adapter._baseline_fallback(
        problem,
        fallback_status="time_limit_baseline",
        source="dispatch_baseline_after_time_limit_no_incumbent",
        solver_status="time_limit",
        relaxed_partial_service=False,
    )

    assert fallback is not None
    outcome, plan = fallback
    assert outcome.solver_status == "time_limit_baseline"
    assert outcome.used_backend == "gurobi"
    assert outcome.supports_exact_milp is False
    assert plan.served_trip_ids == ("t1",)
    assert plan.metadata["source"] == "dispatch_baseline_after_time_limit_no_incumbent"
    assert plan.metadata["status"] == "time_limit_baseline"
    assert plan.metadata["milp_status"] == "time_limit"
    assert plan.metadata["milp_backend"] == "gurobi"
    assert plan.metadata["auto_relaxed_allow_partial_service"] is False
    assert problem.baseline_plan is not None
    assert problem.baseline_plan.metadata["source"] == "dispatch_baseline"


def test_baseline_fallback_requires_a_served_baseline_plan() -> None:
    adapter = GurobiMILPAdapter()
    problem = replace(
        _problem_with_baseline(),
        baseline_plan=AssignmentPlan(served_trip_ids=(), unserved_trip_ids=("t1",)),
    )

    fallback = adapter._baseline_fallback(
        problem,
        fallback_status="time_limit_baseline",
        source="dispatch_baseline_after_time_limit_no_incumbent",
        solver_status="time_limit",
        relaxed_partial_service=False,
    )

    assert fallback is None


def test_milp_optimizer_termination_reason_covers_baseline_fallbacks() -> None:
    optimizer = MILPOptimizer()

    assert optimizer._termination_reason("time_limit_baseline") == "time_limit"
    assert optimizer._termination_reason("auto_relaxed_baseline") == "baseline_after_relax"
