"""
Test solver path routing and legacy mode deprecation.

Verifies Phase 1: Unify or Hard-Gate Solver Paths
"""
from __future__ import annotations

import pytest
import warnings

# Import the function we're testing
import sys
from pathlib import Path
repo_root = Path(__file__).parents[1]
sys.path.insert(0, str(repo_root))

from bff.routers.optimization import _normalize_solver_mode


class TestSolverPathRouting:
    """Test that solver mode normalization correctly handles canonical and legacy modes."""
    
    def test_canonical_modes_pass_through(self):
        """Canonical modes should pass through unchanged."""
        canonical_modes = [
            "mode_milp_only",
            "mode_alns_only",
            "mode_ga_only",
            "mode_abc_only",
            "mode_hybrid",
        ]
        for mode in canonical_modes:
            result = _normalize_solver_mode(mode)
            assert result == mode, f"Canonical mode {mode} should pass through unchanged"
    
    def test_mode_aliases_resolve_to_canonical(self):
        """Aliases should resolve to their canonical equivalents."""
        test_cases = [
            ("milp", "mode_milp_only"),
            ("exact", "mode_milp_only"),
            ("alns", "mode_alns_only"),
            ("heuristic", "mode_alns_only"),
            ("ga", "mode_ga_only"),
            ("genetic", "mode_ga_only"),
            ("abc", "mode_abc_only"),
            ("colony", "mode_abc_only"),
            ("hybrid", "mode_hybrid"),
        ]
        for alias, expected in test_cases:
            result = _normalize_solver_mode(alias)
            assert result == expected, f"Alias '{alias}' should resolve to '{expected}'"
    
    def test_mode_alns_milp_auto_routes_with_warning(self):
        """mode_alns_milp should auto-route to mode_hybrid with deprecation warning."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = _normalize_solver_mode("mode_alns_milp")
            
            assert result == "mode_hybrid", "mode_alns_milp should route to mode_hybrid"
            assert len(w) == 1, "Should emit exactly one warning"
            assert issubclass(w[0].category, DeprecationWarning)
            assert "deprecated" in str(w[0].message).lower()
            assert "mode_hybrid" in str(w[0].message)
    
    def test_legacy_thesis_modes_are_blocked(self):
        """Legacy thesis modes should raise ValueError with clear message."""
        blocked_modes = [
            "thesis_mode",
            "mode_a_journey_charge",
            "mode_a",
            "mode_b_optimistic",
            "mode_b",
        ]
        for mode in blocked_modes:
            with pytest.raises(ValueError) as exc_info:
                _normalize_solver_mode(mode)
            
            error_msg = str(exc_info.value).lower()
            assert "no longer supported" in error_msg or "deprecated" in error_msg
            assert "canonical" in error_msg, "Error should guide to canonical modes"
    
    def test_case_insensitive_normalization(self):
        """Mode strings should be case-insensitive."""
        test_cases = [
            ("MODE_MILP_ONLY", "mode_milp_only"),
            ("Mode_Alns_Only", "mode_alns_only"),
            ("MILP", "mode_milp_only"),
            ("Hybrid", "mode_hybrid"),
        ]
        for input_mode, expected in test_cases:
            result = _normalize_solver_mode(input_mode)
            assert result == expected, f"'{input_mode}' should normalize to '{expected}'"
    
    def test_empty_or_none_defaults_to_milp(self):
        """Empty or None mode should default to mode_milp_only."""
        assert _normalize_solver_mode("") == "mode_milp_only"
        assert _normalize_solver_mode(None) == "mode_milp_only"
        assert _normalize_solver_mode("   ") == "mode_milp_only"
    
    def test_unknown_mode_passes_through(self):
        """Unknown modes should pass through (will be caught downstream)."""
        # This maintains backward compat for any edge cases
        unknown = "some_future_mode"
        result = _normalize_solver_mode(unknown)
        # Should either pass through or default depending on implementation
        assert result in {unknown, "mode_milp_only"}


class TestOptimizationCapabilities:
    """Test that optimization capabilities endpoint reports correct modes."""
    
    def test_capabilities_lists_only_canonical_modes(self):
        """Capabilities should list only supported canonical modes."""
        from bff.routers.optimization import _optimization_capabilities
        
        caps = _optimization_capabilities()
        
        assert "supported_modes" in caps
        supported = caps["supported_modes"]
        
        # All canonical modes should be listed
        expected_modes = {
            "mode_milp_only",
            "mode_alns_only",
            "mode_ga_only",
            "mode_abc_only",
            "mode_hybrid",
        }
        assert set(supported) == expected_modes
        
        # Legacy modes should NOT be in supported list
        legacy_modes = {"thesis_mode", "mode_a_journey_charge", "mode_alns_milp"}
        assert not legacy_modes.intersection(set(supported))
    
    def test_capabilities_documents_deprecated_modes(self):
        """Capabilities should document deprecated modes and their replacements."""
        from bff.routers.optimization import _optimization_capabilities
        
        caps = _optimization_capabilities()
        
        assert "deprecated_modes" in caps
        deprecated = caps["deprecated_modes"]
        
        # mode_alns_milp should be listed as deprecated with hybrid replacement
        assert "mode_alns_milp" in deprecated
        assert "mode_hybrid" in deprecated["mode_alns_milp"].lower()
        
        # Blocked modes should be documented
        assert "thesis_mode" in deprecated
        assert "blocked" in deprecated["thesis_mode"].lower() or "no longer supported" in deprecated["thesis_mode"].lower()
    
    def test_capabilities_specifies_authoritative_engine(self):
        """Capabilities should clarify the authoritative engine."""
        from bff.routers.optimization import _optimization_capabilities
        
        caps = _optimization_capabilities()
        
        assert "authoritative_engine" in caps
        assert "src/optimization" in caps["authoritative_engine"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
