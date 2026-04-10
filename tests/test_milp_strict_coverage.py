from __future__ import annotations

from types import SimpleNamespace

import pytest

import src.optimization.milp.solver_adapter as solver_adapter_module
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.milp.solver_adapter import GurobiMILPAdapter


def _problem(*, service_coverage_mode: str, baseline_plan: AssignmentPlan) -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="strict-milp",
            service_coverage_mode=service_coverage_mode,
        ),
        dispatch_context=SimpleNamespace(),
        trips=(
            ProblemTrip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_min=480,
                arrival_min=510,
                distance_km=5.0,
                allowed_vehicle_types=("ICE",),
            ),
            ProblemTrip(
                trip_id="t2",
                route_id="r1",
                origin="B",
                destination="C",
                departure_min=540,
                arrival_min=570,
                distance_km=5.0,
                allowed_vehicle_types=("ICE",),
            ),
        ),
        vehicles=(
            ProblemVehicle(vehicle_id="veh-1", vehicle_type="ICE", home_depot_id="DEPOT"),
        ),
        baseline_plan=baseline_plan,
        metadata={"service_coverage_mode": service_coverage_mode},
    )


def test_gurobi_unavailable_strict_mode_does_not_return_partial_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(solver_adapter_module, "is_gurobi_available", lambda: False)

    problem = _problem(
        service_coverage_mode="strict",
        baseline_plan=AssignmentPlan(
            served_trip_ids=("t1",),
            unserved_trip_ids=("t2",),
            metadata={"source": "dispatch_baseline"},
        ),
    )
    outcome, plan = GurobiMILPAdapter().solve(problem, OptimizationConfig())

    assert outcome.has_feasible_incumbent is False
    assert outcome.solver_status == "gurobi_unavailable_strict_infeasible"
    assert plan.unserved_trip_ids == ("t1", "t2")


def test_gurobi_unavailable_penalized_mode_can_return_partial_baseline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(solver_adapter_module, "is_gurobi_available", lambda: False)

    baseline_plan = AssignmentPlan(
        served_trip_ids=("t1",),
        unserved_trip_ids=("t2",),
        metadata={"source": "dispatch_baseline"},
    )
    problem = _problem(
        service_coverage_mode="penalized",
        baseline_plan=baseline_plan,
    )
    outcome, plan = GurobiMILPAdapter().solve(problem, OptimizationConfig())

    assert outcome.has_feasible_incumbent is True
    assert outcome.solver_status == "gurobi_unavailable_baseline"
    assert plan.unserved_trip_ids == ("t2",)
