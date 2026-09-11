from dataclasses import replace

import pytest

import src.optimization.engine as engine_module
from src.dispatch.models import (
    DeadheadRule,
    DispatchContext,
    Trip,
    TurnaroundRule,
    VehicleProfile,
)
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    DepotEnergyAsset,
    OptimizationConfig,
    OptimizationMode,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.common.strict_precheck import (
    StrictCoveragePrecheckResult,
    evaluate_strict_coverage_precheck,
)
from src.optimization.common.strict_precheck_cache import (
    strict_precheck_input_fingerprint,
)
from src.optimization.common.problem import OptimizationEngineResult
from src.optimization.engine import OptimizationEngine


def _canonical_problem(*, available: bool = True) -> CanonicalOptimizationProblem:
    trip = ProblemTrip(
        trip_id="trip-1",
        route_id="route-1",
        origin="A",
        destination="B",
        departure_min=480,
        arrival_min=540,
        distance_km=10.0,
        allowed_vehicle_types=("BEV",),
        service_date="2025-01-01",
        operator_id="operator-1",
    )
    dispatch_trip = Trip(
        trip_id=trip.trip_id,
        route_id=trip.route_id,
        origin=trip.origin,
        destination=trip.destination,
        departure_time="08:00",
        arrival_time="09:00",
        distance_km=trip.distance_km,
        allowed_vehicle_types=trip.allowed_vehicle_types,
        operator_id=trip.operator_id,
        origin_stop_id="A",
        destination_stop_id="B",
        route_family_code="route-family-1",
        direction="outbound",
        service_date="2025-01-01",
    )
    context = DispatchContext(
        service_date="2025-01-01",
        trips=[dispatch_trip],
        turnaround_rules={"B": TurnaroundRule("B", 10)},
        deadhead_rules={("B", "A"): DeadheadRule("B", "A", 5)},
        vehicle_profiles={"BEV": VehicleProfile("BEV", battery_capacity_kwh=300.0)},
        location_aliases={"b-terminal": ("B",)},
        horizon_start_min=0,
        turnaround_buffer_min=2,
        daily_return_depot_id="depot-1",
    )
    scenario = OptimizationScenario(
        scenario_id="scenario-1",
        horizon_start="00:00",
        horizon_end="24:00",
        service_coverage_mode="strict",
        allow_same_day_depot_cycles=True,
    )
    vehicle = ProblemVehicle(
        vehicle_id="vehicle-1",
        vehicle_type="BEV",
        home_depot_id="depot-1",
        available=available,
        battery_capacity_kwh=300.0,
    )
    asset = DepotEnergyAsset(
        depot_id="depot-1",
        pv_enabled=True,
        pv_generation_kwh_by_slot=(1.0, 2.0),
        bess_enabled=True,
        bess_energy_kwh=100.0,
        bess_power_kw=50.0,
        bess_initial_soc_kwh=50.0,
        bess_soc_min_kwh=0.0,
        bess_soc_max_kwh=100.0,
    )
    return CanonicalOptimizationProblem(
        scenario=scenario,
        dispatch_context=context,
        trips=(trip,),
        vehicles=(vehicle,),
        depot_energy_assets={"depot-1": asset},
        metadata={
            "service_coverage_mode": "strict",
            "fixed_route_band_mode": False,
            "allow_same_day_depot_cycles": True,
        },
    )


def test_real_canonical_precheck_matches_uncached_and_soc_pv_changes_reuse(
    monkeypatch,
):
    problem = _canonical_problem()
    expected = evaluate_strict_coverage_precheck(problem)
    changed_asset = replace(
        problem.depot_energy_assets["depot-1"],
        pv_generation_kwh_by_slot=(99.0, 98.0),
        bess_initial_soc_kwh=12.0,
    )
    changed_energy_problem = replace(
        problem,
        depot_energy_assets={"depot-1": changed_asset},
    )
    assert strict_precheck_input_fingerprint(problem) == strict_precheck_input_fingerprint(
        changed_energy_problem
    )
    assert evaluate_strict_coverage_precheck(changed_energy_problem) == expected

    calls = []
    real_evaluate = engine_module.evaluate_strict_coverage_precheck

    def counted_evaluate(candidate):
        calls.append(candidate)
        return real_evaluate(candidate)

    monkeypatch.setattr(engine_module, "evaluate_strict_coverage_precheck", counted_evaluate)
    monkeypatch.setattr(
        OptimizationEngine,
        "_finalize_result",
        lambda _self, _problem, result, _config: result,
    )
    solver_calls = []

    def fake_milp(candidate, config):
        solver_calls.append(candidate)
        return OptimizationEngineResult(
            mode=config.mode,
            solver_status="fake",
            objective_value=0.0,
            plan=AssignmentPlan(),
            feasible=True,
        )

    engine = OptimizationEngine()
    monkeypatch.setattr(engine._milp, "solve", fake_milp)
    config = OptimizationConfig(mode=OptimizationMode.MILP, phase="phase3_two_stage")
    engine.solve(problem, config)
    second = engine.solve(changed_energy_problem, config)

    assert len(calls) == 1
    assert len(solver_calls) == 2
    assert evaluate_strict_coverage_precheck(calls[0]) == expected
    assert second.solver_status == "fake"
    audit = solver_calls[1].metadata["strict_coverage_precheck"]
    assert audit["input_sha256"] == strict_precheck_input_fingerprint(problem)
    assert audit["reused_identical_structural_input"] is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: replace(p, trips=(replace(p.trips[0], departure_min=481),)),
        lambda p: replace(p, trips=(replace(p.trips[0], operator_id="operator-2"),)),
        lambda p: replace(
            p,
            vehicles=(replace(p.vehicles[0], vehicle_type="ICE"),),
        ),
        lambda p: replace(
            p,
            vehicles=(replace(p.vehicles[0], available=False),),
        ),
        lambda p: replace(
            p,
            vehicles=(replace(p.vehicles[0], home_depot_id="depot-2"),),
        ),
        lambda p: replace(
            p,
            dispatch_context=replace(
                p.dispatch_context,
                deadhead_rules={("B", "A"): DeadheadRule("B", "A", 99)},
            ),
        ),
        lambda p: replace(
            p,
            dispatch_context=replace(
                p.dispatch_context,
                turnaround_rules={"B": TurnaroundRule("B", 99)},
            ),
        ),
        lambda p: replace(
            p,
            dispatch_context=replace(
                p.dispatch_context,
                location_aliases={"b-terminal": ("different",)},
            ),
        ),
        lambda p: replace(
            p,
            metadata={**p.metadata, "fixed_route_band_mode": True},
        ),
        lambda p: replace(
            p,
            scenario=replace(p.scenario, horizon_start="01:00"),
        ),
    ],
)
def test_structural_mutations_invalidate_fingerprint(mutate):
    problem = _canonical_problem()
    assert strict_precheck_input_fingerprint(problem) != strict_precheck_input_fingerprint(
        mutate(problem)
    )


