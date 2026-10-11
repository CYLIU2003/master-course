"""MIP-based LNS for Stage 1: improves a seed in place without changing the model."""
import pytest

gp = pytest.importorskip("gurobipy")
from gurobipy import GRB  # noqa: E402

from src.optimization.milp.solver_adapter import _configured_stage1_gurobi_search_controls  # noqa: E402
from src.optimization.milp.stage1_lns import (  # noqa: E402
    LnsSettings, LnsTrip, lns_settings_from_controls, run_stage1_lns, trip_index_arrays)

TRIPS = [f"2025-01-06::odpt.T{i}" for i in range(8)]


def _assignment_model():
    env = gp.Env(params={"OutputFlag": 0})
    model = gp.Model(env=env)
    vehicles = ["V1", "V2"]
    y = {(v, t): model.addVar(vtype=GRB.BINARY, name=f"y_{v}_{t}") for v in vehicles for t in TRIPS}
    used = {v: model.addVar(vtype=GRB.BINARY, name=f"used_{v}") for v in vehicles}
    for t in TRIPS:
        model.addConstr(gp.quicksum(y[v, t] for v in vehicles) == 1)
    for v in vehicles:
        for t in TRIPS:
            model.addConstr(y[v, t] <= used[v])
    # V1 is cheap for every trip; V2 costs 10 more per trip and 100 to use.
    model.setObjective(gp.quicksum((1 if v == "V1" else 11) * y[v, t] for v, t in y)
                       + 100 * used["V2"] + 5 * used["V1"])
    for (v, t), var in y.items():  # deliberately bad seed: every trip on V2
        var.Start = 1.0 if v == "V2" else 0.0
    used["V1"].Start, used["V2"].Start = 0.0, 1.0
    return model, y  # deliberately not updated: production calls LNS with pending additions


def _trips():
    return [LnsTrip(trip_id=t, start_min=60 * i, day_index=0, route_key=f"R{i % 2}") for i, t in enumerate(TRIPS)]


def test_trip_index_arrays_parse_family_vehicle_and_trip_tokens():
    first, second, many = trip_index_arrays(
        [f"y_V1_{TRIPS[2]}", f"x_V1_{TRIPS[1]}_{TRIPS[3]}", "used_V1"], TRIPS)
    assert first.tolist() == [2, 1, -1] and second.tolist() == [-1, 3, -1] and not many.any()


def test_lns_improves_bad_seed_and_restores_the_model():
    model, y = _assignment_model()
    model.update()
    lb_before = model.getAttr("LB", model.getVars())
    ub_before = model.getAttr("UB", model.getVars())
    time_limit_before = model.Params.TimeLimit
    result = run_stage1_lns(model, GRB, trips=_trips(), optimize=lambda m: m.optimize(),
                            settings=LnsSettings(time_budget_sec=60, iteration_time_limit_sec=2, seed=1, max_iterations=40))
    assert result["applied"] and result["initial_objective"] == pytest.approx(8 * 11 + 100)
    assert result["best_objective"] < result["initial_objective"]
    assert result["accepted"] >= 1
    assert result["best_objective"] == pytest.approx(8 * 1 + 5)  # all trips on V1
    assert model.getAttr("LB", model.getVars()) == lb_before
    assert model.getAttr("UB", model.getVars()) == ub_before
    assert model.Params.TimeLimit == time_limit_before and model.Params.SolutionLimit == 2_000_000_000
    # The best incumbent is the MIP start of the unchanged model.
    model.Params.SolutionLimit = 1
    model.optimize()
    assert model.ObjVal == pytest.approx(result["best_objective"])


def test_lns_profile_and_budget_guard():
    from types import SimpleNamespace
    controls = _configured_stage1_gurobi_search_controls(SimpleNamespace(stage1_gurobi_search_profile="lns_dual"))
    assert controls["lns_enabled"] and controls["root_method"] == 1
    assert lns_settings_from_controls(controls, stage_time_limit_sec=21600, seed=42).time_budget_sec == 19800
    # Too little time for two iterations after the final-solve reserve: no LNS.
    assert lns_settings_from_controls(controls, stage_time_limit_sec=2000, seed=42) is None
    dual = _configured_stage1_gurobi_search_controls(SimpleNamespace(stage1_gurobi_search_profile="bounded_presolve_dual"))
    assert lns_settings_from_controls(dual, stage_time_limit_sec=21600, seed=42) is None


def test_lns_sees_variables_added_without_update():
    model, _ = _assignment_model()
    result = run_stage1_lns(model, GRB, trips=_trips(), optimize=lambda m: m.optimize(),
                            settings=LnsSettings(time_budget_sec=60, iteration_time_limit_sec=2, seed=3, max_iterations=20))
    assert result["applied"] and result["trip_indexed_binary_count"] == 16
    assert result["best_objective"] == pytest.approx(13)
