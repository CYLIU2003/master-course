from __future__ import annotations

import pytest

from src.data_schema import ProblemData
from src.optimization.common.builder import ProblemBuilder
from src.optimization.common.problem import OptimizationScenario
from src.optimization.common.time_axis import normalize_timestep_min


def test_normalize_timestep_accepts_5_15_30_or_60() -> None:
    assert normalize_timestep_min(5) == 5
    assert normalize_timestep_min("5min") == 5
    assert normalize_timestep_min("PT5M") == 5
    assert normalize_timestep_min(15) == 15
    assert normalize_timestep_min("15min") == 15
    assert normalize_timestep_min("PT15M") == 15
    assert normalize_timestep_min(30) == 30
    assert normalize_timestep_min("30min") == 30
    assert normalize_timestep_min("PT30M") == 30
    assert normalize_timestep_min(60) == 60
    assert normalize_timestep_min("1h") == 60
    assert normalize_timestep_min("PT1H") == 60
    assert normalize_timestep_min(None) == 30

    with pytest.raises(ValueError):
        normalize_timestep_min(10)


def test_problemdata_and_scenario_timestep_are_synchronized() -> None:
    data = ProblemData(planning_horizon_hours=24.0, delta_t_hour=0.5)
    scenario = OptimizationScenario(scenario_id="s", timestep_min=30)

    assert data.delta_t_min == scenario.timestep_min
    assert data.num_periods == 48

    hourly = ProblemData(planning_horizon_hours=24.0, delta_t_hour=1.0)
    assert hourly.timestep_min == 60
    assert hourly.num_periods == 24

    explicit_periods = ProblemData(num_periods=2, delta_t_hour=1.0)
    assert explicit_periods.timestep_min == 60
    assert explicit_periods.num_periods == 2
    assert explicit_periods.planning_horizon_hours == 2.0


def test_explicit_energy_horizon_duration_overrides_clock_only_window() -> None:
    scenario = OptimizationScenario(
        scenario_id="slot-derived-horizon",
        horizon_start="05:00",
        horizon_end="23:00",
        horizon_duration_min=24 * 60,
        timestep_min=15,
        demand_charge_on_peak_yen_per_kw=1200.0,
    )

    assert scenario.planning_horizon_hours == 24.0
    assert scenario.demand_charge_horizon_factor == pytest.approx(1.0 / 30.0)
    assert scenario.demand_charge_on_peak_horizon_yen_per_kw == pytest.approx(40.0)


def test_explicit_energy_horizon_duration_supports_multiple_days() -> None:
    scenario = OptimizationScenario(
        scenario_id="two-day-horizon",
        horizon_start="05:00",
        horizon_end="05:00",
        horizon_duration_min=48 * 60,
        planning_days=2,
    )

    assert scenario.planning_horizon_hours == 48.0


def _operation_window_scenario(*, enabled: bool) -> dict:
    return {
        "meta": {"id": "operation-window-test"},
        "simulation_config": {
            "operation_time_window_enabled": enabled,
            "start_time": "05:00",
            "end_time": "23:00",
            "timestep_min": 60,
        },
        "scenario_overlay": {
            "solver_config": {},
            "cost_coefficients": {},
            "charging_constraints": {},
        },
        "depots": [{"id": "dep-1", "name": "Depot 1"}],
        "routes": [{"id": "route-1", "route_id": "route-1"}],
        "vehicles": [
            {
                "id": "bev-1",
                "depotId": "dep-1",
                "type": "BEV",
                "batteryKwh": 300.0,
                "energyConsumption": 1.2,
                "chargePowerKw": 60.0,
            }
        ],
        "chargers": [{"id": "charger-1", "siteId": "dep-1", "powerKw": 60.0}],
        "timetable_rows": [
            {
                "trip_id": "trip-1",
                "route_id": "route-1",
                "origin": "A",
                "destination": "B",
                "departure": "08:00",
                "arrival": "08:30",
                "distance_km": 10.0,
                "service_id": "WEEKDAY",
                "allowed_vehicle_types": ["BEV"],
            }
        ],
        "deadhead_rules": [],
        "turnaround_rules": [],
    }


def test_problem_builder_uses_an_exact_full_day_when_window_is_disabled() -> None:
    problem = ProblemBuilder().build_from_scenario(
        _operation_window_scenario(enabled=False),
        depot_id="dep-1",
        service_id="WEEKDAY",
    )

    assert problem.scenario.horizon_start == "00:00"
    assert problem.scenario.horizon_end == "00:00"
    assert problem.scenario.horizon_duration_min == 24 * 60
    assert len(problem.price_slots) == 24
    assert problem.metadata["operation_time_window_enabled"] is False
    assert problem.metadata["operation_time_window_requested_start_time"] == "05:00"
    assert problem.metadata["operation_time_window_effective_start_time"] == "00:00"
    assert problem.metadata["operation_time_window_effective_end_time"] == "23:59"


def test_problem_builder_keeps_the_pair_when_window_is_enabled() -> None:
    problem = ProblemBuilder().build_from_scenario(
        _operation_window_scenario(enabled=True),
        depot_id="dep-1",
        service_id="WEEKDAY",
    )

    assert problem.scenario.horizon_start == "05:00"
    assert problem.metadata["operation_time_window_enabled"] is True
    assert problem.metadata["operation_time_window_mode"] == "scoped"
    assert problem.metadata["operation_time_window_effective_start_time"] == "05:00"
    assert problem.metadata["operation_time_window_effective_end_time"] == "23:00"
