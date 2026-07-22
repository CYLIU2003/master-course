from __future__ import annotations

import pytest

from src.gurobi_runtime import ensure_gurobi, is_gurobi_available
from src.optimization.common.problem import (
    CanonicalOptimizationProblem,
    ChargerDefinition,
    OptimizationScenario,
    ProblemVehicle,
)
from src.optimization.milp.solver_adapter import GurobiMILPAdapter


def _problem(vehicle_count: int = 7) -> CanonicalOptimizationProblem:
    return CanonicalOptimizationProblem(
        scenario=OptimizationScenario(scenario_id="charger-types"),
        dispatch_context=None,
        trips=(),
        vehicles=tuple(
            ProblemVehicle(
                vehicle_id=f"bev-{index}",
                vehicle_type="BEV",
                home_depot_id="depot",
                charge_power_max_kw=90.0,
            )
            for index in range(vehicle_count)
        ),
        chargers=(
            ChargerDefinition("charger-90", "depot", 90.0, simultaneous_ports=5),
            ChargerDefinition("charger-50", "depot", 50.0, simultaneous_ports=5),
        ),
    )


def _solve_with_fixed_power(power_by_vehicle: dict[str, float]) -> int:
    gp, grb = ensure_gurobi()
    problem = _problem(len(power_by_vehicle))
    model = gp.Model("physical_charger_assignment_test")
    model.Params.OutputFlag = 0
    charge_on = {}
    charge_power = {}
    for vehicle in problem.vehicles:
        key = (vehicle.vehicle_id, 0)
        charge_on[key] = model.addVar(vtype=grb.BINARY)
        charge_power[key] = model.addVar(lb=0.0, ub=90.0)
        model.addConstr(charge_on[key] == 1)
        model.addConstr(charge_power[key] == power_by_vehicle[vehicle.vehicle_id])

    GurobiMILPAdapter()._add_physical_charger_assignment(
        model=model,
        gp=gp,
        grb=grb,
        problem=problem,
        vehicle_by_id={vehicle.vehicle_id: vehicle for vehicle in problem.vehicles},
        vehicle_ids=tuple(power_by_vehicle),
        slot_indices=(0,),
        charge_power_var=charge_power,
        charge_on_var=charge_on,
        name_prefix="test",
    )
    model.optimize()
    return int(model.Status)


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_six_90kw_sessions_cannot_use_five_90kw_ports() -> None:
    _gp, grb = ensure_gurobi()
    status = _solve_with_fixed_power({f"bev-{index}": 90.0 for index in range(6)})

    assert status == grb.INFEASIBLE


@pytest.mark.skipif(not is_gurobi_available(), reason="Gurobi required")
def test_five_90kw_and_two_50kw_sessions_are_feasible() -> None:
    _gp, grb = ensure_gurobi()
    power = {
        **{f"bev-{index}": 90.0 for index in range(5)},
        "bev-5": 50.0,
        "bev-6": 50.0,
    }

    assert _solve_with_fixed_power(power) == grb.OPTIMAL
