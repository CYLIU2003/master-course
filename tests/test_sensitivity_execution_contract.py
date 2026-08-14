from __future__ import annotations

from bff.services.optimization_run.sensitivity_execution_contract import (
    LATEST_SENSITIVITY_EXECUTION_SCHEMA_VERSION,
    is_supported_sensitivity_execution_schema,
)
from scripts.run_thesis_sensitivity_matrix import SCHEMA_VERSION


def test_runner_uses_latest_declared_sensitivity_schema() -> None:
    assert SCHEMA_VERSION == LATEST_SENSITIVITY_EXECUTION_SCHEMA_VERSION
    assert is_supported_sensitivity_execution_schema(SCHEMA_VERSION)


def test_immutable_legacy_sensitivity_schemas_remain_auditable() -> None:
    assert is_supported_sensitivity_execution_schema(
        "thesis_sensitivity_execution_v2"
    )
    assert is_supported_sensitivity_execution_schema(
        "thesis_sensitivity_execution_v3_turnaround_buffer"
    )


def test_undeclared_sensitivity_schema_is_rejected() -> None:
    assert not is_supported_sensitivity_execution_schema(
        "thesis_sensitivity_execution_v999_unknown"
    )
