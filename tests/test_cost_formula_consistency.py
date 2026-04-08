from __future__ import annotations

import pytest

from src.dispatch.models import DispatchContext, Trip, VehicleProfile
from src.gurobi_runtime import is_gurobi_available
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.evaluator import CostEvaluator
from src.optimization.common.problem import OptimizationConfig, OptimizationMode
from src.optimization.common.problem import EnergyPriceSlot
from src.optimization.milp.engine import MILPOptimizer


def _minimal_dispatch_context() -> DispatchContext:
    return DispatchContext(
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


def test_milp_objective_matches_evaluator_on_tiny_case() -> None:
    if not is_gurobi_available():
        pytest.skip("Gurobi is not available")

    context = _minimal_dispatch_context()
    problem = ProblemBuilder().build_from_dispatch(
        context,
        scenario_id="s_cost_match",
        vehicle_counts={"BEV": 1},
        objective_mode="total_cost",
        initial_soc_percent=80.0,
        final_soc_floor_percent=20.0,
        timestep_min=60,
        cost_component_flags={"electricity_cost": False},
        price_slots=(EnergyPriceSlot(slot_index=8, grid_buy_yen_per_kwh=20.0),),
    )
    result = MILPOptimizer().solve(
        problem,
        OptimizationConfig(
            mode=OptimizationMode.MILP,
            time_limit_sec=30,
            mip_gap=0.0,
            random_seed=42,
            warm_start=False,
        ),
    )

    assert result.feasible
    evaluator = CostEvaluator()
    breakdown = evaluator.evaluate(problem, result.plan)
    model_objective = float(result.plan.metadata["objective_value"])

    assert abs(breakdown.objective_value - model_objective) < 1.0e-6
    assert abs(result.objective_value - model_objective) < 1.0e-6
