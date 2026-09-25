from dataclasses import replace

import pytest

from src.dispatch.models import DeadheadRule
from src.optimization.milp.solver_adapter import GurobiMILPAdapter
from src.optimization.rolling.reoptimizer import assignment_plan_from_serialized_result
from test_daily_return_policy import daily_problem


@pytest.mark.parametrize("daily_return,expected", [(True, 8), (False, 3)])
def test_exported_chain_roundtrips_with_canonical_deadhead(daily_return, expected):
    problem = daily_problem()
    context = replace(problem.dispatch_context,
        daily_return_depot_id="DEPOT" if daily_return else None,
        deadhead_rules={
            ("B", "A"): DeadheadRule("B", "A", 3),
            ("B", "DEPOT"): DeadheadRule("B", "DEPOT", 5),
            ("DEPOT", "A"): DeadheadRule("DEPOT", "A", 3),
        })
    problem = replace(problem, dispatch_context=context)
    duty = GurobiMILPAdapter()._vehicle_duty_from_trip_chain(
        duty_id="test-duty", vehicle_id="bev-1", vehicle_type="BEV",
        trip_chain=[trip.trip_id for trip in context.trips],
        dispatch_trip_by_id=context.trips_by_id(), problem=problem)
    assert duty.legs[1].deadhead_from_prev_min == expected
    saved = {"duties": [{"duty_id": duty.duty_id, "vehicle_type": "BEV",
        "legs": [{"trip_id": leg.trip.trip_id,
                  "deadhead_from_prev_min": leg.deadhead_from_prev_min} for leg in duty.legs]}],
        "served_trip_ids": [trip.trip_id for trip in context.trips],
        "unserved_trip_ids": [], "metadata": {"duty_vehicle_map": {duty.duty_id: "bev-1"}}}
    restored = assignment_plan_from_serialized_result(problem, saved)
    assert restored.duties[0].legs == duty.legs
    if daily_return:
        saved["duties"][0]["legs"][1]["deadhead_from_prev_min"] = 3
        with pytest.raises(ValueError, match="current canonical rules require 8"):
            assignment_plan_from_serialized_result(problem, saved)
