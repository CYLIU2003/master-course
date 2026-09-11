from __future__ import annotations

import pytest

from src.dispatch.models import DeadheadRule, DispatchContext, Trip, VehicleProfile
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    EnergyPriceSlot,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.milp.depot_connection_factors import (
    ArcDomain,
    FactorVariables,
    FactoredConnectionVariables,
    SuccessorRow,
    connection_windows,
    create_factor_variables,
    factor_depot_connections,
)
from src.optimization.milp.solver_adapter import GurobiMILPAdapter


def _problem(*, policy_depot: str = "depot", home_depot: str = "depot", fallback_rates: bool = False,
             target_gap: bool = False) -> CanonicalOptimizationProblem:
    origins = tuple(
        ProblemTrip(
            trip_id=f"o{i}",
            route_id=f"ro{i}",
            origin="S",
            destination="A",
            departure_min=300 + i * 30,
            arrival_min=360 + i * 30,
            distance_km=10.0,
            allowed_vehicle_types=("BEV",),
            energy_kwh=(10.0 if not fallback_rates else 10.0 + i),
            fuel_l=2.0,
            service_date="2026-03-23",
        )
        for i in range(3)
    )
    home_targets = tuple(
        ProblemTrip(
            trip_id=f"h{i}",
            route_id=f"rh{i}",
            origin="depot",
            destination="T",
            departure_min=1500 + i * (37 if target_gap else 30),
            arrival_min=1560 + i * (37 if target_gap else 30),
            distance_km=8.0,
            allowed_vehicle_types=("BEV",),
            energy_kwh=8.0,
            fuel_l=1.6,
            service_date="2026-03-24",
        )
        for i in range(3)
    )
    away_targets = tuple(
        ProblemTrip(
            trip_id=f"a{i}",
            route_id=f"ra{i}",
            origin="Z",
            destination="T",
            departure_min=1700 + i * (37 if target_gap else 30),
            arrival_min=1760 + i * (37 if target_gap else 30),
            distance_km=8.0,
            allowed_vehicle_types=("BEV",),
            energy_kwh=8.0,
            fuel_l=1.6,
            service_date="2026-03-24",
        )
        for i in range(3)
    )
    trips = origins + home_targets + away_targets
    dispatch_trips = [
        Trip(
            trip_id=trip.trip_id,
            route_id=trip.route_id,
            origin=trip.origin,
            destination=trip.destination,
            departure_time=f"{(trip.departure_min % 1440) // 60:02d}:{trip.departure_min % 60:02d}",
            arrival_time=f"{(trip.arrival_min % 1440) // 60:02d}:{trip.arrival_min % 60:02d}",
            distance_km=trip.distance_km,
            allowed_vehicle_types=trip.allowed_vehicle_types,
        )
        for trip in trips
    ]
    context = DispatchContext(
        service_date="2026-03-23",
        trips=dispatch_trips,
        turnaround_rules={},
        deadhead_rules={
            ("A", "depot"): DeadheadRule("A", "depot", 10),
            ("depot", "Z"): DeadheadRule("depot", "Z", 15),
        },
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.0,
            )
        },
        daily_return_depot_id=policy_depot,
    )
    vehicle = ProblemVehicle(
        vehicle_id="v1",
        vehicle_type="BEV",
        home_depot_id=home_depot,
        energy_consumption_kwh_per_km=None if fallback_rates else 1.0,
        fuel_consumption_l_per_km=0.2,
    )
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="factor-test",
            horizon_start="00:00",
            planning_days=2,
            timestep_min=30,
        ),
        dispatch_context=context,
        trips=trips,
        vehicles=(vehicle,),
        vehicle_types=(),
        price_slots=tuple(EnergyPriceSlot(slot_index=i) for i in range(70)),
        feasible_connections={},
        metadata={"deadhead_speed_kmh": 18.0},
    )


def _rows(problem: CanonicalOptimizationProblem, targets: tuple[str, ...]) -> tuple[SuccessorRow, ...]:
    return tuple(
        SuccessorRow("v1", f"o{i}", targets)
        for i in range(3)
    )


def _factor_arcs(domain: ArcDomain, factors: tuple) -> set[tuple[str, str, str]]:
    arcs = set(domain)
    for factor in factors:
        arcs.update(
            (factor.vehicle_id, origin, target)
            for origin in factor.origins
            for target in factor.targets
        )
    return arcs


def _valid_count(problem: CanonicalOptimizationProblem, interval: tuple[int, int]) -> int:
    return sum(interval[0] <= slot.slot_index < interval[1] for slot in problem.price_slots)


def test_complete_home_and_away_groups_preserve_domain_coefficients_and_windows() -> None:
    problem = _problem(target_gap=True)
    rows = _rows(problem, ("h0", "h1", "h2", "a0", "a1", "a2"))
    adapter = GurobiMILPAdapter()
    domain, factors = factor_depot_connections(adapter, problem, rows)

    original = {
        (row.vehicle_id, row.origin, target)
        for row in rows
        for target in row.targets
    }
    assert _factor_arcs(domain, factors) == original
    assert len(factors) == 2
    assert {factor.targets for factor in factors} == {
        ("h0", "h1", "h2"),
        ("a0", "a1", "a2"),
    }

    vehicle = problem.vehicles[0]
    trips = problem.trip_by_id()
    for factor in factors:
        assert factor.origin_envelope_counts
        for origin_index, origin_id in enumerate(factor.origins):
            for target_index, target_id in enumerate(factor.targets):
                envelope, soc = connection_windows(
                    adapter, problem, vehicle, trips[origin_id], trips[target_id]
                )
                assert envelope is not None
                assert _valid_count(problem, envelope) == (
                    factor.origin_envelope_counts[origin_index]
                    + factor.target_envelope_counts[target_index]
                )
                assert _valid_count(problem, soc) == (
                    factor.origin_soc_ranges[origin_index][1]
                    - factor.origin_soc_ranges[origin_index][0]
                    + factor.target_soc_ranges[target_index][1]
                    - factor.target_soc_ranges[target_index][0]
                )
                assert adapter._deadhead_energy_kwh(problem, vehicle, origin_id, target_id) == pytest.approx(
                    factor.target_energy_kwh[target_index]
                )
                assert adapter._deadhead_fuel_l(problem, vehicle, origin_id, target_id) == pytest.approx(
                    factor.target_fuel_l[target_index]
                )


