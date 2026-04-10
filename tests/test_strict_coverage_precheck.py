from __future__ import annotations

from types import SimpleNamespace

from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    OptimizationConfig,
    OptimizationMode,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.common.strict_precheck import evaluate_strict_coverage_precheck
from src.optimization.engine import OptimizationEngine


def _overlapping_problem(*, service_coverage_mode: str = "strict") -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="strict-precheck",
            service_coverage_mode=service_coverage_mode,
        ),
        dispatch_context=SimpleNamespace(),
        trips=(
            ProblemTrip(
                trip_id="t1",
                route_id="r",
                origin="A",
                destination="B",
                departure_min=8 * 60,
                arrival_min=9 * 60,
                distance_km=10.0,
                allowed_vehicle_types=("ICE",),
            ),
            ProblemTrip(
                trip_id="t2",
                route_id="r",
                origin="C",
                destination="D",
                departure_min=8 * 60 + 30,
                arrival_min=9 * 60 + 30,
                distance_km=10.0,
                allowed_vehicle_types=("ICE",),
            ),
        ),
        vehicles=(
            ProblemVehicle(vehicle_id="veh-1", vehicle_type="ICE", home_depot_id="DEPOT"),
        ),
        metadata={"service_coverage_mode": service_coverage_mode},
    )


def test_strict_precheck_proves_vehicle_lower_bound_infeasible() -> None:
    result = evaluate_strict_coverage_precheck(_overlapping_problem())

    assert result.checked is True
    assert result.infeasible is True
    assert result.relaxed_vehicle_lower_bound == 2
    assert result.available_vehicle_count == 1
    assert result.reason == "strict_relaxed_path_cover_requires_more_vehicles_than_available"


def test_strict_precheck_is_skipped_for_penalized_coverage() -> None:
    result = evaluate_strict_coverage_precheck(
        _overlapping_problem(service_coverage_mode="penalized")
    )

    assert result.checked is False
    assert result.infeasible is False


def test_engine_short_circuits_strict_precheck_infeasible_problem() -> None:
    result = OptimizationEngine().solve(
        _overlapping_problem(),
        OptimizationConfig(mode=OptimizationMode.ALNS, time_limit_sec=60),
    )

    precheck = result.solver_metadata["strict_coverage_precheck"]
    assert result.solver_status == "SOLVED_INFEASIBLE"
    assert result.feasible is False
    assert result.objective_value == float("inf")
    assert result.incumbent_history == ()
    assert result.solver_metadata["candidate_generation_mode"] == "strict_coverage_precheck"
    assert result.solver_metadata["termination_reason"] == "strict_coverage_precheck_infeasible"
    assert precheck["relaxed_vehicle_lower_bound"] == 2
    assert precheck["available_vehicle_count"] == 1
