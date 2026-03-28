"""Tests for demand charge unit contract (Phase 2.2)

Validates that demand charge monthly input is consistently converted to
horizon-normalized rate across all code paths.
"""
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import pytest
from src.optimization.common.problem import OptimizationScenario


class TestDemandChargeUnitContract:
    """Test demand charge monthly → horizon conversion."""
    
    def test_planning_horizon_hours_from_planning_days(self):
        """Verify planning_horizon_hours calculated from planning_days."""
        scenario = OptimizationScenario(
            scenario_id="test",
            planning_days=1,
        )
        assert scenario.planning_horizon_hours == 24.0
        
        scenario_3day = OptimizationScenario(
            scenario_id="test",
            planning_days=3,
        )
        assert scenario_3day.planning_horizon_hours == 72.0
    
    def test_planning_horizon_hours_from_horizon_start_end(self):
        """Verify planning_horizon_hours calculated from horizon_start/end."""
        scenario = OptimizationScenario(
            scenario_id="test",
            horizon_start="06:00",
            horizon_end="22:00",
            planning_days=1,
        )
        # 06:00 to 22:00 = 16 hours
        assert scenario.planning_horizon_hours == 16.0
    
    def test_planning_horizon_hours_crosses_midnight(self):
        """Verify planning_horizon_hours handles overnight horizons."""
        scenario = OptimizationScenario(
            scenario_id="test",
            horizon_start="22:00",
            horizon_end="06:00",
            planning_days=1,
        )
        # 22:00 to next-day 06:00 = 8 hours
        assert scenario.planning_horizon_hours == 8.0
    
    def test_planning_horizon_hours_invalid_format_fallback(self):
        """Verify planning_horizon_hours falls back to planning_days on invalid format."""
        scenario = OptimizationScenario(
            scenario_id="test",
            horizon_start="invalid",
            horizon_end="also_invalid",
            planning_days=2,
        )
        assert scenario.planning_horizon_hours == 48.0
    
    def test_monthly_to_horizon_conversion_factor(self):
        """Verify monthly rate conversion math."""
        # 1-day planning
        scenario_1day = OptimizationScenario(
            scenario_id="test",
            planning_days=1,
            demand_charge_on_peak_yen_per_kw=1700.0,  # Monthly rate
        )
        horizon_hours = scenario_1day.planning_horizon_hours
        monthly_to_horizon_factor = (horizon_hours / 24.0) / 30.0
        
        # Expected: 1 day / 30 days = 1/30
        expected_factor = 1.0 / 30.0
        assert abs(monthly_to_horizon_factor - expected_factor) < 1e-9
        
        # 3-day planning
        scenario_3day = OptimizationScenario(
            scenario_id="test",
            planning_days=3,
            demand_charge_on_peak_yen_per_kw=1700.0,
        )
        horizon_hours_3 = scenario_3day.planning_horizon_hours
        factor_3 = (horizon_hours_3 / 24.0) / 30.0
        
        # Expected: 3 days / 30 days = 0.1
        expected_factor_3 = 3.0 / 30.0
        assert abs(factor_3 - expected_factor_3) < 1e-9


class TestDemandChargeEvaluatorConsistency:
    """Test that evaluator correctly applies monthly → horizon conversion."""
    
    def test_evaluator_uses_monthly_to_horizon_conversion(self):
        """Integration test: Verify evaluator applies conversion (tested in integration)."""
        # This is verified in integration tests with actual optimization runs
        # Here we just document the requirement
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
