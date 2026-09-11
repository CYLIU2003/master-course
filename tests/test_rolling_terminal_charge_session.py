"""Regression tests for the finite rolling-window charging boundary."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    ChargingSlot,
    OptimizationScenario,
)
from src.optimization.milp.solver_adapter import GurobiMILPAdapter
from src.optimization.rolling.reoptimizer import RollingReoptimizer


def _piecewise_boundary_problem(
    *, minimum_charge_session_minutes: int
) -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(
            scenario_id="rolling-terminal-charge-session",
            horizon_start="00:00",
            timestep_min=15,
        ),
        dispatch_context=None,
        trips=(),
        vehicles=(),
        metadata={
            "charging_power_model": "piecewise_soc_taper_v1",
            "charge_setup_minutes": 5,
            "charge_teardown_minutes": 5,
            "minimum_charge_session_minutes": minimum_charge_session_minutes,
        },
    )


def _solve_boundary_model(
    *, minimum_charge_session_minutes: int, continuation_slots: int = 0
):
    gp = pytest.importorskip("gurobipy")
    try:
        model = gp.Model("rolling_terminal_charge_session")
    except gp.GurobiError as exc:  # pragma: no cover - license-dependent CI
        pytest.skip(f"Gurobi model creation unavailable: {exc}")
    model.Params.OutputFlag = 0
    charge_on = model.addVar(vtype=gp.GRB.BINARY, name="charge_on")
    charge_power = model.addVar(lb=0.0, ub=90.0, name="charge_power")
    soc = model.addVar(lb=0.0, ub=300.0, name="soc")
    model.addConstr(charge_on == 1)
    model.addConstr(soc == 150.0)
    GurobiMILPAdapter()._add_piecewise_charge_power_constraints(
        model=model,
        gp=gp,
        GRB=gp.GRB,
        problem=_piecewise_boundary_problem(
            minimum_charge_session_minutes=minimum_charge_session_minutes
        ),
        vehicle_id="ev-1",
        slot_indices=(6,),
        soc_var={("ev-1", 6): soc},
        charge_power_var={("ev-1", 6): charge_power},
        charge_on_var={("ev-1", 6): charge_on},
        capacity_kwh=300.0,
        charge_max_kw=90.0,
        timestep_h=0.25,
        session_start_var=None,
        name_prefix="rolling_terminal",
        terminal_session_continuation_slots=continuation_slots,
    )
    model.setObjective(charge_power, gp.GRB.MAXIMIZE)
    model.optimize()
    return gp, model, charge_power


def test_terminal_boundary_continuation_keeps_setup_but_defers_teardown() -> None:
    """A 15-minute new session is 60 kW; a true evaluation end is 30 kW."""

    closed_gp, closed_model, closed_power = _solve_boundary_model(
        minimum_charge_session_minutes=15
    )
    assert closed_model.Status == closed_gp.GRB.OPTIMAL
    assert closed_power.X == pytest.approx(30.0, abs=1.0e-6)
    closed_model.dispose()

    continuation_gp, continuation_model, continuation_power = _solve_boundary_model(
        minimum_charge_session_minutes=15, continuation_slots=1
    )
    assert continuation_model.Status == continuation_gp.GRB.OPTIMAL
    assert continuation_power.X == pytest.approx(60.0, abs=1.0e-6)
    continuation_model.dispose()


def test_known_future_suffix_satisfies_thirty_minute_minimum_session() -> None:
    """A two-slot minimum can cross the window only with one known future slot."""

    closed_gp, closed_model, _ = _solve_boundary_model(
        minimum_charge_session_minutes=30
    )
    assert closed_model.Status == closed_gp.GRB.INFEASIBLE
    closed_model.dispose()

    continuation_gp, continuation_model, _ = _solve_boundary_model(
        minimum_charge_session_minutes=30, continuation_slots=1
    )
    assert continuation_model.Status == continuation_gp.GRB.OPTIMAL
    continuation_model.dispose()



def test_reference_session_metadata_requires_both_sides_and_restores_at_evaluation_end() -> None:
    """Only a positive boundary pair may extend a fixed reference session."""

    from test_multiday_rolling_contract import _fixed_plan, _two_day_problem

    problem = _two_day_problem()
    problem = replace(
        problem,
        metadata={
            **problem.metadata,
            "rolling_window_terminal_policy": "day_ahead_boundary_state",
        },
    )
    rolling = RollingReoptimizer()
    boundary = 25
    plan = replace(
        _fixed_plan(problem),
        charging_slots=(
            ChargingSlot("bev-1", boundary - 1, "charger-a", charge_kw=30.0),
            ChargingSlot("bev-1", boundary, "charger-b", charge_kw=30.0),
            ChargingSlot("bev-1", boundary + 1, "charger-c", charge_kw=30.0),
        ),
        vehicle_soc_kwh_by_vehicle_slot={"bev-1": {boundary: 80.0}},
        bess_soc_kwh_by_depot_slot={"DEPOT": {boundary - 1: 50.0}},
    )
    intermediate = rolling._apply_window_terminal_targets(
        problem, plan, current_min=60, lookahead_hours=24
    )
    reference = intermediate.metadata["rolling_window_terminal_reference"]
    assert reference["charge_session_continuation_slots_by_vehicle"] == {
        "bev-1": 2
    }

    no_future_charge = replace(
        plan,
        charging_slots=(
            ChargingSlot("bev-1", boundary - 1, "charger-a", charge_kw=30.0),
        ),
    )
    no_continuation = rolling._apply_window_terminal_targets(
        problem, no_future_charge, current_min=60, lookahead_hours=24
    )
    assert no_continuation.metadata["rolling_window_terminal_reference"][
        "charge_session_continuation_slots_by_vehicle"
    ] == {}

    evaluation_end = rolling._apply_window_terminal_targets(
        problem, plan, current_min=24 * 60, lookahead_hours=24
    )
    assert "rolling_window_terminal_reference" not in evaluation_end.metadata
