from src.data_schema import ProblemData, Site, Task, Vehicle
from src.model_sets import build_model_sets
from src.parameter_builder import build_derived_params


def _base_problem(tasks):
    return ProblemData(
        vehicles=[
            Vehicle(
                vehicle_id="BEV_1",
                vehicle_type="BEV",
                home_depot="depot_a",
                battery_capacity=300.0,
            )
        ],
        tasks=tasks,
        sites=[Site(site_id="depot_a", site_type="depot")],
        num_periods=8,
        delta_t_hour=0.5,
    )


def test_backfill_bev_energy_from_distance_when_missing() -> None:
    data = _base_problem(
        [
            Task(
                task_id="t1",
                start_time_idx=0,
                end_time_idx=1,
                origin="A",
                destination="B",
                distance_km=10.0,
                energy_required_kwh_bev=0.0,
            )
        ]
    )
    ms = build_model_sets(data)
    dp = build_derived_params(data, ms)

    # Default fallback rate is 1.8 kWh/km when no empirical rate is available.
    assert abs(dp.task_energy_bev["t1"] - 18.0) < 1.0e-9
    assert sum(dp.task_energy_per_slot["t1"]) > 0.0


def test_backfill_uses_empirical_rate_when_available() -> None:
    data = _base_problem(
        [
            Task(
                task_id="known",
                start_time_idx=0,
                end_time_idx=0,
                origin="A",
                destination="B",
                distance_km=10.0,
                energy_required_kwh_bev=15.0,
            ),
            Task(
                task_id="missing",
                start_time_idx=1,
                end_time_idx=1,
                origin="B",
                destination="C",
                distance_km=8.0,
                energy_required_kwh_bev=0.0,
            ),
        ]
    )
    ms = build_model_sets(data)
    dp = build_derived_params(data, ms)

    # known rate is 1.5 kWh/km, so missing becomes 12.0 kWh
    assert abs(dp.task_energy_bev["missing"] - 12.0) < 1.0e-9
