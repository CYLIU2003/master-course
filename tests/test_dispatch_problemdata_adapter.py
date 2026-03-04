"""
tests/test_dispatch_problemdata_adapter.py

Tests for ProblemData -> dispatch travel-connection adapter.
"""

from src.data_schema import ProblemData, Task, Vehicle
from src.dispatch.problemdata_adapter import build_travel_connections_via_dispatch


def _base_problem_data() -> ProblemData:
    vehicles = [
        Vehicle(vehicle_id="BEV_1", vehicle_type="BEV", home_depot="depot_A"),
        Vehicle(vehicle_id="ICE_1", vehicle_type="ICE", home_depot="depot_A"),
    ]
    tasks = [
        Task(
            task_id="T1",
            start_time_idx=0,
            end_time_idx=2,
            origin="A",
            destination="B",
            distance_km=10.0,
        ),
        Task(
            task_id="T2",
            start_time_idx=3,
            end_time_idx=4,
            origin="B",
            destination="C",
            distance_km=8.0,
        ),
        Task(
            task_id="T3",
            start_time_idx=3,
            end_time_idx=4,
            origin="X",
            destination="Y",
            distance_km=8.0,
        ),
    ]
    return ProblemData(
        vehicles=vehicles,
        tasks=tasks,
        chargers=[],
        sites=[],
        num_periods=16,
        delta_t_hour=0.25,
    )


def test_adapter_builds_connections_from_dispatch_feasibility():
    data = _base_problem_data()

    connections, report = build_travel_connections_via_dispatch(
        data=data,
        service_date="2026-03-04",
        default_turnaround_min=0,
    )

    by_pair = {(c.from_task_id, c.to_task_id): c for c in connections}

    assert report.trip_count == 3
    assert report.generated_connections == 6  # 3 * (3-1)

    assert by_pair[("T1", "T2")].can_follow is True
    assert by_pair[("T1", "T2")].deadhead_time_slot == 0

    # Different location with no deadhead rule must be infeasible.
    assert by_pair[("T1", "T3")].can_follow is False
    assert by_pair[("T1", "T3")].deadhead_time_slot == 0


def test_adapter_honors_explicit_deadhead_rules():
    data = _base_problem_data()

    connections, _ = build_travel_connections_via_dispatch(
        data=data,
        service_date="2026-03-04",
        default_turnaround_min=0,
        deadhead_rules={("B", "X"): 15},
    )

    by_pair = {(c.from_task_id, c.to_task_id): c for c in connections}

    assert by_pair[("T1", "T3")].can_follow is True
    # delta_t=15min, deadhead=15min => 1 slot
    assert by_pair[("T1", "T3")].deadhead_time_slot == 1
