from __future__ import annotations

from src.dispatch.models import DispatchContext, Trip, VehicleProfile
from src.optimization.abc import engine as abc_engine
from src.optimization.abc.engine import ABCOptimizer
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import OptimizationConfig, OptimizationMode


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
        scenario_id="abc_runtime_profile",
        vehicle_counts={"BEV": 1},
        objective_mode="total_cost",
        initial_soc_percent=80.0,
        final_soc_floor_percent=20.0,
        timestep_min=60,
    )


def test_abc_optimizer_exports_runtime_profile_fields(monkeypatch) -> None:
    monkeypatch.setattr(abc_engine, "partial_milp_repair", lambda problem, plan, config=None: plan)

    result = ABCOptimizer().solve(
        _tiny_problem(),
        OptimizationConfig(
            mode=OptimizationMode.ABC,
            time_limit_sec=2,
            random_seed=11,
            alns_iterations=4,
            no_improvement_limit=4,
            destroy_fraction=0.2,
            warm_start=True,
        ),
    )

    metadata = dict(result.solver_metadata)
    profile = dict(metadata.get("search_profile") or {})

    assert metadata["solver_display_name"] == "ABC prototype"
    assert metadata["solver_maturity"] == "prototype"
    assert metadata["eligible_for_main_benchmark"] is False
    assert metadata["eligible_for_appendix_benchmark"] is True
    assert "Prototype bee-colony search" in metadata["comparison_note"]
    assert metadata["uses_exact_repair"] == (profile["exact_repair_calls"] > 0)
    assert {
        "total_wall_clock_sec",
        "first_feasible_sec",
        "incumbent_updates",
        "evaluator_calls",
        "avg_evaluator_sec",
        "repair_calls",
        "avg_repair_sec",
        "exact_repair_calls",
        "avg_exact_repair_sec",
        "feasible_candidate_ratio",
        "rejected_candidate_ratio",
        "fallback_count",
    }.issubset(profile)
