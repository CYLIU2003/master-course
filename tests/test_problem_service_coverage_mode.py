"""Tests for service_coverage_mode in OptimizationScenario."""

import pytest
from src.optimization.common.problem import OptimizationScenario


def test_service_coverage_mode_default_strict():
    """Test that service_coverage_mode defaults to 'strict'."""
    scenario = OptimizationScenario(scenario_id="test_scenario")
    assert scenario.service_coverage_mode == "strict"


def test_service_coverage_mode_penalized():
    """Test that 'penalized' mode can be set."""
    scenario = OptimizationScenario(
        scenario_id="test_scenario",
        service_coverage_mode="penalized"
    )
    assert scenario.service_coverage_mode == "penalized"


def test_service_coverage_mode_strict():
    """Test that 'strict' mode can be explicitly set."""
    scenario = OptimizationScenario(
        scenario_id="test_scenario",
        service_coverage_mode="strict"
    )
    assert scenario.service_coverage_mode == "strict"


def test_service_coverage_mode_dataclass_immutable():
    """Test that OptimizationScenario is still frozen."""
    scenario = OptimizationScenario(scenario_id="test_scenario")
    with pytest.raises(Exception):  # frozen dataclass raises FrozenInstanceError or AttributeError
        scenario.service_coverage_mode = "penalized"
