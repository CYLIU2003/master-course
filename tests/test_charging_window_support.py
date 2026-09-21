from dataclasses import replace
from itertools import product

import pytest

from src.optimization.milp.charging_window_support import ChargingWindowSupportEvents


def test_endpoint_recurrence_preserves_every_slot_and_duplicate_opportunity():
    slots = (2, 4, 7, 10, 11)
    windows = ((2, 4, 7, 10, 11), (4, 4, 10), (7,), (), (11,))
    for values in product((0.0, 0.3, 1.0), repeat=len(windows)):
        events = ChargingWindowSupportEvents(slots)
        for window, value in zip(windows, values):
            events.add_slots(window, value)
        running = 0.0
        for position, slot in enumerate(slots):
            running += sum(events.events.get(position, ()))
            assert running == pytest.approx(sum(window.count(slot) * value for window, value in zip(windows, values)))


def test_support_rejects_bad_domain():
    with pytest.raises(ValueError):
        ChargingWindowSupportEvents((3, 1))
    with pytest.raises(ValueError):
        ChargingWindowSupportEvents((1, 1))
    with pytest.raises(KeyError):
        ChargingWindowSupportEvents((1, 2)).add_slots((3,), 1.0)


def test_native_sparse_support_preserves_lp_value_and_reduces_nonzeros():
    gp = pytest.importorskip("gurobipy")
    slots = tuple(range(200))
    windows = [tuple(range(i, 200 - i)) for i in range(40)]
    results = []
    for sparse in (False, True):
        with gp.Model() as model:
            model.Params.OutputFlag = 0
            model.Params.Threads = 1
            model.Params.Presolve = 0
            x = model.addVars(len(windows), lb=0, ub=1)
            a = model.addVars(slots, lb=0, ub=1)
            model.addConstr(gp.quicksum(x.values()) <= 0.65)
            if sparse:
                events = ChargingWindowSupportEvents(slots)
                for i, window in enumerate(windows):
                    events.add_slots(window, x[i])
                support = events.build(model, gp, gp.GRB, vehicle_id="test")
            else:
                support = {slot: gp.quicksum(x[i] for i,w in enumerate(windows) if slot in w) for slot in slots}
            for slot in slots:
                model.addConstr(a[slot] <= support[slot])
            model.setObjective(gp.quicksum((slot % 7 + 1) * a[slot] for slot in slots), gp.GRB.MAXIMIZE)
            model.optimize()
            assert model.Status == gp.GRB.OPTIMAL
            results.append((model.ObjVal, model.NumNZs))
    assert results[0][0] == pytest.approx(results[1][0])
    assert results[1][1] < results[0][1] / 5


def test_native_full_two_day_pipeline_preserves_physical_feasibility_and_objective():
    pytest.importorskip("gurobipy")
    from test_daily_return_policy import daily_problem
    from src.optimization.engine import OptimizationEngine
    from src.optimization.common.problem import OptimizationConfig, OptimizationMode
    from src.optimization.validation.physical_event_schedule import validate_physical_event_schedule
    from src.optimization.common.result import ResultSerializer
    results = []
    for sparse in (False, True):
        problem = daily_problem()
        problem = replace(problem, metadata={**problem.metadata,
            "max_start_fragments_per_vehicle": 100, "max_end_fragments_per_vehicle": 100,
            "stage1_sparse_charge_window_support": sparse})
        config = OptimizationConfig(mode=OptimizationMode.MILP, phase="phase3_two_stage",
            time_limit_sec=20, stage1_time_limit_sec=5, stage2_time_limit_sec=5,
            gurobi_threads=1, stage1_best_obj_stop_enabled=False)
        result = OptimizationEngine().solve(problem, config)
        assert result.feasible, result.infeasibility_reasons
        physical = validate_physical_event_schedule(problem=problem, serialized_result=ResultSerializer.serialize_plan(result.plan))
        assert physical["accepted"], physical["violations"]
        audit = result.plan.metadata["stage1_shared_charger_relaxation"]["charge_window_support"]
        assert audit["representation"] == ("endpoint_events" if sparse else "dense_slots")
        results.append(result)
    assert results[0].plan.metadata["stage1_objective"] == pytest.approx(results[1].plan.metadata["stage1_objective"])
    assert results[0].objective_value == pytest.approx(results[1].objective_value)
