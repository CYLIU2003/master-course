from dataclasses import replace
import json
import pytest

from src.optimization.common.problem import ChargingSlot
from src.optimization.common.result import ResultSerializer
from src.optimization.rolling.reoptimizer import RollingReoptimizer, assignment_plan_from_serialized_result
from test_multiday_rolling_contract import _two_day_problem, _fixed_plan


def reference_case():
    problem = _two_day_problem()
    problem = replace(problem, metadata={**problem.metadata,
        "rolling_window_terminal_policy": "day_ahead_boundary_state"})
    fixed = _fixed_plan(problem)
    # The first leg has no preceding trip; only the second has a 30-min transfer.
    duty = fixed.duties[0]
    fixed = replace(fixed, duties=(replace(duty, legs=(replace(duty.legs[0], deadhead_from_prev_min=0), duty.legs[1])),))
    plan = replace(fixed, vehicle_soc_kwh_by_vehicle_slot={"bev-1": {24: 65.5}},
        bess_soc_kwh_by_depot_slot={"DEPOT": {23: 45.5}},
        charging_slots=(ChargingSlot("bev-1", 23, "charger", 30), ChargingSlot("bev-1", 24, "charger", 30)),
        grid_to_bus_kwh_by_depot_slot={"DEPOT": {23: 30}})
    return problem, ResultSerializer.serialize_plan(plan)


def test_saved_reference_reaches_window_without_copying_executed_flows():
    problem, payload = reference_case()
    payload = json.loads(json.dumps(payload))
    plan = assignment_plan_from_serialized_result(problem, payload)
    window = RollingReoptimizer._apply_window_terminal_targets(problem, plan, 0, 24)
    assert window.metadata["bev_terminal_soc_target_kwh_by_vehicle"] == {"bev-1": 65.5}
    assert window.depot_energy_assets["DEPOT"].bess_terminal_soc_target_kwh == 45.5
    assert window.metadata["rolling_window_terminal_reference"]["charge_session_continuation_slots_by_vehicle"] == {"bev-1": 1}
    assert plan.grid_to_bus_kwh_by_depot_slot == {}
    assert plan.duties[0].legs[0].trip is problem.dispatch_context.trips[0]


@pytest.mark.parametrize("value", [None, float("nan"), float("inf"), True])
def test_invalid_soc_is_not_replaced_with_zero(value):
    problem, payload = reference_case()
    payload["vehicle_soc_kwh_by_vehicle_slot"]["bev-1"][24] = value
    with pytest.raises(ValueError, match="Invalid day-ahead reference"):
        assignment_plan_from_serialized_result(problem, payload)


def test_missing_boundary_still_fails_and_legacy_policy_remains_assignment_only():
    problem, payload = reference_case()
    payload["vehicle_soc_kwh_by_vehicle_slot"] = {}
    plan = assignment_plan_from_serialized_result(problem, payload)
    with pytest.raises(ValueError, match="lacks vehicle"):
        RollingReoptimizer._apply_window_terminal_targets(problem, plan, 0, 24)
    legacy = replace(problem, metadata={**problem.metadata, "rolling_window_terminal_policy": "return_to_evaluation_initial"})
    plan = assignment_plan_from_serialized_result(legacy, reference_case()[1])
    assert not plan.charging_slots and not plan.vehicle_soc_kwh_by_vehicle_slot
