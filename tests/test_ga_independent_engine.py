from __future__ import annotations

import random

from src.dispatch.models import DispatchContext, Trip, VehicleProfile
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import AssignmentPlan, OptimizationConfig, OptimizationMode
from src.optimization.ga import engine as ga_engine
from src.optimization.ga.engine import GAOptimizer


def _tiny_problem():
    context = DispatchContext(
        service_date="2026-03-23",
        trips=[
            Trip(
                trip_id="t1",
                route_id="r1",
                origin="A",
                destination="B",
                departure_time="08:00",
                arrival_time="08:30",
                distance_km=10.0,
                allowed_vehicle_types=("BEV",),
            )
        ],
        turnaround_rules={},
        deadhead_rules={},
        vehicle_profiles={
            "BEV": VehicleProfile(
                vehicle_type="BEV",
                battery_capacity_kwh=300.0,
                energy_consumption_kwh_per_km=1.2,
            )
        },
    )
    return ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="ga_independent",
        vehicle_counts={"BEV": 1},
        objective_mode="total_cost",
        initial_soc_percent=80.0,
        final_soc_floor_percent=20.0,
        timestep_min=60,
    )


def test_ga_optimizer_is_independent_and_reports_profile(monkeypatch) -> None:
    monkeypatch.setattr(ga_engine, "partial_milp_repair", lambda problem, plan, config=None: plan)

    optimizer = GAOptimizer()
    result = optimizer.solve(
        _tiny_problem(),
        OptimizationConfig(
            mode=OptimizationMode.GA,
            time_limit_sec=2,
            random_seed=7,
            alns_iterations=4,
            no_improvement_limit=4,
            destroy_fraction=0.2,
            warm_start=True,
        ),
    )

    metadata = dict(result.solver_metadata)
    profile = dict(metadata.get("search_profile") or {})

    assert not hasattr(optimizer, "_delegate")
    assert metadata["true_solver_family"] == "ga"
    assert metadata["independent_implementation"] is True
    assert metadata["delegates_to"] == "none"
    assert metadata["solver_display_name"] == "GA prototype"
    assert metadata["solver_maturity"] == "prototype"
    assert metadata["candidate_generation_mode"] == "genetic_population_search"
    assert metadata["has_feasible_incumbent"] is True
    assert profile["evaluator_calls"] >= 1
    assert profile["repair_calls"] >= 1
    assert result.feasible is True


def test_ga_crossover_handles_empty_parents() -> None:
    optimizer = GAOptimizer()
    problem = _tiny_problem()
    empty_plan = AssignmentPlan(duties=(), served_trip_ids=(), unserved_trip_ids=("t1",))

    child = optimizer._crossover(problem, empty_plan, empty_plan, random.Random(1))

    assert child.duties == ()
    assert child.unserved_trip_ids == ("t1",)
