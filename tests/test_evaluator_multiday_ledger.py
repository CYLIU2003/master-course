from __future__ import annotations

from src.optimization.common.evaluator import CostBreakdown, CostEvaluator
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationScenario,
    ProblemVehicle,
)


def test_multiday_vehicle_ledger_has_carryover_continuity() -> None:
    problem = CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="s1", planning_days=3, timestep_min=60),
        dispatch_context=None,
        trips=(),
        vehicles=(
            ProblemVehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot_id="dep-1",
                initial_soc=120.0,
                battery_capacity_kwh=300.0,
                initial_fuel_l=80.0,
                fuel_tank_capacity_l=100.0,
            ),
        ),
    )
    plan = AssignmentPlan()
    breakdown = CostBreakdown(total_cost=100.0)

    vehicle_ledger, daily_ledger = CostEvaluator().build_plan_ledgers(problem, plan, breakdown)

    assert len(daily_ledger) == 3
    rows = [row for row in vehicle_ledger if row.vehicle_id == "veh-1"]
    assert len(rows) == 3
    assert rows[0].day_index == 0
    assert rows[1].day_index == 1
    assert rows[2].day_index == 2
    assert rows[0].end_soc_kwh == rows[1].start_soc_kwh
    assert rows[1].end_soc_kwh == rows[2].start_soc_kwh
    assert rows[0].end_fuel_l == rows[1].start_fuel_l
    assert rows[1].end_fuel_l == rows[2].start_fuel_l
