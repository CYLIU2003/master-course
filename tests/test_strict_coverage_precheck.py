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


class _AlwaysConnectedContext:
    def get_deadhead_min(self, from_stop: str, to_stop: str) -> int:
        return 0

    def get_turnaround_min(self, stop: str) -> int:
        return 0

    def locations_equivalent(self, left: str, right: str) -> bool:
        return left == right

    def has_location_data(self, stop: str) -> bool:
        return True


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


def _family_variant_problem(
    *,
    include_family_metadata: bool,
    available_vehicle_count: int,
) -> CanonicalOptimizationProblem:
    family = "渋21" if include_family_metadata else ""
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="strict-precheck-family-variants",
            service_coverage_mode="strict",
            allow_same_day_depot_cycles=False,
        ),
        dispatch_context=_AlwaysConnectedContext(),
        trips=(
            ProblemTrip(
                trip_id="t1",
                route_id="variant_a",
                origin="A",
                destination="B",
                departure_min=8 * 60,
                arrival_min=8 * 60 + 40,
                distance_km=6.0,
                allowed_vehicle_types=("ICE",),
                route_family_code=family,
            ),
            ProblemTrip(
                trip_id="t2",
                route_id="variant_b",
                origin="B",
                destination="C",
                departure_min=8 * 60 + 45,
                arrival_min=9 * 60 + 25,
                distance_km=6.0,
                allowed_vehicle_types=("ICE",),
                route_family_code=family,
            ),
            ProblemTrip(
                trip_id="t3",
                route_id="variant_c",
                origin="A",
                destination="B",
                departure_min=8 * 60 + 10,
                arrival_min=8 * 60 + 50,
                distance_km=6.0,
                allowed_vehicle_types=("ICE",),
                route_family_code=family,
            ),
            ProblemTrip(
                trip_id="t4",
                route_id="variant_d",
                origin="B",
                destination="C",
                departure_min=8 * 60 + 55,
                arrival_min=9 * 60 + 35,
                distance_km=6.0,
                allowed_vehicle_types=("ICE",),
                route_family_code=family,
            ),
        ),
        vehicles=tuple(
            ProblemVehicle(
                vehicle_id=f"veh-{idx + 1}",
                vehicle_type="ICE",
                home_depot_id="DEPOT",
            )
            for idx in range(available_vehicle_count)
        ),
        metadata={
            "service_coverage_mode": "strict",
            "fixed_route_band_mode": True,
            "allow_same_day_depot_cycles": False,
        },
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


def test_strict_precheck_uses_route_family_for_fixed_route_band_grouping() -> None:
    with_family = evaluate_strict_coverage_precheck(
        _family_variant_problem(include_family_metadata=True, available_vehicle_count=1)
    )
    without_family = evaluate_strict_coverage_precheck(
        _family_variant_problem(include_family_metadata=False, available_vehicle_count=1)
    )

    assert with_family.checked is True
    assert with_family.infeasible is True
    assert with_family.relaxed_vehicle_lower_bound == 2
    assert with_family.available_vehicle_count == 1

    assert without_family.checked is True
    assert without_family.infeasible is True
    assert without_family.relaxed_vehicle_lower_bound == 4
    assert without_family.available_vehicle_count == 1


def test_strict_precheck_prepared_like_scope_avoids_false_infeasible_with_family_metadata() -> None:
    result = evaluate_strict_coverage_precheck(
        _family_variant_problem(include_family_metadata=True, available_vehicle_count=2)
    )

    assert result.checked is True
    assert result.infeasible is False
    assert result.relaxed_vehicle_lower_bound == 2
    assert result.available_vehicle_count == 2
