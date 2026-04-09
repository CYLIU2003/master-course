from __future__ import annotations

from src.dispatch.models import DispatchContext, Trip, VehicleProfile
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import OptimizationConfig, OptimizationMode
from src.optimization.abc import engine as abc_engine
from src.optimization.abc.engine import ABCOptimizer


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
        scenario_id="abc_independent",
        vehicle_counts={"BEV": 1},
        objective_mode="total_cost",
        initial_soc_percent=80.0,
        final_soc_floor_percent=20.0,
        timestep_min=60,
    )


def test_abc_optimizer_is_independent_and_reports_colony_stats(monkeypatch) -> None:
    monkeypatch.setattr(abc_engine, "partial_milp_repair", lambda problem, plan, config=None: plan)
    monkeypatch.setattr(
        ABCOptimizer,
        "_mutate",
        lambda self, problem, plan, rng, destroy_ops, repair_ops, profile, exact_repair_call_limit, exact_repair_time_budget_sec: plan,
    )

    optimizer = ABCOptimizer()
    result = optimizer.solve(
        _tiny_problem(),
        OptimizationConfig(
            mode=OptimizationMode.ABC,
            time_limit_sec=2,
            random_seed=11,
            alns_iterations=8,
            no_improvement_limit=4,
            destroy_fraction=0.2,
            warm_start=True,
        ),
    )

    metadata = dict(result.solver_metadata)
    profile = dict(metadata.get("search_profile") or {})

    assert not hasattr(optimizer, "_delegate")
    assert metadata["true_solver_family"] == "abc"
    assert metadata["independent_implementation"] is True
    assert metadata["delegates_to"] == "none"
    assert metadata["candidate_generation_mode"] == "bee_colony_search"
    assert metadata["has_feasible_incumbent"] is True
    assert metadata["food_source_count"] >= 1
    assert metadata["employed_updates"] >= 1
    assert metadata["onlooker_updates"] >= 1
    assert metadata["scout_resets"] >= 1
    assert profile["evaluator_calls"] >= 1
    assert profile["repair_calls"] >= 1
    assert result.feasible is True
