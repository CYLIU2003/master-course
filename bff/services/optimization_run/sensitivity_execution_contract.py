"""Version contract shared by sensitivity execution and its auditors."""

from __future__ import annotations


LATEST_SENSITIVITY_EXECUTION_SCHEMA_VERSION = (
    "thesis_sensitivity_execution_v4_powertrain_coefficients"
)

# v2 is retained for immutable completed tranches. v3 added the declared
# turnaround-buffer field, and v4 adds independently varied BEV-energy and
# ICE-fuel coefficients. Auditors must reject every undeclared version.
SUPPORTED_SENSITIVITY_EXECUTION_SCHEMA_VERSIONS = frozenset(
    {
        "thesis_sensitivity_execution_v2",
        "thesis_sensitivity_execution_v3_turnaround_buffer",
        LATEST_SENSITIVITY_EXECUTION_SCHEMA_VERSION,
    }
)


def is_supported_sensitivity_execution_schema(value: object) -> bool:
    """Return whether an immutable execution manifest has a known schema."""

    return value in SUPPORTED_SENSITIVITY_EXECUTION_SCHEMA_VERSIONS
