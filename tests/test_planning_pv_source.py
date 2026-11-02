import pytest

from scripts.benchmarks.prepare_shibu21_24_seasonal_inputs import planning_pv_profiles

FORECAST, ACTUAL = {"2025-01-06": [0.5]}, {"2025-01-06": [0.1]}


def test_default_plan_uses_the_forecast():
    assert planning_pv_profiles(FORECAST, ACTUAL, "forecast") is FORECAST


def test_hindsight_plan_uses_the_actuals():
    assert planning_pv_profiles(FORECAST, ACTUAL, "actual_hindsight") is ACTUAL


def test_unknown_source_is_rejected():
    with pytest.raises(ValueError, match="Unknown planning PV source"):
        planning_pv_profiles(FORECAST, ACTUAL, "typo")
