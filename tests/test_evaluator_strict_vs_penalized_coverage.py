"""Tests for strict vs penalized coverage mode in evaluator."""

import pytest
from src.optimization.common.problem import (
    AssignmentPlan,
    CanonicalOptimizationProblem,
    OptimizationObjectiveWeights,
    OptimizationScenario,
    EnergyPriceSlot,
    PVSlot,
)
from src.optimization.common.evaluator import CostEvaluator
from unittest.mock import MagicMock


def _make_mock_problem(service_coverage_mode="strict"):
    """Create a properly mocked problem."""
    problem = MagicMock(spec=CanonicalOptimizationProblem)
    problem.scenario = OptimizationScenario(
        scenario_id="test",
        service_coverage_mode=service_coverage_mode,
        objective_mode="total_cost",
        timestep_min=60,
        co2_price_per_kg=0.0,
    )
    problem.metadata = {
        "service_coverage_mode": service_coverage_mode,
        "cost_component_flags": {},
        "cost_component_flags": {},
    }
    problem.objective_weights = OptimizationObjectiveWeights()
    problem.vehicles = []
    problem.vehicle_types = []
    problem.baseline_plan = None
    problem.trips = []
    problem.depots = []
    problem.chargers = []
    problem.price_slots = (
        EnergyPriceSlot(
            slot_index=0,
            grid_buy_yen_per_kwh=25.0,
            grid_sell_yen_per_kwh=0.0,
            demand_charge_weight=0.0,
            co2_factor=0.0,
        ),
    )
    problem.pv_slots = ()
    problem.depot_energy_assets = ()
    problem.dispatch_context = MagicMock()
    return problem


def test_evaluator_strict_coverage_returns_inf_with_unserved():
    """In strict mode, objective_value should be inf when unserved trips exist."""
    problem = _make_mock_problem("strict")
    
    # Plan with unserved trips
    plan = AssignmentPlan(
        duties=(),
        served_trip_ids=("trip1",),
        unserved_trip_ids=("trip2",),
    )
    
    evaluator = CostEvaluator()
    result = evaluator.evaluate(problem, plan)
    
    assert result.objective_value == float('inf')
    assert result.unserved_penalty == 0.0  # Should not apply penalty in strict mode


def test_evaluator_penalized_coverage_applies_penalty():
    """In penalized mode, unserved_penalty should be applied."""
    problem = _make_mock_problem("penalized")
    problem.objective_weights = OptimizationObjectiveWeights(unserved=10000.0)
    
    # Plan with unserved trips
    plan = AssignmentPlan(
        duties=(),
        served_trip_ids=("trip1",),
        unserved_trip_ids=("trip2", "trip3"),  # 2 unserved
    )
    
    evaluator = CostEvaluator()
    result = evaluator.evaluate(problem, plan)
    
    # Should have finite objective and non-zero unserved penalty
    assert result.objective_value != float('inf')
    assert result.unserved_penalty == 2 * 10000.0


def test_evaluator_strict_coverage_full_service_finite():
    """In strict mode with full service (no unserved), objective should be finite."""
    problem = _make_mock_problem("strict")
    
    # Plan with NO unserved trips
    plan = AssignmentPlan(
        duties=(),
        served_trip_ids=("trip1", "trip2"),
        unserved_trip_ids=(),  # Empty!
    )
    
    evaluator = CostEvaluator()
    result = evaluator.evaluate(problem, plan)
    
    # Should have finite objective
    assert result.objective_value != float('inf')
    assert result.unserved_penalty == 0.0