def test_custom_context_subclass_and_extra_fields_disable_cache():
    problem = _canonical_problem()

    class CustomDispatchContext(DispatchContext):
        pass

    custom_context = CustomDispatchContext(**vars(problem.dispatch_context))
    assert strict_precheck_input_fingerprint(replace(problem, dispatch_context=custom_context)) is None

    extra_context = replace(problem, dispatch_context=replace(problem.dispatch_context))
    extra_context.dispatch_context.extra_runtime_rule = object()
    assert strict_precheck_input_fingerprint(extra_context) is None

    extra_scenario = _canonical_problem()
    object.__setattr__(extra_scenario.scenario, "extra_runtime_rule", True)
    assert strict_precheck_input_fingerprint(extra_scenario) is None

    extra_trip = _canonical_problem()
    object.__setattr__(extra_trip.trips[0], "extra_runtime_rule", True)
    assert strict_precheck_input_fingerprint(extra_trip) is None

    extra_vehicle = _canonical_problem()
    object.__setattr__(extra_vehicle.vehicles[0], "extra_runtime_rule", True)
    assert strict_precheck_input_fingerprint(extra_vehicle) is None


def test_unknown_nonserializable_control_disables_cache():
    problem = _canonical_problem()
    changed = replace(
        problem,
        metadata={**problem.metadata, "fixed_route_band_mode": object()},
    )
    assert strict_precheck_input_fingerprint(changed) is None


def test_cache_is_not_stored_when_fingerprint_changes_during_precheck(monkeypatch):
    problem = _canonical_problem()
    fingerprints = iter(("before", "after"))
    monkeypatch.setattr(
        engine_module,
        "strict_precheck_input_fingerprint",
        lambda _candidate: next(fingerprints),
    )
    monkeypatch.setattr(
        engine_module,
        "evaluate_strict_coverage_precheck",
        lambda _candidate: StrictCoveragePrecheckResult(checked=True, infeasible=False),
    )
    monkeypatch.setattr(
        OptimizationEngine,
        "_finalize_result",
        lambda _self, _problem, result, _config: result,
    )
    monkeypatch.setattr(
        OptimizationEngine,
        "_solver_identity",
        staticmethod(lambda _mode: ("fake", "test", "milp")),
    )
    engine = OptimizationEngine()
    monkeypatch.setattr(
        engine._milp,
        "solve",
        lambda _candidate, config: OptimizationEngineResult(
            mode=config.mode,
            solver_status="fake",
            objective_value=0.0,
            plan=AssignmentPlan(),
            feasible=True,
        ),
    )
    engine.solve(
        problem,
        OptimizationConfig(mode=OptimizationMode.MILP, phase="phase3_two_stage"),
    )
    assert engine._strict_precheck_cache is None


def test_infeasible_early_return_preserves_precheck_reuse_audit(monkeypatch):
    """The fast infeasibility return must expose the same cache audit as MILP."""
    problem = _canonical_problem(available=False)
    monkeypatch.setattr(
        OptimizationEngine,
        "_finalize_result",
        lambda _self, _problem, result, _config: result,
    )
    engine = OptimizationEngine()
    config = OptimizationConfig(mode=OptimizationMode.MILP, phase="phase3_two_stage")

    first = engine.solve(problem, config)
    second = engine.solve(problem, config)

    first_audit = first.solver_metadata["strict_coverage_precheck"]
    second_audit = second.solver_metadata["strict_coverage_precheck"]
    expected_sha = strict_precheck_input_fingerprint(problem)
    assert first_audit["input_sha256"] == expected_sha
    assert first_audit["reused_identical_structural_input"] is False
    assert second_audit["input_sha256"] == expected_sha
    assert second_audit["reused_identical_structural_input"] is True
