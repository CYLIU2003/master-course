"""A Stage 1 seed is a MIP start only: rejected seeds stop the run, and the objective ignores it."""
import inspect
from types import SimpleNamespace

from bff.routers.optimization import RunOptimizationBody
from src.optimization.common.problem import OptimizationConfig
from src.optimization.milp import seed_snapshot, solver_adapter


def test_request_carries_rolling_limit_and_embedded_seed():
    body = RunOptimizationBody(rolling_time_limit_seconds=600, stage1_seed_plan={"duties": []})
    dumped = body.model_dump()
    assert dumped["rolling_time_limit_seconds"] == 600 and dumped["stage1_seed_plan"] == {"duties": []}
    defaults = RunOptimizationBody().model_dump()
    assert defaults["rolling_time_limit_seconds"] is None and defaults["stage1_seed_plan"] is None


def test_seed_is_a_separate_config_field_not_the_baseline():
    assert OptimizationConfig().stage1_seed_plan is None
    # switch cost reads problem.baseline_plan, so the seed must not be stored there.
    source = inspect.getsource(seed_snapshot.restore_stage1_seed_plan)
    assert "baseline_plan" not in source


def test_restore_marks_the_seed_source(monkeypatch):
    from src.optimization.common.problem import AssignmentPlan
    from src.optimization.rolling import reoptimizer
    monkeypatch.setattr(reoptimizer, "assignment_plan_from_serialized_result",
                        lambda problem, payload: AssignmentPlan(metadata={"duty_vehicle_map": {"d": "v"}}))
    plan = seed_snapshot.restore_stage1_seed_plan(SimpleNamespace(), {"duties": []})
    assert plan.metadata == {"duty_vehicle_map": {"d": "v"}, "source": "stage1_seed_from_prior_run"}


def test_rejected_seed_stops_the_run():
    source = inspect.getsource(solver_adapter)
    assert '"stage1_seed_plan was rejected: "' in source


def test_request_accepts_the_fixed_assignment_charging_start():
    body = RunOptimizationBody(stage2_charging_start_policy="fixed_assignment_binary")
    assert body.model_dump()["stage2_charging_start_policy"] == "fixed_assignment_binary"


def _charging_problem():
    return SimpleNamespace(vehicles=[SimpleNamespace(vehicle_id="v1")],
                           chargers=[SimpleNamespace(charger_id="c1")])


def test_restore_carries_the_anchor_charging_as_a_start(monkeypatch):
    import pytest
    from src.optimization.common.problem import AssignmentPlan, ChargingSlot
    from src.optimization.rolling import reoptimizer
    monkeypatch.setattr(reoptimizer, "assignment_plan_from_serialized_result",
                        lambda problem, payload: AssignmentPlan(metadata={}))
    payload = {"duties": [], "charging_slots": [{"vehicle_id": "v1", "slot_index": 3, "charger_id": "c1", "charge_kw": 30.0}],
               "charging_start_source": {"result_sha256": "x"}}
    plan = seed_snapshot.restore_stage1_seed_plan(_charging_problem(), payload)
    assert plan.charging_slots == (ChargingSlot("v1", 3, "c1", charge_kw=30.0),)
    assert plan.metadata["charging_start_source"] == {"result_sha256": "x"}
    assert seed_snapshot.restore_stage1_seed_plan(_charging_problem(), {"duties": []}).charging_slots == ()
    for bad in ({"vehicle_id": "v9"}, {"charger_id": "c9"}, {"charge_kw": -1.0}):
        row = {"vehicle_id": "v1", "slot_index": 3, "charger_id": "c1", "charge_kw": 30.0, **bad}
        with pytest.raises(ValueError):
            seed_snapshot.restore_stage1_seed_plan(_charging_problem(), {"duties": [], "charging_slots": [row]})


def test_extractor_sums_the_anchor_charging_per_vehicle_slot_charger():
    import pytest
    from tools.research.extract_stage1_seed import charging_start_from_result
    rows = [{"vehicle_id": "v1", "slot_index": 0, "charger_id": "c1", "charge_kw": 10.0, "discharge_kw": 0.0, "energy_source": "grid"},
            {"vehicle_id": "v1", "slot_index": 0, "charger_id": "c1", "charge_kw": 5.0, "discharge_kw": 0.0, "energy_source": "pv"}]
    result = {"feasible": True, "solver_metadata": {"stage2_has_feasible_incumbent": True}, "charging_schedule": rows}
    assert charging_start_from_result(result) == [{"vehicle_id": "v1", "slot_index": 0, "charger_id": "c1", "charge_kw": 15.0}]
    with pytest.raises(ValueError):
        charging_start_from_result({**result, "feasible": False})
