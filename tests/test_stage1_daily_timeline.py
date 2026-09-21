"""Stage 1 must contain the physical daily-return charging opportunities."""
from dataclasses import replace

import pytest

from src.dispatch.models import DeadheadRule, DutyLeg, VehicleDuty
from src.optimization.common.problem import AssignmentPlan, EnergyPriceSlot
from src.optimization.common.vehicle_timeline import fixed_path_slot_loads
from src.optimization.milp.solver_adapter import GurobiMILPAdapter
from test_daily_return_policy import daily_problem


@pytest.mark.parametrize("sparse", [False, True])
@pytest.mark.parametrize("second_origin", ["A", "DEPOT"])
def test_fixed_path_has_identical_movement_postings_and_complete_home_slots(sparse, second_origin):
    gp = pytest.importorskip("gurobipy")
    problem = daily_problem()
    first, second = problem.trips
    first = replace(first, arrival_min=551)
    second = replace(second, origin=second_origin, departure_min=1913, arrival_min=1973)
    rules = {**problem.dispatch_context.deadhead_rules,
             ("B", "DEPOT"): DeadheadRule("B", "DEPOT", 17),
             ("DEPOT", "A"): DeadheadRule("DEPOT", "A", 19)}
    dispatch = [replace(problem.dispatch_context.trips[0], arrival_time="09:11"),
                replace(problem.dispatch_context.trips[1], origin=second_origin,
                        departure_time="31:53", arrival_time="32:53")]
    problem = replace(problem, trips=(first, second),
        depot_energy_assets={},
        scenario=replace(problem.scenario, timestep_min=15),
        dispatch_context=replace(problem.dispatch_context, trips=dispatch, deadhead_rules=rules),
        price_slots=tuple(EnergyPriceSlot(i) for i in range(192)),
        metadata={**problem.metadata, "stage1_sparse_charge_window_support": sparse,
            "charging_power_model": "piecewise_soc_taper_v1", "charge_setup_minutes": 5,
            "charge_teardown_minutes": 5, "minimum_charge_session_minutes": 15})
    plan = AssignmentPlan(duties=(VehicleDuty("duty", "BEV", tuple(DutyLeg(t) for t in dispatch)),),
        served_trip_ids=(first.trip_id, second.trip_id), metadata={"duty_vehicle_map": {"duty": "bev-1"}})
    expected = fixed_path_slot_loads(problem, plan, list(range(192)))
    vehicle = problem.vehicles[0]
    adapter = GurobiMILPAdapter()
    with gp.Env(empty=True) as env:
        env.setParam("OutputFlag", 0)
        env.start()
        with gp.Model(env=env) as model:
            one = lambda: model.addVar(lb=1, ub=1, vtype=gp.GRB.BINARY)
            adapter._add_stage1_time_indexed_soc_relaxation(model, gp=gp, grb=gp.GRB,
                problem=problem, trip_by_id=problem.trip_by_id(), vehicles=(vehicle,),
                assignment_trip_ids_by_vehicle={"bev-1": plan.served_trip_ids},
                startup_energy_precheck_by_assignment={("bev-1", first.trip_id):
                    adapter._startup_energy_precheck(problem, vehicle, first)},
                y={("bev-1", t.trip_id): one() for t in problem.trips},
                x={("bev-1", first.trip_id, second.trip_id): one()},
                start_arc={("bev-1", first.trip_id): one()},
                end_arc={("bev-1", second.trip_id): one()}, used_vehicle={"bev-1": one()})
            model.update()
            for slot in range(192):
                row = model.getConstrByName(f"stage1_soc_transition__bev-1__slot_{slot}")
                expression = model.getRow(row)
                constant = sum(expression.getCoeff(i) * expression.getVar(i).LB
                    for i in range(expression.size()) if expression.getVar(i).LB == expression.getVar(i).UB)
                load = constant - row.RHS + (80 if slot == 0 else 0)
                assert load == pytest.approx(expected.energy_kwh.get(("bev-1", slot), 0))
            available = [model.getVarByName(f"stage1_charge_available__bev-1__slot_{slot}")
                         for slot in range(192)]
            model.setObjective(gp.quicksum(available), gp.GRB.MAXIMIZE)
            model.optimize()
            assert model.Status == gp.GRB.OPTIMAL
            actual = {slot for slot, var in enumerate(available) if var.X > .99}
            assert actual == expected.home_slots["bev-1"]
