from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

from src.data_schema import ProblemData, Task, Vehicle
from src.dispatch.problemdata_adapter import build_travel_connections_via_dispatch


def test_build_travel_connections_via_dispatch_returns_only_feasible_edges() -> None:
    data = ProblemData(
        vehicles=[
            Vehicle(
                vehicle_id="veh-1",
                vehicle_type="BEV",
                home_depot="dep-1",
                battery_capacity=300.0,
            )
        ],
        tasks=[
            Task(task_id="trip-1", start_time_idx=0, end_time_idx=1, origin="A", destination="B"),
            Task(task_id="trip-2", start_time_idx=2, end_time_idx=3, origin="B", destination="C"),
            Task(task_id="trip-3", start_time_idx=4, end_time_idx=5, origin="C", destination="D"),
        ],
        delta_t_hour=0.5,
    )

    pipeline_result = SimpleNamespace(
        graph={
            "trip-1": ["trip-2"],
            "trip-2": ["trip-3"],
            "trip-3": [],
        },
        warnings=[],
    )

    with mock.patch(
        "src.dispatch.problemdata_adapter.TimetableDispatchPipeline.run",
        return_value=pipeline_result,
    ):
        connections, report = build_travel_connections_via_dispatch(
            data=data,
            service_date="2026-03-22",
        )

    assert {(c.from_task_id, c.to_task_id) for c in connections} == {
        ("trip-1", "trip-2"),
        ("trip-2", "trip-3"),
    }
    assert all(c.can_follow for c in connections)
    assert report.generated_connections == 2
