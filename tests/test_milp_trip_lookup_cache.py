from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from src.dispatch.models import DeadheadRule, DispatchContext
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemTrip,
    ProblemVehicle,
)
from src.optimization.milp.solver_adapter import GurobiMILPAdapter


def _problem(trips: tuple[ProblemTrip, ...]) -> CanonicalOptimizationProblem:
    context = DispatchContext(
        service_date="2026-03-23",
        trips=[],
        turnaround_rules={},
        deadhead_rules={("B", "C"): DeadheadRule("B", "C", 12)},
        vehicle_profiles={},
    )
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="lookup-cache"),
        dispatch_context=context,
        trips=trips,
        vehicles=(),
        metadata={"deadhead_speed_kmh": 18.0},
    )


def _trip(trip_id: str, *, distance_km: float, energy_kwh: float, fuel_l: float) -> ProblemTrip:
    return ProblemTrip(
        trip_id=trip_id,
        route_id=f"route-{trip_id}",
        origin="A",
        destination="B",
        departure_min=60,
        arrival_min=120,
        distance_km=distance_km,
        allowed_vehicle_types=("BEV", "ICE"),
        energy_kwh=energy_kwh,
        fuel_l=fuel_l,
    )


def test_hot_helpers_use_cached_lookup_without_changing_public_map() -> None:
    first = _trip("first", distance_km=10.0, energy_kwh=7.0, fuel_l=2.0)
    next_trip = ProblemTrip(
        trip_id="next",
        route_id="route-next",
        origin="C",
        destination="D",
        departure_min=180,
        arrival_min=240,
        distance_km=20.0,
        allowed_vehicle_types=("BEV", "ICE"),
        energy_kwh=11.0,
        fuel_l=4.0,
    )
    problem = _problem((first, next_trip))
    adapter = GurobiMILPAdapter()
    bev = ProblemVehicle(
        vehicle_id="bev-1",
        vehicle_type="BEV",
        home_depot_id="depot",
        energy_consumption_kwh_per_km=2.5,
    )
    ice = ProblemVehicle(
        vehicle_id="ice-1",
        vehicle_type="ICE",
        home_depot_id="depot",
        fuel_consumption_l_per_km=0.3,
    )

    public_map = problem.trip_by_id()
    cached_map = adapter._cached_trip_lookup(problem)
    assert cached_map is not public_map
    assert cached_map["first"] is first
    assert adapter._trip_energy_kwh(problem, bev, "first") == 25.0
    assert adapter._trip_fuel_l(problem, ice, "first") == 3.0
    assert adapter._deadhead_energy_kwh(problem, bev, "first", "next") == 9.0
    assert adapter._deadhead_fuel_l(problem, ice, "first", "next") == 1.08
    assert public_map == {"first": first, "next": next_trip}

    replacement = _trip("first", distance_km=4.0, energy_kwh=99.0, fuel_l=88.0)
    object.__setattr__(problem, "trips", (replacement, next_trip))

    rebuilt_map = adapter._cached_trip_lookup(problem)
    assert rebuilt_map is not cached_map
    assert rebuilt_map["first"] is replacement
    assert adapter._trip_energy_kwh(problem, bev, "first") == 10.0
    assert adapter._trip_fuel_l(problem, ice, "first") == 1.2
    assert public_map == {"first": first, "next": next_trip}


def test_cached_lookup_is_problem_local_under_concurrent_calls() -> None:
    first_problem_trip = _trip("shared", distance_km=3.0, energy_kwh=1.0, fuel_l=1.0)
    second_problem_trip = _trip("shared", distance_km=30.0, energy_kwh=2.0, fuel_l=2.0)
    first_problem = _problem((first_problem_trip,))
    second_problem = _problem((second_problem_trip,))
    adapter = GurobiMILPAdapter()

    def lookup_trip(problem: CanonicalOptimizationProblem) -> ProblemTrip:
        return adapter._cached_trip_lookup(problem)["shared"]

    problems = [first_problem, second_problem] * 100
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lookup_trip, problems))

    for problem, result in zip(problems, results):
        assert result is problem.trips[0]
