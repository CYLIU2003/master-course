from src.data_schema import ProblemData, Task, Vehicle
from src.model_sets import build_model_sets
from src.parameter_builder import build_derived_params
from src.refuel_schedule import compute_refuel_schedule_l


def test_compute_refuel_schedule_for_ice_vehicle() -> None:
    data = ProblemData(
        vehicles=[
            Vehicle(
                vehicle_id="ice-1",
                vehicle_type="ICE",
                home_depot="dep-1",
                fuel_tank_capacity=160.0,
            )
        ],
        tasks=[
            Task(
                task_id="t1",
                start_time_idx=0,
                end_time_idx=1,
                origin="A",
                destination="B",
                distance_km=10.0,
                fuel_required_liter_ice=50.0,
            ),
            Task(
                task_id="t2",
                start_time_idx=2,
                end_time_idx=3,
                origin="B",
                destination="C",
                distance_km=10.0,
                fuel_required_liter_ice=50.0,
            ),
        ],
        num_periods=8,
        delta_t_hour=0.5,
    )
    data.initial_ice_fuel_percent = 60.0
    data.min_ice_fuel_percent = 10.0
    data.max_ice_fuel_percent = 90.0
    data.default_ice_tank_capacity_l = 160.0

    ms = build_model_sets(data)
    dp = build_derived_params(data, ms)

    schedule = compute_refuel_schedule_l(
        data,
        ms,
        dp,
        assignment={"ice-1": ["t1", "t2"]},
    )

    assert "ice-1" in schedule
    assert len(schedule["ice-1"]) == data.num_periods
    assert sum(schedule["ice-1"]) > 0.0
