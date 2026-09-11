from __future__ import annotations

from src.dispatch.models import DispatchContext, DutyLeg, Trip, VehicleDuty
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.milp.model_builder import MILPModelBuilder


def _trip(
    trip_id: str,
    departure_min: int,
    arrival_min: int,
    route_family_code: str,
    allowed_vehicle_types: tuple[str, ...] = ("BEV",),
) -> ProblemTrip:
    return ProblemTrip(
        trip_id=trip_id,
        route_id=f"route-{trip_id}",
        origin="A",
        destination="B",
        departure_min=departure_min,
        arrival_min=arrival_min,
        distance_km=1.0,
        allowed_vehicle_types=allowed_vehicle_types,
        route_family_code=route_family_code,
    )


def _dispatch_trip(problem_trip: ProblemTrip) -> Trip:
    def hhmm(value: int) -> str:
        return f"{value // 60:02d}:{value % 60:02d}"

    return Trip(
        trip_id=problem_trip.trip_id,
        route_id=problem_trip.route_id,
        origin=problem_trip.origin,
        destination=problem_trip.destination,
        departure_time=hhmm(problem_trip.departure_min % 1440),
        arrival_time=hhmm(problem_trip.arrival_min % 1440),
        distance_km=problem_trip.distance_km,
        allowed_vehicle_types=problem_trip.allowed_vehicle_types,
        route_family_code=problem_trip.route_family_code,
    )


def _problem(*, successor_limit: object = 1, with_baseline: bool = True) -> CanonicalOptimizationProblem:
    trips = (
        _trip("from", 60, 120, "family-a"),
        _trip("same-day-other-family", 180, 240, "family-b"),
        _trip("same-day-same-family", 300, 360, "family-a"),
        _trip("next-day-first", 1500, 1560, "family-c"),
        _trip("next-day-baseline", 1600, 1660, "family-c"),
    )
    dispatch_trips = [_dispatch_trip(trip) for trip in trips]
    baseline = None
    if with_baseline:
        baseline = AssignmentPlan(
            duties=(
                VehicleDuty(
                    duty_id="duty-v1",
                    vehicle_type="BEV",
                    legs=(
                        DutyLeg(dispatch_trips[0]),
                        DutyLeg(dispatch_trips[4]),
                    ),
                ),
            ),
            metadata={"duty_vehicle_map": {"duty-v1": "v1"}},
        )
    context = DispatchContext(
        service_date="2026-03-23",
        trips=dispatch_trips,
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={},
    )
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="arc-iterator", planning_days=2),
        dispatch_context=context,
        trips=trips,
        vehicles=(
            ProblemVehicle("v1", "BEV", "depot"),
            ProblemVehicle("v2", "BEV", "depot"),
            ProblemVehicle("ice", "ICE", "depot"),
            ProblemVehicle("unavailable", "BEV", "depot", available=False),
        ),
        feasible_connections={
            "from": (
                "same-day-other-family",
                "same-day-same-family",
                "next-day-first",
                "next-day-baseline",
            )
        },
        baseline_plan=baseline,
        metadata={
            "fixed_route_band_mode": True,
            "horizon_start_min": 0,
            "milp_max_successors_per_trip": successor_limit,
        },
    )


def test_iter_arc_successors_preserves_filter_sort_cap_and_baseline() -> None:
    builder = MILPModelBuilder()
    problem = _problem(successor_limit=1)
    items = [
        item
        for item in builder.iter_arc_successors(problem, problem.trip_by_id())
        if item.selected_successors
    ]

    assert [(item.vehicle_id, item.from_trip_id) for item in items] == [
        ("v1", "from"),
        ("v2", "from"),
    ]
    assert items[0].candidate_count == 3
    assert items[0].selected_successors == ("same-day-same-family", "next-day-baseline")
    assert items[0].baseline_preserved_count == 1
    assert items[1].selected_successors == ("same-day-same-family",)
    assert items[1].baseline_preserved_count == 0

    assert builder.enumerate_arc_pairs(problem, problem.trip_by_id()) == [
        ("v1", "from", "same-day-same-family"),
        ("v1", "from", "next-day-baseline"),
        ("v2", "from", "same-day-same-family"),
    ]

    summary = builder.arc_pruning_summary(problem, problem.trip_by_id())
    assert summary == {
        "milp_max_successors_per_trip": 1,
        "successor_pruning_enabled": True,
        "candidate_arc_count_before_successor_pruning": 6,
        "arc_count_after_successor_pruning": 3,
        "pruned_arc_count": 3,
        "pruned_origin_count": 2,
        "max_candidate_successors_per_origin": 3,
        "baseline_preserved_arc_count": 1,
    }


def test_iter_arc_successors_unlimited_reuses_same_type_candidate_tuple() -> None:
    builder = MILPModelBuilder()
    problem = _problem(successor_limit=None, with_baseline=False)
    items = [
        item
        for item in builder.iter_arc_successors(problem, problem.trip_by_id())
        if item.selected_successors
    ]

    assert len(items) == 2
    assert items[0].selected_successors == (
        "same-day-same-family",
        "next-day-first",
        "next-day-baseline",
    )
    assert items[0].selected_successors is items[1].selected_successors
    assert items[0].candidate_count == 3
    assert items[1].candidate_count == 3
    assert items[0].baseline_preserved_count == 0
    assert items[1].baseline_preserved_count == 0

    summary = builder.arc_pruning_summary(problem, problem.trip_by_id())
    assert summary["successor_pruning_enabled"] is False
    assert summary["candidate_arc_count_before_successor_pruning"] == 6
    assert summary["arc_count_after_successor_pruning"] == 6
    assert summary["pruned_arc_count"] == 0
    assert summary["pruned_origin_count"] == 0