def test_home_policy_mismatch_keeps_all_arcs_explicit() -> None:
    problem = _problem(home_depot="other-depot")
    rows = _rows(problem, ("h0", "h1", "h2"))
    domain, factors = factor_depot_connections(GurobiMILPAdapter(), problem, rows)

    assert factors == ()
    assert set(domain) == set(_factor_arcs(domain, factors))
    assert len(domain) == 9


def test_incomplete_candidate_sets_are_not_merged_with_a_hole() -> None:
    problem = _problem()
    rows = (
        SuccessorRow("v1", "o0", ("h0", "h1", "h2")),
        SuccessorRow("v1", "o1", ("h0", "h1")),
        SuccessorRow("v1", "o2", ("h0", "h1", "h2")),
    )
    domain, factors = factor_depot_connections(GurobiMILPAdapter(), problem, rows)

    original = {(row.vehicle_id, row.origin, target) for row in rows for target in row.targets}
    assert _factor_arcs(domain, factors) == original
    assert all("o1" not in factor.origins for factor in factors)


def test_fallback_per_trip_rates_split_different_origin_rates() -> None:
    problem = _problem(fallback_rates=True)
    rows = _rows(problem, ("h0", "h1", "h2"))
    domain, factors = factor_depot_connections(GurobiMILPAdapter(), problem, rows)

    assert _factor_arcs(domain, factors) == set(domain)
    assert factors == ()


def test_multiple_days_and_fragment_rows_remain_reconstructible() -> None:
    problem = _problem()
    rows = (
        SuccessorRow("v1", "o0", ("h0", "h1", "h2")),
        SuccessorRow("v1", "o1", ("h0", "h1", "h2")),
        SuccessorRow("v1", "o2", ("h0", "h1", "h2")),
    )
    domain, factors = factor_depot_connections(GurobiMILPAdapter(), problem, rows)

    assert problem.scenario.planning_days == 2
    original = {(row.vehicle_id, row.origin, target) for row in rows for target in row.targets}
    assert _factor_arcs(domain, factors) == original
    assert factors


class _FakeVar:
    def __init__(self) -> None:
        self.Start = None


class _FakeModel:
    def __init__(self) -> None:
        self.variables: list[_FakeVar] = []
        self.constraints: list[object] = []

    def addVar(self, **_kwargs: object) -> _FakeVar:
        variable = _FakeVar()
        self.variables.append(variable)
        return variable

    def addConstr(self, expression: object, **_kwargs: object) -> None:
        self.constraints.append(expression)


class _FakeGP:
    @staticmethod
    def quicksum(values: object) -> int:
        return sum(1 for _ in values)


class _FakeGRB:
    BINARY = "BINARY"


def test_factor_variables_reconstruct_balanced_integer_selection_and_starts() -> None:
    problem = _problem()
    rows = _rows(problem, ("h0", "h1", "h2"))
    _domain, factors = factor_depot_connections(GurobiMILPAdapter(), problem, rows)
    assert len(factors) == 1

    model = _FakeModel()
    variables = create_factor_variables(model, _FakeGP, _FakeGRB, factors)
    factored = FactoredConnectionVariables({}, variables)
    selected = {
        ("v1", "o0", "h1"),
        ("v1", "o1", "h2"),
        ("v1", "o2", "h0"),
    }
    factored.set_factor_starts(selected)

    reconstructed = factored.expanded_selection(
        lambda variable, **_kwargs: bool(variable.Start)
    )
    assert {origin for _vehicle, origin, _target in reconstructed} == {
        origin for _vehicle, origin, _target in selected
    }
    assert {target for _vehicle, _origin, target in reconstructed} == {
        target for _vehicle, _origin, target in selected
    }
    assert reconstructed <= {
        ("v1", origin, target)
        for origin in ("o0", "o1", "o2")
        for target in ("h0", "h1", "h2")
    }
    assert all(variable.Start in (0.0, 1.0) for variable in model.variables)
    assert len(model.constraints) == 1


def test_home_and_away_factors_share_origin_and_require_cross_factor_flow_bound() -> None:
    problem = _problem(target_gap=True)
    rows = _rows(problem, ("h0", "h1", "h2", "a0", "a1", "a2"))
    domain, factors = factor_depot_connections(GurobiMILPAdapter(), problem, rows)
    assert len(factors) == 2

    variables = FactoredConnectionVariables(
        {},
        tuple(
            FactorVariables(
                factor,
                tuple(_FakeVar() for _ in factor.origins),
                tuple(_FakeVar() for _ in factor.targets),
            )
            for factor in factors
        ),
    )
    assert all(len(variables.by_origin[("v1", origin)]) == 2 for origin in ("o0", "o1", "o2"))
    assert set(domain) == set()
