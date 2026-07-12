from __future__ import annotations

import pytest

from src.data_schema import ProblemData
from src.optimization.common.problem import OptimizationScenario
from src.optimization.common.time_axis import normalize_timestep_min


def test_normalize_timestep_accepts_15_30_or_60() -> None:
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
        normalize_timestep_min(5)


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
