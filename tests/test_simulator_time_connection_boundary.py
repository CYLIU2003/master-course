from __future__ import annotations

from src.data_schema import ProblemData, Site, Task, Vehicle
from src.milp_model import MILPResult
from src.model_sets import build_model_sets
from src.parameter_builder import build_derived_params
from src.simulator import check_schedule_feasibility


def test_back_to_back_tasks_do_not_trigger_time_connection_overlap_without_can_follow() -> None:
    data = ProblemData(
        vehicles=[
            Vehicle(
                vehicle_id="veh-1",
                vehicle_type="ICE",
                home_depot="dep-1",
            )
        ],
        tasks=[
            Task(
                task_id="trip-1",
                start_time_idx=0,
                end_time_idx=1,
                origin="A",
                destination="B",
                fuel_required_liter_ice=1.0,
            ),
            Task(
                task_id="trip-2",
                start_time_idx=1,
                end_time_idx=2,
                origin="B",
                destination="C",
                fuel_required_liter_ice=1.0,
            ),
        ],
        sites=[Site(site_id="dep-1", site_type="depot")],
        num_periods=3,
        delta_t_hour=1.0,
    )
    ms = build_model_sets(data)
    dp = build_derived_params(data, ms)
    dp.can_follow = {}
    result = MILPResult(
        status="feasible",
        assignment={"veh-1": ["trip-1", "trip-2"]},
    )

    report = check_schedule_feasibility(data, ms, dp, result)

    assert report.time_connection_ok is True
    assert not any(issue.category == "time_connection" for issue in report.issues)
