from dataclasses import asdict, replace

import pytest

from src.dispatch.graph_builder import ConnectionGraphBuilder
from src.dispatch.lookup_snapshot import snapshot_location_lookups
from src.dispatch.models import (
    DeadheadRule,
    DispatchContext,
    Trip,
    TurnaroundRule,
    VehicleProfile,
)
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.common import strict_precheck


def _clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _context() -> DispatchContext:
    stops = ["stop-a", "stop-b", "stop-c", "stop-d", "DEPOT"]
    trips = [
        Trip(
            trip_id=f"d{day}-t{i}",
            route_id=f"route-{i % 2}",
            origin=stops[i % 4],
            destination=stops[(i + 1) % 4],
            departure_time=_clock(day * 1440 + 480 + i * 30),
            arrival_time=_clock(day * 1440 + 500 + i * 30),
            distance_km=5.0,
            allowed_vehicle_types=("BEV", "ICE"),
            day_index=day,
        )
        for day in range(7)
        for i in range(5)
    ]
    return DispatchContext(
        service_date="2025-02-03",
        trips=trips,
        turnaround_rules={stop: TurnaroundRule(stop, 5) for stop in stops},
        deadhead_rules={
            (left, right): DeadheadRule(left, right, 7)
            for left in stops
            for right in stops
            if left != right
        },
        vehicle_profiles={kind: VehicleProfile(kind) for kind in ("BEV", "ICE")},
        location_aliases={
            "Ａ": ("stop-a",),
            "stop-a": ("Ａ", "a-cycle"),
            "a-cycle": ("stop-a",),
        },
        daily_return_depot_id="DEPOT",
    )


def test_snapshot_preserves_lookup_order_cycles_missing_locations_and_serialized_inputs():
    context = _context()
    original = asdict(context)
    snapshot = snapshot_location_lookups(context)
    locations = ["Ａ", "stop-a", "a-cycle", "stop-b", "DEPOT", "missing", ""]
    for left in locations:
        assert snapshot.resolve_location_ids(left) == context.resolve_location_ids(left)
        assert snapshot.get_turnaround_min(left) == context.get_turnaround_min(left)
        assert snapshot.has_location_data(left) == context.has_location_data(left)
        for right in locations:
            assert snapshot.get_deadhead_min(left, right) == context.get_deadhead_min(
                left, right
            )
            assert snapshot.locations_equivalent(
                left, right
            ) == context.locations_equivalent(left, right)
    assert asdict(context) == asdict(snapshot) == original


def test_changes_between_batches_and_turnaround_sensitivity_do_not_reuse_stale_rules():
    context = _context()
    first = snapshot_location_lookups(context)
    assert first.get_deadhead_min("stop-a", "stop-b") == 7
    context.deadhead_rules[("stop-a", "stop-b")] = DeadheadRule("stop-a", "stop-b", 23)
    context.turnaround_rules["stop-a"] = TurnaroundRule("stop-a", 12)
    context.location_aliases["a-cycle"] = ("missing",)
    second = snapshot_location_lookups(context)
    assert first.get_deadhead_min("stop-a", "stop-b") == 7
    assert second.get_deadhead_min("stop-a", "stop-b") == 23
    assert second.resolve_location_ids("a-cycle") == context.resolve_location_ids(
        "a-cycle"
    )
    assert second.get_turnaround_min("stop-a") == 12
    buffered = snapshot_location_lookups(replace(context, turnaround_buffer_min=15))
    assert buffered.get_turnaround_min("stop-a") == 27


@pytest.mark.parametrize("fixed_route_band_mode", [False, True])
def test_cached_graph_matches_every_uncached_candidate_across_days_and_missing_deadheads(
    fixed_route_band_mode,
):
    context = _context()
    context.fixed_route_band_mode = fixed_route_band_mode
    context.deadhead_rules.pop(("stop-c", "stop-a"))
    builder = ConnectionGraphBuilder()
    for kind in ("BEV", "ICE"):
        expected = {trip.trip_id: [] for trip in context.trips}
        for arc in builder.analyze(context, kind):
            if arc.feasible:
                expected[arc.from_trip_id].append(arc.to_trip_id)
        assert builder.build(context, kind) == expected


def test_strict_audit_preserves_bounds_counts_and_all_blocked_reason_samples(
    monkeypatch,
):
    context = _context()
    context.deadhead_rules.pop(("stop-c", "DEPOT"))
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="lookup-equivalence", service_coverage_mode="strict"
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
                day_index=trip.day_index,
            )
            for trip in context.trips
        ),
        vehicles=tuple(
            ProblemVehicle(f"vehicle-{i}", "ICE", home_depot_id="DEPOT")
            for i in range(2)
        ),
        metadata={"service_coverage_mode": "strict"},
    )
    cached = strict_precheck.evaluate_strict_coverage_precheck(problem)
    monkeypatch.setattr(
        strict_precheck, "snapshot_location_lookups", lambda context: context
    )
    assert cached == strict_precheck.evaluate_strict_coverage_precheck(problem)


def test_cache_is_bounded_and_custom_context_behavior_is_preserved():
    snapshot = snapshot_location_lookups(_context())
    for index in range(5000):
        assert snapshot.resolve_location_ids(f"missing-{index}") == (
            f"missing-{index}",
        )
    assert len(snapshot._resolved_cache) <= 4096
    context = _context()
    context.get_deadhead_min = lambda left, right: 99
    assert snapshot_location_lookups(context) is context
    assert context.get_deadhead_min("stop-a", "stop-b") == 99
