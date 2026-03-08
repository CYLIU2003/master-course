from bff.routers.optimization import _optimization_capabilities
from bff.routers.simulation import _simulation_capabilities


def test_simulation_capabilities_expose_job_persistence():
    payload = _simulation_capabilities()

    assert payload["implemented"] is True
    assert payload["async_job"] is True
    assert payload["job_persistence"]["store"] == "process_memory"
    assert payload["job_persistence"]["survives_restart"] is False
    assert "ProblemData" in " ".join(payload["notes"])


def test_optimization_capabilities_expose_supported_modes():
    payload = _optimization_capabilities()

    assert payload["implemented"] is True
    assert payload["supports_reoptimization"] is True
    assert "hybrid" in payload["supported_modes"]
    assert payload["job_persistence"]["survives_restart"] is False
