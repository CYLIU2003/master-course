from bff.routers.optimization import _parse_mode
from src.optimization import OptimizationMode


def test_parse_mode_maps_supported_aliases():
    assert _parse_mode("milp") == OptimizationMode.MILP
    assert _parse_mode("ALNS") == OptimizationMode.ALNS
    assert _parse_mode("heuristic") == OptimizationMode.ALNS
    assert _parse_mode("hybrid") == OptimizationMode.HYBRID
    assert _parse_mode("unknown") == OptimizationMode.HYBRID
